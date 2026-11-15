"""Loads and cleans the NMIS livestock market CSV and answers simple questions about it.

Plain-language summary of what happens here:
  1. Read the CSV (Amharic column names are renamed to English by position).
  2. Remove exact duplicate rows, fix rows where max price < min price, and drop
     clearly-wrong prices (more than ~2x away from the usual price for that market+grade).
  3. Turn each row into one "mid price" (average of low and high) per animal.
  4. Provide helpers: current price level for a market, price history, and a
     "selling pressure" proxy built from how many animals arrive at markets.
"""
import json
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.environ.get("NMIS_CSV", os.path.join(HERE, "data", "Livestock_Market_Table_Data.csv"))

COLS = ["market", "breed", "area", "type", "sex", "age", "grade", "pmin", "pmax", "qty", "date"]
GRADES = ["Thin", "Moderate Weight", "Very Fat"]          # index 0,1,2 used by the engine
OUTLIER_LOG_DEVIATION = float(os.environ.get("OUTLIER_LOG_DEVIATION", "0.75"))   # ~ x2.1 away from market+grade median
OUTLIER_FILTER_ON = os.environ.get("OUTLIER_FILTER", "1") != "0"                  # set OUTLIER_FILTER=0 to keep every price


_REG = None
def region_info(market):
    """Which region (Afar/Somali/Oromia) and area group a market belongs to. Edit data/market_regions.json."""
    global _REG
    if _REG is None:
        try:
            _REG = json.load(open(os.path.join(HERE, "data", "market_regions.json"), encoding="utf-8"))
        except Exception:
            _REG = {}
    return _REG.get(market, {"region": "Unknown", "area": "Other / unknown"})


