"""Climate context for the advisor: ENSO (ONI), Indian Ocean Dipole (DMI) and the official seasonal outlook.

IMPORTANT: this is CONTEXT ONLY. It is shown to the user but does NOT change the sell/hold numbers, because the link
between these signals and drought in Borana has not been tested on local rainfall yet (see rain_enso_iod_skill_test.py).
"""
import json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ONI_FILE = os.environ.get("ONI_FILE", os.path.join(HERE, "data", "enso_oni.txt"))
DMI_FILE = os.environ.get("DMI_FILE", os.path.join(HERE, "data", "iod_dmi.txt"))
OUTLOOK_FILE = os.environ.get("OFFICIAL_OUTLOOK_FILE", os.path.join(HERE, "data", "official_outlook.json"))
SEAS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]   # centre month = index + 1


def _today():
    t = os.environ.get("ASOF_TODAY")
    return pd.Timestamp(t) if t else pd.Timestamp.today().normalize()


def _oni_series():
    rows = []
    for ln in open(ONI_FILE, encoding="utf-8", errors="ignore"):
        p = ln.split()
        if len(p) == 4 and p[0] in SEAS and p[1].isdigit():
            rows.append((pd.Timestamp(int(p[1]), SEAS.index(p[0]) + 1, 1), p[0] + " " + p[1], float(p[3])))
    return pd.DataFrame(rows, columns=["t", "label", "anom"]).set_index("t").sort_index()


def _strength(v):
    a = abs(v)
    return "very strong" if a >= 2.0 else "strong" if a >= 1.5 else "moderate" if a >= 1.0 else "weak"


def enso():
    s = _oni_series()
    last = s.iloc[-1]; t = s.index[-1]; v = float(last.anom)
    phase = "El Nino" if v >= 0.5 else "La Nina" if v <= -0.5 else "neutral"
    out = {"season": last.label, "oni": round(v, 2), "phase": phase,
           "strength": _strength(v) if phase != "neutral" else None,
           "age_days": int((_today() - t).days), "source_file": os.path.basename(ONI_FILE)}
    if phase == "El Nino" and v >= 1.5:     # what has usually followed strong El Ninos, counted from the file itself
        n = hit = 0
        for y in range(int(s.index.year.min()), int(s.index.year.max()) - 1):
            pk = s.loc[pd.Timestamp(y, 9, 1):pd.Timestamp(y + 1, 2, 1), "anom"]
            if len(pk) == 0 or pk.max() < 1.5:
                continue
            after = s.loc[pd.Timestamp(y + 1, 3, 1):pd.Timestamp(y + 2, 12, 1), "anom"]
            if len(after) < 12:
                continue
            n += 1; hit += int(after.min() <= -0.5)
        if n:
            out["strong_el_nino_history"] = {"events": n, "followed_by_la_nina_within_2y": hit,
                "note": "In %d of %d past strong El Nino events the ONI later fell to La Nina levels (<= -0.5). "
                        "La Nina is usually DRY for southern Ethiopia, so risk can rise in 2027 even though 2026 is wet. "
                        "This is a historical pattern, not a forecast." % (hit, n)}
    return out


IOD_LIVE_FILE = os.environ.get("IOD_LIVE_FILE", os.path.join(HERE, "data", "iod_live.json"))
IOD_LIVE_STALE_DAYS = 21


def _iod_from_file():
    """Monthly DMI history file (usually months out of date)."""
    last = None
    for ln in open(DMI_FILE, encoding="utf-8", errors="ignore"):
        p = ln.split()
        if len(p) == 13 and p[0].isdigit():
            for i, x in enumerate(p[1:], start=1):
                if float(x) > -900:
                    last = (int(p[0]), i, float(x))
    if last is None:
        return {"status": "unavailable"}
    y, m, v = last
    age = int((_today() - pd.Timestamp(y, m, 1)).days)
    phase = "positive" if v >= 0.4 else "negative" if v <= -0.4 else "neutral"
    return {"month": "%d-%02d" % (y, m), "dmi": round(v, 2), "phase": phase, "age_days": age,
            "stale": age > 90, "source_file": os.path.basename(DMI_FILE),
            "note": ("This DMI file stops in %d-%02d, so it cannot show the current state of the Indian Ocean Dipole. "
                     "Use a faster-updating source for live monitoring." % (y, m)) if age > 90 else None}


