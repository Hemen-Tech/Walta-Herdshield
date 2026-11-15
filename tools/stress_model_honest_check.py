"""Honest re-check of the 'PNIS livestock stress' model idea from Livestock_Forecasting.ipynb.

Question: can rainfall + vegetation data PREDICT that vegetation will be stressed (viq < 85% of average) 1, 3 or 9 dekads
(10 days, 1 month, 3 months) ahead BETTER THAN SIMPLE BASELINES?  The notebook never compared with baselines, and its headline
numbers (precision/recall 1.00, accuracy 0.978) come from (a) a target that was already in the inputs, (b) a majority-class
metric, and (c) a model evaluated on the same rows it was trained and calibrated on.

Baselines it must beat:  CLIMATOLOGY (typical stress rate for that time of year) and PERSISTENCE (stress now -> stress later).
Fixes: future labels are shifted WITHIN each region (not across regions); train / calibrate / test are separate TIME blocks;
calibration is fitted on the calibration years, not on the training rows; no fillna(0) (NaN rows dropped); scores that matter for
rare events (Brier skill, PR-AUC) instead of accuracy; year-block bootstrap for the uncertainty.

Usage (Colab or PC, needs internet unless you pass files):
    python tools/stress_model_honest_check.py
    python tools/stress_model_honest_check.py --rain-file rain.csv --ndvi-file ndvi.csv --focus ET04
"""
import argparse, warnings
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, precision_recall_curve
warnings.filterwarnings("ignore")

RAIN_URL = "https://data.humdata.org/dataset/423143be-315f-48d7-9e90-ae23738da564/resource/49e3a707-d153-423e-b22b-30484d678dd7/download/eth-rainfall-subnat-full.csv"
NDVI_URL = "https://data.humdata.org/dataset/f7956713-9cce-4784-a1b9-bca5a60f4729/resource/4d430d98-3dd3-4b27-b917-3c7eae559d1a/download/eth-ndvi-subnat-full.csv"
ap = argparse.ArgumentParser()
ap.add_argument("--rain-file"); ap.add_argument("--ndvi-file"); ap.add_argument("--focus", action="append", help="P-code(s) to report separately (e.g. your Borena zone)")
ap.add_argument("--stress-below", type=float, default=85.0); ap.add_argument("--train-end", type=int, default=2015); ap.add_argument("--calib-end", type=int, default=2019)
ap.add_argument("--boot", type=int, default=300)
A = ap.parse_args()
HORIZONS = {"10 days (1 dekad)": 1, "1 month (3 dekads)": 3, "3 months (9 dekads)": 9}


def load(src):
    d = pd.read_csv(src); d = d[~d["date"].astype(str).str.startswith("#")]
    d["date"] = pd.to_datetime(d["date"], errors="coerce"); return d.dropna(subset=["date"])
rain, ndvi = load(A.rain_file or RAIN_URL), load(A.ndvi_file or NDVI_URL)
num = lambda d, cols: d.assign(**{c: pd.to_numeric(d[c], errors="coerce") for c in cols if c in d})
rain = num(rain, ["rfh", "rfh_avg", "r1h", "r3h", "rfq", "r1q", "r3q"]); ndvi = num(ndvi, ["vim", "vim_avg", "viq"])
keep_r = ["date", "PCODE", "rfh", "rfh_avg", "r1h", "r3h", "rfq", "r1q", "r3q"]; keep_n = ["date", "PCODE", "vim", "vim_avg", "viq"]
df = rain[keep_r].merge(ndvi[keep_n], on=["date", "PCODE"], how="inner").drop_duplicates(["PCODE", "date"]).sort_values(["PCODE", "date"]).reset_index(drop=True)
g = df.groupby("PCODE")
for w, n in ((9, "3m"), (18, "6m")):                                    # same rolling features as the notebook, but computed per region
    for c in ("rfh", "viq", "r3q"): df["%s_rolling_%s" % (c, n)] = g[c].transform(lambda x: x.rolling(w, min_periods=w).mean())
