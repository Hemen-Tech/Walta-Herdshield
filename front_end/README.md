# Walta HerdShield climate observation MVP

This climate dashboard fetches observed historical weather estimates instead of inventing dashboard values or random "forecast" probabilities. In the containing project it is served by the Flask app, which registers the climate endpoints from `climate_api.py`. The `backend/` package is also included for standalone FastAPI use.

## Run on Windows

From the project directory, create and activate a virtual environment, install dependencies, and start the application:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

For standalone FastAPI use, run the commands below from this directory and open `http://127.0.0.1:8000/`. In the containing project, use `python app.py` and open `http://127.0.0.1:5000/`; the integrated Flask app serves the frontend and climate API on the same origin.

## Data and behavior

- The API retrieves daily precipitation, mean 2 m temperature, and FAO reference evapotranspiration (ETâ‚€) from the Open-Meteo Historical Weather API, backed by ERA5-Land reanalysis.
- Each listed region is represented by one approximate grid point near a regional center. These are gridded estimates, not station readings or administrative-area averages.
- The dashboard displays a 90-day observed-data window. The provider can have a reporting delay; the API limits the default end date to seven days before the current date.
- The rainfall assessment compares a 90-day observed total with up to ten prior matching calendar periods. Its shortfall bands are uncalibrated screening thresholds, not a trained or validated drought model, and do not predict future conditions.
- The app now includes a transparent baseline forecast endpoint that scores rainfall risk across 0â€“18 month horizons using the recent anomaly relative to the same calendar period in prior years.
- The climate policy page loads dynamic, data-derived recommendations from the forecast signal for the current region.
- The SQLite database stores a 12-hour cache of provider responses and a small model-run archive.
- API outages, invalid responses, and insufficient historical data are shown as errors rather than replaced with synthetic values.

## Data attribution and limitations

Data are provided through [Open-Meteo's Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) and include ERA5-Land data from ECMWF. Open-Meteo's terms specify CC BY 4.0 attribution and restrict use of its free API to non-commercial purposes. Review current [Open-Meteo terms](https://open-meteo.com/en/terms) before deployment or commercial use.

This MVP has no authentication, user roles, operational policy workflow, or trained forecast model. It must not be used by itself for emergency response, resource allocation, or other high-impact decisions. A production forecasting system would need locally validated datasets and labels, spatial coverage beyond representative points, time-aware backtesting, calibrated uncertainty, monitoring, expert review, and a deployment/security plan.

## Tests

```powershell
python -m unittest discover -s tests -v
```
