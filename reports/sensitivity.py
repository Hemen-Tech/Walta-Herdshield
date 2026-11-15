"""Sensitivity of the SELL/HOLD decision to the assumed numbers.
Each uncertain assumption is nudged down/up by 50% (and monthly price drift by -/+1%), one at a time.
Run:  python reports/sensitivity.py   -> writes reports/SENSITIVITY.md"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_store import get_store, GRADES
import engine

store = get_store()
mk_list = ["Yabalo", "Nagelle Borana", "Miyo", "Arero", "Moyale Oromiya"]
flips = collections.Counter(); total = collections.Counter(); steps = collections.Counter()
sev_flip = collections.Counter(); sev_total = collections.Counter()
for mk in mk_list:
    lv = store.price_level(mk)
    if not lv: continue
    level = lv[0]; pressure = store.pressure(mk)[0]
    for g0, g in enumerate(GRADES):
        P0 = {i: level * store.grade_ratio[GRADES[i]] for i in range(3)}
        for sev in range(4):
            probs = [0.0]*4; probs[sev] = 1.0
            base = engine._decide(P0, g0, probs, store.drift, pressure, engine.A)[0]
            variants = [(grp, f, engine._decide(P0, g0, probs, store.drift, pressure, engine._perturbed(engine.A, grp, f))[0]) for grp in engine.PERTURB_GROUPS for f in (0.5, 1.5)]
            variants += [("price_drift", sh, engine._decide(P0, g0, probs, store.drift + sh, pressure, engine.A)[0]) for sh in (-0.01, 0.01)]
            for grp, f, a in variants:
                total[grp] += 1; sev_total[sev] += 1
                if a != base:
                    flips[grp] += 1; sev_flip[sev] += 1
                    steps[abs(engine.ACTIONS.index(a) - engine.ACTIONS.index(base))] += 1
lines = ["# Sensitivity of the decision to the assumptions", "",
         f"Tested {len(mk_list)} markets x 3 animal conditions x 4 drought scenarios, nudging one assumption at a time.", "",
         "| Assumption nudged (-50% / +50%; drift -1% / +1% per month) | Share of tests where the advice changed |", "|---|---|"]
for grp in engine.PERTURB_GROUPS + ["price_drift"]:
    lines.append(f"| {grp} | {flips[grp]/total[grp]*100:.0f}% |")
lines += ["", "| Drought scenario | Share of tests where the advice changed |", "|---|---|"]
for sev in range(4):
    lines.append(f"| {engine.SEV[sev]} | {sev_flip[sev]/sev_total[sev]*100:.0f}% |")
lines += ["", f"When advice changed it moved by one step in {steps[1]} cases and by two or more steps in {sum(v for k,v in steps.items() if k>=2)} cases.", "",
          "Reading: where the share is high, that assumption MUST be replaced with local evidence before the advice is trusted."]
out = "\n".join(lines)
open(os.path.join(os.path.dirname(__file__), "SENSITIVITY.md"), "w").write(out)
print(out)