df["year"] = df["date"].dt.year; df["doy10"] = ((df["date"].dt.month - 1) * 3 + (df["date"].dt.day - 1) // 10).clip(upper=35)
df["stress_now"] = (df["viq"] < A.stress_below).astype(float).where(df["viq"].notna())
print("merged rows: %d | regions: %d | %s -> %s" % (len(df), df.PCODE.nunique(), df.date.min().date(), df.date.max().date()))
BASE = ["rfh", "rfh_avg", "r1h", "r3h", "rfq", "r1q", "r3q", "vim", "vim_avg", "rfh_rolling_3m", "r3q_rolling_3m", "rfh_rolling_6m", "r3q_rolling_6m"]
FULL = BASE + ["viq", "viq_rolling_3m", "viq_rolling_6m"]            # FULL is what the saved .pkl uses (it contains today's vegetation anomaly)


def fit_rate_table(train, keys, tgt):
    t = train.groupby(keys)[tgt].agg(["sum", "count"]); base = train[tgt].mean()
    return ((t["sum"] + 2 * base) / (t["count"] + 2)).to_dict(), base
def lookup(tab, base, frame, keys):
    return np.array([tab.get(k if len(keys) > 1 else k[0] if isinstance(k, tuple) else k, base) for k in map(tuple, frame[keys].values)]) if len(keys) > 1 else frame[keys[0]].map(tab).fillna(base).values
def hgb(tr, cols, tgt):
    m = HistGradientBoostingClassifier(max_iter=150, max_depth=4, learning_rate=0.05, l2_regularization=1.0, random_state=0)
    return m.fit(tr[cols], tr[tgt])
def brier(p, y): return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def evaluate(H, focus=None):
    d = df.copy(); d["y"] = d.groupby("PCODE")["stress_now"].shift(-H)              # label shifted WITHIN region
    d = d.dropna(subset=FULL + ["y", "stress_now"]).copy()
    tr, ca, te = d[d.year <= A.train_end], d[(d.year > A.train_end) & (d.year <= A.calib_end)], d[d.year > A.calib_end]
    if focus is not None: te = te[te.PCODE.isin(focus)]
    if len(tr) < 500 or len(ca) < 200 or len(te) < 200 or te.y.sum() < 5: return None
    out = {}
    tab, b = fit_rate_table(tr, ["doy10"], "y"); out["climatology (time of year)"] = lambda f: lookup(tab, b, f, ["doy10"])
    tab2, b2 = fit_rate_table(tr, ["stress_now"], "y"); out["persistence (stress now)"] = lambda f: lookup(tab2, b2, f, ["stress_now"])
    for name, cols in (("model WITHOUT current vegetation", BASE), ("model WITH current vegetation (= your .pkl)", FULL)):
        m = hgb(tr, cols, "y"); iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(m.predict_proba(ca[cols])[:, 1], ca["y"])   # calibrate on calib years
        out[name] = (lambda mm, ii, cc: (lambda f: ii.predict(mm.predict_proba(f[cc])[:, 1])))(m, iso, cols)
    P = {k: f(te) for k, f in out.items()}
    clim = brier(P["climatology (time of year)"], te.y); pers = brier(P["persistence (stress now)"], te.y)
    res = {"n": len(te), "rate": float(te.y.mean()), "te": te, "P": P, "clim": clim, "pers": pers}
    # threshold picked on CALIBRATION years only, then applied to test
    res["rows"] = []
    for k, f in out.items():
        pc = f(ca); pr, rc, th = precision_recall_curve(ca.y, pc); f1 = 2 * pr * rc / (pr + rc + 1e-9); t = th[np.argmax(f1[:-1])] if len(th) else 0.5
        yhat = P[k] >= t; tp = float((yhat & (te.y.values == 1)).sum())
        res["rows"].append((k, brier(P[k], te.y), 1 - brier(P[k], te.y) / clim, 1 - brier(P[k], te.y) / pers, average_precision_score(te.y, P[k]),
                            tp / max(1, yhat.sum()), tp / max(1, te.y.sum())))
    return res


def show(title, focus=None):
    print("\n" + "=" * 100 + "\n" + title)
    for name, H in HORIZONS.items():
        r = evaluate(H, focus)
        if r is None: print("\n-- %s: not enough data/events to score" % name); continue
        print("\n-- predicting stress %s ahead | test rows %d (years > %d) | stress rate in test %.3f (a model that always says 'no stress' is %.1f%% 'accurate')" % (name, r["n"], A.calib_end, r["rate"], 100 * (1 - r["rate"])))
        print("   %-46s %7s %12s %12s %7s %9s %7s" % ("model", "Brier", "skill vs clim", "skill vs pers", "PR-AUC", "precision", "recall"))
        for k, bsc, sc, sp, ap_, pre, rec in r["rows"]:
            print("   %-46s %7.4f %+12.3f %+12.3f %7.3f %9.2f %7.2f" % (k, bsc, sc, sp, ap_, pre, rec))
        te, P = r["te"], r["P"]; yrs = te.year.unique(); rng = np.random.default_rng(0); d = []
        gm, gp = P["model WITHOUT current vegetation"], P["persistence (stress now)"]
        idx = {y: np.where(te.year.values == y)[0] for y in yrs}
        for _ in range(A.boot):
            s = np.concatenate([idx[y] for y in rng.choice(yrs, len(yrs))]); yy = te.y.values[s]
            d.append(1 - brier(gm[s], yy) / brier(gp[s], yy))
        lo, hi = np.percentile(d, [5, 95]); gain = (lo > 0)
        print("   >> rain+season-only model vs persistence: skill %+.3f, 90%% interval %+.3f..%+.3f -> %s" % (np.mean(d), lo, hi, "ADDS value beyond persistence" if gain else "does NOT clearly beat persistence"))


show("ALL REGIONS")
if A.focus: show("FOCUS AREA %s" % A.focus, A.focus)
print("\nHOW TO READ: 'skill vs pers' > 0 means better than just assuming today's vegetation condition continues. If the model WITH current")
print("vegetation only matches persistence, it is a persistence model, and its 'livestock mortality' labels are unsupported: the target is a")
print("vegetation anomaly, not animal deaths. Only use it if it beats persistence at the horizon you need (the app needs ~3 months).")
