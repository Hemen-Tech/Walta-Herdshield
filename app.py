"""Destocking advisor backend: serves the dashboard AND the phone (USSD) service from one app.

Run locally:   python app.py            (http://localhost:5000)
Run on Replit: gunicorn app:app --bind 0.0.0.0:$PORT
Africa's Talking USSD and SMS callbacks are documented in README.md.
"""
import collections
import hmac
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from flask import Flask, Response, jsonify, request
import ussd as ussd_mod
import sms_service as sms_mod
from climate_api import bp as climate_api
from advisor_routes import make_blueprint

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.join(HERE, "front_end")
app = Flask(__name__, static_folder=None)
app.config["JSON_AS_ASCII"] = False
app.register_blueprint(make_blueprint(FRONT, "", ussd_mod.USSD_MARKETS))
app.register_blueprint(climate_api)


# --- USSD hardening ---------------------------------------------------------------------------------------------
# Africa's Talking does not sign callbacks. So: (1) put a secret in the URL (env USSD_SECRET -> POST /ussd/<secret>),
# (2) optionally allow only Africa's Talking server IPs (env USSD_ALLOWED_IPS, comma separated), (3) rate-limit per phone.
USSD_SECRET = os.environ.get("USSD_SECRET", "")
SMS_WEBHOOK_SECRET = os.environ.get("SMS_WEBHOOK_SECRET", "")
ALLOWED_IPS = [i.strip() for i in os.environ.get("USSD_ALLOWED_IPS", "").split(",") if i.strip()]
RATE_MAX, RATE_WINDOW = int(os.environ.get("USSD_RATE_MAX", "40")), 600        # requests per phone per 10 minutes
_hits = collections.defaultdict(collections.deque)
SMS_RATE_MAX, SMS_RATE_WINDOW = 5, 600
_sms_hits = collections.defaultdict(collections.deque)
REGISTRATION_RATE_MAX, REGISTRATION_RATE_WINDOW = 5, 3600
_registration_hits = collections.defaultdict(collections.deque)


def _rate_limited(key):
    now, q = time.time(), _hits[key]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(_hits) > 20000:                       # keep memory bounded
        _hits.clear()
    if len(q) >= RATE_MAX:
        return True
    q.append(now)
    return False


def _client_ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0]).strip()


def _ussd_handler(secret_ok):
    if not secret_ok:
        return Response("END Not found", status=404, mimetype="text/plain")
    if ALLOWED_IPS and _client_ip() not in ALLOWED_IPS:
        return Response("END Not allowed", status=403, mimetype="text/plain")
    payload = request.get_json(silent=True) or request.form
    phone = str(payload.get("phoneNumber", "") or _client_ip())
    if _rate_limited(phone):
        return Response("END Too many requests, try later.\nIrra deddeebi'ame, booda yaali.", mimetype="text/plain")
    return Response(ussd_mod.handle(str(payload.get("text", "") or "")), mimetype="text/plain")


@app.post("/ussd")
def ussd_route():
    return _ussd_handler(secret_ok=False)


@app.post("/ussd/<secret>")
def ussd_secret_route(secret):
    configured_secret = USSD_SECRET.strip()
    return _ussd_handler(
        secret_ok=bool(configured_secret)
        and hmac.compare_digest(secret, configured_secret)
    )


def _sms_rate_limited(phone):
    now = time.time()
    if len(_sms_hits) > 20000:
        _sms_hits.clear()
    hits = _sms_hits[phone]
    while hits and now - hits[0] > SMS_RATE_WINDOW:
        hits.popleft()
    if len(hits) >= SMS_RATE_MAX:
        return True
    hits.append(now)
    return False


def _registration_rate_limited(client_key):
    now = time.time()
    if len(_registration_hits) > 20000:
        _registration_hits.clear()
    hits = _registration_hits[client_key]
    while hits and now - hits[0] > REGISTRATION_RATE_WINDOW:
        hits.popleft()
    if len(hits) >= REGISTRATION_RATE_MAX:
        return True
    hits.append(now)
    return False


@app.get("/api/registration/options")
def registration_options_route():
    return jsonify(sms_mod.registration_options())


