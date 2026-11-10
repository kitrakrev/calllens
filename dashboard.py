"""CallLens dashboard: every Vapi call, Jev verdict per call, latency/failure/language panels."""
import html

import httpx

import calllens

CACHE: dict[str, dict] = {}  # call_id -> summary (Jev is only asked once per ended call)


def jev_verdict(transcript: str) -> dict:
    if not calllens.JEV or not transcript:
        return {}
    r = httpx.post(
        "https://api.typesafe.ai/v1/systemone",
        headers={"Authorization": f"Bearer {calllens.JEV}"},
        json={
            "model": "jev-latest",
            "state": transcript,
            "questions": {
                "goal_met": {"type": "noul", "instructions": "The caller got what they called for by the end of the call."},
                "quality": {
                    "type": "choice",
                    "instructions": "Overall, how good was this voice-agent conversation for the caller?",
                    "criteria": {"great": "Fast, understood first time, solved", "ok": "Solved with some friction",
                                 "poor": "Lots of repeats, delays or confusion", "failed": "Caller gave up or goal not met"},
                },
            },
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["answers"]


def summarize(call: dict) -> dict:
    cid = call["id"]
    if cid in CACHE:
        return CACHE[cid]
    d = calllens.diagnose(cid)
    text = "\n".join(f"{t['role']}: {t['text']}" for t in d["turns"])
    try:
        v = jev_verdict(text)
    except Exception as e:
        print("verdict failed:", e)
        v = {}
    p = d["perf"]
    s = {
        "id": cid,
        "when": (call.get("startedAt") or call.get("createdAt") or "")[:16].replace("T", " "),
        "ended": call.get("endedReason", ""),
        "turns": len(d["turns"]),
        "fails": sum(t["issue"] not in ("ok", "?") for t in d["turns"]),
        "issues": sorted({t["issue"] for t in d["turns"] if t["issue"] not in ("ok", "?")}),
        "worst_gap": max((t["gap"] or 0 for t in d["turns"]), default=0),
        "turn_ms": round(p.get("turnLatencyAverage", 0)),
        "stt_ms": round(p.get("transcriberLatencyAverage", 0)),
        "llm_ms": round(p.get("modelLatencyAverage", 0)),
        "tts_ms": round(p.get("voiceLatencyAverage", 0)),
        "endp_ms": round(p.get("endpointingLatencyAverage", 0)),
        "lang": (d.get("meta", {}).get("lang") or {}).get("choice", "?"),
        "quality": (v.get("quality") or {}).get("choice", "?"),
        "goal": (v.get("goal_met") or {}).get("noul"),
    }
    if call.get("status") == "ended":
        CACHE[cid] = s
    return s


def bar(label: str, val: float, mx: float, color: str) -> str:
    w = 0 if not mx else int(260 * val / mx)
    return (f"<div class=b><span>{label}</span><svg width=270 height=14><rect width={w} height=14 rx=3 fill={color} /></svg>"
            f"<b>{val:g}</b></div>")


def page() -> str:
    calls = httpx.get("https://api.vapi.ai/call?limit=30", headers=calllens.H, timeout=15).json()
    rows = [summarize(c) for c in calls if c.get("status") == "ended"]
    n = len(rows) or 1
    avg = lambda k: round(sum(r[k] for r in rows) / n)  # noqa: E731
    stage = "".join(bar(k, avg(f), max(avg(x) for x in ("stt_ms", "llm_ms", "tts_ms", "endp_ms")) or 1, c)
                    for k, f, c in (("Transcriber (Deepgram)", "stt_ms", "#f2a65a"), ("Endpointing", "endp_ms", "#8ab4f8"),
                                    ("LLM", "llm_ms", "#5ce1a6"), ("Voice (Deepgram)", "tts_ms", "#c792ea")))
    counts: dict[str, int] = {}
    for r in rows:
        for i in r["issues"]:
            counts[i] = counts.get(i, 0) + 1
    fails = "".join(bar(k, v, max(counts.values()), "#ff6b6b") for k, v in sorted(counts.items(), key=lambda x: -x[1])) or "<p>none</p>"
    langs: dict[str, int] = {}
    quals: dict[str, int] = {}
    for r in rows:
        langs[r["lang"]] = langs.get(r["lang"], 0) + 1
        quals[r["quality"]] = quals.get(r["quality"], 0) + 1
    lang_b = "".join(bar(k, v, max(langs.values()), "#8ab4f8") for k, v in langs.items()) or "<p>-</p>"
    qual_b = "".join(bar(k, v, max(quals.values()), {"great": "#5ce1a6", "ok": "#f2d45a", "poor": "#f2a65a", "failed": "#ff6b6b"}.get(k, "#888"))
                     for k, v in quals.items()) or "<p>-</p>"
    trs = "".join(
        f"<tr><td><a href='/lens?call_id={r['id']}'>{r['when']}</a></td><td class=q-{r['quality']}>{r['quality']}</td>"
        f"<td>{'-' if r['goal'] is None else f'{r[chr(103)+chr(111)+chr(97)+chr(108)]:.0%}'}</td><td>{r['lang']}</td>"
        f"<td>{r['turn_ms']} ms</td><td>{r['stt_ms']} ms</td><td>{r['worst_gap']}s</td>"
        f"<td>{r['fails']}/{r['turns']}</td><td>{html.escape(', '.join(r['issues']))}</td><td>{r['ended']}</td></tr>"
        for r in rows)
    stat = lambda t, v: f"<div class=s><div>{t}</div><b>{v}</b></div>"  # noqa: E731
    goal_rate = [r["goal"] for r in rows if r["goal"] is not None]
    return f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=20><title>CallLens Dashboard</title>
<style>body{{font-family:system-ui;margin:20px;background:#0b0d12;color:#e6e6e6}}h1{{color:#5ce1a6;margin:0 0 4px}}
.g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;margin:14px 0}}
.p{{background:#151922;border:1px solid #262b36;border-radius:8px;padding:12px}}.p h3{{margin:0 0 10px;font-size:14px;color:#9aa4b2}}
.s{{display:inline-block;background:#151922;border:1px solid #262b36;border-radius:8px;padding:10px 16px;margin-right:10px}}
.s div{{font-size:12px;color:#9aa4b2}}.s b{{font-size:24px}}.b{{display:flex;align-items:center;gap:8px;font-size:13px;margin:4px 0}}
.b span{{width:170px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border-bottom:1px solid #262b36;padding:6px;text-align:left}}
a{{color:#8ab4f8}}.q-great{{color:#5ce1a6}}.q-ok{{color:#f2d45a}}.q-poor{{color:#f2a65a}}.q-failed{{color:#ff6b6b}}</style>
<h1>🔍 CallLens Dashboard</h1><div style=color:#9aa4b2>Side Quest Hotline · every call judged by Jev (TypeSafe) · Vapi + Deepgram + Exa · auto-refresh 20s</div>
<div style=margin-top:14px>{stat('Calls', len(rows))}{stat('Avg turn latency', f"{avg('turn_ms')} ms")}{stat('Avg transcriber', f"{avg('stt_ms')} ms")}
{stat('Goal met (Jev)', f"{sum(goal_rate)/len(goal_rate):.0%}" if goal_rate else '-')}{stat('Failed turns', f"{sum(r['fails'] for r in rows)}/{sum(r['turns'] for r in rows)}")}</div>
<div class=g><div class=p><h3>Avg latency by stage (ms)</h3>{stage}</div><div class=p><h3>Failure types (calls affected)</h3>{fails}</div>
<div class=p><h3>Conversation quality (Jev)</h3>{qual_b}</div><div class=p><h3>Caller language (Jev)</h3>{lang_b}</div></div>
<div class=p><h3>All calls - click to verify turn by turn</h3><table><tr><th>time (UTC)</th><th>Jev verdict</th><th>goal met</th><th>language</th>
<th>turn latency</th><th>transcriber</th><th>worst gap</th><th>failed turns</th><th>issues</th><th>ended</th></tr>{trs}</table></div>"""
