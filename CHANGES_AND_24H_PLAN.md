# What was fixed in code (done) and what you must do in 24 hours

## Fixed in code (both `destock_app/` and `herdshield_update/`)
1. **Stale prices now detected.** Freshness is measured against TODAY, not the newest row in the file. Prices older than 30 days
   (env `MAX_PRICE_AGE_DAYS`) force data confidence to LOW and add a reason line. API fields: `prices_stale`, `price_age_days`, `file_age_days`.
   (Today, Nagelle Borana's newest price is already 45 days old and is now flagged.)
2. **CSV reloads automatically** when the file changes (no restart needed).
3. **Unproven "market crash" effect is OFF in the headline advice.** The API still returns `if_market_crash_effect_is_real` for comparison.
   Turn it on only after calibrating: `"apply_crash_effect_in_headline": true` in assumptions.json.
   Effect: severe drought now says "sell 50%" (was 75%) for the tested case; stability checks now include crash-effect variants.
4. **Outlier filter no longer deletes real crashes.** A big price move is kept if another report for the same market+grade within 21 days moved the same way.
   Only isolated jumps and rows whose max is >5x their min (typos like 8,800-87,000) are removed. See `data_report` in /api/meta.
5. **Forecast storage:** set `DROUGHT_FILE` to a persistent path, or (best) host `drought_outlook.json` at a URL and set `DROUGHT_MODEL_URL`.
   POST /api/drought now warns when it saved to a folder that is wiped on restart.
6. **USSD hardening:** set `USSD_SECRET=<long random text>` and give Africa's Talking `https://<host>/ussd/<that text>`; the plain `/ussd` then returns 404.
   Optional `USSD_ALLOWED_IPS`. Rate limit: 40 requests / phone / 10 min (`USSD_RATE_MAX`). In-memory, so per server instance.
7. **18 tests pass** (7 new: stale-price flag, crash effect, secret path, rate limit, 160-char screens, corroborated outliers).

## NOT fixable by code - your 24-hour checklist (in priority order)
1. (30 min) Set Replit/Cloud Run secrets: `ADMIN_KEY`, `USSD_SECRET`; update the Africa's Talking callback URL; republish.
2. (1 h) **Update the CSV** with the newest NMIS export. Nagelle's data ends 22 Sep, Moyale's 21 Jul.
3. (2 h) **Open every source in data/evidence.json**, read the actual numbers, set `checked_by_human` to true only for ones you confirmed.
   Priority: MDPI Climate 2025 (price vs drought), FAO x5553e (herd losses). Remove the Yeda (Amhara) item.
4. (3-4 h) **Drought forecast:** run `borana_drought_outlook.ipynb` in Colab once, upload the resulting JSON. If it says `climatology_only`, leave it:
   the app correctly rates it LOW. Re-run monthly (put a calendar reminder).
5. (2 h) **Ask 2-3 local people** (livestock office / extension agent / a herder) to look at 5 sample advice screens (English and Afaan Oromoo)
   and tell you what is wrong. Ask a native speaker to fix the Oromo/Amharic wording.
6. (1 h) Test the USSD on one real basic phone.
7. Label the launch honestly: "pilot / decision aid, not a validated forecast".

## Do NOT do in 24 hours
- Don't build a backtest against past droughts or rebuild the model. Don't spend time on Probe (optional, low value).
- Don't present the four old demo pages (Dashboard/Forecast/XAI/Policy) as real; link only to the advisor page.

---
# Update 2: climate data you supplied (ONI, DMI, model file)

## Added to the app (both copies, 19 tests pass)
- `climate_signals.py`, `data/enso_oni.txt`, `data/iod_dmi.txt`, `data/official_outlook.json`
- API: `/api/climate`; also `climate` in `/api/meta` and `climate_context` in `/api/advice`
- Dashboard card (English only for now) showing: official ICPAC Oct-Dec 2026 outlook, El Nino/La Nina state, Indian Ocean Dipole state.
- **It is CONTEXT ONLY and does not change sell/hold numbers** (a test enforces this). Reason: the link between these signals and
  Borana drought has not been proven on local rainfall.
- `data/official_outlook.json` is entered from public ICPAC material (found by web search, not read from the full PDF) and is marked
  `verified_by_human: false`. Open the ICPAC statement and the Ethiopian Meteorological Institute outlook, confirm, then set it to true.
- Refresh monthly: replace `enso_oni.txt` (NOAA CPC ONI) and edit `official_outlook.json` when new outlooks come out.

## What the data says right now
- ONI: ASO 2026 = +2.46 -> very strong El Nino. ICPAC (Aug 2026): ~90% chance of wetter-than-normal Oct-Dec rains in southern Ethiopia.
- In 7 of 9 past strong El Nino events (from your ONI file) the ONI later dropped to La Nina levels, which is usually DRY for southern Ethiopia.
  So the bigger destocking risk may be 2027, not now. This is a pattern, not a forecast: ask ICPAC/EMI for the 2027 March-May outlook when issued (Feb).
- The DMI file ends May 2026, so it cannot show the current Indian Ocean Dipole. Use a faster source for live use.

## Not used: pnis_livestock_stress_model.pkl
- Saved with an older scikit-learn; it only loads here with a compatibility shim. It needs 16 satellite inputs (rainfall `rfh/r1h/r3h/rfq...`,
  vegetation `vim/viq...`, rolling means) that the app does not have; and the label it predicts, its training data and its accuracy are not documented.
- On random inputs it returns near-certain 0/1 outputs, a sign of an over-confident model. Do not connect it until you can supply:
  what the target means, the training/test data and a held-out accuracy (precision/recall/Brier), and a live feed of those 16 inputs for Borana.

## tools/rain_enso_iod_skill_test.py
- Your rain test, extended with ONI and DMI, scored on the rainy-season origins (Feb, Sep), year-bootstrap intervals, and a plain table
  of how often Oct-Dec was dry in El Nino / neutral / La Nina Septembers. Needs your six `open-meteo-*.csv` files:
  `python tools/rain_enso_iod_skill_test.py <folder> oni_ascii.txt dmi_had_long_data.txt`
- Smoke-tested on SYNTHETIC rain only (pipeline check, not a result about Borana). With ~28 seasons the test has little power:
  "inconclusive" does not mean "no relationship".

---
# Update 3: your Livestock_Forecasting.ipynb (21 tests pass)

## Verdict on the notebook / .pkl: see STRESS_MODEL_REVIEW.md
The target is a 10-day vegetation anomaly, not livestock; the "1.00" scores are leakage; calibration is in-sample. NOT connected to the advisor.

## What I built from it
- `tools/fetch_current_conditions.py`: pulls observed rainfall and vegetation (same HDX links your notebook used) -> `data/current_conditions.json` -> shown as "Observed conditions".
  YOU MUST: run it with your Borena zone P-code (`--pcode`) because the default ET04 is all of Oromia. Re-run every 10 days / monthly.
- `tools/stress_model_honest_check.py`: fair re-test of the model idea against baselines (run it in Colab; tested only on synthetic data here).
- The advisor's climate card now has observed conditions and is available in English, Amharic and Afaan Oromoo.
  **The Amharic and Oromo text is a machine-written draft: have a native speaker review it.** (Same for `summary_am/om` in `data/official_outlook.json`.)

## Other fixes
- Old demo pages (Dashboard, Forecast, XAI, Policy: simulated numbers) now return 404 and are removed from the menu. Set `SHOW_DEMO_PAGES=1` to show them.
- Removed the duplicate `probe_patch` copy from `herdshield_update/` (single copy in `destock_app/probe_patch/`).
- New tests: observed-conditions reader (incl. stale data), demo pages hidden, en/am/om string sets identical.

## Remaining for YOU (cannot be done in code)
1. Run `fetch_current_conditions.py --pcode <Borena zone code> --label "Borena zone"` and check the numbers look right for your area.
2. Update the price CSV; set env secrets (ADMIN_KEY, USSD_SECRET); update the Africa's Talking callback.
3. Verify `evidence.json` and `official_outlook.json` against the original sources, then set the verified flags.
4. Get a native-speaker check of Amharic / Afaan Oromoo text; run the USSD on one real phone.
5. Decide how "wetter than normal" should map to drought probabilities (needs a local expert), or keep the advisor in scenario mode.
6. Optional: run `tools/rain_enso_iod_skill_test.py` (needs your rainfall CSVs) and `tools/stress_model_honest_check.py` in Colab.

---
# Update 4: getting recent price data

Where the data comes from: Ethiopia's National Livestock Market Information System (NLMIS), run by the Ministry of Trade and Regional Integration.
Prices are collected weekly in roughly 45-56 markets by enumerators using SMS. A Livestock Information System (LIS) web portal shows NLMIS prices
by body condition (Fat / Moderate / ...), the same categories as your CSV. (Not verified by me: I could not open the portal, it blocks automated access.)

Your CSV is read BY COLUMN POSITION: 11 columns in this order: market, breed, area, type, sex, age, grade, min price, max price, quantity, date (YYYY-MM-DD).
Any new export must match that, or be converted.

If you cannot get a file, type recent prices into tools/price_template.csv and run:  python tools/add_prices.py <your file> --dry-run   then without --dry-run.
It rejects typos, reversed prices, future dates and duplicates, and keeps a backup. (22 tests pass.)

---
# Update 5: live Indian Ocean Dipole reading (23 tests pass)

## What changed
- New `data/iod_live.json` = a hand-entered weekly BoM reading. The app now uses it instead of the old DMI file (which ended in May 2026) and shows
  its date, source and the IRI outlook. Readings older than 21 days are flagged stale (warning sign + note). The old file is kept as `history_file`.
- The climate card now adds: "A wet season can also bring floods and animal disease. Ask your local livestock office what to watch for." (en/am/om, drafts for am/om)
- Still CONTEXT ONLY: it does not change sell/hold numbers (tested). The drought forecast stays "climatology only / scenario mode", with no hand-edited probabilities.

## Current reading, safe to copy into your notes (checked against the source pages on 7 Nov 2026)
- Positive Indian Ocean Dipole: +0.69 (BoM, week ending 25 Oct 2026), above +0.4 for 7 weeks in a row; BoM says positive values are forecast to continue.
- Columbia/IRI (Oct 2026 forecast): positive through December, possibly peaking in November, neutral again Jan-Apr 2027.
- Very strong El Nino: ONI +2.46 (ASO 2026, from your file). ICPAC outlook (Aug 2026): ~90% chance of wetter-than-normal Oct-Dec rains in southern Ethiopia.
- Past pattern from your ONI file: 7 of 9 strong El Ninos were followed by La Nina within 2 years (usually dry for southern Ethiopia): a pattern, not a forecast.
  So the March-May 2027 long rains deserve attention.

## NOT checked (do not rely on or publish until you verify)
- "IRI September value +0.51", the ICPAC scientist quote, "2019 East African rainfall 300% above normal".
- "1982, 1997 and 2023 short rains were wetter" and "the signals add only a small gain": those come from another tool's runs on your rainfall file; I have not seen that file.
- Whether floods or disease hurt Borana in past wet years: ask the zone livestock office.

## Routine
- Weekly or fortnightly: update `data/iod_live.json` from bom.gov.au/climate/enso (week_ending, value, weeks_above_threshold).
- About monthly: replace `data/enso_oni.txt` and `data/iod_dmi.txt` with fresh downloads from the same NOAA sources you used before.
- Ask a local livestock officer: "If the short rains are good, what do herders do about feed and selling, and what worries them about 2027?"
