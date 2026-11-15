# Using Probe with the Destocking Advisor

## What this integration is (and is not)
Probe is built to pressure-test startup ideas: it searches papers and online discussions and labels each as supporting or challenging an assumption.
It does NOT measure livestock death rates. So here Probe is a **research helper that finds candidate sources**, and a **person** decides what goes into the advisor.
Nothing Probe returns changes the advice automatically.

```
Probe server  --probe_bridge.py-->  data/evidence_candidates.json  --you read & decide-->  data/evidence.json  -->  dashboard "Where the numbers come from"
```

## Two things I found in Probe that you must know
1. Unpatched Probe can return **invented papers** (fake authors and statistics about students, cooking, SaaS) marked "success" when its paper-search key is missing or the search fails. Apply the patch in `probe_patch/` first. The bridge also rejects those papers and anything that does not mention livestock or pastoral terms.
2. Probe's "supports / challenges" labels are automatic and tuned for startup ideas. The bridge keeps them only as `probe_auto_stance_unverified`.

## Steps (Windows)
1. Ensure the Probe deployment has the safeguards in `probe_patch/` applied and its `GEMINI_API_KEY` and `SCHOLARXIV_API_KEY` configured (never share these). Without the ScholarXIV key, the patched Probe should say "unavailable" rather than return sample papers.
2. The default Probe server is `https://probe.ethiodeploy.com`. Its `/api/health` endpoint was checked and returned `{"status":"ok","service":"Probe Research Search Engine"}`. This confirms service reachability, not that research searches work.
3. In the advisor folder, install the `requests` dependency if needed, then run `python probe_bridge.py`. This sends the advisor's evidence-assumption queries to Probe and writes screened candidate results. To use a different server, set `PROBE_URL` or pass `--probe`.
   It prints, for each claim, how many papers were kept and how many were rejected and why.
4. Open `data/evidence_candidates.json`, read each paper (the link, not just the abstract), and if it really gives Borana or pastoral cattle numbers, add it to `data/evidence.json` (sources + a note, and change the item's status). The dashboard then shows it.

## Honest expectations
- ScholarXIV is mostly computer-science and economics preprints. Expect few or no Borana livestock papers. Better places for the numbers: FAO/ILRI reports, the sources already listed in the dashboard, the Borana zone livestock office, and herder interviews.
- Probe's other search sources (Reddit, X, LinkedIn) say little about herder death rates. Its more useful side here is `/api/research/stream`, which can pressure-test the *product idea* (would herders trust and use USSD advice?).
- Probe and the advisor are two separate apps. Probe's screens are not embedded in the dashboard.
- The bridge was tested against a mock Probe server that includes the fake-paper case. The deployed service's health endpoint was checked, but no research queries have been submitted to it yet.
