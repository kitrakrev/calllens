# CallLens + Side Quest Hotline

**Project page + 50s demo:** https://kitrakrev.github.io/calllens/

Built at the Vapi "Side Quest Hotline" hackathon (Nov 9, 2026).

- **Side Quest Hotline**: Vapi voice agent (Deepgram Nova-3 + Aura). Tool server searches live with Exa; TypeSafe Jev picks the best result (typed Choice + probabilities).
- **CallLens**: per-call, per-turn diagnosis of Vapi calls: latency by stage, dead air, mishearing, Jev verdict (quality, goal met, language).
- **Self-heal**: turns findings into a live `PATCH /assistant` (Deepgram keyterms, endpointing wait, multilingual).

Routes: `/vapi` (tool), `/dashboard`, `/lens?call_id=`, `/ab` (with vs without Jev), `/heal`.

Run: `pip install fastapi uvicorn httpx`, set `EXA_API_KEY`, `JEV_API_KEY`, `VAPI_API_KEY`, `VAPI_ASSISTANT_ID` in `.env`, then `uvicorn app:app --port 8000`.

## Self-heal result (repeat call, same script)

| | Before | After |
|---|---|---|
| "Embarcadero" heard as | Aero / Arrow / Amir | Embarcadero, first try |
| Location re-asks | 3 | 1 |
| Turns | 22 | 17 |
| Avg turn latency | 2731 ms | 2947 ms (not fixed; transcriber-bound) |
