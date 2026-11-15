# Review of Livestock_Forecasting.ipynb and pnis_livestock_stress_model.pkl

## What it actually is
- **Data:** WFP/CHIRPS rainfall and MODIS NDVI vegetation, per Ethiopian administrative area, every 10 days (dekad). Good, official sources.
- **Target:** `Livestock_Stress_Target` / `Future_Stress` = "vegetation anomaly (`viq`) below 85% of average, in the NEXT 10-DAY period".
  That is a **vegetation** measure. No livestock data (deaths, weight, sales, prices) is used anywhere in the notebook.
- **Horizon:** 10 days. The destocking advisor needs about 3 months.

## Problems found (from the notebook's own outputs)
1. **"Livestock stress / mortality" is not measured.** The API labels outputs "MODERATE THINNING RISK" and "CRITICAL MORTALITY RISK". Nothing in the notebook links
   vegetation anomalies to thinning or death. The 0.25 / 0.50 / 0.27 cut-offs are hard-coded in the API cell and not derived from any analysis.
2. **The perfect scores are leakage.** Cell 8 predicts `viq < 85` using `viq` itself (same row): precision/recall 1.00 is trivial. Cell 10's identical
   "1.00" report has the same test sizes as cell 8 (20,784 / 741), and the execution order (cell 9 = 15, cell 8 = 24, cell 10 = 25) shows cell 10 reused cell 8's leaked split.
3. **The only honest test (cell 9: time split, no `viq`) is weak:** for stress events, precision 0.18 and recall 0.36 (the stress rate in the test years is 4.8%).
4. **Accuracy 0.978 is meaningless here.** Only 3,706 of 107,625 rows (3.4%) are "stress", so predicting "no stress" always scores 96.6%. One fold (0.934) is below that.
5. **The saved model includes today's `viq` and its rolling means** to predict next-dekad `viq`. That is mostly persistence ("greenness stays as it is"). It was never compared with a persistence or climatology baseline.
6. **Calibration was done on the training rows** (`cv='prefit'` fitted on the same X, y). So the probabilities are in-sample and overconfident: the model returns almost exactly 0 or 1 for arbitrary inputs.
7. **Smaller issues:** `fillna(0)` turns missing rainfall/vegetation into "zero"; `shift(-1)` in cell 11 runs across region boundaries; the spatial cross-validation ignores time.

## Verdict
Do not connect the .pkl to the advisor. It does not predict livestock outcomes, it looks 10 days ahead, and its accuracy is not demonstrated.

## What was kept from it (the useful part)
- The **data source**: `tools/fetch_current_conditions.py` loads the latest observed 3-month rainfall (% of average) and vegetation (% of average) for your area and the app shows them
  as "Observed conditions" (context only). Observed conditions are more trustworthy than a model that was never validated.
- `tools/stress_model_honest_check.py` re-tests the model idea fairly (baselines, time blocks, 10-day / 1-month / 3-month horizons, calibration on separate years, year-block bootstrap).
  Run it in Colab. If a model does not clearly beat persistence at the 3-month horizon, drop it.

## To make a real livestock model you would need
Actual outcome data: livestock mortality or body-condition surveys (e.g. from the zone livestock office, FEWS NET, WFP/ILRI index-insurance records, or NMIS price drops) at zone level, matched to the dekad data.
