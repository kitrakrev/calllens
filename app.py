"""Side Quest Hotline backend: Vapi tool server.

Vapi calls POST /vapi with a tool-call payload -> Exa live search -> Jev (TypeSafe)
picks the best quest as structured JSON -> spoken answer returned to Vapi.
"""
import html
import json
import os
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

import calllens
import dashboard
import heal

EXA_KEY = os.environ.get("EXA_API_KEY", "")
JEV_URL = os.environ.get("JEV_URL", "")  # get endpoint from TypeSafe team
JEV_KEY = os.environ.get("JEV_API_KEY", "")

app = FastAPI()
LOG = []  # latency log shown on /stats for the demo
AB = []  # with vs without Jev, per tool call


def exa_search(query: str, area: str) -> list[dict]:
    r = httpx.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": EXA_KEY},
        json={
            "query": f"{query} happening tonight in {area}",
            "numResults": 5,
            "type": "fast",
            "contents": {"highlights": {"numSentences": 1}},
        },
        timeout=10,
    )
    r.raise_for_status()
    return [
        {"title": x.get("title"), "url": x.get("url"), "summary": " ".join(x.get("highlights") or [])[:200]}
        for x in r.json().get("results", [])
    ]


def jev_pick(mood: str, minutes: int, options: list[dict]) -> dict:
    """Jev (TypeSafe System One) Choice over Exa results; falls back to the first option."""
    if not options:
        return {"name": "Walk the Embarcadero waterfront", "why": "always open, always good", "url": "", "confidence": 0}
    if JEV_KEY:
        try:
            criteria = {f"q{i}": f"{o['title']}: {o['summary'][:200]}" for i, o in enumerate(options)}
            r = httpx.post(
                "https://api.typesafe.ai/v1/systemone",
                headers={"Authorization": f"Bearer {JEV_KEY}"},
                json={
                    "model": "jev-latest",
                    "state": f"Caller mood: {mood}. Time available: {minutes} minutes. Wants something happening now.",
                    "questions": {"pick": {
                        "type": "choice",
                        "instructions": "Which option is the best side quest for this caller right now?",
                        "criteria": criteria,
                    }},
                },
                timeout=10,
            )
            r.raise_for_status()
            ans = r.json()["answers"]["pick"]
            o = options[int(ans["choice"][1:])]
            return {"name": o["title"], "why": "Jev's top pick for your vibe", "url": o["url"],
                    "confidence": ans.get("confidence"), "probs": ans.get("probabilities")}
        except Exception as e:  # keep the demo alive
            print("jev failed:", e)
    o = options[0]
    return {"name": o["title"], "why": "closest fun thing happening right now", "url": o["url"], "confidence": 0}


@app.post("/vapi")
async def vapi(req: Request):
    body = await req.json()
    calls = body.get("message", {}).get("toolCallList", [])
    results = []
    for c in calls:
        t0 = time.time()
        args = c.get("function", {}).get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        mood = args.get("mood", "fun")
        area = args.get("area", "San Francisco")
        minutes = int(args.get("minutes", 120))
        opts = exa_search(f"{mood} things to do", area)
        tj = time.time()
        pick = jev_pick(mood, minutes, opts)
        AB.append({"mood": mood, "area": area, "jev_ms": int((time.time() - tj) * 1000),
                   "without_jev": opts[0]["title"] if opts else "-", "with_jev": pick["name"],
                   "probs": {opts[int(k[1:])]["title"][:60]: v for k, v in (pick.get("probs") or {}).items() if k[1:].isdigit() and int(k[1:]) < len(opts)},
                   "confidence": pick.get("confidence"), "changed": bool(opts) and pick["name"] != opts[0]["title"]})
        ms = int((time.time() - t0) * 1000)
        LOG.append({"mood": mood, "area": area, "pick": pick, "ms": ms})
        results.append({
            "toolCallId": c.get("id"),
            "result": f"Your side quest: {pick['name']}. {pick['why']}. Link: {pick['url']}",
        })
    return {"results": results}


@app.get("/stats")
def stats():
    return {"calls": LOG[-10:]}


@app.get("/lens", response_class=HTMLResponse)
def lens_page(call_id: str | None = None):
    return calllens.report_html(calllens.diagnose(call_id))


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    return dashboard.page()


def pct(x):
    return "" if x is None else f"{x:.0%}"


@app.get("/ab", response_class=HTMLResponse)
def ab_page():
    rows = "".join(
        f"<tr><td>{html.escape(a['mood'])} @ {html.escape(a['area'])}</td><td>{html.escape(a['without_jev'])}</td>"
        f"<td class={'chg' if a['changed'] else ''}>{html.escape(a['with_jev'])}</td><td>{pct(a['confidence'])}</td>"
        f"<td>{a['jev_ms']} ms</td><td>{'<br>'.join(f'{html.escape(k)}: {v:.0%}' for k, v in sorted(a['probs'].items(), key=lambda x: -x[1])[:3])}</td></tr>"
        for a in reversed(AB))
    changed = sum(a["changed"] for a in AB)
    avg = round(sum(a["jev_ms"] for a in AB) / len(AB)) if AB else 0
    return f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=15><title>With vs without Jev</title>