class DataStore:
    def __init__(self, csv_path=CSV_PATH):
        self.csv_path = csv_path
        self.report = {}
        self.df = self._load()
        self.asof = self.df["date"].max()
        self.loaded_mtime = os.path.getmtime(self.csv_path)
        self.report["file_newest_record"] = str(self.asof.date())
        self.report["file_age_days_vs_today"] = self.data_age_days()
        self._compute_grade_ratios()
        self._compute_drift()

    # ---------- loading / cleaning ----------
    def _load(self):
        raw = pd.read_csv(self.csv_path, encoding="utf-8-sig")
        raw.columns = COLS
        rep = {"rows_in_file": int(len(raw))}
        df = raw.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "pmin", "pmax", "qty", "market", "grade"])
        df["market"] = df["market"].str.replace("_", " ").str.strip()
        df["grade"] = df["grade"].astype(str).str.strip()
        unknown = ~df["grade"].isin(GRADES)
        rep["rows_unknown_grade_dropped"] = int(unknown.sum())
        df = df[~unknown]

        before = len(df)
        df = df.drop_duplicates()
        rep["exact_duplicates_removed"] = int(before - len(df))

        swapped = df["pmax"] < df["pmin"]
        rep["rows_min_max_swapped"] = int(swapped.sum())
        df.loc[swapped, ["pmin", "pmax"]] = df.loc[swapped, ["pmax", "pmin"]].values

        df["pmid"] = (df["pmin"] + df["pmax"]) / 2.0
        df["lp"] = np.log(df["pmid"])
        med = df.groupby(["market", "grade"])["lp"].transform("median")
        cnt = df.groupby(["market", "grade"])["lp"].transform("size")
        dev = df["lp"] - med
        flagged = (cnt >= 5) & (dev.abs() > OUTLIER_LOG_DEVIATION) & OUTLIER_FILTER_ON
        # A real drought crash is a SHARED move: if another report for the same market+grade within 21 days
        # deviates the same way, keep it. Only isolated jumps, or rows whose own max is >5x their min, are dropped.
        corroborated = pd.Series(False, index=df.index)
        for (_, _), g in df[flagged].groupby(["market", "grade"]):
            pool = df[(df["market"] == g["market"].iloc[0]) & (df["grade"] == g["grade"].iloc[0])]
            for i, r in g.iterrows():
                near = pool[(pool.index != i) & ((pool["date"] - r["date"]).abs() <= pd.Timedelta(days=21))]
                same_way = near[(dev[near.index] * dev[i] > 0) & (dev[near.index].abs() > 0.5 * OUTLIER_LOG_DEVIATION)]
                if len(same_way) >= 1:
                    corroborated[i] = True
        absurd_range = (df["pmax"] / df["pmin"].replace(0, np.nan)) > 5
        outlier = ((flagged & ~corroborated) | (absurd_range & OUTLIER_FILTER_ON)).fillna(False)
        rep["outlier_filter"] = "on" if OUTLIER_FILTER_ON else "off"
        rep["price_outliers_removed"] = int(outlier.sum())
        rep["outliers_kept_because_corroborated"] = int((flagged & corroborated).sum())
        rep["outlier_examples"] = df.loc[outlier, ["market", "grade", "pmin", "pmax", "date"]].astype(str).head(8).to_dict("records")
        df = df[~outlier].copy()

        rep["rows_used"] = int(len(df))
        rep["date_from"] = str(df["date"].min().date())
        rep["date_to"] = str(df["date"].max().date())
        rep["markets"] = int(df["market"].nunique())
        self.report = rep
        return df.reset_index(drop=True)

    def _compute_grade_ratios(self):
        """How much more/less a Thin or Very Fat animal sells for compared with a Moderate one."""
        d = self.df.copy()
        d["ym"] = d["date"].dt.to_period("M")
        piv = d.groupby(["market", "ym", "grade"])["pmid"].median().unstack("grade")
        ratios = {}
        for g in GRADES:
            if g == "Moderate Weight":
                ratios[g] = 1.0
                continue
            fallback = {"Thin": 0.85, "Very Fat": 1.12}[g]
            if g not in piv.columns or "Moderate Weight" not in piv.columns:
                ratios[g] = fallback
                continue
            both = piv[[g, "Moderate Weight"]].dropna()
            ratios[g] = float((both[g] / both["Moderate Weight"]).median()) if len(both) >= 5 else fallback
        self.grade_ratio = ratios
        self.df["pnorm"] = self.df["pmid"] / self.df["grade"].map(ratios)   # "Moderate-equivalent" price
        self.report["grade_price_ratio_vs_moderate"] = {k: round(v, 3) for k, v in ratios.items()}

    def _compute_drift(self):
        """Typical month-to-month price change (log) in normal times, from the data itself."""
        d = self.df.copy()
        d["ym"] = d["date"].dt.to_period("M")
        m = d.groupby(["market", "ym"])["pnorm"].agg(["median", "size"]).reset_index()
        m = m[m["size"] >= 3].sort_values(["market", "ym"])
        diffs = []
        for _, g in m.groupby("market"):
            g = g.reset_index(drop=True)
            for i in range(1, len(g)):
                if (g.loc[i, "ym"] - g.loc[i - 1, "ym"]).n == 1:
                    diffs.append(np.log(g.loc[i, "median"] / g.loc[i - 1, "median"]))
        drift = float(np.median(diffs)) if len(diffs) >= 8 else 0.0
        self.drift_estimated = float(np.clip(drift, -0.02, 0.03))
        use = os.environ.get("USE_ESTIMATED_DRIFT", "0") == "1"
        self.drift = self.drift_estimated if use else 0.0      # backtest: estimate did not beat 'no change'
        self.report["monthly_price_drift_estimated"] = round(self.drift_estimated, 4)
        self.report["monthly_price_drift_used"] = round(self.drift, 4)
        self.report["drift_pairs_used"] = len(diffs)

    def today(self):
        """Today's date (env ASOF_TODAY=YYYY-MM-DD overrides it, for tests)."""
        t = os.environ.get("ASOF_TODAY")
        return pd.Timestamp(t) if t else pd.Timestamp.today().normalize()

    def data_age_days(self):
        """How old the NEWEST price in the file is compared with TODAY (not with the file's own latest date)."""
        return int((self.today() - self.asof).days)

    # ---------- queries ----------
    def markets(self):
        c = self.df.groupby("market").agg(records=("pmid", "size"), last=("date", "max")).sort_values("records", ascending=False)
        out = []
        for k, v in c.iterrows():
            info = region_info(k)
            out.append({"market": k, "records": int(v.records), "last_record": str(v["last"].date()),
                        "region": info["region"], "area": info["area"]})
        order = {"Borana area": 0, "Other Oromia": 1, "Somali": 2, "Afar": 3}
        return sorted(out, key=lambda x: (order.get(x["area"], 9), -x["records"]))

    def price_level(self, market, window_days=45):
        """Current Moderate-equivalent price for a market. Widens the window if data is thin.
        Returns (level, n_records_used, window_used, last_record_date)."""
        d = self.df[self.df["market"] == market]
        if d.empty:
            return None
        for w in (window_days, 90, 180, 400):
            recent = d[d["date"] >= self.asof - pd.Timedelta(days=w)]
            if len(recent) >= 3 or w == 400:
                if recent.empty:
                    return None
                # plain median: the meaning of the 'quantity' column is not confirmed, so it is NOT used as a weight
                return float(recent["pnorm"].median()), int(len(recent)), w, d["date"].max()

    def region_level(self):
        recent = self.df[self.df["date"] >= self.asof - pd.Timedelta(days=60)]
        return float(recent["pnorm"].median())

    def pressure(self, market):
        """Selling-pressure proxy in [0,1], built from PRICES only (the 'quantity' column is unconfirmed).
        Idea: if prices at many markets are falling (last 45 days vs the 90 days before), more people are
        probably selling at once. Weak proxy: falling prices can also be seasonal. Returns
        (score, price_change_used, n_markets_in_calc)."""
        d = self.df
        rs, ps = self.asof - pd.Timedelta(days=45), self.asof - pd.Timedelta(days=135)
        ch = {}
        for m, g in d.groupby("market"):
            rec = g[g["date"] >= rs]["pnorm"]
            pri = g[(g["date"] < rs) & (g["date"] >= ps)]["pnorm"]
            if len(rec) >= 3 and len(pri) >= 3:
                ch[m] = float(np.log(rec.median() / pri.median()))
        if not ch:
            return 0.0, None, 0
        region = float(np.median(list(ch.values())))
        used = region if market not in ch else 0.5 * ch[market] + 0.5 * region
        return float(np.clip(-used / 0.10, 0.0, 1.0)), round(used, 3), len(ch)

    def history(self, market):
        d = self.df[self.df["market"] == market].copy()
        d["ym"] = d["date"].dt.to_period("M").astype(str)
        months = sorted(d["ym"].unique())
        price = d.groupby(["ym", "grade"])["pmid"].median().unstack("grade")
        qty = d.groupby("ym")["qty"].median()
        n = d.groupby("ym").size()
        out = {"months": months, "n_records": [int(n[m]) for m in months], "median_qty_per_report": [float(qty[m]) for m in months]}
        for g in GRADES:
            out[g] = [None if (g not in price.columns or pd.isna(price.loc[m, g])) else round(float(price.loc[m, g])) for m in months]
        return out


_store = None
def get_store():
    global _store
    try:
        changed = _store is not None and os.path.getmtime(_store.csv_path) != _store.loaded_mtime
    except OSError:
        changed = False
    if _store is None or changed:        # new CSV dropped in -> picked up without a restart
        _store = DataStore()
    return _store
