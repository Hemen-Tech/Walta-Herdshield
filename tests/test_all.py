import datetime, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ADMIN_KEY"] = "testkey"
os.environ.update(
    {
        "SMS_STAKEHOLDER_PASTORALIST_1": "+251900010001",
        "SMS_STAKEHOLDER_PASTORALIST_2": "+251900010002",
        "SMS_STAKEHOLDER_PASTORALIST_3": "+251900010003",
        "SMS_STAKEHOLDER_LIVESTOCK_OWNER": "+251900010004",
        "SMS_STAKEHOLDER_VETERINARIAN": "+251900010005",
        "SMS_STAKEHOLDER_NGO": "+251900010006",
        "SMS_STAKEHOLDER_GOVERNMENT": "+251900010007",
    }
)
os.environ.pop("DROUGHT_MODEL_URL", None)
import drought_provider as dp
dp.FILE = os.path.join(tempfile.mkdtemp(), "drought_outlook.json")      # never touch the real file in tests
from app import app
import ussd as U
from engine import advise, MAX_HERD

c = app.test_client()
ORDER = ["hold", "sell_25", "sell_50", "sell_75"]
GOOD = {"No Drought": .3, "Mild": .3, "Moderate": .25, "Severe": .15}

def ussd(text):
    import app as A
    old_secret = A.USSD_SECRET
    A.USSD_SECRET = "test-ussd-secret"
    try:
        r = c.post(
            "/ussd/test-ussd-secret",
            data={"sessionId": "x", "phoneNumber": "+251900000000", "text": text},
        )
    finally:
        A.USSD_SECRET = old_secret
    assert r.status_code == 200 and r.mimetype == "text/plain"
    body = r.get_data(as_text=True)
    assert body.startswith(("CON ", "END ")) and len(body) <= 182, (len(body), body)
    return body

def set_outlook(body, expect=200):
    r = c.post("/api/drought", json=body, headers={"X-Api-Key": "testkey"})
    assert r.status_code == expect, r.get_json()
    return r

def clear_outlook():
    if os.path.exists(dp.FILE): os.remove(dp.FILE)

def test_ussd_flow_and_bad_inputs():
    for t in ["", "1", "1*1", "1*1*1", "1*1*1*20", "2*2*3*15"]: ussd(t)
    assert ussd("9").startswith("CON "); assert ussd("1*9").startswith("CON "); assert ussd("1*1*7").startswith("CON ")
    assert ussd("1*1*1*abc").startswith("CON "); assert ussd("1*1*1*0").startswith("CON "); assert ussd(f"1*1*1*{MAX_HERD+1}").startswith("CON ")

def test_unavailable_forecast_is_never_shown_as_no_drought():
    clear_outlook()
    a = c.get("/api/advice?market=Yabalo&grade=Thin&herd=10").get_json()
    assert a["status"] == "unavailable" and a["conditional"] and "IF NORMAL" in a["action_title"]
    assert a["confidence_parts"]["drought"]["level"] == "low" and a["confidence"] == "low"
    assert len(a["scenarios"]) == 4
    out = ussd("1*2*1*10")                     # English, Yabalo, thin, 10 animals
    assert "Forecast offline" in out and "Moderate drought" in out, out

def test_scenario_mode_monotone_and_labelled():
    acts = []
    for s in range(4):
        a = c.get(f"/api/advice?market=Yabalo&grade=Moderate%20Weight&severity={s}").get_json()
        assert a["status"] == "scenario" and not a["conditional"] and a["confidence_parts"]["drought"]["level"] is None
        acts.append(ORDER.index(a["action"]))
    assert acts == sorted(acts) and acts[0] == 0 and acts[3] >= 2, acts   # severe must be at least sell_50 (sell_75 needs the unproven crash effect)

def test_confidence_never_high_while_assumptions_unvalidated():
    for s in range(4):
        assert c.get(f"/api/advice?market=Miyo&grade=Thin&severity={s}").get_json()["confidence"] != "high"

def test_drought_validation_rejects_bad_inputs():
    bad = [{"No Drought": -10, "Mild": 2, "Moderate": 0, "Severe": 0}, {"No Drought": float("nan"), "Mild": .3, "Moderate": .3, "Severe": .4},
           {"No Drought": .5, "Mild": .5, "Moderate": .5, "Severe": .5}, {"No Drought": "x", "Mild": 0, "Moderate": 0, "Severe": 1}, {"label": "Catastrophic"}, {"foo": 1}]
    for b in bad:
        assert dp.validate(b) is not None, b
        set_outlook({"regions": {"Oromia": b}}, expect=400)
    assert dp.validate(GOOD) is None and dp.validate({"label": "Moderate"}) is None
    assert c.post("/api/drought", json={"regions": {"Oromia": GOOD}}).status_code == 401

def test_fresh_saved_forecast_is_used_and_marked():
    clear_outlook(); set_outlook({"source": "test", "regions": {"Oromia": GOOD}})
    a = c.get("/api/advice?market=Yabalo&grade=Thin&herd=10").get_json()
    assert a["status"] == "cached_file" and not a["conditional"] and a["inputs"]["drought_scope"] == "region"
    assert c.get("/api/meta").get_json()["drought"]["status"] == "cached_file"
    clear_outlook()

def test_stale_or_undated_forecast_is_unavailable_not_normal():
    old = (datetime.date.today() - datetime.timedelta(days=dp.MAX_AGE_DAYS + 5)).isoformat()
    json.dump({"updated": old, "regions": {"Oromia": {"label": "Severe"}}}, open(dp.FILE, "w"))
    assert advise("Yabalo", "Thin", 5)["status"] == "unavailable"
    json.dump({"regions": {"Oromia": {"label": "Severe"}}}, open(dp.FILE, "w"))          # no date at all
    assert advise("Yabalo", "Thin", 5)["status"] == "unavailable"
    clear_outlook()

