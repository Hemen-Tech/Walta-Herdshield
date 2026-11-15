"""Does El Nino / Indian Ocean Dipole information help predict Borana rainy-season failure better than plain climatology?

Usage:  python rain_enso_iod_skill_test.py <folder with open-meteo-*.csv>  [oni_ascii.txt]  [dmi_had_long_data.txt]

Honest design (fixes to the first script):
 * expanding window: every year the models are retrained ONLY on origins whose 3-month outcome was already known
 * the score that matters is on the RAINY-SEASON origins: Feb (-> Mar-May long rains) and Sep (-> Oct-Dec short rains).
   "All months" is printed too, but dry-season SPI is mostly noise.
 * ENSO uses the ONI value centred on the PREVIOUS month (its 3-month window is fully known at the origin), DMI is lagged 1 month.
 * the incomplete last month is dropped automatically; same rows are scored for every model (complete cases only)
 * a model is called 'skilful' only if the 90% year-bootstrap interval of its skill stays above zero
NOTE: the DMI file you have stops months before today. A live system needs a faster IOD feed.
"""
import glob, os, sys, warnings
import numpy as np, pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
warnings.filterwarnings("ignore")

CSV_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
ONI_FILE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(CSV_DIR, "oni_ascii.txt")
DMI_FILE = sys.argv[3] if len(sys.argv) > 3 else os.path.join(CSV_DIR, "dmi_had_long_data.txt")
BASELINE, DMI_LAG, FIRST_TEST, SEASON_ORIGINS = (1981, 2010), 1, 1998, {2: "Feb->MAM long rains", 9: "Sep->OND short rains"}
SEAS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]

# ---------- rainfall ----------
files = sorted(glob.glob(os.path.join(CSV_DIR, "open-meteo-*.csv")))
assert files, "No open-meteo-*.csv files in %s" % CSV_DIR
cols = {}
for f in files:
    lines = open(f, encoding="utf-8", errors="ignore").read().splitlines()
    k = next(i for i, l in enumerate(lines) if l.lower().startswith("time"))
    d = pd.read_csv(f, skiprows=k).iloc[:, :2]; d.columns = ["time", "p"]; d["time"] = pd.to_datetime(d["time"])
    cols[os.path.basename(f)] = d.set_index("time")["p"].astype(float)       # full file name as key: no silent overwrites
daily = pd.DataFrame(cols)
print("files:", len(files), "| daily", daily.index.min().date(), "->", daily.index.max().date(), "| NaN share", round(float(daily.isna().mean().mean()), 4))
monthly = daily.resample("MS").sum(min_count=20).mean(axis=1)
last_day = daily.index.max()
if last_day != last_day + pd.offsets.MonthEnd(0):                              # last month incomplete -> drop it
    monthly = monthly[monthly.index < last_day.replace(day=1)]

def spi_series(r, k):
    acc = r.rolling(k, min_periods=k).sum(); out = pd.Series(np.nan, index=acc.index)
    for m in range(1, 13):
        sel = acc[acc.index.month == m].dropna()
        base = sel[(sel.index.year >= BASELINE[0]) & (sel.index.year <= BASELINE[1])]
        pos = base[base > 0]
        if len(pos) < 10: continue
        p0 = (base <= 0).mean(); a, _, sc = stats.gamma.fit(pos, floc=0)
        cdf = p0 + (1 - p0) * stats.gamma.cdf(sel.clip(lower=0), a, loc=0, scale=sc)
        out.loc[sel.index] = stats.norm.ppf(np.clip(cdf, 1e-6, 1 - 1e-6))
    return out

df = pd.DataFrame({"rain": monthly})
for k in (1, 3, 6, 12): df["spi%d" % k] = spi_series(monthly, k)
ang = 2 * np.pi * df.index.month / 12; df["m_sin"], df["m_cos"] = np.sin(ang), np.cos(ang)
df["t3"] = df["spi3"].shift(-3)                                                 # SPI of the 3 months AFTER the origin month

# ---------- ENSO + IOD ----------
rows = []
for ln in open(ONI_FILE, encoding="utf-8", errors="ignore"):
    p = ln.split()
    if len(p) == 4 and p[0] in SEAS and p[1].isdigit():
        rows.append((pd.Timestamp(int(p[1]), SEAS.index(p[0]) + 1, 1), float(p[3])))
oni_c = pd.Series(dict(rows)).sort_index()                                      # indexed by CENTRE month of the 3-month season
oni_use = oni_c.copy(); oni_use.index = oni_use.index + pd.offsets.MonthBegin(1)  # value known at the END of origin month t = centred on t-1
df["oni"] = oni_use.reindex(df.index); df["oni_trend"] = df["oni"] - df["oni"].shift(3)
dm = {}
for ln in open(DMI_FILE, encoding="utf-8", errors="ignore"):
    p = ln.split()
    if len(p) == 13 and p[0].isdigit():
        for i, x in enumerate(p[1:], 1):
            if float(x) > -900: dm[pd.Timestamp(int(p[0]), i, 1)] = float(x)
