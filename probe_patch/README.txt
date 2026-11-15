PATCH FOR PROBE (Novarion-main) - stops it inventing evidence
==============================================================
What was wrong (in the Probe.zip you sent):
 1. When SCHOLARXIV_API_KEY is missing, or the live search fails or finds nothing, Probe silently returns 8 FABRICATED
    sample papers (invented authors and statistics about students, cooking and micro-SaaS; ids sx-edu-*, sx-cook-*,
    sx-acct-*) and reports status "success". Any query gets them, even about cattle.
 2. If the assumption-research endpoint crashes, it replies status "ok" with "No conflicting literature identified",
    which looks like evidence but is an error.

What the patch does:
 1. The fabricated papers are used ONLY if you set PROBE_ALLOW_DEMO_CORPUS=1 (for demos). Otherwise Probe reports "unavailable".
 2. A crash now returns HTTP 502 with status "error" and "No conclusion can be drawn."

Two ways to apply (pick one):
 A) Easiest on Windows: copy the two files under  patched/src/...  over the same paths inside Novarion-main
    (src/lib/server/apiApp.ts and src/lib/server/integrations/scholarxiv.ts). They are based on the Probe.zip you sent.
 B) With the 'patch' tool, inside Novarion-main:   patch -p1 < probe_no_fake_evidence.patch
The patch was checked to apply cleanly (dry run). I could not compile or run Probe here (no internet), so run
'npm run lint' once after applying.