def test_climatology_only_forecast_gets_low_drought_confidence():
    today = datetime.date.today().isoformat()
    json.dump({"updated": today, "source": "t", "skill": "climatology_only", "markets": {"Yabalo": GOOD}}, open(dp.FILE, "w"))
    a = c.get("/api/advice?market=Yabalo&grade=Thin&herd=10").get_json()
    assert a["status"] == "cached_file" and a["confidence_parts"]["drought"]["level"] == "low" and a["confidence"] == "low"
    assert a["conditional"] is False
    assert not any("unavailable or too old" in reason for reason in a["reasons"])
    assert any("historical average" in r for r in a["reasons"])
    json.dump({"updated": today, "source": "t", "markets": {"Yabalo": GOOD}}, open(dp.FILE, "w"))
    assert c.get("/api/advice?market=Yabalo&grade=Thin&herd=10").get_json()["confidence_parts"]["drought"]["level"] == "medium"
    clear_outlook()

def test_herd_limits_and_errors():
    assert c.get("/api/advice?market=Yabalo&herd=0").status_code == 400
    assert c.get(f"/api/advice?market=Yabalo&herd={MAX_HERD+1}").status_code == 400
    assert c.get("/api/advice?market=Yabalo&herd=abc").status_code == 400
    assert c.get("/api/advice?market=Nowhere").status_code == 400

def test_api_pages_and_no_open_cors_by_default():
    m = c.get("/api/meta"); assert len(m.get_json()["markets"]) >= 20 and "Access-Control-Allow-Origin" not in m.headers
    assert c.get("/api/history?market=Yabalo").get_json()["months"]
    assert c.get("/").status_code == 200 and c.get("/css/destock.css").status_code == 200
    assert c.get("/backend/admas.db").status_code == 404
    assert c.get("/Backend/db.py").status_code == 404
    assert c.get("/backend./db.py").status_code == 404
    assert c.get("/backend/db.py").status_code == 404
    a = c.get("/api/advice?market=Yabalo&grade=Thin&herd=10&severity=2&lang=am").get_json()
    assert a["decision_stability"]["variants_tested"] == 10 and a["action"] in ORDER

def test_evidence_endpoint_is_honest():
    e = c.get("/api/evidence?lang=om").get_json()
    keys = {i["key"]: i for i in e["items"]}
    assert keys["crash_effect"]["status"] == "assumed" and keys["crash_effect"]["sensitivity_pct"] == 25
    assert keys["holding_cost"]["status"] == "assumed" and keys["holding_cost"]["sources"] == []
    assert "Thin" in keys["grade_price_gap"]["measured_value"]
    for it in e["items"]:
        for s in it["sources"]: assert s["checked_by_human"] is False
    assert "candidates_waiting" in e

def test_probe_bridge_rejects_fabricated_and_irrelevant_papers():
    import probe_bridge as pb
    fake = {"status": "success", "papers": [{"id": "sx-edu-2025-01", "title": "Study habits", "abstract": "cattle", "url": "https://x"}]}
    ok, bad, prob = pb.screen(fake); assert ok == [] and bad and "fabricated" in bad[0][1]
    off = {"status": "success", "papers": [{"id": "sx-9", "title": "Freelancer pricing", "abstract": "software subscriptions", "url": "https://x"}]}
    ok, bad, prob = pb.screen(off); assert ok == [] and "livestock" in bad[0][1]
    assert pb.screen({"status": "ok", "papers": [{}]})[2] is not None          # Probe's error-as-ok reply is not 'success'
    assert pb.screen({"status": "unavailable", "papers": []})[2] is not None
    good = {"status": "success", "papers": [{"id": "sx-77", "title": "Cattle mortality in Borana drought", "abstract": "Pastoral herds...", "url": "https://real.example/p", "stance": "SUPPORTS"}]}
    ok, bad, prob = pb.screen(good); assert len(ok) == 1 and ok[0]["needs_human_review"] and ok[0]["probe_auto_stance_unverified"] == "SUPPORTS"

def test_probe_bridge_end_to_end_with_mock_probe():
    import threading, probe_bridge as pb
    from flask import Flask, jsonify, request
    from werkzeug.serving import make_server
    mock = Flask("mock")
    @mock.get("/api/health")
    def h(): return jsonify({"status": "ok"})
    @mock.post("/api/research/assumption")
    def ra():
        k = request.get_json()["assumptionId"]
        if k == "mortality":     # one real paper + one fabricated + one irrelevant, all marked success
            return jsonify({"status": "success", "papers": [
                {"id": "sx-1", "title": "Drought cattle losses among Borana pastoralists", "abstract": "livestock mortality", "url": "https://real.example/1", "stance": "SUPPORTS"},
                {"id": "sx-cook-2026-01", "title": "Decision fatigue in cooking", "abstract": "households", "url": "https://www.scholarxiv.com/papers/sx-cook-2026-01"},
                {"id": "sx-3", "title": "Micro-SaaS pricing", "abstract": "developers", "url": "https://x/3"}]})
        if k == "thinning":
            return jsonify({"status": "unavailable", "papers": []})
        return jsonify({"status": "error"}), 502
    srv = make_server("127.0.0.1", 5099, mock); th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
    out = os.path.join(tempfile.mkdtemp(), "cand.json")
    try:
        pb.run("http://127.0.0.1:5099", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "evidence_claims.json"), out, 6, 10)
    finally:
        srv.shutdown()
    cand = json.load(open(out))["candidates"]
    assert len(cand) == 1 and cand[0]["claim_key"] == "mortality" and "real.example" in cand[0]["url"]

def test_stale_prices_are_flagged_against_today_not_the_file():
    import data_store, pandas as pd
    st = data_store.get_store()
    old = os.environ.get("ASOF_TODAY")
    try:
        os.environ["ASOF_TODAY"] = str((st.asof + pd.Timedelta(days=120)).date())   # pretend nobody updated the CSV for 4 months
        a = advise("Nagelle Borana", "Moderate Weight", 5, "en", 0)
        assert a["prices_stale"] is True and a["confidence_parts"]["data"]["level"] == "low" and a["confidence"] == "low", a
    finally:
        if old is None: os.environ.pop("ASOF_TODAY", None)
        else: os.environ["ASOF_TODAY"] = old