dmi = pd.Series(dm).sort_index(); dmi.index = dmi.index + pd.DateOffset(months=DMI_LAG)
df["dmi"] = dmi.reindex(df.index)
print("ONI last used:", oni_c.index.max().date(), "| DMI last valid:", (dmi.index.max() - pd.DateOffset(months=DMI_LAG)).date())

BASE = ["spi1", "spi3", "spi6", "spi12", "m_sin", "m_cos"]
ENSO = BASE + ["oni", "oni_trend"]; ENSO_IOD = ENSO + ["dmi"]
d = df.dropna(subset=ENSO_IOD + ["t3"]).copy()                                  # SAME rows for every model
d["bad"] = (np.select([d.t3 >= -0.5, d.t3 >= -1.0, d.t3 >= -1.5], [0, 1, 2], default=3) >= 2).astype(int)   # moderate+ dryness
d["oy"], d["om"] = d.index.year, d.index.month
d["ecls"] = np.select([d.oni >= 0.5, d.oni <= -0.5], [1, -1], default=0)       # El Nino / La Nina / neutral
print("complete-case origins:", len(d), "|", d.index.min().date(), "->", d.index.max().date(), "| base rate of 'bad':", round(d.bad.mean(), 3))

def clim(train, test):
    g = train.bad.mean(); out = []
    for m in test.om:
        s = train[train.om == m].bad; out.append((s.sum() + 5 * g) / (len(s) + 5))
    return np.array(out)
def enso_comp(train, test, base):                                               # P(bad | month, ENSO class), shrunk to month climatology
    out = []
    for (m, c), b in zip(zip(test.om, test.ecls), base):
        s = train[(train.om == m) & (train.ecls == c)].bad; out.append((s.sum() + 4 * b) / (len(s) + 4))
    return np.array(out)
def lr(train, test, cols, C=0.03):
    if train.bad.nunique() < 2: return np.full(len(test), train.bad.mean())
    m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=3000)); m.fit(train[cols], train.bad)
    return m.predict_proba(test[cols])[:, 1]

recs = []
for Y in range(FIRST_TEST, int(d.oy.max()) + 1):
    train, test = d[d.index <= pd.Timestamp(Y - 1, 9, 1)], d[d.oy == Y]
    if len(test) == 0 or len(train) < 60: continue
    pc = clim(train, test)
    recs.append(pd.DataFrame({"year": Y, "month": test.om.values, "obs": test.bad.values, "climatology": pc,
        "LR rain only": lr(train, test, BASE), "LR + ENSO": lr(train, test, ENSO), "LR + ENSO + IOD": lr(train, test, ENSO_IOD),
        "ENSO-class composite": enso_comp(train, test, pc)}))
R = pd.concat(recs); MODELS = ["LR rain only", "LR + ENSO", "LR + ENSO + IOD", "ENSO-class composite"]
bs = lambda p, o: np.mean((p - o) ** 2)
skill = lambda s, k: 1 - bs(s[k], s.obs) / bs(s.climatology, s.obs)
rng = np.random.default_rng(0)
def boot(sub, k, n=500):
    ys = sub.year.unique(); groups = {y: sub[sub.year == y] for y in ys}; v = []
    for _ in range(n): v.append(skill(pd.concat([groups[y] for y in rng.choice(ys, len(ys))]), k))
    return np.percentile(v, 5), np.percentile(v, 95)
def report(sub, title):
    print("\n%s  (n=%d origins, %d years, 'bad' rate %.2f)" % (title, len(sub), sub.year.nunique(), sub.obs.mean()))
    print("   %-22s %8s   %-22s  verdict" % ("model", "skill", "90% interval"))
    for k in MODELS:
        s = skill(sub, k); lo, hi = boot(sub, k)
        verdict = "SKILFUL (interval > 0)" if lo > 0 else ("inconclusive" if s > 0 else "no skill")
        print("   %-22s %+8.3f   %+.3f .. %+.3f        %s" % (k, s, lo, hi, verdict))
report(R, "ALL origin months")
rs = R[R.month.isin(SEASON_ORIGINS)]
report(rs, "RAINY-SEASON origins only (Feb + Sep)  <-- the one that matters")
for m, name in SEASON_ORIGINS.items(): report(R[R.month == m], name)
report(rs[rs.year >= 2013], "Rainy-season origins, 2013 onward")

# what do the past years say, in plain numbers? (OND failure rate by ENSO state, using ALL years)
sep = d[d.om == 9]
print("\nShare of years where Oct-Dec was moderately dry or worse (SPI3 <= -1.0), by ENSO state in September:")
for c, name in [(1, "El Nino"), (0, "neutral"), (-1, "La Nina")]:
    s = sep[sep.ecls == c]; print("   %-8s %2d of %2d years (%.0f%%)" % (name, s.bad.sum(), len(s), 100 * s.bad.mean() if len(s) else float('nan')))
print("\nREAD THIS: a model is only worth wiring into the app if its Rainy-season interval stays above zero.")
print("If not, keep ENSO/IOD as context only (as the app does now) and rely on the official ICPAC/EMI outlook.")
