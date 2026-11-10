import glob, os, sys, requests, soundfile as sf
from f5_tts.api import F5TTS
V = '/content/drive/MyDrive/karthik_voice'
print(os.listdir(V))
ck = sorted(glob.glob(V + '/**/*.safetensors', recursive=True) + glob.glob(V + '/**/*.pt', recursive=True))[0]
vocab = glob.glob(V + '/**/*vocab*.txt', recursive=True)[0]
up = sys.argv[1]
r = requests.get(up + '/ref.wav', timeout=60)
if r.ok and len(r.content) > 10000:
    open('/content/ref_me.wav', 'wb').write(r.content)
refs = glob.glob('/content/ref_me.wav') + glob.glob(V + '/**/ref*.wav', recursive=True)
if not refs:
    sys.exit('NO REF WAV: upload a 10s clip of your voice to karthik_voice/ref.wav')
ref = refs[0]
print('ckpt', ck, 'vocab', vocab, 'ref', ref)
REF = "Hi, I'm Karthik. Tonight I built Call Lens, a tool that shows exactly why voice agent calls fail, and fixes them live. "
tts = F5TTS(model="F5TTS_v1_Base", ckpt_file=ck, vocab_file=vocab)
lines = [
 "Voice agents fail silently. This is Call Lens, a live dashboard of every call to my Side Quest Hotline, built on Vah-pee, Deepgram, Ex-uh, and Type Safe Jev.",
 "The transcriber is the bottleneck at fifteen hundred milliseconds, while the L L M is only three hundred thirty four. Jev rated this call poor, ten of twenty two turns failed.",
 "Click any call to verify it turn by turn. Every turn is judged by Jev.",
 "I said Embarcadero. Deepgram heard Aero, Arrow, and Amir. The agent asked my location three times, and every problem comes with a fix.",
 "With Jev, a typed choice over all search results picked a better fit in three out of three searches, in about a hundred and twenty milliseconds.",
 "Self heal patches the live Vah-pee assistant: a Deepgram keyterm for Embarcadero and a shorter endpointing wait. Vah-pee tells you what happened. Call Lens tells you why, and fixes it.",
]
RS = sf.info(ref).duration
for i, s in enumerate(lines, 1):
    d = RS + len(s.split()) * 0.46 + s.count(',') * 0.25 + 0.2
    w, sr, _ = tts.infer(ref, REF, s, nfe_step=32, cfg_strength=2.0, sway_sampling_coef=-1.0, seed=7, remove_silence=False, fix_duration=d)
    p = f'/content/calllens_{i}.wav'; sf.write(p, w, sr)
    print(i, requests.post(f'{up}/voice/{i}', data=open(p, 'rb').read(), timeout=60).status_code)
print('ALL DONE')