def test_crash_effect_not_in_headline_but_reported():
    a = advise("Miyo", "Thin", 5, "en", 3)
    assert a["crash_effect_in_headline"] is False and "if_market_crash_effect_is_real" in a
    assert a["if_market_crash_effect_is_real"]["action"] in ORDER

def test_ussd_screens_fit_and_secret_path_and_rate_limit():
    import app as A
    old = (A.USSD_SECRET, A.RATE_MAX)
    try:
        A.USSD_SECRET = ""
        assert c.post("/ussd", data={"text": ""}).status_code == 404
        assert c.post("/ussd/anything", data={"text": ""}).status_code == 404
        A.USSD_SECRET = "   "
        assert c.post("/ussd", data={"text": ""}).status_code == 404
        assert c.post("/ussd/anything", data={"text": ""}).status_code == 404
        A.USSD_SECRET = "s3cret"
        assert c.post("/ussd", data={"text": ""}).status_code == 404
        assert c.post("/ussd/wrong", data={"text": ""}).status_code == 404
        assert c.post("/ussd/s3cret", data={"text": "", "phoneNumber": "+2511"}).status_code == 200
        A.RATE_MAX = 2
        A._hits.clear()
        codes = [
            c.post(
                "/ussd/s3cret",
                data={"text": "", "phoneNumber": "+2512"},
            ).get_data(as_text=True)[:3]
            for _ in range(4)
        ]
        assert codes[-1] == "END" and codes[0] == "CON", codes                    # 3rd+ call inside the window is refused
    finally:
        A.USSD_SECRET, A.RATE_MAX = old
        A._hits.clear()

def test_all_ussd_screens_under_160_chars():
    for lang in ("1", "2"):
        for text in ["", lang, lang + "*1", lang + "*1*1", lang + "*1*1*10", lang + "*1*3*2000", lang + "*9"]:
            body = ussd(text)
            assert len(body) <= 160, (len(body), text, body)

def test_corroborated_price_moves_are_kept():
    import data_store
    r = data_store.get_store().report
    assert "outliers_kept_because_corroborated" in r and r["price_outliers_removed"] <= 10

def test_climate_context_is_informational_and_present():
    r = c.get("/api/climate").get_json()
    assert r["affects_advice"] is False and r["enso"]["phase"] in ("El Nino", "La Nina", "neutral")
    assert r["iod"].get("stale") is True or r["iod"].get("status") == "unavailable" or r["iod"]["age_days"] <= 90
    assert "official_outlook" in r and r["official_outlook"].get("verified_by_human") in (True, False)
    base = advise("Miyo", "Thin", 5, "en", 2)
    via_api = c.get("/api/advice?market=Miyo&grade=Thin&herd=5&severity=2").get_json()
    assert via_api["action"] == base["action"] and via_api["climate_context"]["affects_advice"] is False   # advice unchanged by climate data
    assert "climate" in c.get("/api/meta").get_json()

def test_observed_conditions_reader_and_missing_file():
    import climate_signals as cs, json as _j
    assert cs.observed().get("status") in ("not_loaded", None) or "rain" in cs.observed()
    p = os.path.join(tempfile.mkdtemp(), "cc.json")
    _j.dump({"area_label": "T", "rain": {"dekad": "2026-10-21", "r3q": 60.0}, "vegetation": {"dekad": "2026-10-21", "viq": 90.0}}, open(p, "w"))
    old_file, old_today = cs.OBS_FILE, os.environ.get("ASOF_TODAY")
    try:
        cs.OBS_FILE, os.environ["ASOF_TODAY"] = p, "2026-11-06"
        o = cs.observed(); assert o["reading"] == "dry" and o["stale"] is False and o["rain"]["age_days"] == 16
        os.environ["ASOF_TODAY"] = "2027-03-01"; assert cs.observed()["stale"] is True          # old observations are flagged
    finally:
        cs.OBS_FILE = old_file
        if old_today is None: os.environ.pop("ASOF_TODAY", None)
        else: os.environ["ASOF_TODAY"] = old_today

def test_replacement_frontend_pages_and_languages_match():
    for page in ("index.html", "forecast.html", "xai.html", "policy.html", "destock.html"):
        assert c.get("/" + page).status_code == 200, page
    assert c.get("/").status_code == 200
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "front_end", "lang")
    keys = {
        language: set(json.load(open(os.path.join(base, language + ".json"), encoding="utf-8")))
        for language in ("en", "am", "om")
    }
    assert keys["en"] == keys["am"] == keys["om"], (
        keys["en"] ^ keys["am"],
        keys["en"] ^ keys["om"],
    )
    destock_keys = {
        language: set(
            json.load(open(os.path.join(base, language + ".json"), encoding="utf-8"))["destock"]
        )
        for language in ("en", "am", "om")
    }
    assert destock_keys["en"] == destock_keys["am"] == destock_keys["om"]

def test_climate_api_routes_are_registered_and_validate_regions():
    assert c.get("/api/health").get_json() == {"status": "ok"}
    assert "Afar" in c.get("/api/regions").get_json()["regions"]
    response = c.get("/api/observations?region=Unknown")
    assert response.status_code == 404
    assert response.get_json()["detail"] == "Unknown region."

def test_add_prices_tool_accepts_good_rows_and_rejects_bad_ones():
    import subprocess, shutil
    d = tempfile.mkdtemp(); main_copy = os.path.join(d, "main.csv"); new = os.path.join(d, "new.csv")
    shutil.copyfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "Livestock_Market_Table_Data.csv"), main_copy)
    open(new, "w").write("market,grade,min_price,max_price,qty,date\nYabalo,Moderate Weight,62000,75000,120,2026-10-28\n"
                         "Yabalo,Thin,70000,60000,10,2026-10-28\nNagele Borana,Thin,40000,52000,9,2026-10-28\nMiyo,Thin,400,520,5,2026-10-28\nMiyo,Thin,40000,52000,5,2099-01-01\n")
    tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "add_prices.py")
    out = subprocess.run([sys.executable, tool, new, "--main", main_copy, "--today", "2026-11-06"], capture_output=True, text=True).stdout
    assert "rows ok: 1 | skipped: 4" in out and "did you mean Nagelle Borana" in out, out
    assert open(main_copy, encoding="utf-8-sig").read().count("2026-10-28") >= 1
    import pandas as pd
    assert len(pd.read_csv(main_copy, encoding="utf-8-sig")) == 554                       # exactly one row added, format intact

