"""Add recent livestock prices by hand (from the weekly NLMIS report, SMS replies or the zone livestock office) to the price CSV.

1. Make a small CSV with these columns (header row required):   market,grade,min_price,max_price,qty,date
   example:   Yabalo,Moderate Weight,62000,75000,120,2026-10-28
   grade must be one of:  Thin | Moderate Weight | Very Fat      (qty = number of animals, optional)
2. Preview:   python tools/add_prices.py my_new_prices.csv --dry-run
3. Add:       python tools/add_prices.py my_new_prices.csv           (a backup of the old file is saved first)
Rows are checked: valid date (not in the future), min <= max, sensible price range, known market name (typos are suggested), no duplicates.
Rows with problems are SKIPPED and listed, so nothing bad enters the data. Only enter numbers you can trace to a real report.
"""
import argparse, csv, difflib, io, os, shutil, sys
from datetime import date, datetime
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(os.path.dirname(HERE), "data", "Livestock_Market_Table_Data.csv")
GRADES = {"thin": "Thin", "moderate weight": "Moderate Weight", "moderate": "Moderate Weight", "medium": "Moderate Weight",
          "very fat": "Very Fat", "fat": "Very Fat"}
LOW, HIGH = 3000, 400000          # sanity range for one ox, Birr


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("new_csv"); ap.add_argument("--main", default=MAIN); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today", default=None, help="override today's date (tests)")
    a = ap.parse_args()
    today = datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else date.today()
    main_df = pd.read_csv(a.main, dtype=str, encoding="utf-8-sig"); cols = list(main_df.columns)
    if len(cols) != 11: sys.exit("The main CSV must have 11 columns, found %d" % len(cols))
    markets = sorted(set(main_df[cols[0]].dropna())); seen = set(zip(main_df[cols[0]], main_df[cols[6]], main_df[cols[10]]))
    new = pd.read_csv(a.new_csv, dtype=str, skipinitialspace=True); new.columns = [c.strip().lower() for c in new.columns]
    need = {"market", "grade", "min_price", "max_price", "date"}
    if not need <= set(new.columns): sys.exit("Missing columns: %s" % sorted(need - set(new.columns)))
    good, bad = [], []
    for i, r in new.iterrows():
        line, why = i + 2, None
        mk, gr = str(r["market"]).strip(), GRADES.get(str(r["grade"]).strip().lower())
        try:
            dt = datetime.strptime(str(r["date"]).strip(), "%Y-%m-%d").date(); lo, hi = float(r["min_price"]), float(r["max_price"])
            qty = str(r.get("qty", "") or "").strip(); qty = str(int(float(qty))) if qty not in ("", "nan") else ""
        except ValueError:
            bad.append((line, "could not read date/price/qty (date must be YYYY-MM-DD)")); continue
        if mk not in markets:
            sug = difflib.get_close_matches(mk, markets, n=2); why = "unknown market '%s'%s" % (mk, (" - did you mean " + " or ".join(sug) + "?") if sug else " (new markets must be added by hand)")
        elif gr is None: why = "grade must be Thin, Moderate Weight or Very Fat"
        elif dt > today: why = "date is in the future"
        elif lo > hi: why = "min price is higher than max price"
        elif not (LOW <= lo and hi <= HIGH): why = "price outside %d-%d Birr, check the number" % (LOW, HIGH)
        elif hi / lo > 5: why = "max is more than 5x the min, check for a typo"
        elif (mk, gr, str(dt)) in seen: why = "already in the file for that market, grade and date"
        if why: bad.append((line, why)); continue
        seen.add((mk, gr, str(dt)))
        good.append([mk, "Ox(Indegenous)", "N/A", "Uncastrated", "Male", "N/A", gr, "%.2f" % lo, "%.2f" % hi, qty or "1", str(dt)])
    print("rows ok: %d | skipped: %d" % (len(good), len(bad)))
    for line, why in bad: print("  line %d skipped: %s" % (line, why))
    for g in good: print("  + %s | %s | %s-%s | %s" % (g[0], g[6], g[7], g[8], g[10]))
    if a.dry_run or not good: print("(nothing written)"); return
    shutil.copyfile(a.main, a.main + ".backup_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(a.main, "ab") as f:
        buf = io.StringIO(); w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n"); w.writerows(good); f.write(buf.getvalue().encode("utf-8"))
    print("added %d rows to %s (backup saved). Restart the app, or just wait: it reloads when the file changes." % (len(good), a.main))


if __name__ == "__main__":
    main()
