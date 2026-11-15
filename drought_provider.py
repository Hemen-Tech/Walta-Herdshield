"""Where the drought outlook comes from, and a strict check on what we accept.

Your model reports by REGION (Afar, Somali, Oromia), not by town, so every market is mapped to its region
(data/market_regions.json). Borana markets therefore use the OROMIA outlook (coarse: southern Borana can differ).

Accepted formats for one region (any ONE):
    {"No Drought": 0.40, "Mild": 0.30, "Moderate": 0.20, "Severe": 0.10}   # 4 probabilities, each 0-1, sum ~1 (+/-0.05)
    {"label": "Moderate"}                                                   # class only
Optional top-level field  "skill": "climatology_only"  means the numbers are just the historical average (no forecast
skill); the advisor then rates the drought forecast confidence LOW.
Sources, tried in this order (the result says which one was used in `_status`):
 1. env DROUGHT_MODEL_URL : GET <url>?region=Oromia&market=<market>      -> _status "live_model"
 2. data/drought_outlook.json (saved forecast, needs an "updated" date)  -> _status "cached_file"
 3. nothing, or older than MAX_AGE_DAYS                                  -> None (engine says 'unavailable', it never pretends)
If the live URL FAILS, the error is kept in LAST_ERROR and the saved file is used only if it is still fresh.
"""
import datetime
import json
import math
import os
import time
from data_store import region_info

HERE = os.path.dirname(os.path.abspath(__file__))
# Where the saved forecast lives. On Cloud Run/Replit deployments the app folder is wiped on restart, so for a durable
# forecast EITHER point DROUGHT_FILE at a persistent disk path OR (better) host drought_outlook.json at a URL and set
# DROUGHT_MODEL_URL (pull model, nothing is lost on restart).
FILE = os.environ.get("DROUGHT_FILE", os.path.join(HERE, "data", "drought_outlook.json"))
KEYS = ["No Drought", "Mild", "Moderate", "Severe"]
LABELS = {k.lower(): i for i, k in enumerate(KEYS)}
LABELS.update({"none": 0, "no_drought": 0, "normal": 0, "severe drought": 3, "moderate drought": 2, "mild drought": 1})
MAX_AGE_DAYS = int(os.environ.get("DROUGHT_MAX_AGE_DAYS", "14"))
CACHE_SECONDS = 600
LAST_ERROR = None
_cache = {}


def validate(d):
    """Return an error message, or None if `d` is an acceptable outlook for one region."""
    if not isinstance(d, dict):
        return "outlook must be an object"
    if all(k in d for k in KEYS):
        vals = []
        for k in KEYS:
            v = d[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return f"'{k}' must be a number"
            if not math.isfinite(v):
                return f"'{k}' is not a finite number"
            if v < 0 or v > 1:
                return f"'{k}' must be between 0 and 1"
            vals.append(float(v))
        if abs(sum(vals) - 1.0) > 0.05:
            return f"probabilities must add up to about 1 (they add up to {sum(vals):.3f})"
        return None
    if "label" in d:
        return None if str(d["label"]).strip().lower() in LABELS else "unknown label (use No Drought, Mild, Moderate or Severe)"
    return f"need the 4 probabilities {KEYS} or a 'label'"


def parse(d, source, scope):
    """Validated outlook -> 4 probabilities that sum to 1, with metadata. Returns None if invalid."""
    if validate(d) is not None:
        return None
    if all(k in d for k in KEYS):
        out = {k: float(d[k]) for k in KEYS}
    else:
        i = LABELS[str(d["label"]).strip().lower()]
        w = [0.0] * 4
        w[i] = 0.70                       # a class label alone is less certain than probabilities
        for j in (i - 1, i + 1):
            if 0 <= j < 4:
                w[j] += 0.15
        out = dict(zip(KEYS, w))
    t = sum(out.values())
    out = {k: v / t for k, v in out.items()}
    out["_source"] = source
    out["_scope"] = scope
    return out


def _age_days(updated):
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(str(updated)[:10])).days
    except (TypeError, ValueError):
        return None


def status():
    """Small summary for the dashboard/meta endpoint."""
    o = get_outlook("Yabalo")
    return {"status": "unavailable" if o is None else o["_status"], "age_days": None if o is None else o.get("_age_days"),
            "last_error": LAST_ERROR, "max_age_days": MAX_AGE_DAYS}


def get_outlook(market):
    global LAST_ERROR
    region = region_info(market)["region"]
    url = os.environ.get("DROUGHT_MODEL_URL")
    if url:
        key = (region, market)
        if key in _cache and time.time() - _cache[key][0] < CACHE_SECONDS:
            return _cache[key][1]
        try:
            import requests
            r = requests.get(url, params={"region": region, "market": market}, timeout=6)
            r.raise_for_status()
            body = r.json()
            val = parse(body, "model_url", "region")
            if val is None:
                raise ValueError("model returned an invalid outlook: %s" % validate(body))
            age = _age_days(body.get("forecast_date") or body.get("updated")) if isinstance(body, dict) else None
            if age is not None and age > MAX_AGE_DAYS:
                raise ValueError("model forecast is %d days old" % age)
            val.update({"_status": "live_model", "_age_days": age, "_skill": body.get("skill") if isinstance(body, dict) else None})
            _cache[key] = (time.time(), val)
            LAST_ERROR = None
            return val
        except Exception as e:          # do NOT hide it: remember why the live model was not used
            LAST_ERROR = "%s: %s" % (type(e).__name__, e)
    if os.path.exists(FILE):
        try:
            d = json.load(open(FILE, encoding="utf-8"))
            age = _age_days(d.get("updated"))
            if age is None or age > MAX_AGE_DAYS or age < 0:
                return None             # undated or too old: treated as unavailable, never as 'no drought'
            src = d.get("source", "file")
            if market in d.get("markets", {}):
                val = parse(d["markets"][market], src, "market")
            else:
                val = parse(d.get("regions", {}).get(region), src, "region")
            if val is None:
                return None
            val.update({"_status": "cached_file", "_age_days": age, "_skill": d.get("skill")})
            return val
        except Exception as e:
            LAST_ERROR = "%s: %s" % (type(e).__name__, e)
            return None
    return None