def test_live_iod_reading_is_used_and_goes_stale():
    import climate_signals as cs
    old = os.environ.get("ASOF_TODAY")
    try:
        os.environ["ASOF_TODAY"] = "2026-11-07"
        i = cs.iod()
        assert i["live"] is True and i["phase"] == "positive" and i["dmi"] == 0.69 and i["stale"] is False, i
        assert i["history_file"]["stale"] is True                         # the old monthly file is still flagged as out of date
        os.environ["ASOF_TODAY"] = "2026-12-20"                           # weekly reading >21 days old -> must be flagged
        j = cs.iod(); assert j["stale"] is True and "update data/iod_live.json" in j["note"], j
        assert cs.context()["affects_advice"] is False                    # still context only
    finally:
        if old is None: os.environ.pop("ASOF_TODAY", None)
        else: os.environ["ASOF_TODAY"] = old

def test_sms_answers_use_existing_price_and_advice_data():
    import sms_service
    assert "Birr per medium animal" in sms_service.build_reply("What is the price at Yabalo?")
    assert "outlook" in sms_service.build_reply("Is there a drought in Yabalo?").lower()
    advice = sms_service.build_reply("ADVICE Yabalo thin 10")
    assert "Birr per animal" in advice and "confidence" in advice.lower(), advice
    assert "ADVICE Yabalo" in sms_service.build_reply("Should I sell in Yabalo?")
    assert "PRICE" in sms_service.build_reply("HELP")
    assert "number of animals" in sms_service.build_reply("ADVICE Yabalo thin 0")

def test_sms_opt_out_is_persistent_and_blocks_delivery():
    import sms_service
    old_db = os.environ.get("SMS_OPTOUT_DB")
    try:
        os.environ["SMS_OPTOUT_DB"] = os.path.join(tempfile.mkdtemp(), "sms.sqlite3")
        sms_service.set_opted_out("+251911111111", True)
        assert sms_service.is_opted_out("+251911111111")
        try:
            sms_service.send_sms("+251911111111", "test")
            assert False, "opted-out recipients must not receive messages"
        except ValueError as error:
            assert "opted out" in str(error)
        sms_service.set_opted_out("+251911111111", False)
        assert not sms_service.is_opted_out("+251911111111")
    finally:
        if old_db is None: os.environ.pop("SMS_OPTOUT_DB", None)
        else: os.environ["SMS_OPTOUT_DB"] = old_db

def test_sms_provider_request_uses_configured_credentials_and_sender():
    import sms_service
    from unittest.mock import Mock, patch
    env_names = ("SMS_OPTOUT_DB", "AT_USERNAME", "AT_API_KEY", "AT_SENDER_ID", "AT_ENVIRONMENT")
    old_env = {name: os.environ.get(name) for name in env_names}
    try:
        os.environ["SMS_OPTOUT_DB"] = os.path.join(tempfile.mkdtemp(), "sms.sqlite3")
        os.environ["AT_USERNAME"] = "test-user"
        os.environ["AT_API_KEY"] = "test-key"
        os.environ["AT_SENDER_ID"] = "WALTA"
        os.environ["AT_ENVIRONMENT"] = "sandbox"
        response = Mock()
        response.json.return_value = {
            "SMSMessageData": {"Recipients": [{"statusCode": 101, "status": "Success"}]}
        }
        with patch.object(sms_service.requests, "post", return_value=response) as post:
            result = sms_service.send_sms("+251911111111", "A test message")
        assert result["status_code"] == 101
        args, kwargs = post.call_args
        assert args[0] == sms_service.SANDBOX_SMS_API_URL
        assert kwargs["headers"]["apiKey"] == "test-key"
        assert kwargs["data"]["username"] == "test-user"
        assert "from" not in kwargs["data"]
        os.environ["AT_ENVIRONMENT"] = "production"
        with patch.object(sms_service.requests, "post", return_value=response) as post:
            sms_service.send_sms("+251911111111", "A test message")
        args, kwargs = post.call_args
        assert args[0] == sms_service.PRODUCTION_SMS_API_URL
        assert kwargs["data"]["from"] == "WALTA"
        os.environ["AT_ENVIRONMENT"] = "invalid"
        with patch.object(sms_service.requests, "post") as post:
            try:
                sms_service.send_sms("+251911111111", "A test message")
                assert False, "invalid mode should fail before sending"
            except sms_service.SMSConfigurationError:
                assert not post.called
    finally:
        for name, value in old_env.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value

