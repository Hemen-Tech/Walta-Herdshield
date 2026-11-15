from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.climate import (
    DAILY_VARIABLES,
    OPEN_METEO_ARCHIVE_URL,
    REGIONS,
    SOURCE_NAME,
    SOURCE_URL,
    aggregate_observations,
    build_archive_params,
    build_forecast_summary,
    compare_rainfall_to_history,
    generate_policy_recommendations,
)
from backend.db import initialize_db, list_model_runs, save_model_run, validate_api_key


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(__file__).resolve().parent / "climate_cache.sqlite3"
CACHE_TTL_SECONDS = 12 * 60 * 60


def initialize_cache() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS climate_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            )
            """
        )


def read_cached_payload(cache_key: str) -> dict[str, Any] | None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT payload, fetched_at FROM climate_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if row is None:
        return None

    import time

    if time.time() - row[1] > CACHE_TTL_SECONDS:
        return None
    return json.loads(row[0])


def cache_payload(cache_key: str, payload: dict[str, Any]) -> None:
    import time

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO climate_cache (cache_key, payload, fetched_at)
            VALUES (?, ?, ?)
            """,
            (cache_key, json.dumps(payload), int(time.time())),
        )


def cached_daily_key(params: dict[str, str | float]) -> str:
    serialized = json.dumps(params, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def fetch_daily_data(params: dict[str, str | float]) -> dict[str, Any]:
    cache_key = cached_daily_key(params)
    cached = read_cached_payload(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(OPEN_METEO_ARCHIVE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504, detail="Climate data provider timed out. Please try again."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Climate data provider returned HTTP {exc.response.status_code}.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the climate data provider.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="Climate data provider returned invalid JSON."
        ) from exc

    cache_payload(cache_key, payload)
    return payload


def region_coordinates(region: str) -> dict[str, float]:
    coordinates = REGIONS.get(region)
    if coordinates is None:
        raise HTTPException(status_code=404, detail="Unknown region.")
    return coordinates


def parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Date must use the YYYY-MM-DD format."
        ) from exc
    if parsed > date.today():
        raise HTTPException(status_code=422, detail="Date cannot be in the future.")
    return parsed


def get_api_key(authorization: str | None = Header(default=None, alias="Authorization")) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def require_admin_api_key(api_key: str | None = Depends(get_api_key)) -> bool:
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Authentication required for admin access.")
    return True


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_cache()
    initialize_db()
    yield


app = FastAPI(
    title="Walta HerdShield Climate Data API",
    description="Local API for observed Ethiopian climate data, rainfall risk baselines, and admin reporting.",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/regions")
async def regions() -> dict[str, list[str]]:
    return {"regions": list(REGIONS)}


@app.get("/api/observations")
async def observations(
    region: str = Query(...),
    end_date: str | None = Query(default=None),
) -> dict[str, Any]:
    coordinates = region_coordinates(region)
    last_available_day = date.today() - timedelta(days=7)
    period_end = parse_date(end_date) if end_date else last_available_day
    if period_end > last_available_day:
        period_end = last_available_day

    period_start = period_end - timedelta(days=89)
    params = build_archive_params(
        coordinates["latitude"], coordinates["longitude"], period_start, period_end
    )
    payload = await fetch_daily_data(params)
    try:
        data = aggregate_observations(payload)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "region": region,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "licence": "CC BY 4.0; credit Open-Meteo and ECMWF ERA5-Land",
        **data,
    }


@app.get("/api/assessment")
async def assessment(
    region: str = Query(...),
    assessment_date: str = Query(...),
) -> dict[str, Any]:
    coordinates = region_coordinates(region)
    period_end = parse_date(assessment_date)
    period_start = period_end - timedelta(days=10 * 366 + 89)
    params = build_archive_params(
        coordinates["latitude"],
        coordinates["longitude"],
        period_start,
        period_end,
        daily="precipitation_sum",
    )
    payload = await fetch_daily_data(params)
    try:
        comparison = compare_rainfall_to_history(payload, period_end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "region": region,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "licence": "CC BY 4.0; credit Open-Meteo and ECMWF ERA5-Land",
        **comparison,
    }


@app.get("/api/forecast")
async def forecast(
    region: str = Query(...),
    assessment_date: str | None = Query(default=None),
) -> dict[str, Any]:
    coordinates = region_coordinates(region)
    last_available_day = date.today() - timedelta(days=7)
    period_end = parse_date(assessment_date) if assessment_date else last_available_day
    if period_end > last_available_day:
        period_end = last_available_day
    period_start = period_end - timedelta(days=10 * 366 + 89)

    params = build_archive_params(
        coordinates["latitude"],
        coordinates["longitude"],
        period_start,
        period_end,
    )
    payload = await fetch_daily_data(params)
    try:
        forecast = build_forecast_summary(region, payload, period_end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    save_model_run(
        region,
        forecast["assessment_date"],
        float(forecast["risk_score"]),
        forecast["risk_level"],
        forecast,
    )

    return {
        "region": region,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "licence": "CC BY 4.0; credit Open-Meteo and ECMWF ERA5-Land",
        **forecast,
    }


@app.get("/api/policy-recommendations")
async def policy_recommendations(
    region: str = Query(...),
    assessment_date: str | None = Query(default=None),
) -> dict[str, Any]:
    last_available_day = date.today() - timedelta(days=7)
    period_end = parse_date(assessment_date) if assessment_date else last_available_day
    if period_end > last_available_day:
        period_end = last_available_day
    coordinates = region_coordinates(region)
    params = build_archive_params(
        coordinates["latitude"],
        coordinates["longitude"],
        period_end - timedelta(days=10 * 366 + 89),
        period_end,
    )
    payload = await fetch_daily_data(params)
    forecast = build_forecast_summary(region, payload, period_end)
    recommendations = generate_policy_recommendations(
        region,
        forecast["risk_level"],
        forecast["risk_score"],
    )
    return {
        "region": region,
        "assessment_date": forecast["assessment_date"],
        "risk_score": forecast["risk_score"],
        "risk_level": forecast["risk_level"],
        "recommendations": recommendations,
        "caveat": forecast["caveat"],
    }


@app.post("/api/admin/login")
async def admin_login(
    payload: dict[str, str] | None = None,
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, str | bool]:
    provided = (payload or {}).get("api_key") if payload else None
    if provided is None:
        provided = api_key
    if not validate_api_key(provided):
        raise HTTPException(status_code=401, detail="Invalid admin API key.")
    return {"status": "authenticated", "valid": True, "key_name": "default_admin"}


@app.get("/api/admin/model-runs")
async def admin_model_runs(_: bool = Depends(require_admin_api_key)) -> dict[str, Any]:
    return {"runs": list_model_runs(limit=25)}


for static_path in ("css", "js", "lang"):
    app.mount(
        f"/{static_path}",
        StaticFiles(directory=PROJECT_ROOT / static_path),
        name=static_path,
    )


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "index.html")


for page in ("index", "forecast", "policy", "xai"):
    app.add_api_route(
        f"/{page}.html",
        lambda page=page: FileResponse(PROJECT_ROOT / f"{page}.html"),
        include_in_schema=False,
    )