<style>body{{font-family:system-ui;margin:20px;background:#0b0d12;color:#e6e6e6}}h1{{color:#5ce1a6}}table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #262b36;padding:6px;text-align:left;vertical-align:top}}.chg{{color:#5ce1a6;font-weight:600}}</style>
<h1>With vs without Jev</h1><p>Without Jev the agent reads Exa's #1 result. With Jev, a typed Choice over all results picks the best fit for the caller's mood and time.
Jev changed the pick in <b>{changed}/{len(AB)}</b> searches · avg Jev decision time <b>{avg} ms</b>. Jev's reasoning = its probability over every option.</p>
<table><tr><th>caller asked</th><th>without Jev (Exa #1)</th><th>with Jev</th><th>confidence</th><th>Jev time</th><th>Jev probabilities (top 3)</th></tr>{rows}</table>"""


@app.get("/heal", response_class=HTMLResponse)
def heal_page(call_id: str | None = None, go: int = 0):
    p = heal.apply(call_id) if go else heal.plan(call_id)
    items = "".join(f"<li>{html.escape(f)}</li>" for f in p["fixes"]) or "<li>No fixes needed</li>"
    state = (f"<p style=color:#5ce1a6>Applied to live assistant (HTTP {p.get('status')}). Call again to verify.</p>" if go and not p.get("error")
             else f"<p style=color:#ff6b6b>{html.escape(str(p.get('error')))}</p>" if go else
             f"<a href='/heal?go=1{'&call_id=' + call_id if call_id else ''}' style='background:#5ce1a6;color:#000;padding:10px 16px;border-radius:6px;text-decoration:none'>Apply fixes to live agent</a>")
    return f"""<!doctype html><meta charset=utf-8><title>Self-heal</title><style>body{{font-family:system-ui;margin:24px;background:#0b0d12;color:#e6e6e6}}h1{{color:#5ce1a6}}</style>
<h1>Self-heal</h1><p>Call {p['call']}: CallLens findings turned into a live patch on the Vapi assistant.</p><ul>{items}</ul>{state}
<pre style=color:#9aa4b2>{html.escape(str(p['patch']))}</pre>"""


@app.get("/gen.py")
def gen_script():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(open("voice/gen.py").read())


@app.post("/voice/{i}")
async def voice_upload(i: int, req: Request):
    if not 1 <= i <= 6:
        return {"ok": False}
    open(f"voice/calllens_{i}.wav", "wb").write(await req.body())
    return {"ok": True}


@app.get("/ref.wav")
def ref_wav():
    from fastapi.responses import FileResponse
    return FileResponse("voice/ref.wav", media_type="audio/wav")


# POLISH: shared nav + theme injected into every HTML page for the demo
POLISH = """<link rel=preconnect href=https://fonts.googleapis.com><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Space+Grotesk:wght@600;700&display=swap" rel=stylesheet>
<style>
:root{--bg:#0b0d12;--panel:#141922;--line:#252b37;--txt:#e6e8ec;--mut:#8f9aab;--grn:#5ce1a6;--org:#f2a65a;--red:#ff6b6b;--blu:#8ab4f8}
body{font-family:Inter,system-ui,sans-serif!important;background:var(--bg)!important;color:var(--txt)!important;margin:0!important;padding:0 28px 40px!important;font-size:15px}
h1{font-family:'Space Grotesk',Inter,sans-serif!important;font-size:30px!important;color:var(--grn)!important;margin:18px 0 6px!important}
h3{font-family:'Space Grotesk',Inter,sans-serif;color:#c9d1dd;letter-spacing:.2px}
nav.cl{position:sticky;top:0;z-index:9;display:flex;align-items:center;gap:6px;margin:0 -28px 8px;padding:12px 28px;background:rgba(11,13,18,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
nav.cl b{font-family:'Space Grotesk';font-size:18px;color:var(--grn);margin-right:18px}
nav.cl a{color:var(--mut);text-decoration:none;padding:7px 14px;border-radius:999px;font-weight:600;font-size:14px}
nav.cl a:hover{background:var(--panel);color:var(--txt)}nav.cl a.on{background:var(--grn);color:#08110c}
nav.cl span{margin-left:auto;color:var(--mut);font-size:13px}nav.cl span i{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--grn);margin-right:6px;box-shadow:0 0 8px var(--grn)}
table{border-collapse:separate!important;border-spacing:0!important;width:100%;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th{background:#1a2030;color:var(--mut)!important;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.6px}
td,th{border-bottom:1px solid var(--line)!important;padding:10px 12px!important}
tr.bad td{background:rgba(255,107,107,.08)!important}tr.bad td:nth-child(4) b{background:var(--red);color:#1a0505;padding:2px 10px;border-radius:999px;font-size:12px;text-transform:uppercase}
tr:not(.bad) td:nth-child(4) b{background:rgba(92,225,166,.15);color:var(--grn);padding:2px 10px;border-radius:999px;font-size:12px;text-transform:uppercase}
ul{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 32px!important}
a{color:var(--blu)}pre{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.p,.s{border-radius:12px!important}
</style>"""


def _nav(path: str) -> str:
    items = [("/dashboard", "Dashboard"), ("/lens", "Call report"), ("/ab", "Jev A/B"), ("/heal", "Self-heal")]
    links = "".join(f"<a class='{'on' if path.startswith(u) else ''}' href='{u}'>{t}</a>" for u, t in items)
    return f"<nav class=cl><b>🔍 CallLens</b>{links}<span><i></i>Side Quest Hotline · +1 (541) 777-8465</span></nav>"


@app.middleware("http")
async def polish(request: Request, call_next):
    resp = await call_next(request)
    if not resp.headers.get("content-type", "").startswith("text/html"):
        return resp
    body = b"".join([c async for c in resp.body_iterator]).decode()
    path = request.url.path if request.url.path != "/" else "/dashboard"
    i = body.find("</style>")
    i = i + len("</style>") if i >= 0 else 0
    body = body[:i] + POLISH + _nav(path) + body[i:]
    return HTMLResponse(body, status_code=resp.status_code)