def test_sms_webhook_and_admin_send_are_protected():
    import app as A
    import sms_service
    from unittest.mock import patch
    old_secret = A.SMS_WEBHOOK_SECRET
    old_db = os.environ.get("SMS_OPTOUT_DB")
    old_username = os.environ.get("AT_USERNAME")
    old_api_key = os.environ.get("AT_API_KEY")
    old_environment = os.environ.get("AT_ENVIRONMENT")
    try:
        A.SMS_WEBHOOK_SECRET = "sms-test-secret-0123456789-0123456789"
        os.environ["AT_USERNAME"] = "test"
        os.environ["AT_API_KEY"] = "test-key"
        os.environ["AT_ENVIRONMENT"] = "sandbox"
        os.environ["SMS_OPTOUT_DB"] = os.path.join(tempfile.mkdtemp(), "sms.sqlite3")
        A._sms_hits.clear()
        with patch.object(sms_service, "send_sms", return_value={"status": "Success", "status_code": 101}) as send:
            assert c.post("/sms/inbound/wrong", data={"from": "+251911111111", "text": "HELP"}).status_code == 404
            assert c.post(
                "/sms/inbound/sms-test-secret-0123456789-0123456789",
                data={"from": "+251911111111", "text": "HELP"},
            ).status_code == 200
            send.assert_called_once()
            send.reset_mock()
            stopped = c.post(
                "/sms/inbound/sms-test-secret-0123456789-0123456789",
                data={"from": "+251911111111", "text": "STOP"},
            )
            assert stopped.status_code == 200 and sms_service.is_opted_out("+251911111111")
            send.assert_called_once()
            send.reset_mock()
            suppressed = c.post(
                "/sms/inbound/sms-test-secret-0123456789-0123456789",
                data={"from": "+251911111111", "text": "HELP"},
            )
            assert suppressed.status_code == 200 and not send.called
            restarted = c.post(
                "/sms/inbound/sms-test-secret-0123456789-0123456789",
                data={"from": "+251911111111", "text": "START"},
            )
            assert restarted.status_code == 200 and not sms_service.is_opted_out("+251911111111")
            assert c.post("/api/sms/send", json={"to": "+251911111111", "message": "Hi"}).status_code == 401
            sent = c.post(
                "/api/sms/send", json={"to": "+251911111111", "message": "Hi"},
                headers={"X-Api-Key": "testkey"},
            )
            assert sent.status_code == 200 and sent.get_json()["sent"] is True
            sms_service.set_opted_out("+251911111111", True)
            blocked = c.post(
                "/api/sms/send", json={"to": "+251911111111", "message": "Hi"},
                headers={"X-Api-Key": "testkey"},
            )
            assert blocked.status_code == 409
    finally:
        A.SMS_WEBHOOK_SECRET = old_secret
        A._sms_hits.clear()
        if old_db is None: os.environ.pop("SMS_OPTOUT_DB", None)
        else: os.environ["SMS_OPTOUT_DB"] = old_db
        if old_username is None: os.environ.pop("AT_USERNAME", None)
        else: os.environ["AT_USERNAME"] = old_username
        if old_api_key is None: os.environ.pop("AT_API_KEY", None)
        else: os.environ["AT_API_KEY"] = old_api_key
        if old_environment is None: os.environ.pop("AT_ENVIRONMENT", None)
        else: os.environ["AT_ENVIRONMENT"] = old_environment

def test_sms_credentials_are_not_in_api_responses():
    names = ("AT_API_KEY", "AT_USERNAME", "SMS_WEBHOOK_SECRET", "ADMIN_KEY")
    old_values = {name: os.environ.get(name) for name in names}
    sentinels = {
        "AT_API_KEY": "test-provider-key-not-for-response",
        "AT_USERNAME": "test-sandbox-user-not-for-response",
        "SMS_WEBHOOK_SECRET": "test-webhook-secret-not-for-response",
        "ADMIN_KEY": "test-admin-key-not-for-response",
    }
    try:
        os.environ.update(sentinels)
        for path in ("/api/meta", "/api/climate", "/health"):
            response = c.get(path)
            body = response.get_data(as_text=True)
            assert all(value not in body for value in sentinels.values()), path
    finally:
        for name, value in old_values.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value