@app.post("/api/registrations")
def registration_create_route():
    client_key = request.remote_addr or "unknown"
    if _registration_rate_limited(client_key):
        return jsonify({"error": "Too many registration attempts. Please try again later."}), 429

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Submit the registration as a JSON object."}), 400

    full_name = body.get("full_name")
    phone_value = body.get("phone")
    region = body.get("region")
    area = body.get("area", "")
    category = body.get("category")
    billing_period = body.get("billing_period")
    if not all(isinstance(value, str) for value in (full_name, phone_value, region, area, category, billing_period)):
        return jsonify({"error": "Complete all required fields using the provided options."}), 400

    full_name = " ".join(full_name.split())
    area = " ".join(area.split())
    if (
        not full_name
        or len(full_name) > 100
        or any(ord(char) < 32 for char in full_name)
    ):
        return jsonify({"error": "Enter a valid name up to 100 characters."}), 400
    if len(area) > 100 or any(ord(char) < 32 for char in area):
        return jsonify({"error": "Zone or district must be 100 characters or fewer."}), 400

    phone = sms_mod.normalize_phone(phone_value)
    if not phone or not re.fullmatch(r"\+2519\d{8}", phone):
        return jsonify({"error": "Enter a valid Ethiopian mobile number, such as +2519XXXXXXXX."}), 400
    options = sms_mod.registration_options()
    if region not in options["regions"]:
        return jsonify({"error": "Select a region from the list."}), 400
    if category not in options["categories"]:
        return jsonify({"error": "Select a user category from the list."}), 400
    if billing_period not in {"monthly", "yearly"}:
        return jsonify({"error": "Select monthly or yearly billing."}), 400
    if body.get("sms_consent") is not True:
        return jsonify({"error": "Consent to the registration and welcome SMS is required."}), 400
    if sms_mod.identify_stakeholder(phone):
        return jsonify({"error": "This number is already assigned to a Sandbox stakeholder identity."}), 409

    registration_id = str(uuid.uuid4())
    try:
        sms_mod.create_registration(
            registration_id=registration_id,
            full_name=full_name,
            phone=phone,
            region=region,
            area=area,
            category=category,
            billing_period=billing_period,
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "This phone number is already registered."}), 409
    except sqlite3.Error:
        app.logger.exception("Could not save registration")
        return jsonify({"error": "Registration could not be saved. Please try again later."}), 503

    price = sms_mod.CATEGORY_PRICES[category][billing_period]
    registration = {
        "id": registration_id,
        "phone": phone,
        "region": region,
        "area": area,
        "category": category,
        "billing_period": billing_period,
        "price_etb": price,
    }
    sms_status = "pending_configuration"
    provider_status = ""
    if sms_mod.is_opted_out(phone):
        sms_status = "suppressed_opted_out"
    elif not sms_mod.is_configured():
        sms_status = "not_configured"
    else:
        try:
            if sms_mod.sms_api_url() != sms_mod.SANDBOX_SMS_API_URL:
                sms_status = "sandbox_required"
            else:
                welcome = sms_mod.build_registration_welcome(registration)
                delivery = sms_mod.send_sms(phone, welcome)
                sms_status = "accepted"
                provider_status = delivery["status"]
        except sms_mod.SMSConfigurationError:
            sms_status = "sandbox_required"
        except sms_mod.SMSProviderError:
            app.logger.exception("Registration saved but welcome SMS delivery failed")
            sms_status = "failed"
        except ValueError:
            sms_status = "suppressed_opted_out"

    try:
        sms_mod.set_registration_sms_status(registration_id, sms_status, provider_status)
    except sqlite3.Error:
        app.logger.exception("Registration saved but SMS status could not be recorded")
        sms_status = "status_recording_failed"

    return jsonify(
        {
            "registration_id": registration_id,
            "category": category,
            "region": region,
            "area": area,
            "billing_period": billing_period,
            "price_etb": price,
            "subscription_status": "pending_payment",
            "sms_status": sms_status,
        }
    ), 201


