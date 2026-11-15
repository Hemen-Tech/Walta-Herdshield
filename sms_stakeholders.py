"""Sandbox-only stakeholder identities and their authorized SMS request labels."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Stakeholder:
    phone: str
    role: str
    request: str
    region: str | None = None
    area: str | None = None
    registration_id: str | None = None


STAKEHOLDER_COMMANDS = (
    ("Pastoralist 1", "DROUGHT STATUS", "SMS_STAKEHOLDER_PASTORALIST_1"),
    ("Pastoralist 2", "LIVESTOCK ADVICE", "SMS_STAKEHOLDER_PASTORALIST_2"),
    ("Pastoralist 3", "WATER UPDATE", "SMS_STAKEHOLDER_PASTORALIST_3"),
    ("Agro-pastoralist / Livestock owner", "HERD RISK", "SMS_STAKEHOLDER_LIVESTOCK_OWNER"),
    ("Veterinarian", "ANIMAL HEALTH", "SMS_STAKEHOLDER_VETERINARIAN"),
    ("NGO representative", "COMMUNITY REPORT", "SMS_STAKEHOLDER_NGO"),
    ("Government representative", "DISTRICT SUMMARY", "SMS_STAKEHOLDER_GOVERNMENT"),
)

load_dotenv(Path(__file__).resolve().parent / ".env.stakeholders", override=False)


def normalize_phone(value: str) -> str | None:
    """Normalize common phone formatting to +digits; accept Ethiopian local notation."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if (
        not raw
        or re.search(r"[^0-9+().\-\s]", raw)
        or raw.count("+") > 1
        or ("+" in raw and not raw.startswith("+"))
    ):
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "251" + digits[1:]
    elif digits.startswith("2510") and len(digits) == 13:
        digits = "251" + digits[4:]
    if not re.fullmatch(r"[1-9]\d{7,14}", digits):
        return None
    return "+" + digits


def _configured_stakeholders() -> tuple[Stakeholder, ...]:
    stakeholders = []
    seen_phones = set()
    for role, request, variable in STAKEHOLDER_COMMANDS:
        configured_phone = os.environ.get(variable, "").strip()
        if not configured_phone:
            continue
        phone = normalize_phone(configured_phone)
        if not phone or not re.fullmatch(r"\+2519\d{8}", phone):
            raise ValueError(f"{variable} must contain a valid Ethiopian mobile number.")
        if phone in seen_phones:
            raise ValueError("Each configured stakeholder must have a unique phone number.")
        seen_phones.add(phone)
        stakeholders.append(Stakeholder(phone, role, request))
    return tuple(stakeholders)


STAKEHOLDERS = _configured_stakeholders()
STAKEHOLDERS_BY_PHONE = {entry.phone: entry for entry in STAKEHOLDERS}


def identify_stakeholder(phone: str) -> Stakeholder | None:
    normalized = normalize_phone(phone)
    return STAKEHOLDERS_BY_PHONE.get(normalized) if normalized else None


def identify_request(text: str) -> tuple[str | None, str]:
    """Return a known stakeholder command and its trailing arguments."""
    normalized = " ".join((text or "").strip().upper().split())
    for _role, request, _variable in sorted(
        STAKEHOLDER_COMMANDS, key=lambda command: len(command[1]), reverse=True
    ):
        if normalized == request:
            return request, ""
        if normalized.startswith(request + " "):
            return request, normalized[len(request):].strip()
    return None, ""


CATEGORY_REQUESTS = {
    "Pastoralist": "DROUGHT STATUS",
    "Agro-pastoralist": "LIVESTOCK ADVICE",
    "Livestock business / livestock owner": "HERD RISK",
    "Veterinarian / animal health worker": "ANIMAL HEALTH",
    "NGO / development organization": "COMMUNITY REPORT",
    "Government institution": "DISTRICT SUMMARY",
}

CATEGORY_PRICES = {
    "Pastoralist": {"monthly": 30, "yearly": 300},
    "Agro-pastoralist": {"monthly": 100, "yearly": 1000},
    "Livestock business / livestock owner": {"monthly": 400, "yearly": 4000},
    "Veterinarian / animal health worker": {"monthly": 250, "yearly": 2500},
    "NGO / development organization": {"monthly": 2000, "yearly": 20000},
    "Government institution": {"monthly": 5000, "yearly": 50000},
}

REGISTRATION_REGIONS = (
    "Oromia",
    "Somali",
    "Afar",
    "Southern Ethiopia",
    "Sidama",
    "Central Ethiopia",
    "Southwest Ethiopia",
    "Amhara",
    "Tigray",
    "Benishangul-Gumuz",
    "Gambela",
    "Harari",
    "Dire Dawa",
    "Addis Ababa",
)