def test_seven_stakeholder_sms_workflow_is_sandbox_only_and_private():
    import sqlite3
    import app as A
    import sms_service
    from sms_stakeholders import STAKEHOLDERS, identify_stakeholder, normalize_phone
    from unittest.mock import patch

    env_names = ("SMS_OPTOUT_DB", "AT_USERNAME", "AT_API_KEY", "AT_ENVIRONMENT")
    old_env = {name: os.environ.get(name) for name in env_names}
    old_secret = A.SMS_WEBHOOK_SECRET
    db_path = os.path.join(tempfile.mkdtemp(), "stakeholder-sms.sqlite3")
    webhook_secret = "stakeholder-test-secret-0123456789-abcdefgh"
    climate_data = {
        "region": "Afar",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "observations": {
            "precipitation_90d_mm": 35.2,
            "mean_temperature_90d_c": 31.7,
            "et0_90d_mm": 420.3,
        },
        "risk": {
            "score": 64.8,
            "level": "High",
            "comparison": {"difference_percent": -64.8},
        },
    }
    try:
        os.environ["SMS_OPTOUT_DB"] = db_path
        os.environ["AT_USERNAME"] = "sandbox"
        os.environ["AT_API_KEY"] = "test-key-not-used"
        os.environ["AT_ENVIRONMENT"] = "sandbox"
        A.SMS_WEBHOOK_SECRET = webhook_secret
        A._sms_hits.clear()

        assert len(STAKEHOLDERS) == 7
        pastoralist_1, pastoralist_2, pastoralist_3, livestock_owner, veterinarian, ngo, government = (
            stakeholder.phone for stakeholder in STAKEHOLDERS
        )
        local_pastoralist_2 = "0" + pastoralist_2[4:]
        assert normalize_phone(local_pastoralist_2) == pastoralist_2
        assert normalize_phone(pastoralist_2[1:]) == pastoralist_2
        assert normalize_phone("+" + pastoralist_2[1:]) == pastoralist_2
        assert identify_stakeholder(local_pastoralist_2).role == "Pastoralist 2"
        for stakeholder in STAKEHOLDERS:
            another_request = next(
                item.request for item in STAKEHOLDERS if item.request != stakeholder.request
            )
            result = sms_service.process_stakeholder_request(
                stakeholder.phone, another_request
            )
            assert result["response_status"] == "unauthorized"

        messages = [
            (pastoralist_1, "DROUGHT STATUS Afar", "screening level High"),
            (pastoralist_2, "LIVESTOCK ADVICE Yabalo thin 10", "3-month decision aid"),
            (pastoralist_3, "WATER UPDATE Afar", "Water-point and groundwater data are unavailable"),
            (livestock_owner, "HERD RISK Yabalo medium 20", "3-month decision aid"),
            (veterinarian, "ANIMAL HEALTH Afar", "Climate stress context only"),
            (ngo, "COMMUNITY REPORT Afar", "Community livestock-loss"),
            (government, "DISTRICT SUMMARY Afar", "not a district average"),
        ]
        with (
            patch.object(
                sms_service,
                "send_sms",
                return_value={"status": "Success", "status_code": 101},
            ) as send,
            patch.object(sms_service, "_regional_climate_data", return_value=climate_data),
            patch.object(sms_service, "_advice_reply", return_value="Recommendation from existing advisor."),
        ):
            for phone, text, expected in messages:
                response = c.post(
                    f"/sms/inbound/{webhook_secret}",
                    json={"from": phone, "to": "16273", "text": text},
                )
                assert response.status_code == 200, response.get_json()
                assert response.get_json()["delivery"] == "Success"
                assert expected in send.call_args.args[1], send.call_args.args[1]
                assert send.call_args.args[0] == phone
            assert send.call_count == 7

            unauthorized = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={
                    "from": pastoralist_1,
                    "to": "16273",
                    "text": "HERD RISK Yabalo thin 10",
                },
            )
            assert unauthorized.status_code == 200
            assert "Not authorized" in send.call_args.args[1]

            unknown = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={
                    "from": "+251900009999",
                    "to": "16273",
                    "text": "DISTRICT SUMMARY Afar",
                },
            )
            assert unknown.status_code == 200
            assert "limited to registered numbers" in send.call_args.args[1]

            before_invalid = send.call_count
            invalid = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={"from": pastoralist_1, "to": "16273", "text": ""},
            )
            assert invalid.status_code == 400
            assert send.call_count == before_invalid

            with patch.object(sms_service, "_regional_climate_data", return_value=None):
                unavailable = c.post(
                    f"/sms/inbound/{webhook_secret}",
                    json={
                        "from": pastoralist_1,
                        "to": "16273",
                        "text": "DROUGHT STATUS Afar",
                    },
                )
            assert unavailable.status_code == 200
            assert "observations are unavailable" in send.call_args.args[1]

            send.side_effect = sms_service.SMSProviderError("mocked failure")
            failure = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={
                    "from": veterinarian,
                    "to": "16273",
                    "text": "ANIMAL HEALTH",
                },
            )
            assert failure.status_code == 502
            send.side_effect = None

            wrong_destination = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={
                    "from": veterinarian,
                    "to": "12345",
                    "text": "ANIMAL HEALTH",
                },
            )
            assert wrong_destination.status_code == 400

            assert c.post(
                "/sms/inbound/wrong-secret",
                json={"from": veterinarian, "to": "16273", "text": "ANIMAL HEALTH"},
            ).status_code == 404

            stopped = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={"from": veterinarian, "to": "16273", "text": "STOP"},
            )
            assert stopped.status_code == 200 and sms_service.is_opted_out(veterinarian)
            suppressed = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={"from": veterinarian, "to": "16273", "text": "ANIMAL HEALTH"},
            )
            assert suppressed.status_code == 200
            restarted = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={"from": veterinarian, "to": "16273", "text": "START"},
            )
            assert restarted.status_code == 200 and not sms_service.is_opted_out(veterinarian)

        os.environ["AT_ENVIRONMENT"] = "production"
        with patch.object(sms_service, "send_sms") as send:
            blocked = c.post(
                f"/sms/inbound/{webhook_secret}",
                json={
                    "from": pastoralist_1,
                    "to": "16273",
                    "text": "DROUGHT STATUS Afar",
                },
            )
            assert blocked.status_code == 503
            assert not send.called

        with sqlite3.connect(db_path) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(sms_request_audit)")
            }
            assert columns == {
                "id", "request_type", "stakeholder_role", "response_status", "created_at"
            }
            rows = connection.execute(
                "SELECT request_type, stakeholder_role, response_status, created_at "
                "FROM sms_request_audit"
            ).fetchall()
            expected_roles = {
                ("DROUGHT STATUS", "Pastoralist 1"),
                ("LIVESTOCK ADVICE", "Pastoralist 2"),
                ("WATER UPDATE", "Pastoralist 3"),
                ("HERD RISK", "Agro-pastoralist / Livestock owner"),
                ("ANIMAL HEALTH", "Veterinarian"),
                ("COMMUNITY REPORT", "NGO representative"),
                ("DISTRICT SUMMARY", "Government representative"),
            }
            assert expected_roles.issubset({row[:2] for row in rows})
            assert any(row[2] == "unauthorized_delivered" for row in rows)
            assert any(row[2] == "unknown_sender_delivered" for row in rows)
            assert any(row[2] == "data_unavailable_delivery_failed" for row in rows)
            assert all(row[3] for row in rows)
            assert all("251" not in repr(row) for row in rows)
            assert all("Afar" not in repr(row) for row in rows)
    finally:
        A.SMS_WEBHOOK_SECRET = old_secret
        A._sms_hits.clear()
        for name, value in old_env.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value

def test_sms_climate_summary_uses_recent_observations_and_historical_baseline():
    import climate_api
    from datetime import date, timedelta
    from unittest.mock import patch

    period_end = date.today() - timedelta(days=7)
    period_start = period_end - timedelta(days=10 * 366 + 89)
    dates = [
        (period_start + timedelta(days=offset)).isoformat()
        for offset in range((period_end - period_start).days + 1)
    ]
    payload = {
        "daily": {
            "time": dates,
            "precipitation_sum": [1.0] * len(dates),
            "temperature_2m_mean": [29.5] * len(dates),
            "et0_fao_evapotranspiration": [4.0] * len(dates),
        }
    }
    with patch.object(climate_api, "_fetch_daily_data", return_value=payload) as fetch:
        summary = climate_api.sms_regional_summary("Afar")

    assert fetch.call_count == 1
    assert summary["source"] == "ERA5-Land historical reanalysis via Open-Meteo"
    assert summary["observations"]["days"] == 90
    assert summary["observations"]["precipitation_90d_mm"] == 90.0
    assert summary["observations"]["mean_temperature_90d_c"] == 29.5
    assert summary["observations"]["et0_90d_mm"] == 360.0
    assert summary["risk"]["comparison"]["indicator_type"] == "retrospective_rainfall_comparison"

