"""The 'sell or hold?' advice engine.

Plain-language idea (an 'optimal stopping' problem):
  Every month you can SELL an animal at today's price or WAIT one more month. Waiting can pay more (the animal may
  fatten if rains are good) but costs (feed, water), risks (animal gets thinner or dies) and can hurt (if everyone
  waits and then sells at once, the market crashes). We work backwards from the end of a 3-month window and compare
  "wait" with "sell now".  waiting_value / sell_now_value  ->  hold, or sell 25% / 50% / 75%.

What is REAL and what is ASSUMED:
  - Real (NMIS file): current price per market, thin/medium/fat price gaps, price-based selling-pressure proxy.
  - Assumed (assumptions.json): death rates, thinning chances, pressure effect, holding cost, decision thresholds.
  - Price drift: estimated, but a backtest showed it does not beat 'no change', so it is 0 by default.

Honesty features (added after review):
  - status: live_model / cached_file / scenario / unavailable. If the drought forecast is unavailable or too old the
    headline advice is clearly marked 'IF NORMAL CONDITIONS' and a table shows the advice for every drought scenario.
  - Confidence is split in three: data quality, drought forecast, decision stability (does the advice change when the
    assumptions are nudged up/down?). The overall confidence is the WEAKEST of them.
"""
import copy
import json
import os
import numpy as np
from data_store import GRADES, get_store, region_info
from drought_provider import get_outlook
import texts

HERE = os.path.dirname(os.path.abspath(__file__))
A = json.load(open(os.path.join(HERE, "assumptions.json"), encoding="utf-8"))
K_REFERENCE = A["price_drop_per_full_unit_of_extra_pressure"]          # the unproven 'market crash' strength
APPLY_CRASH_EFFECT = bool(A.get("apply_crash_effect_in_headline", False))
if not APPLY_CRASH_EFFECT:
    A["price_drop_per_full_unit_of_extra_pressure"] = 0.0              # headline advice does NOT rely on the unproven crash effect
A_WITH_CRASH = copy.deepcopy(A)
A_WITH_CRASH["price_drop_per_full_unit_of_extra_pressure"] = K_REFERENCE
MAX_PRICE_AGE_OK = int(os.environ.get("MAX_PRICE_AGE_DAYS", "30"))     # prices older than this (vs TODAY) cap data confidence
SEV = A["severity_names"]
ACTIONS = ["hold", "sell_25", "sell_50", "sell_75"]
MAX_HERD = 5000          # animals per request; larger numbers are not realistic for one household/herd group
LEVELS = ["low", "medium", "high"]
ASSUMPTIONS_VALIDATED = False   # death/thinning/cost numbers are not yet checked against local Borana data -> overall confidence never "high"


def _wait_value(P0, g0, H, sev, drift, pressure0, p):
    """Expected value per animal of the best stop-or-wait plan if drought severity `sev` lasts the whole window.
    Returns (value_of_waiting, best_month_if_condition_unchanged)."""
    mort = [p["monthly_mortality_by_severity"][g][sev] for g in GRADES]
    p_thin = p["monthly_chance_animal_gets_thinner_by_severity"][sev]
    p_fat = p["monthly_chance_animal_gets_fatter_by_severity"][sev]
    push = p["monthly_extra_selling_pressure_by_severity"][sev]
    k = p["price_drop_per_full_unit_of_extra_pressure"]
    hold_cost = p["monthly_holding_cost_fraction_of_price_by_severity"][sev]

    def price(g, t):
        extra = min(push * t, 1.0 - pressure0) if t > 0 else 0.0
        return P0[g] * (1 + drift) ** t * (1 - k * extra)

    V = {g: price(g, H) for g in range(3)}          # forced sale at end of window
    rows = []
    for t in range(H - 1, -1, -1):
        newV, stop_g0 = {}, None
        for g in range(3):
            down, up = max(g - 1, 0), min(g + 1, 2)
            exp_next = p_thin * V[down] + p_fat * V[up] + (1 - p_thin - p_fat) * V[g]
            wait = (1 - mort[g]) * exp_next - hold_cost * price(g, t)
            sell = price(g, t)
            newV[g] = max(sell, wait)
            if g == g0:
                stop_g0 = (sell >= wait, wait)
        V = newV
        rows.append((t, stop_g0))
    wait_now = rows[-1][1][1]
    best_m = H
    for t, (sell_ok, _) in sorted(rows):
        if t > 0 and sell_ok:
            best_m = t
            break
    return wait_now, best_m


def _action_from_ratio(r, p):
    th = p["decision_thresholds_hold_value_divided_by_sell_now_value"]
    if r >= th["hold_if_at_least"]:
        return "hold"
    if r >= th["sell_25_if_at_least"]:
        return "sell_25"
    if r >= th["sell_50_if_at_least"]:
        return "sell_50"
    return "sell_75"


