import json, time, urllib.request

# Sharper prompt: fix is FIRST and gets explicit examples; notes trimmed.
SYS = """You correct English for an Indian software engineer writing work messages.

Return JSON with keys in this order: fix, polished, short, notes.

fix    = minimal grammar/spelling/tense/article correction. Change ONLY what is wrong.
         Always expand shorthand: pls->please, thx->thanks, u->you, asap->as soon as possible.
         Never use present perfect with a past time word: "I have sent it yesterday" is WRONG,
         write "I sent it yesterday".
polished = natural fluent English, concise.
short  = shortest polite version.
notes  = up to 2 short grammar rules he broke. [] if input was already correct.

BANNED words/phrases anywhere in output: kindly, do the needful, revert back, leverage,
circle back, hope this email finds you well, please be informed.
Never add greetings or sign-offs he did not write."""

SCHEMA = {"type": "object",
  "properties": {"fix": {"type": "string"}, "polished": {"type": "string"},
                 "short": {"type": "string"}, "notes": {"type": "array", "items": {"type": "string"}}},
  "required": ["fix", "polished", "short", "notes"]}

TEXT = "i has send the mail yesterday, pls check it and let me know if any changes require from my side"

body = {"model": "qwen3:8b", "system": SYS, "prompt": TEXT, "stream": True,
        "think": False, "keep_alive": "30m", "format": SCHEMA,
        "options": {"temperature": 0.2, "num_predict": 400}}
req = urllib.request.Request("http://localhost:11434/api/generate",
    data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})

t0 = time.time()
buf = ""
marks = {}
for line in urllib.request.urlopen(req, timeout=280):
    chunk = json.loads(line)
    buf += chunk.get("response", "")
    # when does each field become fully readable?
    for field, nxt in [("fix", '"polished"'), ("polished", '"short"'), ("short", '"notes"')]:
        if field not in marks and nxt in buf:
            marks[field] = time.time() - t0
    if chunk.get("done"):
        marks["total"] = time.time() - t0

print("TIME-TO-USABLE per field:")
for k in ("fix", "polished", "short", "total"):
    if k in marks:
        print(f"  {k:9} {marks[k]:5.2f}s")
print()
r = json.loads(buf)
for k in ("fix", "polished", "short"):
    print(f"{k:9}: {r[k]}")
print(f"{'notes':9}: {r['notes']}")
