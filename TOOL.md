Vapi tool (Assistant > Tools > Create > Function):
  name: search_quests
  description: Find a real side quest happening now near the caller.
  parameters: {"type":"object","properties":{"mood":{"type":"string"},"area":{"type":"string"},"minutes":{"type":"integer"}},"required":["mood","area"]}
  server url: https://<ngrok>.ngrok-free.app/vapi

System prompt:
  You are the Side Quest Hotline: playful, fast, under 20 words per turn.
  Ask the caller's mood, how much time they have, and where they are.
  Then call search_quests. Read back ONE quest and offer another if they want.

Transcriber: Deepgram nova-3. Voice: Deepgram Aura (or Cartesia).

Run:
  pip install fastapi uvicorn httpx
  export EXA_API_KEY=... JEV_URL=... JEV_API_KEY=...
  uvicorn app:app --port 8000 &
  ngrok http 8000
