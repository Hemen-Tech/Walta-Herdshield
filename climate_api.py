"""Climate observation API routes used by the dashboard and forecast pages."""

import hashlib
import json
import threading
import time
from datetime import date, timedelta

import requests
from flask import Blueprint, jsonify, request

from climate_data import (
    OPEN_METEO_ARCHIVE_URL,
    REGIONS,
    SOURCE_NAME,
    SOURCE_URL,
    aggregate_observations,
    build_archive_params,
    build_forecast_summary,
    generate_policy_recommendations,
)


bp = Blueprint("climate_api", __name__)
_CACHE_TTL_SECONDS = 12 * 60 * 60
_cache = {}
_cache_lock = threading.Lock()


class ClimateAPIError(Exception):
    def __init__(self, detail, status_code):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@bp.errorhandler(ClimateAPIError)
def handle_climate_api_error(error):
    return jsonify({"detail": error.detail}), error.status_code


def _region_coordinates(region):
    coordinates = REGIONS.get(region)
    if coordinates is None:
        raise ClimateAPIError("Unknown region.", 404)
    return coordinates


def _parse_date(value):
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ClimateAPIError("Date must use the YYYY-MM-DD format.", 422) from exc
    if parsed > date.today():
        raise ClimateAPIError("Date cannot be in the future.", 422)
    return parsed


def _period_end(value=None):
    last_available_day = date.today() - timedelta(days=7)
    period_end = _parse_date(value) if value else last_available_day
    return min(period_end, last_available_day)


def _fetch_daily_data(params):
    cache_key = hashlib.sha256(
        json.dumps(params, sort_keys=True).encode("utf-8")
    ).hexdigest()
    now = time.time()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    try:
        response = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise ClimateAPIError(
            "Climate data provider timed out. Please try again.", 504
        ) from exc
    except requests.HTTPError as exc:
        raise ClimateAPIError(
            f"Climate data provider returned HTTP {exc.response.status_code}.", 502
        ) from exc
    except requests.RequestException as exc:
        raise ClimateAPIError(
            "Could not connect to the climate data provider.", 502
        ) from exc
    except ValueError as exc:
        raise ClimateAPIError(
            "Climate data provider returned invalid JSON.", 502
        ) from exc

    if not isinstance(payload, dict):
        raise ClimateAPIError("Climate data provider returned invalid data.", 502)
    with _cache_lock:
        _cache[cache_key] = (time.time(), payload)
    return payload


def _forecast_data(region, period_end):
    coordinates = _region_coordinates(region)
    params = build_archive_params(
        coordinates["latitude"],
        coordinates["longitude"],
        period_end - timedelta(days=10 * 366 + 89),
        period_end,
    )
    payload = _fetch_daily_data(params)
    try:
        return build_forecast_summary(region, payload, period_end)
    except ValueError as exc:
        raise ClimateAPIError(str(exc), 422) from exc


def sms_regional_summary(region):
    """Return observed 90-day climate and retrospective rainfall screening for SMS."""
    period_end = _period_end()
    coordinates = _region_coordinates(region)
    params = build_archive_params(
        coordinates["latitude"],
        coordinates["longitude"],
        period_end - timedelta(days=10 * 366 + 89),
        period_end,
    )
    payload = _fetch_daily_data(params)
    try:
        risk = build_forecast_summary(region, payload, period_end)
        daily = payload.get("daily") or {}
        dates = daily.get("time") or []
        period_start = period_end - timedelta(days=89)
        indices = [
            index
            for index, value in enumerate(dates)
            if period_start.isoformat() <= value <= period_end.isoformat()
        ]
        recent = {
            "daily": {
                name: [values[index] for index in indices]
                for name, values in daily.items()
                if isinstance(values, list) and len(values) == len(dates)
            }
        }
        observations = aggregate_observations(recent)
    except (TypeError, ValueError, IndexError) as exc:
        raise ClimateAPIError("Climate observations are currently unavailable.", 502) from exc

    return {
        "region": region,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "source": SOURCE_NAME,
        "observations": observations["summary"],
        "risk": {
            "score": risk["risk_score"],
            "level": risk["risk_level"],
            "comparison": risk["comparison"],
            "caveat": risk["caveat"],
        },
    }


@bp.get("/api/health")
def climate_health():
    return jsonify({"status": "ok"})


@bp.get("/api/regions")
def climate_regions():
    return jsonify({"regions": list(REGIONS)})


@bp.get("/api/observations")
def climate_observations():
    region = request.args.get("region", "")
    coordinates = _region_coordinates(region)
    period_end = _period_end(request.args.get("end_date"))
    period_start = period_end - timedelta(days=89)
    params = build_archive_params(
        coordinates["latitude"], coordinates["longitude"], period_start, period_end
    )
    payload = _fetch_daily_data(params)
    try:
        data = aggregate_observations(payload)
    except ValueError as exc:
        raise ClimateAPIError(str(exc), 502) from exc

    return jsonify(
        {
            "region": region,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "licence": "CC BY 4.0; credit Open-Meteo and ECMWF ERA5-Land",
            **data,
        }
    )


@bp.get("/api/forecast")
def climate_forecast():
    region = request.args.get("region", "")
    period_end = _period_end(request.args.get("assessment_date"))
    forecast = _forecast_data(region, period_end)
    return jsonify(
        {
            "region": region,
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "licence": "CC BY 4.0; credit Open-Meteo and ECMWF ERA5-Land",
            **forecast,
        }
    )


@bp.get("/api/policy-recommendations")
def climate_policy_recommendations():
    region = request.args.get("region", "")
    period_end = _period_end(request.args.get("assessment_date"))
    forecast = _forecast_data(region, period_end)
    recommendations = generate_policy_recommendations(
        region, forecast["risk_level"], forecast["risk_score"]
    )
    return jsonify(
        {
            "region": region,
            "assessment_date": forecast["assessment_date"],
            "risk_score": forecast["risk_score"],
            "risk_level": forecast["risk_level"],
            "recommendations": recommendations,
            "caveat": forecast["caveat"],
        }
    )
