from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Any


OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOURCE_NAME = "ERA5-Land historical reanalysis via Open-Meteo"
SOURCE_URL = "https://open-meteo.com/en/docs/historical-weather-api"
REGIONS = {
    "Afar": {"latitude": 11.75, "longitude": 41.0},
    "Somali": {"latitude": 9.35, "longitude": 42.8},
    "Mekele": {"latitude": 13.4967, "longitude": 39.4753},
    "Borena": {"latitude": 4.9, "longitude": 38.5},
    "Gambela": {"latitude": 8.25, "longitude": 34.6},
    "Gonder": {"latitude": 12.6, "longitude": 37.47},
    "Wag-Himra": {"latitude": 12.9, "longitude": 38.4},
    "Yabello": {"latitude": 4.88, "longitude": 38.08},
    "Oromia": {"latitude": 8.5, "longitude": 39.2},
    "Amhara": {"latitude": 11.4, "longitude": 37.9},
    "SNNPR": {"latitude": 7.0, "longitude": 37.9},
    "Tigray": {"latitude": 13.5, "longitude": 39.5},
    "Dire Dawa": {"latitude": 9.6, "longitude": 41.86},
    "Harari": {"latitude": 9.3, "longitude": 42.13},
}
DAILY_VARIABLES = (
    "precipitation_sum,temperature_2m_mean,et0_fao_evapotranspiration"
)


def build_archive_params(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    daily: str = DAILY_VARIABLES,
) -> dict[str, str | float]:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": daily,
        "timezone": "UTC",
    }


def aggregate_observations(payload: dict[str, Any]) -> dict[str, Any]:
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    precipitation = daily.get("precipitation_sum") or []
    temperature = daily.get("temperature_2m_mean") or []
    evapotranspiration = daily.get("et0_fao_evapotranspiration") or []

    if not dates or not (
        len(dates) == len(precipitation) == len(temperature) == len(evapotranspiration)
    ):
        raise ValueError("The climate provider returned incomplete daily data.")

    return {
        "dates": dates,
        "precipitation_mm": precipitation,
        "temperature_c": temperature,
        "et0_mm": evapotranspiration,
        "summary": {
            "precipitation_90d_mm": _sum_available(precipitation),
            "mean_temperature_90d_c": _mean_available(temperature),
            "et0_90d_mm": _sum_available(evapotranspiration),
            "days": len(dates),
        },
    }


def compare_rainfall_to_history(
    daily_payload: dict[str, Any], assessment_date: date, years: int = 10
) -> dict[str, Any]:
    daily = daily_payload.get("daily") or {}
    dates = daily.get("time") or []
    precipitation = daily.get("precipitation_sum") or []
    if len(dates) != len(precipitation):
        raise ValueError("The climate provider returned incomplete rainfall data.")

    rainfall_by_date = dict(zip(dates, precipitation))
    current_total, current_days = _rainfall_window(rainfall_by_date, assessment_date)
    if current_days < 75:
        raise ValueError(
            "The selected 90-day period has too many missing rainfall observations."
        )

    historical_totals = []
    for offset in range(1, years + 1):
        try:
            historical_end = assessment_date.replace(year=assessment_date.year - offset)
        except ValueError:
            historical_end = assessment_date.replace(
                year=assessment_date.year - offset, day=28
            )
        total, valid_days = _rainfall_window(rainfall_by_date, historical_end)
        if valid_days >= 75:
            historical_totals.append(total)

    if len(historical_totals) < 5:
        raise ValueError(
            "At least five complete historical comparison periods are required."
        )

    historical_mean = mean(historical_totals)
    if historical_mean <= 0:
        raise ValueError("Historical rainfall baseline is not usable.")

    ratio = current_total / historical_mean
    percentile = 100 * sum(value <= current_total for value in historical_totals) / len(
        historical_totals
    )
    if ratio < 0.4:
        category = "Severe rainfall shortfall"
    elif ratio < 0.6:
        category = "Major rainfall shortfall"
    elif ratio < 0.8:
        category = "Moderate rainfall shortfall"
    else:
        category = "Near or above historical baseline"

    return {
        "period_start": (assessment_date - timedelta(days=89)).isoformat(),
        "period_end": assessment_date.isoformat(),
        "current_rainfall_mm": round(current_total, 1),
        "historical_mean_mm": round(historical_mean, 1),
        "difference_percent": round((ratio - 1) * 100, 1),
        "historical_percentile": round(percentile, 1),
        "comparison_years": len(historical_totals),
        "category": category,
        "indicator_type": "retrospective_rainfall_comparison",
        "caveat": (
            "This compares observed rainfall with historical rainfall for the same "
            "calendar period. The shortfall categories are uncalibrated screening "
            "thresholds, not a drought diagnosis or a future forecast."
        ),
    }


