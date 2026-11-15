"""Web + JSON routes for the advisor, shared by the standalone app (prefix '') and the HerdShield merge (prefix '/advisor')."""
import datetime
import json
import os
from flask import Blueprint, abort, jsonify, request, send_from_directory
import climate_signals
from data_store import GRADES, get_store
from engine import advise, A as ASSUMPTIONS, MAX_HERD
import drought_provider as dp


def make_blueprint(front_dir, url_prefix, ussd_markets):
    bp = Blueprint("advisor", __name__, url_prefix=url_prefix)
    allowed_origin = os.environ.get("ALLOWED_ORIGIN")          # same-origin by default; set to allow another site

    @bp.after_request
    def _cors(resp):
        if allowed_origin:
            resp.headers["Access-Control-Allow-Origin"] = allowed_origin
        return resp

    @bp.get("/")
    def home():
        return send_from_directory(front_dir, "index.html")

    @bp.get("/api/meta")
    def meta():
        store = get_store()
        markets = store.markets()
        st = dp.status()
        return jsonify({
            "markets": markets, "grades": GRADES, "data_report": store.report,
            "ussd_markets": list(ussd_markets), "max_herd": MAX_HERD,
            "assumptions": {k: v for k, v in ASSUMPTIONS.items() if not k.startswith("_")},
            "drought": st, "drought_connected": st["status"] != "unavailable",
            "regions_note": "Drought outlook is per region (Afar/Somali/Oromia); Borana markets use Oromia.",
            "default_market": "Nagelle Borana" if any(m["market"] == "Nagelle Borana" for m in markets) else markets[0]["market"],
            "climate": climate_signals.context(),
        })

    @bp.get("/api/climate")
    def api_climate():
        return jsonify(climate_signals.context())

    @bp.get("/api/advice")
    def api_advice():
        market = request.args.get("market", "")
        grade = request.args.get("grade", "Moderate Weight")
        lang = request.args.get("lang", "en")
        try:
            herd = int(request.args.get("herd", "1"))
            sev = request.args.get("severity")
            sev = None if sev in (None, "", "auto") else int(sev)
            if sev is not None and sev not in (0, 1, 2, 3):
                raise ValueError("severity must be 0-3")
            out = advise(market, grade, herd, lang, sev)
            out["climate_context"] = climate_signals.context()          # informational only, never changes the advice
            return jsonify(out)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @bp.get("/api/history")
    def api_history():
        market = request.args.get("market", "")
        store = get_store()
        if market not in store.df["market"].values:
            return jsonify({"error": "unknown market"}), 404
        h = store.history(market)
        h["pressure"] = store.pressure(market)[0]
        return jsonify(h)

    @bp.post("/api/drought")
    def api_drought_update():
        """Your drought model pushes its latest outlook. Header X-Api-Key must equal the ADMIN_KEY secret."""
        key = os.environ.get("ADMIN_KEY")
        if not key or request.headers.get("X-Api-Key") != key:
            return jsonify({"error": "unauthorized"}), 401
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "send a JSON object"}), 400
        items = {**{"regions/" + k: v for k, v in (body.get("regions") or {}).items()},
                 **{"markets/" + k: v for k, v in (body.get("markets") or {}).items()}}
        if not items:
            return jsonify({"error": "need 'regions' and/or 'markets'"}), 400
        for name, v in items.items():
            err = dp.validate(v)
            if err:
                return jsonify({"error": "%s: %s" % (name, err)}), 400
        body["updated"] = str(body.get("updated") or datetime.date.today().isoformat())[:10]
        tmp = dp.FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=1)
        os.replace(tmp, dp.FILE)                                  # atomic: readers never see a half-written file
        return jsonify({"saved": True, "updated": body["updated"], "file": dp.FILE,
                        "warning": None if os.environ.get("DROUGHT_FILE") else
                        "Saved to the app folder. On Cloud Run/Replit this is lost on restart: set DROUGHT_FILE to a persistent path or use DROUGHT_MODEL_URL."})

    @bp.get("/api/evidence")
    def api_evidence():
        """Where each assumption comes from, and how well it is supported (data/evidence.json), plus how many
        Probe candidates are waiting for a human to review. Candidates never affect the advice."""
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        try:
            lib = json.load(open(os.path.join(base, "evidence.json"), encoding="utf-8"))
        except (OSError, ValueError):
            return jsonify({"error": "evidence library not found"}), 404
        lang = request.args.get("lang", "en")
        lang = lang if lang in ("en", "om", "am") else "en"
        store = get_store()
        items = []
        for it in lib["items"]:
            row = dict(it)
            row["label"] = it["label"].get(lang) or it["label"]["en"]
            row["sources"] = [dict(lib["sources"][k], id=k) for k in it.get("sources", []) if k in lib["sources"]]
            if it["key"] == "grade_price_gap":
                gr = store.grade_ratio
                row["measured_value"] = "Thin %+.0f%%, Very Fat %+.0f%% vs medium" % ((gr["Thin"] - 1) * 100, (gr["Very Fat"] - 1) * 100)
            items.append(row)
        n_cand = 0
        try:
            n_cand = len(json.load(open(os.path.join(base, "evidence_candidates.json"), encoding="utf-8")).get("candidates", []))
        except (OSError, ValueError):
            pass
        return jsonify({"updated": lib.get("updated"), "how_to_read": lib.get("how_to_read"), "items": items, "candidates_waiting": n_cand})

    @bp.get("/<path:filename>")
    def static_files(filename):
        if any(
            part.strip(" .").casefold() == "backend"
            for part in filename.replace("\\", "/").split("/")
        ):
            abort(404)
        return send_from_directory(front_dir, filename)

    return bp