def test_registration_workflow_all_categories_prices_and_sms_templates():
    import sqlite3
    import app as A
    import sms_service
    from sms_stakeholders import CATEGORY_PRICES, CATEGORY_REQUESTS, REGISTRATION_REGIONS
    from unittest.mock import patch

    env_names = ("SMS_OPTOUT_DB", "AT_USERNAME", "AT_API_KEY", "AT_ENVIRONMENT")
    old_env = {name: os.environ.get(name) for name in env_names}
    old_secret = A.SMS_WEBHOOK_SECRET
    db_path = os.path.join(tempfile.mkdtemp(), "registration-test.sqlite3")
    webhook_secret = "registration-test-secret-0123456789-abcdefgh"
    climate_data = {
        "region": "Oromia",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "observations": {
            "precipitation_90d_mm": 35.2,
            "mean_temperature_90d_c": 31.7,
            "et0_90d_mm": 420.3,
        },
        "risk": {
            "score": 64.8,
            "level": "High",
            "comparison": {"difference_percent": -64.8},
        },
    }
    templates = {
        "Pastoralist": "pastoralist registration",
        "Agro-pastoralist": "agro-pastoral registration",
        "Livestock business / livestock owner": "livestock business registration",
        "Veterinarian / animal health worker": "animal-health registration",
        "NGO / development organization": "organization registration",
        "Government institution": "government registration",
    }
    try:
        os.environ["SMS_OPTOUT_DB"] = db_path
        os.environ["AT_USERNAME"] = "sandbox"
        os.environ["AT_API_KEY"] = "test-key-not-used"
        os.environ["AT_ENVIRONMENT"] = "sandbox"
        A.SMS_WEBHOOK_SECRET = webhook_secret
        A._sms_hits.clear()
        A._registration_hits.clear()

        options = c.get("/api/registration/options").get_json()
        assert options["regions"] == list(REGISTRATION_REGIONS)
        assert options["prices"] == CATEGORY_PRICES
        assert "Oromia" in options["climate_reference_points"]
        assert "Southern Ethiopia" not in options["climate_reference_points"]

        phone_numbers = {}
        with (
            patch.object(sms_service, "_regional_climate_data", return_value=climate_data),
            patch.object(
                sms_service,
                "send_sms",
                return_value={"status": "Sandbox accepted", "status_code": 101},
            ) as send,
        ):
            request_index = 0
            for category, price_options in CATEGORY_PRICES.items():
                for period, price in price_options.items():
                    request_index += 1
                    phone = f"+2519{request_index:08d}"
                    phone_numbers[(category, period)] = phone
                    response = c.post(
                        "/api/registrations",
                        json={
                            "full_name": f"Test User {request_index}",
                            "phone": phone,
                            "region": "Oromia",
                            "area": "Borena",
                            "category": category,
                            "billing_period": period,
                            "sms_consent": True,
                        },
                        environ_base={"REMOTE_ADDR": f"192.0.2.{request_index}"},
                    )
                    assert response.status_code == 201, (request_index, phone, response.get_json())
                    result = response.get_json()
                    assert result["price_etb"] == price
                    assert result["subscription_status"] == "pending_payment"
                    assert result["sms_status"] == "accepted"
                    assert result["category"] == category and result["region"] == "Oromia"
                    registration = sms_service.registration_by_phone(phone)
                    stakeholder = sms_service.registration_for_stakeholder(phone)
                    assert registration["price_etb"] == price
                    assert registration["area"] == "Borena"
                    assert registration["billing_period"] == period
                    assert registration["subscription_status"] == "pending_payment"
                    assert registration["sms_status"] == "accepted"
                    assert stakeholder.request == CATEGORY_REQUESTS[category]
                    assert stakeholder.region == "Oromia" and stakeholder.area == "Borena"
                    sent_message = send.call_args.args[1]
                    assert templates[category] in sent_message
                    assert "Oromia" in sent_message and "ERA5-Land observations" in sent_message
                    assert "Borena" in sent_message
                    response_body = response.get_data(as_text=True)
                    assert "test-key-not-used" not in response_body
                    assert webhook_secret not in response_body

            assert send.call_count == len(CATEGORY_PRICES) * 2
            duplicate = c.post(
                "/api/registrations",
                json={
                    "full_name": "Duplicate User",
                    "phone": phone_numbers[("Pastoralist", "monthly")],
                    "region": "Oromia",
                    "category": "Pastoralist",
                    "billing_period": "monthly",
                    "sms_consent": True,
                },
                environ_base={"REMOTE_ADDR": "192.0.2.100"},
            )
            assert duplicate.status_code == 409
            assert send.call_count == len(CATEGORY_PRICES) * 2

        with sqlite3.connect(db_path) as connection:
            attempts = connection.execute(
                "SELECT COUNT(*) FROM registration_sms_attempts WHERE status = 'accepted'"
            ).fetchone()[0]
            assert attempts == len(CATEGORY_PRICES) * 2
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(registrations)")
            }
            assert {
                "id", "full_name", "phone", "region", "area", "category",
                "billing_period", "price_etb", "subscription_status", "sms_consent",
                "sms_status", "created_at",
            }.issubset(columns)
    finally:
        A.SMS_WEBHOOK_SECRET = old_secret
        A._sms_hits.clear()
        A._registration_hits.clear()
        for name, value in old_env.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value

