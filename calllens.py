"""CallLens: diagnose a Vapi call (latency per stage, dead air, misheard turns) with Jev as judge."""
import html
import os

import httpx

VAPI = os.environ.get("VAPI_API_KEY", "")
JEV = os.environ.get("JEV_API_KEY", "")
H = {"Authorization": f"Bearer {VAPI}"}


def latest_call(call_id: str | None = None) -> dict:
    if call_id:
        return httpx.get(f"https://api.vapi.ai/call/{call_id}", headers=H, timeout=15).json()
    calls = httpx.get("https://api.vapi.ai/call?limit=5", headers=H, timeout=15).json()
    return next((c for c in calls if c.get("status") == "ended"), calls[0] if calls else {})


def jev_classify(turns: list[str]) -> list[dict]:
    """One Jev request, one Choice question per turn."""
    if not JEV or not turns:
        return [{} for _ in turns]
    qs = {
        f"t{i}": {
            "type": "choice",
            "instructions": "What, if anything, went wrong in this voice-agent turn?",
            "criteria": {
                "ok": "Turn went fine",
                "slow": "Agent was too slow / dead air before replying",
                "misheard": "Speech-to-text misheard the caller or caller had to repeat",
                "tool_issue": "Tool/search result was wrong, stale or failed",
                "talked_over": "Agent and caller interrupted each other",
                "off_track": "Agent answered something the caller did not ask",
            },
        }
        for i in range(len(turns))
    }
    qs["lang"] = {
        "type": "choice",
        "instructions": "What language (or mix) is the CALLER speaking across this call?",
        "criteria": {"english": "English only", "hinglish": "Hindi/English mix", "tamil": "Tamil or Tamil/English mix",
                     "spanish": "Spanish or Spanish/English mix", "other": "Another language or mix"},
    }
    qs["lang_issue"] = {
        "type": "noul",
        "instructions": "The caller's words were garbled by speech-to-text because of accent or language mixing.",
    }
    r = httpx.post(
        "https://api.typesafe.ai/v1/systemone",
        headers={"Authorization": f"Bearer {JEV}"},
        json={"model": "jev-latest", "state": "\n".join(f"[t{i}] {t}" for i, t in enumerate(turns)), "questions": qs},
        timeout=20,
    )
    r.raise_for_status()
    a = r.json()["answers"]
    jev_classify.meta = {"lang": a.get("lang", {}), "lang_issue": a.get("lang_issue", {})}
    return [a.get(f"t{i}", {}) for i in range(len(turns))]


FIX = {
    "slow": "Lower endpointing wait (Vapi default ~1.5s), use a faster model, add a tool request-start filler.",
    "misheard": "Add Deepgram keyterms / custom vocab; enable noise suppression; confirm critical slots back to caller.",
    "tool_issue": "Add recency filter + freshness check on tool results; return a fallback when empty.",
    "talked_over": "Tune interruption threshold (numWordsToInterruptAssistant) and backchannel settings.",
    "off_track": "Tighten system prompt; restate the caller's ask before calling tools.",
}


def diagnose(call_id: str | None = None) -> dict:
    c = latest_call(call_id)
    msgs = [m for m in (c.get("artifact", {}).get("messages") or c.get("messages") or []) if m.get("role") in ("user", "bot", "assistant")]
    turns, gaps = [], []
    prev_user_end = None
    for m in msgs:
        role = "caller" if m["role"] == "user" else "agent"
        start, end = m.get("secondsFromStart", 0), m.get("secondsFromStart", 0) + (m.get("duration", 0) or 0) / 1000
        gap = round(start - prev_user_end, 2) if role == "agent" and prev_user_end is not None else None
        turns.append({"role": role, "text": m.get("message", ""), "gap": gap})
        if role == "caller":
            prev_user_end = end
    labels = jev_classify([f"{t['role']}: {t['text']} (reply gap {t['gap']}s)" for t in turns])
    for t, l in zip(turns, labels):
        t["issue"], t["conf"] = l.get("choice", "ok"), l.get("confidence")
        if t["conf"] is not None and t["conf"] < 0.35:  # Jev unsure -> trust measurements
            t["issue"], t["conf"] = "ok", None
        if t["gap"] is not None and t["gap"] > 1.5:
            t["issue"] = "slow"
        if t["role"] == "agent" and any(w in t["text"].lower() for w in ("where are you", "full location", "share your city", "another area")):
            t["issue"] = "misheard"  # agent had to re-ask: caller wasn't understood
    perf = (c.get("artifact") or {}).get("performanceMetrics") or {}
    return {"id": c.get("id"), "turns": turns, "perf": perf, "meta": getattr(jev_classify, "meta", {})}


