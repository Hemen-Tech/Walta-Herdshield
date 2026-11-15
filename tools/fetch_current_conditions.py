"""Fetch OBSERVED rainfall + vegetation conditions (WFP/CHIRPS rainfall and MODIS NDVI, via HDX) for your area and write
data/current_conditions.json, which the app shows as 'Observed conditions' (context only, never changes the sell/hold advice).

Usage (needs internet; works in Colab, Replit or your PC):
    python tools/fetch_current_conditions.py --pcode ET04                 # Oromia region (default, coarse)
    python tools/fetch_current_conditions.py --pcode ET0414 --label "Borena zone"   # <- use the REAL zone P-code (see below)
    python tools/fetch_current_conditions.py --rain-file rain.csv --ndvi-file ndvi.csv --pcode ET04   # files you downloaded by hand

FIND THE RIGHT P-CODE: download 'Ethiopia - Subnational Administrative Boundaries' (OCHA COD) from data.humdata.org and look up the
Borena zone's admin-2 code. Zone boundaries changed in 2025, so confirm which zone(s) your markets are in. The default ET04 is the whole
Oromia region and hides local differences. Run again every 10 days (dekad) or at least monthly.
Numbers: r1q / r3q = rainfall of the last 1 / 3 months as % of the long-term average; viq = vegetation greenness as % of average.
"""
import argparse, json, os, sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "data", "current_conditions.json")
# the same two links your Colab notebook loaded successfully
RAIN_URL = "https://data.humdata.org/dataset/423143be-315f-48d7-9e90-ae23738da564/resource/49e3a707-d153-423e-b22b-30484d678dd7/download/eth-rainfall-subnat-full.csv"
NDVI_URL = "https://data.humdata.org/dataset/f7956713-9cce-4784-a1b9-bca5a60f4729/resource/4d430d98-3dd3-4b27-b917-3c7eae559d1a/download/eth-ndvi-subnat-full.csv"


def num(x):
    try:
        v = float(x)
        return None if pd.isna(v) else round(v, 2)
    except (TypeError, ValueError):
        return None


def load(src):
    d = pd.read_csv(src, skiprows=lambda i: False)
    d = d[~d["date"].astype(str).str.startswith("#")]          # HDX files may carry a '#' tag row under the header
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    return d.dropna(subset=["date"])


def latest(d, pcodes, cols):
    sub = d[d["PCODE"].isin(pcodes)]
    if sub.empty:
        sys.exit("No rows for P-code(s) %s. First codes available: %s" % (pcodes, sorted(d["PCODE"].unique())[:25]))
    g = sub.groupby("date")[cols].apply(lambda x: x.apply(pd.to_numeric, errors="coerce").mean()).sort_index()   # mean if several areas
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcode", action="append", help="P-code(s) of your area; repeat for several (default ET04)")
    ap.add_argument("--label", default=None, help="Human name shown in the app, e.g. 'Borena zone'")
    ap.add_argument("--rain-file"); ap.add_argument("--ndvi-file"); ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    pcodes = a.pcode or ["ET04"]
    rain, ndvi = load(a.rain_file or RAIN_URL), load(a.ndvi_file or NDVI_URL)
    r = latest(rain, pcodes, ["rfh", "r1q", "r3q", "rfq"]); v = latest(ndvi, pcodes, ["viq", "vim", "vim_avg"])
    rd, vd = r.index.max(), v.index.max()
    out = {
        "area_label": a.label or ("P-code " + ", ".join(pcodes)), "pcodes": pcodes,
        "fetched": str(pd.Timestamp.today().date()),
        "source": "WFP/CHIRPS subnational rainfall and MODIS NDVI via HDX (data.humdata.org)",
        "rain": {"dekad": str(rd.date()), **{k: num(r.loc[rd, k]) for k in ["rfh", "r1q", "r3q", "rfq"]}},
        "vegetation": {"dekad": str(vd.date()), **{k: num(v.loc[vd, k]) for k in ["viq", "vim", "vim_avg"]}},
        "history": {"dekads": [str(x.date()) for x in r.index[-6:]], "r3q": [num(x) for x in r["r3q"].iloc[-6:]],
                    "viq_dekads": [str(x.date()) for x in v.index[-6:]], "viq": [num(x) for x in v["viq"].iloc[-6:]]},
        "verified_by_human": False,
        "note": "Observed data, not a forecast. Check the P-code really covers your markets (see tool header).",
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False)); print("\nwritten ->", a.out)


if __name__ == "__main__":
    main()