def test_registration_rejects_bad_input_duplicate_stakeholder_and_respects_optout():
    import app as A
    import sms_service
    from sms_stakeholders import STAKEHOLDERS
    from unittest.mock import patch

    old_db = os.environ.get("SMS_OPTOUT_DB")
    db_path = os.path.join(tempfile.mkdtemp(), "registration-validation.sqlite3")
    os.environ["SMS_OPTOUT_DB"] = db_path
    A._registration_hits.clear()
    base = {
        "full_name": "Test User",
        "phone": "+251911222333",
        "region": "Oromia",
        "area": "",
        "category": "Pastoralist",
        "billing_period": "monthly",
        "sms_consent": True,
    }
    try:
        invalid_cases = [
            ({**base, "phone": "12345"}, "phone"),
            ({**base, "phone": "+251811222333"}, "phone"),
            ({**base, "full_name": ""}, "full_name"),
            ({**base, "region": "Not a region"}, "region"),
            ({**base, "category": "Administrator"}, "category"),
            ({**base, "billing_period": "weekly"}, "billing_period"),
            ({**base, "sms_consent": False}, "sms_consent"),
        ]
        with patch.object(sms_service, "send_sms") as send:
            for index, (payload, _field) in enumerate(invalid_cases):
                result = c.post(
                    "/api/registrations",
                    json=payload,
                    environ_base={"REMOTE_ADDR": f"198.51.100.{index + 1}"},
                )
                assert result.status_code == 400, result.get_json()
            assert not send.called
            for attempt in range(5):
                limited = c.post(
                    "/api/registrations",
                    json={},
                    environ_base={"REMOTE_ADDR": "198.51.100.99"},
                )
                assert limited.status_code == 400
            assert c.post(
                "/api/registrations",
                json={},
                environ_base={"REMOTE_ADDR": "198.51.100.99"},
            ).status_code == 429

            assigned_number = c.post(
                "/api/registrations",
                json={**base, "phone": STAKEHOLDERS[0].phone},
                environ_base={"REMOTE_ADDR": "198.51.100.20"},
            )
            assert assigned_number.status_code == 409
            assert not send.called

            sms_service.set_opted_out(base["phone"], True)
            saved = c.post(
                "/api/registrations",
                json=base,
                environ_base={"REMOTE_ADDR": "198.51.100.21"},
            )
            assert saved.status_code == 201
            assert saved.get_json()["sms_status"] == "suppressed_opted_out"
            assert sms_service.registration_by_phone(base["phone"]) is not None
            assert not send.called
    finally:
        sms_service.set_opted_out(base["phone"], False)
        A._registration_hits.clear()
        if old_db is None: os.environ.pop("SMS_OPTOUT_DB", None)
        else: os.environ["SMS_OPTOUT_DB"] = old_db

def test_registration_sms_failure_keeps_registration_and_dynamic_routing_scoped():
    import app as A
    import sms_service
    from unittest.mock import patch

    env_names = ("SMS_OPTOUT_DB", "AT_USERNAME", "AT_API_KEY", "AT_ENVIRONMENT")
    old_env = {name: os.environ.get(name) for name in env_names}
    old_secret = A.SMS_WEBHOOK_SECRET
    db_path = os.path.join(tempfile.mkdtemp(), "registration-routing.sqlite3")
    secret = "registration-routing-secret-0123456789-abcdef"
    phone = "+251911333444"
    climate_data = {
        "region": "Oromia",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "observations": {
            "precipitation_90d_mm": 40.0,
            "mean_temperature_90d_c": 30.0,
            "et0_90d_mm": 400.0,
        },
        "risk": {
            "score": 50.0,
            "level": "High",
            "comparison": {"difference_percent": -50.0},
        },
    }
    try:
        os.environ["SMS_OPTOUT_DB"] = db_path
        os.environ["AT_USERNAME"] = "sandbox"
        os.environ["AT_API_KEY"] = "test-key-not-used"
        os.environ["AT_ENVIRONMENT"] = "sandbox"
        A.SMS_WEBHOOK_SECRET = secret
        A._sms_hits.clear()
        A._registration_hits.clear()
        with patch.object(sms_service, "_regional_climate_data", return_value=climate_data), patch.object(
            sms_service,
            "send_sms",
            side_effect=sms_service.SMSProviderError("mocked provider failure"),
        ) as send:
            failed_delivery = c.post(
                "/api/registrations",
                json={
                    "full_name": "Routing Test",
                    "phone": phone,
                    "region": "Oromia",
                    "area": "Borena",
                    "category": "Pastoralist",
                    "billing_period": "yearly",
                    "sms_consent": True,
                },
                environ_base={"REMOTE_ADDR": "203.0.113.11"},
            )
            assert failed_delivery.status_code == 201
            assert failed_delivery.get_json()["sms_status"] == "failed"
            registration = sms_service.registration_by_phone(phone)
            assert registration is not None
            assert registration["subscription_status"] == "pending_payment"
            send.assert_called_once()

        with patch.object(sms_service, "_regional_climate_data", return_value=climate_data), patch.object(
            sms_service,
            "send_sms",
            return_value={"status": "Accepted", "status_code": 101},
        ) as send:
            inbound = c.post(
                f"/sms/inbound/{secret}",
                json={"from": phone, "to": "16273", "text": "DROUGHT STATUS"},
            )
            assert inbound.status_code == 200
            assert inbound.get_json()["delivery"] == "Accepted"
            assert send.call_args.args[0] == phone
            assert "Borena representative grid" in send.call_args.args[1]

            wrong_command = c.post(
                f"/sms/inbound/{secret}",
                json={"from": phone, "to": "16273", "text": "DISTRICT SUMMARY"},
            )
            assert wrong_command.status_code == 200
            assert "Not authorized" in send.call_args.args[1]

            wrong_region = c.post(
                f"/sms/inbound/{secret}",
                json={"from": phone, "to": "16273", "text": "DROUGHT STATUS Afar"},
            )
            assert wrong_region.status_code == 200
            assert "limited to your registered region" in send.call_args.args[1]

        os.environ["AT_ENVIRONMENT"] = "production"
        with patch.object(sms_service, "send_sms") as send:
            prod_registration = c.post(
                "/api/registrations",
                json={
                    "full_name": "Sandbox Gate Test",
                    "phone": "+251911333445",
                    "region": "Oromia",
                    "area": "",
                    "category": "Pastoralist",
                    "billing_period": "monthly",
                    "sms_consent": True,
                },
                environ_base={"REMOTE_ADDR": "203.0.113.12"},
            )
            assert prod_registration.status_code == 201
            assert prod_registration.get_json()["sms_status"] == "sandbox_required"
            assert not send.called
    finally:
        A.SMS_WEBHOOK_SECRET = old_secret
        A._sms_hits.clear()
        A._registration_hits.clear()
        for name, value in old_env.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"): f(); print("PASS", n)