def _iod_live():
    """Hand-entered weekly BoM reading (data/iod_live.json). Returns None if absent/unreadable."""
    try:
        j = json.load(open(IOD_LIVE_FILE, encoding="utf-8"))
        v = float(j["value"]); thr = float(j.get("threshold", 0.4))
        age = int((_today() - pd.Timestamp(j["week_ending"])).days)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {"month": j["week_ending"], "dmi": round(v, 2),
            "phase": "positive" if v >= thr else "negative" if v <= -thr else "neutral",
            "age_days": age, "stale": age > IOD_LIVE_STALE_DAYS, "live": True, "source": j.get("source"),
            "weeks_above_threshold": j.get("weeks_above_threshold"), "outlook": j.get("outlook"),
            "verified_by_human": bool(j.get("verified_by_human")),
            "note": ("This reading is %d days old: update data/iod_live.json from the BoM page." % age) if age > IOD_LIVE_STALE_DAYS else None}


def iod():
    """Prefer the weekly live reading; fall back to the (older) DMI file. The old file is kept for reference."""
    live = _iod_live()
    try:
        old = _iod_from_file()
    except Exception as ex:
        old = {"status": "unavailable", "error": str(ex)[:80]}
    if live is None:
        return old
    live["history_file"] = {k: old.get(k) for k in ("month", "dmi", "age_days", "stale")}
    return live


def official_outlook():
    try:
        o = json.load(open(OUTLOOK_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unavailable"}
    try:
        o["age_days"] = int((_today() - pd.Timestamp(o["issued"])).days)
    except Exception:
        o["age_days"] = None
    return o


OBS_FILE = os.environ.get("CURRENT_CONDITIONS_FILE", os.path.join(HERE, "data", "current_conditions.json"))


def observed():
    """Observed rainfall / vegetation (written by tools/fetch_current_conditions.py). Observed, not forecast."""
    try:
        o = json.load(open(OBS_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "not_loaded", "how": "Run tools/fetch_current_conditions.py to load observed rainfall and vegetation."}
    today = _today()
    for key in ("rain", "vegetation"):
        try:
            o[key]["age_days"] = int((today - pd.Timestamp(o[key]["dekad"])).days)
        except Exception:
            o[key]["age_days"] = None
    ages = [o[k].get("age_days") for k in ("rain", "vegetation") if o.get(k, {}).get("age_days") is not None]
    o["stale"] = (not ages) or max(ages) > 30
    r3, vi = o.get("rain", {}).get("r3q"), o.get("vegetation", {}).get("viq")
    # display words only (simple thresholds, NOT used in the advice): 85% matches the vegetation-stress line in your notebook
    dry = (r3 is not None and r3 < 75) or (vi is not None and vi < 85)
    watch = (r3 is not None and r3 < 90) or (vi is not None and vi < 95)
    o["reading"] = None if (r3 is None and vi is None) else ("dry" if dry else "below average" if watch else "near or above average")
    return o


def context():
    try:
        e = enso()
    except Exception as ex:                          # never let context break the advice
        e = {"status": "unavailable", "error": str(ex)[:80]}
    try:
        i = iod()
    except Exception as ex:
        i = {"status": "unavailable", "error": str(ex)[:80]}
    return {"affects_advice": False,
            "why_not": "Context only. The link between these signals and Borana drought has not been tested on local rainfall yet.",
            "enso": e, "iod": i, "official_outlook": official_outlook(), "observed": observed()}