def _decide(P0, g0, probs, drift, pressure0, p):
    """Mixture over drought severities -> (action, wait/sell ratio, best month)."""
    H = p["horizon_months"]
    vals, months = [], []
    for s in range(4):
        w, m = _wait_value(P0, g0, H, s, drift, pressure0, p)
        vals.append(w)
        months.append(m)
    wait = float(sum(q * w for q, w in zip(probs, vals)))
    best = int(round(sum(q * m for q, m in zip(probs, months))))
    r = wait / P0[g0]
    return _action_from_ratio(r, p), r, best, wait


def _perturbed(p, group, factor):
    q = copy.deepcopy(p)
    if group == "mortality":
        for g in GRADES:
            q["monthly_mortality_by_severity"][g] = [min(x * factor, 0.5) for x in q["monthly_mortality_by_severity"][g]]
    elif group == "thinning":
        q["monthly_chance_animal_gets_thinner_by_severity"] = [min(x * factor, 0.9) for x in q["monthly_chance_animal_gets_thinner_by_severity"]]
    elif group == "holding_cost":
        q["monthly_holding_cost_fraction_of_price_by_severity"] = [x * factor for x in q["monthly_holding_cost_fraction_of_price_by_severity"]]
    elif group == "crash_effect":
        q["price_drop_per_full_unit_of_extra_pressure"] = K_REFERENCE * factor      # absolute: tests "what if a crash effect exists?"
        q["monthly_extra_selling_pressure_by_severity"] = [x * factor for x in q["monthly_extra_selling_pressure_by_severity"]]
    return q


PERTURB_GROUPS = ["mortality", "thinning", "holding_cost", "crash_effect"]


def robustness(P0, g0, probs, drift, pressure0, base_action, p=A):
    """Nudge each uncertain assumption down/up by 50% and, separately, shift monthly price drift by -/+1%.
    Returns (label, how many of the 10 variants gave the same action, the actions seen)."""
    seen = [base_action]
    for grp in PERTURB_GROUPS:
        for f in (0.5, 1.5):
            seen.append(_decide(P0, g0, probs, drift, pressure0, _perturbed(p, grp, f))[0])
    for shift in (-0.01, 0.01):
        seen.append(_decide(P0, g0, probs, drift + shift, pressure0, p)[0])
    idx = [ACTIONS.index(a) for a in seen]
    spread = max(idx) - min(idx)
    label = "high" if spread == 0 else "medium" if spread == 1 else "low"
    same = sum(1 for a in seen[1:] if a == base_action)
    return label, same, sorted(set(seen), key=ACTIONS.index)


def _severity_probs(outlook, severity_override):
    """Returns (probs, status). status in scenario / live_model / cached_file / unavailable."""
    if severity_override is not None:
        probs = [0.0] * 4
        probs[int(severity_override)] = 1.0
        return probs, "scenario"
    if outlook is None:
        return [1.0, 0.0, 0.0, 0.0], "unavailable"       # only used to show 'if normal'; clearly flagged
    probs = [float(outlook.get(n, 0.0)) for n in SEV]
    s = sum(probs)
    return [x / s for x in probs], outlook.get("_status", "cached_file")


