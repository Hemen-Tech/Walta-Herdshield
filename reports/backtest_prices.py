"""Rolling-origin backtest: does a constant monthly price drift predict next month's price better than 'no change'?
Time-based: the drift used for month t is estimated ONLY from month-to-month changes that ended before t.
Run:  python reports/backtest_prices.py   -> writes reports/PRICE_BACKTEST.md"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_store import DataStore

s = DataStore()
d = s.df.copy(); d["ym"] = d["date"].dt.to_period("M")
m = d.groupby(["market", "ym"])["pnorm"].agg(["median", "size"]).reset_index()
m = m[m["size"] >= 3].sort_values(["market", "ym"]).reset_index(drop=True)

pairs = []
for mk, g in m.groupby("market"):
    g = g.reset_index(drop=True)
    for i in range(1, len(g)):
        if (g.loc[i, "ym"] - g.loc[i - 1, "ym"]).n == 1:
            pairs.append((mk, g.loc[i, "ym"], float(np.log(g.loc[i, "median"] / g.loc[i - 1, "median"]))))
p = pd.DataFrame(pairs, columns=["market", "ym", "chg"])
rows = []
for _, r in p.iterrows():
    past = p[p["ym"] < r["ym"]]["chg"]
    drift = float(np.clip(past.median(), -0.02, 0.03)) if len(past) >= 8 else np.nan
    rows.append((r["chg"], drift))
b = pd.DataFrame(rows, columns=["actual", "drift"]).dropna()
mae_naive, mae_drift = b["actual"].abs().mean(), (b["actual"] - b["drift"]).abs().mean()
md = f"""# Price backtest (1 month ahead, time-based)

- Month-to-month price pairs available: {len(p)}; pairs with a drift estimated only from earlier months: {len(b)}
- Typical month-to-month change: median {p['chg'].median():+.3f}, standard deviation {p['chg'].std():.3f} (log scale)
- Mean absolute error, 'no change' forecast: **{mae_naive:.4f}**
- Mean absolute error, constant-drift forecast: **{mae_drift:.4f}**

Result: the drift model {'does NOT beat' if mae_drift >= mae_naive else 'beats'} the 'no change' forecast. Month-to-month noise
(~{p['chg'].std()*100:.0f}%) is far larger than the drift (~{p['chg'].median()*100:.1f}%/month), so the engine uses drift = 0 by default.
Limits: ~14 months, thin coverage, no seasonality test possible with less than 2 full years.
"""
open(os.path.join(os.path.dirname(__file__), "PRICE_BACKTEST.md"), "w").write(md)
print(md)
