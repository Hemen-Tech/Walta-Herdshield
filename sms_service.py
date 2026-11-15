"""Africa's Talking SMS transport and deterministic livestock question replies."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import requests

from data_store import get_store, region_info
from drought_provider import get_outlook
from engine import advise
from sms_stakeholders import (
    CATEGORY_PRICES,
    CATEGORY_REQUESTS,
    REGISTRATION_REGIONS,
    Stakeholder,
    identify_request,
    identify_stakeholder,
    normalize_phone,
)

HERE = Path(__file__).resolve().parent
SANDBOX_SMS_API_URL = "https://api.sandbox.africastalking.com/version1/messaging"
PRODUCTION_SMS_API_URL = "https://api.africastalking.com/version1/messaging"
MAX_SMS_LENGTH = 500
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
GRADE_ALIASES = {
    "thin": "Thin",
    "medium": "Moderate Weight",
    "moderate weight": "Moderate Weight",
    "fat": "Very Fat",
    "very fat": "Very Fat",
}


class SMSConfigurationError(RuntimeError):
    pass


class SMSProviderError(RuntimeError):
    pass


def sms_api_url() -> str:
    environment = os.environ.get("AT_ENVIRONMENT", "sandbox").strip().lower()
    if environment == "sandbox":
        return SANDBOX_SMS_API_URL
    if environment == "production":
        return PRODUCTION_SMS_API_URL
    raise SMSConfigurationError("AT_ENVIRONMENT must be 'sandbox' or 'production'.")


def is_configured() -> bool:
    return bool(os.environ.get("AT_USERNAME") and os.environ.get("AT_API_KEY"))


def validate_phone(phone: str) -> bool:
    return bool(PHONE_RE.fullmatch(phone.strip())) if isinstance(phone, str) else False


def is_sandbox_shortcode(value: str) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw or re.search(r"[^0-9+()\-\s]", raw) or raw.count("+") > 1:
        return False
    if "+" in raw and not raw.startswith("+"):
        return False
    return re.sub(r"\D", "", raw) == "16273"


def _optout_database() -> sqlite3.Connection:
    path = Path(os.environ.get("SMS_OPTOUT_DB", str(HERE / "data" / "sms_optouts.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS sms_optouts (phone TEXT PRIMARY KEY, opted_out_at TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS sms_request_audit ("
        "id INTEGER PRIMARY KEY, request_type TEXT NOT NULL, stakeholder_role TEXT NOT NULL, "
        "response_status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS registrations ("
        "id TEXT PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE, "
        "region TEXT NOT NULL, area TEXT NOT NULL DEFAULT '', category TEXT NOT NULL, "
        "billing_period TEXT NOT NULL CHECK (billing_period IN ('monthly', 'yearly')), "
        "price_etb INTEGER NOT NULL, subscription_status TEXT NOT NULL DEFAULT 'pending_payment', "
        "sms_consent INTEGER NOT NULL CHECK (sms_consent = 1), "
        "sms_status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS registration_sms_attempts ("
        "id INTEGER PRIMARY KEY, registration_id TEXT NOT NULL, status TEXT NOT NULL, "
        "provider_status TEXT NOT NULL DEFAULT '', attempted_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    return connection


def registration_options() -> dict[str, Any]:
    from climate_data import REGIONS

    return {
        "categories": list(CATEGORY_PRICES),
        "prices": CATEGORY_PRICES,
        "regions": list(REGISTRATION_REGIONS),
        "climate_reference_points": list(REGIONS),
    }


def create_registration(
    *,
    registration_id: str,
    full_name: str,
    phone: str,
    region: str,
    area: str,
    category: str,
    billing_period: str,
) -> None:
    price = CATEGORY_PRICES[category][billing_period]
    with _optout_database() as connection:
        connection.execute(
            "INSERT INTO registrations "
            "(id, full_name, phone, region, area, category, billing_period, price_etb, sms_consent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                registration_id,
                full_name,
                phone,
                region,
                area,
                category,
                billing_period,
                price,
            ),
        )


def registration_by_phone(phone: str) -> dict[str, Any] | None:
    with _optout_database() as connection:
        row = connection.execute(
            "SELECT id, phone, region, area, category, billing_period, price_etb, "
            "subscription_status, sms_status FROM registrations WHERE phone = ?",
            (phone,),
        ).fetchone()
    if row is None:
        return None
    names = (
        "id",
        "phone",
        "region",
        "area",
        "category",
        "billing_period",
        "price_etb",
        "subscription_status",
        "sms_status",
    )
    return dict(zip(names, row))


def registration_for_stakeholder(phone: str) -> Stakeholder | None:
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    configured = identify_stakeholder(normalized)
    if configured:
        return configured
    with _optout_database() as connection:
        row = connection.execute(
            "SELECT id, region, area, category FROM registrations "
            "WHERE phone = ? AND subscription_status = 'pending_payment' AND sms_consent = 1",
            (normalized,),
        ).fetchone()
    if row is None or row[3] not in CATEGORY_REQUESTS:
        return None
    registration_id, region, area, category = row
    return Stakeholder(
        normalized,
        category,
        CATEGORY_REQUESTS[category],
        region=region,
        area=area,
        registration_id=registration_id,
    )


def _registration_reference_location(region: str, area: str) -> str | None:
    area_reference_parents = {
        "borena": "Oromia",
        "yabello": "Oromia",
        "mekele": "Tigray",
        "gonder": "Amhara",
        "wag-himra": "Amhara",
    }
    if area.casefold() in area_reference_parents:
        parent = area_reference_parents[area.casefold()]
        if region.casefold() == parent.casefold():
            return _resolve_region(area)
    return _resolve_region(region)


def build_registration_welcome(registration: dict[str, Any]) -> str:
    category = registration["category"]
    region = registration["region"]
    area = registration["area"]
    templates = {
        "Pastoralist": (
            f"Welcome to Walta HerdShield! Your pastoralist registration for {region} is received. "
            "Get drought context, livestock-risk updates and practical herd guidance."
        ),
        "Agro-pastoralist": (
            f"Welcome to Walta HerdShield! Your agro-pastoral registration for {region} is received. "
            "Get climate context and livestock-management guidance."
        ),
        "Livestock business / livestock owner": (
            f"Welcome to Walta HerdShield! Your livestock business registration for {region} is received. "
            "Get herd-risk context and management insights."
        ),
        "Veterinarian / animal health worker": (
            f"Welcome to Walta HerdShield! Your animal-health registration for {region} is received. "
            "Available climate context is not disease surveillance or a diagnosis."
        ),
        "NGO / development organization": (
            f"Welcome to Walta HerdShield! Your organization registration for {region} is received. "
            "Get regional climate context and available community livestock-risk information."
        ),
        "Government institution": (
            f"Welcome to Walta HerdShield! Your government registration for {region} is received. "
            "Get regional climate context and available livestock-risk summaries."
        ),
    }
    message = templates[category]
    reference = _registration_reference_location(region, area)
    if reference:
        message += " " + _climate_report(reference, "DROUGHT STATUS")
    else:
        message += (
            f" Climate observations for {region} are not currently available in the connected "
            "regional dataset; no local estimate is provided."
        )
    if len(message) > MAX_SMS_LENGTH:
        message = message[: MAX_SMS_LENGTH - 1].rstrip() + "…"
    return message


def _registered_area_report(stakeholder: Stakeholder, command: str, arguments: str) -> str:
    requested_area = arguments.strip()
    registered_area = stakeholder.area or ""
    region = stakeholder.region or ""
    if requested_area and requested_area.casefold() not in {
        region.casefold(),
        registered_area.casefold(),
    }:
        return "This report is limited to your registered region and area."
    reference = _registration_reference_location(region, registered_area)
    if not reference:
        return (
            f"No connected climate reference point is available for {region}. "
            "No local observation or estimate is provided."
        )
    report_type = "DROUGHT STATUS" if command == "ANIMAL HEALTH" else command
    return _climate_report(reference, report_type)


def _registered_market_matches(arguments: str, stakeholder: Stakeholder) -> bool:
    match = re.fullmatch(
        r"(.+?)\s+(thin|medium|moderate weight|fat|very fat)\s+(\d+)",
        arguments.strip(),
        re.IGNORECASE,
    )
    if not match:
        return False
    market = _find_market(match.group(1))
    if not market:
        return False
    market_region = region_info(market)["region"].casefold()
    registered_region = (stakeholder.region or "").casefold()
    aliases = {
        "borena": "oromia",
        "yabello": "oromia",
    }
    registered_area = (stakeholder.area or "").casefold()
    expected_region = aliases.get(registered_area, registered_region)
    return market_region != "unknown" and market_region == expected_region


def set_registration_sms_status(
    registration_id: str, status: str, provider_status: str = ""
) -> None:
    with _optout_database() as connection:
        connection.execute(
            "UPDATE registrations SET sms_status = ? WHERE id = ?",
            (status[:40], registration_id),
        )
        connection.execute(
            "INSERT INTO registration_sms_attempts "
            "(registration_id, status, provider_status) VALUES (?, ?, ?)",
            (registration_id, status[:40], provider_status[:80]),
        )


def record_stakeholder_event(
    request_type: str, stakeholder_role: str, response_status: str
) -> None:
    """Persist request metadata only; never save sender numbers or message text."""
    with _optout_database() as connection:
        connection.execute(
            "INSERT INTO sms_request_audit (request_type, stakeholder_role, response_status) "
            "VALUES (?, ?, ?)",
            (request_type[:40], stakeholder_role[:80], response_status[:40]),
        )


def is_opted_out(phone: str) -> bool:
    with _optout_database() as connection:
        return connection.execute(
            "SELECT 1 FROM sms_optouts WHERE phone = ?", (phone,)
        ).fetchone() is not None


def set_opted_out(phone: str, opted_out: bool) -> None:
    with _optout_database() as connection:
        if opted_out:
            connection.execute(
                "INSERT OR REPLACE INTO sms_optouts (phone, opted_out_at) "
                "VALUES (?, datetime('now'))",
                (phone,),
            )
        else:
            connection.execute("DELETE FROM sms_optouts WHERE phone = ?", (phone,))


def send_sms(phone: str, message: str, *, allow_opted_out: bool = False) -> dict[str, Any]:
    if not validate_phone(phone):
        raise ValueError("Recipient must be an international phone number in E.164 format.")
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_SMS_LENGTH:
        raise ValueError(f"Message must contain 1 to {MAX_SMS_LENGTH} characters.")
    if is_opted_out(phone) and not allow_opted_out:
        raise ValueError("This recipient has opted out of SMS messages.")
    if not is_configured():
        raise SMSConfigurationError("Set AT_USERNAME and AT_API_KEY to enable SMS delivery.")
    api_url = sms_api_url()

    payload = {
        "username": os.environ["AT_USERNAME"],
        "to": phone,
        "message": message.strip(),
    }
    sender_id = os.environ.get("AT_SENDER_ID", "").strip() if api_url == PRODUCTION_SMS_API_URL else ""
    if sender_id:
        payload["from"] = sender_id

    try:
        response = requests.post(
            api_url,
            data=payload,
            headers={"apiKey": os.environ["AT_API_KEY"], "Accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise SMSProviderError("Africa's Talking SMS request failed.") from error

    try:
        body = response.json()
    except ValueError as error:
        raise SMSProviderError("Africa's Talking returned an invalid response.") from error

    if not isinstance(body, dict):
        raise SMSProviderError("Africa's Talking returned an invalid response.")
    recipients = (body.get("SMSMessageData") or {}).get("Recipients")
    if not isinstance(recipients, list) or not recipients or not isinstance(recipients[0], dict):
        raise SMSProviderError("Africa's Talking did not confirm an SMS recipient.")
    result = recipients[0]
    try:
        status_code = int(result.get("statusCode"))
    except (TypeError, ValueError):
        status_code = 0
    if status_code not in (101, 102):
        raise SMSProviderError(f"Africa's Talking rejected the SMS (status {status_code}).")
    return {"status": str(result.get("status") or "Accepted"), "status_code": status_code}


def _find_market(text: str) -> str | None:
    markets = get_store().markets()
    for item in sorted(markets, key=lambda row: len(row["market"]), reverse=True):
        market = item["market"]
        if re.search(rf"(?<!\w){re.escape(market)}(?!\w)", text, re.IGNORECASE):
            return market
    return None


def _price_reply(market: str) -> str:
    store = get_store()
    price = store.price_level(market)
    if price is None:
        return f"No current price records are available for {market}."
    level, records, _window, last_record = price
    reference = round(level * store.grade_ratio["Moderate Weight"], -2)
    age = int((store.today() - last_record).days)
    freshness = f" The latest record is {age} days old." if age > 30 else ""
    return (
        f"{market}: about {reference:,.0f} Birr per medium animal "
        f"(reference from {records} price reports through {last_record.date()}).{freshness}"
    )


def _drought_reply(market: str) -> str:
    region = region_info(market)["region"]
    outlook = get_outlook(market)
    if outlook is None:
        return (
            f"No current drought outlook is available for {region}. "
            "Unavailable does not mean no drought."
        )
    if "_label" in outlook:
        summary = str(outlook["_label"])
    else:
        summary = ", ".join(
            f"{name}: {round(float(outlook.get(name, 0)) * 100)}%"
            for name in ("No Drought", "Mild", "Moderate", "Severe")
            if name in outlook
        )
    caveat = " Regional outlook, not a local diagnosis."
    if outlook.get("_skill") == "climatology_only":
        caveat += " Historical-average outlook only; it has not shown forecast skill."
    return f"{region} outlook: {summary}.{caveat}"


def _advice_reply(market: str, grade: str, herd: int) -> str:
    advice = advise(market, grade, herd, "en")
    message = (
        f"{advice['action_title']}. About {advice['price_now_per_animal']:,} Birr per animal; "
        f"confidence {advice['confidence']}."
    )
    if advice["conditional"]:
        scenarios = {item["severity"]: item["title"] for item in advice["scenarios"]}
        message += (
            " Drought outlook unavailable; conditional on normal conditions. "
            f"Moderate-drought scenario: {scenarios[2]}."
        )
    elif advice["confidence"] == "low":
        message += " Treat this as a cautious decision aid, not a guarantee."
    elif advice["inputs"]["drought_status"] == "cached_file":
        message += " Uses a saved drought outlook."
    return message


def _resolve_region(value: str) -> str | None:
    from climate_data import REGIONS

    return next((name for name in REGIONS if name.casefold() == value.strip().casefold()), None)


def _regional_climate_data(region: str) -> dict[str, Any] | None:
    from climate_api import ClimateAPIError, sms_regional_summary

    try:
        return sms_regional_summary(region)
    except ClimateAPIError:
        return None


def _number(value: Any, suffix: str) -> str:
    if not isinstance(value, (int, float)):
        return "unavailable"
    return f"{value:.1f}{suffix}"


def _climate_report(region: str, report_type: str) -> str:
    data = _regional_climate_data(region)
    if data is None:
        return f"{region}: recent climate observations are unavailable. No estimate was generated."

    observed = data["observations"]
    risk = data["risk"]
    comparison = risk["comparison"]
    rainfall = _number(observed["precipitation_90d_mm"], "mm")
    temperature = _number(observed["mean_temperature_90d_c"], "C")
    et0 = _number(observed["et0_90d_mm"], "mm")
    difference = comparison["difference_percent"]
    change = f"{difference:+.0f}%" if isinstance(difference, (int, float)) else "unavailable"
    screen = (
        f"ERA5-Land observations {data['period_start']} to {data['period_end']}: "
        f"rain {rainfall}, mean temp {temperature}, reference ET0 {et0}. "
        f"90-day rainfall vs historical baseline: {change}; screening level {risk['level']} "
        f"(score {risk['score']}/100)."
    )

    if report_type == "DROUGHT STATUS":
        return (
            f"{region} representative grid: {screen} Retrospective screening only; "
            "not a drought diagnosis or forecast."
        )
    if report_type == "WATER UPDATE":
        return (
            f"{region}: {screen} These are climate proxies, not water supply. "
            "Water-point and groundwater data are unavailable."
        )
    if report_type == "COMMUNITY REPORT":
        return (
            f"{region} community context (representative grid): {screen} "
            "Community livestock-loss and service records are unavailable."
        )
    return (
        f"{region} district context (representative grid, not a district average): {screen} "
        "District livestock outcomes and trends are unavailable."
    )


def _livestock_risk_reply(arguments: str) -> str:
    match = re.fullmatch(
        r"(.+?)\s+(thin|medium|moderate weight|fat|very fat)\s+(\d+)",
        arguments.strip(),
        re.IGNORECASE,
    )
    if not match:
        return (
            "Use HERD RISK <market> <thin|medium|fat> <herd size>. "
            "Example: HERD RISK Yabalo medium 20."
        )
    market = _find_market(match.group(1))
    if not market:
        return "Market not recognized. Use a market name listed by Walta HerdShield."
    grade = GRADE_ALIASES[match.group(2).casefold()]
    try:
        return (
            "3-month decision aid (not a validated loss prediction): "
            + _advice_reply(market, grade, int(match.group(3)))
        )
    except ValueError:
        return "Herd size must be 1-5000. No livestock-loss probability is available."


def _livestock_advice_reply(arguments: str) -> str:
    match = re.fullmatch(
        r"(.+?)\s+(thin|medium|moderate weight|fat|very fat)\s+(\d+)",
        arguments.strip(),
        re.IGNORECASE,
    )
    if not match:
        return (
            "Use LIVESTOCK ADVICE <market> <thin|medium|fat> <herd size>. "
            "Example: LIVESTOCK ADVICE Yabalo medium 20."
        )
    market = _find_market(match.group(1))
    if not market:
        return "Market not recognized. Use a market name listed by Walta HerdShield."
    grade = GRADE_ALIASES[match.group(2).casefold()]
    try:
        return (
            "3-month decision aid (assumption-based, not a validated forecast): "
            + _advice_reply(market, grade, int(match.group(3)))
        )
    except ValueError:
        return "Herd size must be 1-5000. Please provide a number from 1 to 5000."


def process_stakeholder_request(phone: str, text: str) -> dict[str, str]:
    """Authorize and answer one registered stakeholder command."""
    stakeholder = registration_for_stakeholder(phone)
    dynamic_registration = bool(stakeholder and stakeholder.registration_id)
    command, arguments = identify_request(text)
    if not stakeholder:
        return {
            "request_type": command or "UNSUPPORTED",
            "stakeholder_role": "UNKNOWN",
            "response_status": "unknown_sender",
            "reply": "Stakeholder reports are limited to registered numbers. Send HELP for supported commands.",
        }

    if text.strip().casefold() in {"help", "menu"}:
        scope_note = (
            f"Reports use your registered area ({stakeholder.region}). "
            if dynamic_registration
            else "Add a region to regional reports. "
        )
        return {
            "request_type": "HELP",
            "stakeholder_role": stakeholder.role,
            "response_status": "replied",
            "reply": (
                f"Your authorized command: {stakeholder.request}. "
                f"{scope_note}For advice add market, condition and herd size. Send STOP to opt out."
            ),
        }
    if command is None:
        return {
            "request_type": "UNSUPPORTED",
            "stakeholder_role": stakeholder.role,
            "response_status": "unsupported",
            "reply": (
                "Commands: DROUGHT STATUS, LIVESTOCK ADVICE, WATER UPDATE, HERD RISK, "
                "ANIMAL HEALTH, COMMUNITY REPORT, DISTRICT SUMMARY. Registered roles only; send HELP."
            ),
        }
    if command != stakeholder.request:
        return {
            "request_type": command,
            "stakeholder_role": stakeholder.role,
            "response_status": "unauthorized",
            "reply": f"Not authorized for {command}. Your assigned request is {stakeholder.request}.",
        }

    if dynamic_registration and command in {
        "DROUGHT STATUS",
        "WATER UPDATE",
        "COMMUNITY REPORT",
        "DISTRICT SUMMARY",
        "ANIMAL HEALTH",
    }:
        reply = _registered_area_report(stakeholder, command, arguments)
        if command == "ANIMAL HEALTH":
            reply += " Disease surveillance is unavailable; this is not a diagnosis."
    elif dynamic_registration and command in {"LIVESTOCK ADVICE", "HERD RISK"}:
        if not arguments:
            area_context = _registered_area_report(
                stakeholder, "DROUGHT STATUS", ""
            )
            reply = (
                f"{area_context} Decision aid: use {command} <market> "
                "<thin|medium|fat> <herd size>; only a market mapped to your "
                "registered region can be assessed."
            )
        elif not _registered_market_matches(arguments, stakeholder):
            reply = (
                f"No matching market data is mapped to your registered region "
                f"({stakeholder.region}); no cross-region estimate was provided."
            )
        elif command == "LIVESTOCK ADVICE":
            reply = _livestock_advice_reply(arguments)
        else:
            reply = _livestock_risk_reply(arguments)
    elif command in {"DROUGHT STATUS", "WATER UPDATE", "COMMUNITY REPORT", "DISTRICT SUMMARY"}:
        region = _resolve_region(arguments)
        if not arguments or not region:
            return {
                "request_type": command,
                "stakeholder_role": stakeholder.role,
                "response_status": "invalid_request",
                "reply": (
                    f"Use {command} <region>. Example: {command} Afar. "
                    "Send HELP for valid regions."
                ),
            }
        reply = _climate_report(region, command)
    elif command == "LIVESTOCK ADVICE":
        reply = _livestock_advice_reply(arguments)
    elif command == "HERD RISK":
        reply = _livestock_risk_reply(arguments)
    else:
        if not arguments:
            reply = (
                "Animal-health surveillance and disease data are not connected. "
                "Send ANIMAL HEALTH <region> for climate-stress context only; "
                "consult a veterinarian for diagnosis."
            )
        else:
            region = _resolve_region(arguments)
            if not region:
                reply = "Use ANIMAL HEALTH <region>. This provides environmental context, not a diagnosis."
            else:
                data = _regional_climate_data(region)
                if data is None:
                    reply = (
                        f"{region}: environmental indicators are unavailable. "
                        "Disease surveillance is not connected; no diagnosis is provided."
                    )
                else:
                    reply = (
                        _climate_report(region, "DROUGHT STATUS")
                        + " Climate stress context only; no disease surveillance or diagnosis."
                    )
    lowered_reply = reply.casefold()
    if "unavailable" in lowered_reply or "not connected" in lowered_reply:
        status = "data_unavailable"
    elif (
        lowered_reply.startswith("use ")
        or lowered_reply.startswith("market not recognized")
        or lowered_reply.startswith("herd size must")
    ):
        status = "invalid_request"
    else:
        status = "replied"
    return {
        "request_type": command,
        "stakeholder_role": stakeholder.role,
        "response_status": status,
        "reply": reply[:MAX_SMS_LENGTH],
    }


def build_reply(text: str) -> str:
    """Answer supported SMS questions with existing price, climate, and advice data."""
    query = re.sub(r"\s+", " ", (text or "").strip())
    if not query:
        return "Send HELP for question formats."
    if query.casefold() in {"help", "menu", "start"}:
        return (
            "Walta HerdShield: PRICE <market>; DROUGHT <market>; "
            "ADVICE <market> <thin|medium|fat> <herd size>. Stakeholder reports: "
            "DROUGHT STATUS, LIVESTOCK ADVICE, WATER UPDATE, HERD RISK, ANIMAL HEALTH, "
            "COMMUNITY REPORT, DISTRICT SUMMARY (registered roles only). Reply STOP to opt out."
        )

    advice_match = re.fullmatch(
        r"(?i)advice\s+(.+?)\s+(thin|medium|moderate weight|fat|very fat)\s+(\d+)",
        query,
    )
    if advice_match:
        market = _find_market(advice_match.group(1))
        grade = GRADE_ALIASES[advice_match.group(2).casefold()]
        if not market:
            return "Market not recognized. Check its spelling or send HELP."
        try:
            return _advice_reply(market, grade, int(advice_match.group(3)))
        except ValueError as error:
            return f"{error} Send HELP for the correct format."

    market = _find_market(query)
    if market and re.search(r"\b(price|cost|worth)\b", query, re.IGNORECASE):
        return _price_reply(market)
    if market and re.search(r"\b(drought|dry|rain|rainfall)\b", query, re.IGNORECASE):
        return _drought_reply(market)
    if market and re.search(r"\b(advice|sell|hold|should)\b", query, re.IGNORECASE):
        return f"To get livestock advice, send: ADVICE {market} <thin|medium|fat> <herd size>."
    return (
        "I can answer price, drought and livestock advice questions. Stakeholder reports are "
        "available to registered roles only. Send HELP for formats."
    )