def advise(market, grade, herd=1, lang="en", severity=None):
    store = get_store()
    if grade not in GRADES:
        raise ValueError("grade must be one of %s" % GRADES)
    herd = 1 if herd is None else int(herd)
    if not (1 <= herd <= MAX_HERD):
        raise ValueError("number of animals must be between 1 and %d" % MAX_HERD)
    lv = store.price_level(market)
    if lv is None:
        raise ValueError("no price data for market '%s'" % market)
    level, n_used, window, last_rec = lv
    ratio = store.grade_ratio
    g0 = GRADES.index(grade)
    P0 = {i: level * ratio[GRADES[i]] for i in range(3)}
    price_now = P0[g0]

    outlook = get_outlook(market)
    probs, status = _severity_probs(outlook, severity)
    pressure0, price_chg, n_mk = store.pressure(market)
    drift = store.drift

    action, r, best_month, wait_value = _decide(P0, g0, probs, drift, pressure0, A)
    # advice under each single drought scenario (useful when the forecast is missing or uncertain)
    scen = []
    for s in range(4):
        one = [0.0] * 4
        one[s] = 1.0
        a_s, r_s, _, _ = _decide(P0, g0, one, drift, pressure0, A)
        scen.append({"severity": s, "name": texts.SEV_NAME[lang if lang in texts.SEV_NAME else "en"][s], "action": a_s,
                     "title": texts.SHORT_ACTION[a_s]["en" if lang == "am" else lang if lang in ("en", "om") else "en"],
                     "wait_vs_sell_now_ratio": round(r_s, 3)})
    rob_label, rob_same, rob_seen = robustness(P0, g0, probs, drift, pressure0, action)
    crash_action, crash_ratio, _, _ = _decide(P0, g0, probs, drift, pressure0, A_WITH_CRASH)

    # ---- confidence in three parts; overall = weakest ----
    days_old = int((store.today() - last_rec).days)            # age of this market's newest price vs TODAY
    file_age = store.data_age_days()
    score = (2 if n_used >= 6 else 1 if n_used >= 3 else 0) + (1 if days_old <= 21 else 0) + (1 if window <= 90 else 0)
    data_conf = "high" if score >= 3 else "medium" if score >= 2 else "low"
    prices_stale = days_old > MAX_PRICE_AGE_OK or file_age > MAX_PRICE_AGE_OK
    if prices_stale:
        data_conf = "low"                                      # old prices can never look trustworthy
    scope = (outlook or {}).get("_scope")
    age = (outlook or {}).get("_age_days")
    if status == "scenario":
        drought_conf = None                                   # a chosen scenario is not a prediction
    elif status == "unavailable":
        drought_conf = "low"
    elif status == "cached_file":
        drought_conf = "medium" if (age is not None and age <= 7) else "low"
    else:                                                     # live model: capped at medium until validated
        drought_conf = "medium"
    climatology_only = bool(outlook) and outlook.get("_skill") == "climatology_only"
    if climatology_only and drought_conf is not None:
        drought_conf = "low"                                  # historical average only: no real information about the coming months
    parts = {"data": data_conf, "drought": drought_conf, "robustness": rob_label}
    overall = min([v for v in parts.values() if v], key=LEVELS.index)
    if not ASSUMPTIONS_VALIDATED and overall == "high":
        overall = "medium"

    L = lang if lang in ("en", "om", "am") else "en"
    T = texts.REASON
    p_bad = probs[2] + probs[3]
    reasons = [T["price"][L].format(market=market, price=int(round(price_now, -2)), grade=texts.GRADE_NAME[grade][L]),
               T["data_basis"][L].format(n=n_used, w=window, d=days_old)]
    if status == "unavailable":
        reasons.append(T["drought_unavailable"][L])
    elif status == "scenario":
        reasons.append(T["scenario_mode"][L].format(name=texts.SEV_NAME[L][int(severity)]))
    else:
        if climatology_only:
            reasons.append(T["climatology_only"][L])
        elif status == "cached_file":
            reasons.append(T["drought_cached"][L].format(age=age if age is not None else "?"))
        reasons.append(T["drought_high"][L] if p_bad >= 0.4 else T["drought_low"][L] if p_bad <= 0.15 else T["drought_mid"][L])
        if scope == "region":
            reasons.append(T["regional_outlook"][L].format(region=region_info(market)["region"]))
    pct = abs(r - 1) * 100
    reasons.append((T["hold_better"] if r >= 1 else T["sell_better"])[L].format(pct=pct))
    if pressure0 >= 0.25:
        reasons.append(T["pressure_high"][L])
    if action != "hold" and (g0 == 0 or herd > 1):
        reasons.append(T["thin_first"][L])
    if action == "hold" and status != "unavailable":
        reasons.append(T["best_month"][L].format(m=max(best_month, 1)))
    if rob_label == "low":
        reasons.append(T["fragile"][L])
    if n_used < 3 or days_old > 45 or prices_stale:
        reasons.append(T["low_data"][L])

    title = texts.ACTION_TITLE[action][L] + (texts.IF_NORMAL[L] if status == "unavailable" else "")
    lab = lambda c: None if c is None else texts.CONF[c][L]
    return {
        "market": market, "grade": grade, "herd": herd, "lang": L, "status": status,
        "conditional": status == "unavailable",
        "action": action, "action_title": title,
        "sell_fraction": {"hold": 0, "sell_25": 0.25, "sell_50": 0.5, "sell_75": 0.75}[action],
        "price_now_per_animal": int(round(price_now, -2)),
        "expected_value_if_waiting_per_animal": int(round(wait_value, -2)),
        "wait_vs_sell_now_ratio": round(r, 3),
        "best_month_to_sell_if_unchanged": best_month,
        "herd_value_now": int(round(price_now * herd, -3)),
        "confidence": overall, "confidence_label": texts.CONF[overall][L],
        "confidence_parts": {k: {"level": v, "label": lab(v)} for k, v in parts.items()},
        "decision_stability": {"same_action_in_variants": rob_same, "variants_tested": 10, "actions_seen": rob_seen},
        "scenarios": scen,
        "prices_stale": prices_stale, "price_age_days": days_old, "file_age_days": file_age,
        "crash_effect_in_headline": APPLY_CRASH_EFFECT,
        "if_market_crash_effect_is_real": {"action": crash_action, "wait_vs_sell_now_ratio": round(crash_ratio, 3),
                                           "note": "UNPROVEN assumption (no local evidence yet). Shown for information; the headline does not use it."},
        "reasons": reasons,
        "inputs": {
            "drought_status": status, "drought_probs": dict(zip(SEV, [round(q, 3) for q in probs])), "drought_scope": scope,
            "drought_age_days": age, "selling_pressure": round(pressure0, 3), "recent_price_change_used": price_chg,
            "markets_in_pressure_calc": n_mk, "price_records_used": n_used, "price_window_days": window,
            "days_since_last_record": days_old, "monthly_price_drift_used": round(drift, 4),
            "grade_price_ratio": {k: round(v, 3) for k, v in ratio.items()},
        },
    }