def report_html(d: dict) -> str:
    rows = ""
    for t in d["turns"]:
        bad = t["issue"] not in ("ok", "?")
        gap = f"{t['gap']}s" if t["gap"] is not None else ""
        rows += (f"<tr class={'bad' if bad else ''}><td>{t['role']}</td><td>{html.escape(t['text'])}</td>"
                 f"<td>{gap}</td><td><b>{t['issue']}</b> {'' if t['conf'] is None else f'({t[chr(99)+chr(111)+chr(110)+chr(102)]:.0%})'}</td>"
                 f"<td>{FIX.get(t['issue'], '')}</td></tr>")
    p = d["perf"]
    bad = [t for t in d["turns"] if t["issue"] not in ("ok", "?")]
    worst = max((t["gap"] or 0 for t in d["turns"]), default=0)
    summary = (f"<div style='font-size:20px;margin:12px 0'>{len(bad)} of {len(d['turns'])} turns had problems · "
               f"worst reply gap <b>{worst}s</b> · avg turn latency <b>{round(p.get('turnLatencyAverage', 0))} ms</b> · "
               f"transcriber <b>{round(p.get('transcriberLatencyAverage', 0))} ms</b> (biggest stage)</div>")
    stages = "".join(f"<li>{k}: {round(v)} ms</li>" for k, v in p.items() if isinstance(v, (int, float)) and "Average" in k)
    m = d.get("meta", {})
    lang, li = m.get("lang", {}), m.get("lang_issue", {})
    li_v = li.get("noul")
    lang_html = (f"<h3>Language (Jev)</h3><p>Caller language: <b>{lang.get('choice', '?')}</b>"
                 f"{'' if lang.get('confidence') is None else f' ({lang[chr(99)+chr(111)+chr(110)+chr(102)+chr(105)+chr(100)+chr(101)+chr(110)+chr(99)+chr(101)]:.0%})'}"
                 f" · accent/code-switch garbling: <b>{'n/a' if li_v is None else f'{li_v:.0%}'}</b></p>"
                 + ("<p>Fix: set Deepgram nova-3 <code>language: multi</code> and add local keyterms (e.g. Embarcadero).</p>"
                    if (li_v or 0) > 0.4 or lang.get('choice') not in (None, 'english') else ""))
    return f"""<!doctype html><meta charset=utf-8><title>CallLens</title>
<style>body{{font-family:system-ui;margin:24px;background:#0f1115;color:#e8e8e8}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #333;padding:8px;vertical-align:top}}tr.bad td{{background:#3a1d1d}}h1{{color:#5ce1a6}}</style>
<h1>🔍 CallLens</h1><p>Call {d['id']} · judged by Jev (TypeSafe) · Vapi + Deepgram + Exa</p>
{summary}<h3>Latency by stage</h3><ul>{stages or '<li>per-stage metrics not available for this call</li>'}</ul>
{lang_html}<h3>Turn-by-turn diagnosis</h3><table><tr><th>who</th><th>said</th><th>reply gap</th><th>issue (Jev)</th><th>fix</th></tr>{rows}</table>"""
