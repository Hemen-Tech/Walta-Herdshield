#!/usr/bin/env python3
"""Find CANDIDATE literature for the advisor's weakest assumptions, using a running Probe server.

IMPORTANT: results are only *candidates* for a human to read. Nothing here changes the advice. Why:
  * Probe was built to pressure-test startup ideas, not to measure livestock death rates. Its 'supports/challenges'
    labels are automatic and are kept below only as 'probe_auto_stance_unverified'.
  * Unpatched Probe silently returns 8 FABRICATED sample papers (ids sx-edu-*, sx-cook-*, sx-acct-*) with status
    'success' when its ScholarXIV key is missing or the search fails. This script rejects them, and also rejects
    anything that does not mention livestock/pastoral terms. Please also apply probe_patch/ to Probe itself.

Usage:   python probe_bridge.py
Output:  data/evidence_candidates.json  (shown on the dashboard as 'candidates waiting for review')
"""
import argparse
import datetime
import json
import os
import re
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROBE_URL = "https://probe.ethiodeploy.com"
FABRICATED_ID = re.compile(r"^sx-(edu|cook|acct)-\d{4}-\d{2}$")      # Probe's built-in demo papers
CORE_TERMS = ("cattle", "livestock", "pastoral", "borana", "boran ", "rangeland", "herd", "oxen", "destock",
              "grazing", "forage", "zebu", "ruminant", "bovine")


def screen(result, limit=6):
    """Pure function: decide what to keep from one Probe /api/research/assumption reply.
    Returns (accepted_papers, rejected [(title, reason)], problem or None)."""
    if not isinstance(result, dict):
        return [], [], "reply is not a JSON object"
    if result.get("status") != "success":
        return [], [], "Probe status is %r (need 'success')" % result.get("status")
    papers = result.get("papers") or []
    if not papers:
        return [], [], "no papers returned"
    accepted, rejected = [], []
    for p in papers:
        title = str(p.get("title", ""))[:140]
        pid = str(p.get("id", ""))
        if FABRICATED_ID.match(pid):
            rejected.append((title, "fabricated demo paper built into Probe"))
            continue
        text = ("%s %s" % (p.get("title", ""), p.get("abstract", ""))).lower() + " "
        hits = [t.strip() for t in CORE_TERMS if t in text]
        if not hits:
            rejected.append((title, "does not mention livestock or pastoral terms"))
            continue
        if not (p.get("url") or p.get("doi")):
            rejected.append((title, "no URL or DOI to check"))
            continue
        accepted.append({
            "title": p.get("title"), "authors": p.get("authors"), "year": p.get("year"), "url": p.get("url"), "doi": p.get("doi"),
            "abstract": str(p.get("abstract", ""))[:600], "matched_terms": hits,
            "probe_auto_stance_unverified": p.get("stance"), "needs_human_review": True,
        })
    return accepted[:limit], rejected, None


def run(probe, claims_path, out_path, limit, timeout):
    probe = probe.rstrip("/")
    try:
        requests.get(probe + "/api/health", timeout=10).raise_for_status()
    except Exception as e:
        sys.exit("Cannot reach Probe at %s (%s). Start it first (npm run dev) and check the address." % (probe, e))
    claims = json.load(open(claims_path, encoding="utf-8"))["claims"]
    existing = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {"candidates": []}
    seen = {(c["claim_key"], c.get("url")) for c in existing["candidates"]}
    today = datetime.date.today().isoformat()
    report = []
    for c in claims:
        body = {"assumptionId": c["key"], "assumptionText": c["probe_text"], "idea": "livestock destocking decisions in Borana, Ethiopia", "limit": limit, "forceRefresh": True}
        try:
            r = requests.post(probe + "/api/research/assumption", json=body, timeout=timeout)
            reply = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
            if r.status_code != 200:
                report.append((c["key"], 0, 0, "HTTP %d" % r.status_code)); continue
        except Exception as e:
            report.append((c["key"], 0, 0, "request failed: %s" % e)); continue
        ok, bad, problem = screen(reply, limit)
        for p in ok:
            if (c["key"], p["url"]) not in seen:
                existing["candidates"].append({"claim_key": c["key"], "retrieved": today, "query_text": c["probe_text"], **p})
                seen.add((c["key"], p["url"]))
        report.append((c["key"], len(ok), len(bad), problem or "; ".join(sorted({reason for _, reason in bad})) or "ok"))
    existing["updated"] = today
    existing["warning"] = "Candidates only. A person must read each source before it is moved into evidence.json."
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print("%-14s %8s %9s  note" % ("claim", "kept", "rejected"))
    for k, a, b, note in report:
        print("%-14s %8d %9d  %s" % (k, a, b, note))
    print("Saved to", out_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", default=os.environ.get("PROBE_URL", DEFAULT_PROBE_URL))
    ap.add_argument("--claims", default=os.path.join(HERE, "data", "evidence_claims.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "data", "evidence_candidates.json"))
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=60)
    a = ap.parse_args()
    run(a.probe, a.claims, a.out, a.limit, a.timeout)
