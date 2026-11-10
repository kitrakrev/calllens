"""Self-healing: turn CallLens findings into a live patch on the Vapi assistant."""
import os
import re

import httpx

import calllens

ASSISTANT = os.environ.get("VAPI_ASSISTANT_ID", "")
KNOWN_PLACES = ["Embarcadero", "Dolores Park", "Mission District", "SoMa", "Hayes Valley", "North Beach", "Ferry Building"]


def plan(call_id: str | None = None) -> dict:
    d = calllens.diagnose(call_id)
    issues = {t["issue"] for t in d["turns"]}
    caller_text = " ".join(t["text"] for t in d["turns"] if t["role"] == "caller")
    fixes, patch = [], {}
    cur = httpx.get(f"https://api.vapi.ai/assistant/{ASSISTANT}", headers=calllens.H, timeout=15).json()
    tr = dict(cur.get("transcriber") or {})
    if "misheard" in issues:
        terms = [p for p in KNOWN_PLACES if p.lower() in caller_text.lower() or p.lower().split()[0][:4] in caller_text.lower()]
        terms = sorted(set(terms + ["Embarcadero"]))
        tr["keyterm"] = sorted(set((tr.get("keyterm") or []) + terms))
        fixes.append(f"Deepgram keyterms added: {', '.join(terms)} (caller's place names were misheard)")
    lang = (d.get("meta", {}).get("lang") or {}).get("choice")
    li = (d.get("meta", {}).get("lang_issue") or {}).get("noul") or 0
    if lang not in (None, "english") or li > 0.4:
        tr["language"] = "multi"
        fixes.append(f"Deepgram language -> multi (Jev: caller language '{lang}', garbling {li:.0%})")
    if tr != (cur.get("transcriber") or {}):
        patch["transcriber"] = tr
    if "slow" in issues:
        patch["startSpeakingPlan"] = {"waitSeconds": 0.4}
        fixes.append("Endpointing wait lowered to 0.4s (slow replies / dead air detected)")
    return {"call": d["id"], "fixes": fixes, "patch": patch}


def apply(call_id: str | None = None) -> dict:
    p = plan(call_id)
    if p["patch"]:
        r = httpx.patch(f"https://api.vapi.ai/assistant/{ASSISTANT}", headers=calllens.H, json=p["patch"], timeout=15)
        p["status"] = r.status_code
        p["error"] = None if r.is_success else r.text[:300]
    return p