@app.post("/sms/inbound/<secret>")
def sms_inbound_route(secret):
    if len(SMS_WEBHOOK_SECRET) < 32 or not hmac.compare_digest(secret, SMS_WEBHOOK_SECRET):
        return jsonify({"error": "not found"}), 404

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form
    phone = sms_mod.normalize_phone(
        str(payload.get("from", "") or payload.get("phoneNumber", "")).strip()
    )
    destination = str(payload.get("to", "") or "").strip()
    if destination and not sms_mod.is_sandbox_shortcode(destination):
        return jsonify({"error": "inbound destination is not the Sandbox shortcode"}), 400
    text = str(payload.get("text", "") or "").strip()
    if not phone or not sms_mod.validate_phone(phone) or not text:
        if phone:
            invalid_stakeholder = sms_mod.registration_for_stakeholder(phone)
            sms_mod.record_stakeholder_event(
                "INVALID",
                invalid_stakeholder.role if invalid_stakeholder else "UNKNOWN",
                "invalid_request",
            )
        return jsonify({"error": "a valid sender number and message are required"}), 400
    if len(text) > sms_mod.MAX_SMS_LENGTH:
        stakeholder = sms_mod.registration_for_stakeholder(phone)
        sms_mod.record_stakeholder_event(
            "INVALID",
            stakeholder.role if stakeholder else "UNKNOWN",
            "invalid_request",
        )
        return jsonify({"error": "message is too long"}), 400

    command = text.casefold()
    stakeholder = sms_mod.registration_for_stakeholder(phone)
    stakeholder_role = stakeholder.role if stakeholder else "UNKNOWN"
    if command in {"stop", "stop all", "unsubscribe", "cancel", "end", "quit"}:
        if sms_mod.is_opted_out(phone):
            sms_mod.record_stakeholder_event(
                "STOP", stakeholder.role if stakeholder else "UNKNOWN", "already_opted_out"
            )
            return jsonify({"accepted": True, "reply": "suppressed"}), 200
        sms_mod.set_opted_out(phone, True)
        reply = "You are unsubscribed from Walta HerdShield SMS."
        allow_opted_out = True
        request_type, request_status = "STOP", "opted_out"
    elif command in {"start", "unstop"}:
        sms_mod.set_opted_out(phone, False)
        if _sms_rate_limited(phone):
            sms_mod.record_stakeholder_event(
                "START", stakeholder.role if stakeholder else "UNKNOWN", "rate_limited"
            )
            return jsonify({"accepted": True, "reply": "rate_limited"}), 200
        reply = "Walta HerdShield SMS is active. Send HELP for question formats."
        allow_opted_out = False
        request_type, request_status = "START", "restarted"
    elif sms_mod.is_opted_out(phone):
        requested, _arguments = sms_mod.identify_request(text)
        sms_mod.record_stakeholder_event(
            requested or "SUPPRESSED",
            stakeholder.role if stakeholder else "UNKNOWN",
            "opted_out_suppressed",
        )
        return jsonify({"accepted": True, "reply": "suppressed"}), 200
    else:
        if _sms_rate_limited(phone):
            requested, _arguments = sms_mod.identify_request(text)
            sms_mod.record_stakeholder_event(
                requested or "RATE_LIMITED",
                stakeholder.role if stakeholder else "UNKNOWN",
                "rate_limited",
            )
            return jsonify({"accepted": True, "reply": "rate_limited"}), 200
        if stakeholder or sms_mod.identify_request(text)[0]:
            result = sms_mod.process_stakeholder_request(phone, text)
            reply = result["reply"]
            request_type, request_status = result["request_type"], result["response_status"]
            stakeholder_role = result["stakeholder_role"]
        else:
            reply = sms_mod.build_reply(text)
            request_type = "LEGACY"
            request_status = "replied"
            stakeholder_role = "UNREGISTERED"
        allow_opted_out = False

    try:
        if sms_mod.sms_api_url() != sms_mod.SANDBOX_SMS_API_URL:
            sms_mod.record_stakeholder_event(request_type, stakeholder_role, "sandbox_required")
            return jsonify({"error": "stakeholder SMS replies require Sandbox mode"}), 503
    except sms_mod.SMSConfigurationError:
        sms_mod.record_stakeholder_event(
            request_type, stakeholder_role, "sandbox_required"
        )
        return jsonify({"error": "stakeholder SMS replies require Sandbox mode"}), 503

    if not sms_mod.is_configured():
        sms_mod.record_stakeholder_event(request_type, stakeholder_role, "delivery_not_configured")
        return jsonify({"error": "SMS delivery is not configured"}), 503
    try:
        delivery = sms_mod.send_sms(phone, reply, allow_opted_out=allow_opted_out)
    except (sms_mod.SMSProviderError, sms_mod.SMSConfigurationError):
        app.logger.exception("Could not deliver SMS webhook reply")
        sms_mod.record_stakeholder_event(
            request_type,
            stakeholder_role,
            f"{request_status}_delivery_failed",
        )
        return jsonify({"error": "SMS reply delivery failed"}), 502
    sms_mod.record_stakeholder_event(
        request_type,
        stakeholder_role,
        f"{request_status}_delivered",
    )
    return jsonify({"accepted": True, "delivery": delivery["status"]}), 200


@app.post("/api/sms/send")
def sms_send_route():
    admin_key = os.environ.get("ADMIN_KEY", "")
    supplied_key = request.headers.get("X-Api-Key", "")
    if not admin_key or not hmac.compare_digest(supplied_key, admin_key):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "send a JSON object"}), 400
    phone, message = body.get("to"), body.get("message")
    if not isinstance(phone, str) or not sms_mod.validate_phone(phone):
        return jsonify({"error": "to must be an international E.164 phone number"}), 400
    if not isinstance(message, str) or not message.strip() or len(message) > sms_mod.MAX_SMS_LENGTH:
        return jsonify({"error": f"message must contain 1 to {sms_mod.MAX_SMS_LENGTH} characters"}), 400
    if sms_mod.is_opted_out(phone):
        return jsonify({"error": "recipient has opted out of SMS messages"}), 409
    try:
        delivery = sms_mod.send_sms(phone, message)
    except sms_mod.SMSConfigurationError as error:
        return jsonify({"error": str(error)}), 503
    except sms_mod.SMSProviderError:
        app.logger.exception("Could not deliver requested SMS")
        return jsonify({"error": "SMS provider delivery failed"}), 502
    return jsonify({"sent": True, "status": delivery["status"]}), 200


@app.get("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