def build_forecast_summary(
    region: str, weather_payload: dict[str, Any], assessment_date: date
) -> dict[str, Any]:
    comparison = compare_rainfall_to_history(weather_payload, assessment_date)
    baseline = max(comparison["historical_mean_mm"], 1.0)
    current = comparison["current_rainfall_mm"]
    risk_score = max(0.0, min(100.0, 100.0 * (1.0 - (current / baseline))))
    if risk_score < 20:
        risk_level = "Low"
    elif risk_score < 45:
        risk_level = "Moderate"
    elif risk_score < 70:
        risk_level = "High"
    else:
        risk_level = "Severe"

    horizons = [
        {
            "label": "0-3 months",
            "risk_score": round(min(100.0, risk_score * 0.92), 1),
            "priority": "Immediate response",
        },
        {
            "label": "3-6 months",
            "risk_score": round(min(100.0, risk_score * 1.08), 1),
            "priority": "Preparedness",
        },
        {
            "label": "6-12 months",
            "risk_score": round(min(100.0, risk_score * 1.18), 1),
            "priority": "Adaptive planning",
        },
        {
            "label": "12-18 months",
            "risk_score": round(min(100.0, risk_score * 1.3), 1),
            "priority": "Resilience investment",
        },
    ]

    return {
        "region": region,
        "assessment_date": assessment_date.isoformat(),
        "risk_score": round(risk_score, 1),
        "risk_level": risk_level,
        "comparison": comparison,
        "horizons": horizons,
        "model_type": "observed-rainfall-baseline-risk-model",
        "generated_by": "Observed rainfall anomaly baseline model",
        "caveat": (
            "This is a transparent baseline risk estimate derived from the last 90 days "
            "of rainfall versus historical analog periods. It is not a validated operational "
            "forecast or a drought diagnosis."
        ),
    }


def generate_policy_recommendations(
    region: str, risk_level: str, risk_score: float
) -> list[dict[str, str | float]]:
    if risk_level == "Severe":
        priorities = [
            ("Immediate water allocation", "Prioritize critical water supply, emergency feed, and fodder logistics for vulnerable households and herders."),
            ("Agricultural support", "Fast-track seed, livestock, and cash support programs to reduce crop and herd losses."),
            ("Monitoring", "Increase field inspections and community reporting to catch deteriorating conditions before they escalate."),
        ]
    elif risk_level == "High":
        priorities = [
            ("Irrigation and resilience", "Expand water-saving irrigation and targeted livestock water support in the most affected communities."),
            ("Food security reserves", "Trigger regional buffer stocks and strengthen local market monitoring for staple goods."),
            ("Risk communication", "Issue early warnings and public advisories with clear action steps for farmers and pastoralists."),
        ]
    elif risk_level == "Moderate":
        priorities = [
            ("Preparedness planning", "Prepare contingency budgets and local response plans that can be activated if rainfall remains weak."),
            ("Seed and input support", "Prioritize drought-tolerant seeds, soil moisture protection, and fodder planning."),
            ("Infrastructure review", "Review water and recharge infrastructure reliability before the next dry season.") ,
        ]
    else:
        priorities = [
            ("Maintain surveillance", "Keep observing rainfall and soil moisture to ensure early detection of emerging stress."),
            ("Protect livelihood buffers", "Support diversified crop and livestock options to reduce exposure to volatility."),
            ("Targeted readiness", "Prepare community, water, and food-response protocols for rapidly changing conditions.") ,
        ]

    return [
        {
            "title": f"{region} risk outlook",
            "priority": title,
            "action": description,
            "risk_score": round(risk_score, 1),
            "risk_level": risk_level,
        }
        for title, description in priorities
    ]


def _rainfall_window(
    rainfall_by_date: dict[str, Any], period_end: date
) -> tuple[float, int]:
    values = [
        rainfall_by_date.get((period_end - timedelta(days=day)).isoformat())
        for day in range(90)
    ]
    valid_values = [value for value in values if value is not None]
    return sum(valid_values), len(valid_values)


def _sum_available(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return round(sum(available), 1) if available else None


def _mean_available(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return round(mean(available), 1) if available else None
