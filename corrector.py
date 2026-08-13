#!/usr/bin/env python3
"""saaf - correct English in work messages, locally.

    saaf "i has send the mail yesterday"     three suggestions, human readable
    saaf --fast "..."                        one suggestion, what the hotkey uses
    saaf --formal "..."                      for a client or someone senior
    saaf --brief "..."                       for Slack or WhatsApp, fewest words
    saaf --json "..."                        machine readable, for the hotkey
    saaf stats                               your most frequent mistakes

Runs entirely on this Mac via Ollama. Nothing is sent anywhere.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blocklist  # noqa: E402

MODEL = os.environ.get("SAAF_MODEL", "qwen3:4b")
OLLAMA = "http://localhost:11434"
LOG = Path.home() / ".saaf" / "mistakes.log"

# Two timeouts, because there are two very different waits. A resident model
# answers in ~1.6s; loading one off disk is 15-50s. A single 25s limit was right
# for the first case and cancelled the second just before it would have
# succeeded, which read as a broken tool rather than a slow one.
TIMEOUT_WARM = 25
TIMEOUT_COLD = 90

SYSTEM = """You correct English for an Indian senior software engineer writing work messages (email, Slack, WhatsApp).

Return JSON with keys in this order: fix, natural, short, notes.

fix     = minimal correction. Change ONLY what is grammatically wrong: verb form,
          tense, articles, plurals, spelling, punctuation. Keep his wording
          everywhere it was already correct. Expand shorthand: pls->please,
          thx->thanks, u->you, asap->as soon as possible.
natural = the same message as a real person would type it at work. Correct but NOT
          polished. It must not read like AI wrote it: no "Additionally",
          "Furthermore", "Moreover"; no em dashes; no "Not only X but also Y";
          no "serves as"/"represents" instead of "is"; no zombie nouns
          ("provide clarification" -> "clarify", "make a decision" -> "decide");
          no servile openers ("Certainly", "I'd be happy to"); no cheerful ending
          he did not write ("Looking forward to hearing from you"). Vary sentence
          length. Contractions are good: I'll, don't, can't. Say it and stop.
short   = the same message as briefly as possible while staying polite.
notes   = up to 2 short notes naming the grammar rules he broke. [] if the input
          was already correct.

Grammar rules he breaks often - apply them:
- Present perfect cannot pair with a past time word. "I have sent it yesterday" is
  WRONG; write "I sent it yesterday".
- "did" takes the base verb: "didn't got" -> "didn't get".
- "having" is not used for possession: "I am having 4 years experience" ->
  "I have 4 years of experience".
- "one of" needs a plural noun: "one of my colleague" -> "one of my colleagues".
- Duration takes "for", not "since": "since 4 years" -> "for 4 years".
- "discuss" takes no preposition: "discussed about X" -> "discussed X".
- "myself Aadil" is not an English introduction; write "I am Aadil".
- Do not drop articles: "come to office" -> "come to the office".

NEVER add greetings, sign-offs, or facts he did not write, and NEVER delete ones he
did write - if he wrote "hi sir" or "thanks", they stay. Never add certainty he did
not express. Never invent a name, date, or number.
Preserve his line breaks and blank lines exactly. Four short paragraphs in means
four short paragraphs out."""

SCHEMA = {
    "type": "object",
    "properties": {
        "fix": {"type": "string"},
        "natural": {"type": "string"},
        "short": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["fix", "natural", "short", "notes"],
}

FIELDS = ("fix", "natural", "short")

# Instant mode: one variant instead of three. Fewer output tokens means a shorter
# generation, so this is genuinely faster rather than just skipping the popup.
FAST_SCHEMA = {
    "type": "object",
    "properties": {
        "natural": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["natural", "notes"],
}

FAST_EXTRA = ("\n\nIMPORTANT: return ONLY the keys natural and notes. "
              "Do not return fix or short.")

# A lean prompt for instant mode. The full SYSTEM prompt is roughly 600 tokens, and
# every one of them is re-processed on each request; the variant descriptions and
# examples are dead weight when only one variant is wanted. Grammar rules that
# blocklist.py already enforces are omitted here too - they are handled after the
# model returns, so spending prompt tokens on them twice buys nothing.
FAST_SYSTEM = """Correct the English in this work message from an Indian software engineer.

Write it as a real person would type it at work. Correct, plain, and brief.
Keep his meaning. Never add greetings, sign-offs, facts, or certainty he did not write.
Never delete or reword a greeting or sign-off he DID write; copy it through unchanged.
Keep his line breaks and blank lines exactly where they are. A message written as
four short paragraphs must come back as four short paragraphs, not one.
Do not sound like AI: no "Additionally", "Furthermore", "Moreover", no em dashes,
no "provide clarification" (say "clarify"), no "Looking forward to hearing from you".
Contractions are fine.

Return JSON: natural (the corrected message), notes (up to 2 short names of the
grammar rules he broke, [] if none)."""

# Who the message is going to. This is the dimension the three variants never
# covered: fix/natural/short are three flavours of ONE register, but "the same
# message, for a client" is a different question entirely.
#
# Kept to three because each one has to be worth a prompt line and a test case.
# An audience that cannot be described in a sentence is not a real audience, it
# is a preference, and preferences belong in how you write the message.
TONES = {
    # The register everything was tuned for: a peer on your own team.
    "default": "",

    "formal": (
        "\n\nThis message is going to a client or someone senior outside his team. "
        "Use complete sentences and no contractions - write \"I will\", not \"I'll\". "
        "Keep it precise and respectful. Do NOT add greetings, sign-offs, apologies, "
        "or flattery he did not write, and do not make it longer than it needs to be."),

    # Deliberately empty: brief is served by the three-variant prompt's `short`
    # field, not by a fragment of its own. Three attempts at a fragment all
    # failed on a 52-word message - "fewest words" gave 39, and an explicit
    # "AT MOST 25 words, count them" gave 50, 28, 50. The `short` field of the
    # full prompt gave 18, 17, 16 on the same input, and has been passing the
    # suite since the beginning. Reusing a proven prompt beats tuning a new one.
    # See correct(), which routes this tone accordingly.
    "brief": "",
}

# Tones that need the full three-variant prompt rather than the lean one, because
# the answer they want is a field that prompt already produces well.
TONES_VIA_VARIANTS = {"brief": "short"}


class SaafError(Exception):
    """Anything the user needs to be told about, in words they can act on."""


def _ollama_state():
    """Returns (reachable, model_is_resident).

    One request answers both questions: /api/ps lists the models currently held
    in memory, so a successful call proves Ollama is up and an empty list proves
    this model still has to be read off disk. That second fact is what picks the
    timeout below.
    """
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=3) as r:
            models = json.load(r).get("models") or []
    except Exception:
        return False, False
    return True, any(
        m.get("name") == MODEL or m.get("model") == MODEL for m in models)


def _request(text, extra="", fast=False, timeout=TIMEOUT_WARM, tone="default"):
    body = {
        "model": MODEL,
        # The tone fragment goes before `extra`, so a blocklist retry instruction
        # stays the last thing the model reads.
        "system": (FAST_SYSTEM if fast else SYSTEM) + TONES.get(tone, "") + extra,
        "prompt": text,
        "stream": False,
        "think": False,
        "keep_alive": "8h",
        "format": FAST_SCHEMA if fast else SCHEMA,
        "options": {
            "temperature": 0.2,
            "num_predict": 200 if fast else 500,
            # Without this Ollama honours the model's advertised maximum context.
            # qwen3:4b advertises 262144, which reserves 42GB, does not fit in 16GB,
            # and silently spills inference onto the CPU: slow and battery-hungry.
            "num_ctx": 2048,
        },
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        raw = json.load(urllib.request.urlopen(req, timeout=timeout))["response"]
    except urllib.error.URLError as e:
        raise SaafError(f"Cannot reach Ollama. Is it running? ({e.reason})")
    except TimeoutError:
        if timeout == TIMEOUT_COLD:
            raise SaafError(
                f"Model did not finish loading in {timeout}s. Run "
                f"`ollama run {MODEL}` once, then try again.")
        raise SaafError(f"Model took longer than {timeout}s. Try shorter text.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise SaafError("Model returned unreadable output. Try again.")


def correct(text, fast=False, tone="default"):
    """Correct text. Returns dict with fix, natural, short, notes, hints, seconds.

    fast=True asks for only the `natural` variant, for the instant hotkey that
    pastes without showing a chooser. The other fields are filled from it so
    callers do not need to care which mode produced the result.

    tone selects who the message is going to; see TONES. It only ever appends a
    sentence to the system prompt, so an unknown tone degrades to the default
    rather than failing - the hotkey should never break because a menu item and
    this file disagree about a name.

    Each tone is produced by whichever prompt does it best, and the caller does
    not need to know which:

      formal  the lean prompt plus a fragment. Forces single-answer mode: the
              three-variant prompt says "Contractions are good: I'll, don't,
              can't" while formal says the opposite, and measured, the variant
              definition wins and the tone is silently ignored. Layering an
              audience over three registers asks for two register systems at
              once, so tone replaces that dimension instead.
      brief   the full three-variant prompt, returning its `short` field. Costs
              about a second more and is worth it - see TONES for the numbers.
    """
    if tone in TONES_VIA_VARIANTS:
        fast = False               # this tone needs the three-variant prompt
    elif tone != "default":
        fast = True                # every other tone is a single answer
    text = text.strip()
    if not text:
        raise SaafError("Nothing selected.")
    if len(text) > 4000:
        raise SaafError(f"Text is {len(text)} characters. Select less than 4000.")
    reachable, warm = _ollama_state()
    if not reachable:
        raise SaafError("Ollama is not running. Start it with: ollama serve")
    timeout = TIMEOUT_WARM if warm else TIMEOUT_COLD

    t0 = time.time()

    if fast:
        r = _request(text, fast=True, timeout=timeout, tone=tone)
        # Order matters: undo model typos first, so clean() then fixes the case
        # of anything restored, and the currency check sees the final wording.
        best = blocklist.strip_invented_currency(text, blocklist.clean(
            blocklist.restore_mangled_words(text, r.get("natural", "")))) or text
        out = {
            "fix": best, "natural": best, "short": best,
            "notes": _plausible_notes(r.get("notes", []), text),
            "hints": list(dict.fromkeys(
                blocklist.hints(best) + blocklist.hints(text))),
            "changes": {"natural": _changes(text, best, limit=4)},
            "best": best,
            "seconds": round(time.time() - t0, 2),
            "tone": tone,
            "fast": True,
        }
        # Instant mode is the common path, so it must feed the mistake log too -
        # otherwise `saaf stats` would only ever see the corrections you paused
        # to choose between.
        _log(text, out)
        return out

    result = _request(text, timeout=timeout, tone=tone)

    for f in FIELDS:
        result[f] = blocklist.strip_invented_currency(text, blocklist.clean(
            blocklist.restore_mangled_words(text, result.get(f, ""))))

    # One retry for words that have a real meaning but no safe swap. Measured to
    # work: "leverage the API to facilitate onboarding" -> "use the API to speed up
    # onboarding". Phrases with no recoverable meaning are handled as hints instead.
    bad = sorted({v for f in FIELDS for v in blocklist.violations(result[f])})
    if bad:
        named = ", ".join(f'"{b}"' for b in bad)
        try:
            retry = _request(text, timeout=TIMEOUT_WARM, tone=tone, extra=(
                f"\n\nYour previous attempt used {named}, which is forbidden. "
                "Rewrite so those words are not needed at all. Do not swap them for "
                "synonyms, restructure the sentence."))
            for f in FIELDS:
                retry[f] = blocklist.strip_invented_currency(text, blocklist.clean(
                    blocklist.restore_mangled_words(text, retry.get(f, ""))))
            if len(blocklist.violations(retry["fix"])) < len(blocklist.violations(result["fix"])):
                result = retry
        except SaafError:
            pass                      # the first attempt is still usable

    # Never return an empty suggestion: fall back to the input rather than
    # replacing the user's text with nothing.
    for f in FIELDS:
        if not result.get(f, "").strip():
            result[f] = text

    result["notes"] = _plausible_notes(result.get("notes", []), text)
    result["hints"] = blocklist.hints(result["fix"]) + blocklist.hints(text)
    result["hints"] = list(dict.fromkeys(result["hints"]))
    # "fix" is diffed against what the user wrote; the other two are diffed against
    # "fix". All three share the same base corrections, so diffing every variant
    # against the original made them look alike and pushed the one distinguishing
    # change past the display limit. Diffing against "fix" shows what each option
    # adds on top, which is the actual choice being made.
    result["changes"] = {
        "fix": _changes(text, result["fix"], limit=4),
        "natural": _changes(result["fix"], result["natural"]),
        "short": _changes(result["fix"], result["short"]),
    }
    result["tone"] = tone
    # `natural` is the right answer for every tone except the ones routed here
    # specifically to collect a different field.
    result["best"] = result[TONES_VIA_VARIANTS.get(tone, "natural")]
    result["seconds"] = round(time.time() - t0, 2)
    _log(text, result)
    return result


def _changes(original, corrected, limit=3):
    """Word-level list of what changed, as "old -> new" strings.

    The popup truncates long lines, and the three variants often differ only at the
    END of a sentence - which is exactly what gets cut. Testing showed "fix" and
    "natural" rendering byte-identical in the chooser even though they differed,
    leaving nothing to choose between. Showing the changes instead of relying on the
    full text makes each option distinguishable at a glance.
    """
    a, b = original.split(), corrected.split()
    out = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        old, new = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if tag == "replace":
            out.append(f"{old} -> {new}")
        elif tag == "delete":
            out.append(f"-{old}")
        elif tag == "insert":
            out.append(f"+{new}")
        if len(out) >= limit:
            break
    return out


def _plausible_notes(notes, original):
    """Drop notes that quote text the user never wrote.

    Observed: for "i has send the mail yesterday" the model reported "plural noun
    after 'one of'" - a rule from the prompt's examples, not from this sentence.
    A note about a mistake you did not make is worse than no note, because the whole
    point of notes is learning what you actually get wrong.

    A note is kept unless every phrase it quotes is absent from the original.
    """
    low = original.lower()
    kept = []
    for n in notes:
        if not isinstance(n, str) or not n.strip():
            continue
        quoted = re.findall(r"['\"]([^'\"]{2,40})['\"]", n)
        # Keep notes that quote nothing (they describe a rule generally), and notes
        # where at least one quoted fragment really appears in what the user wrote.
        if quoted and not any(q.lower() in low for q in quoted):
            continue
        kept.append(n.strip())
    return kept[:2]


def _log(original, result):
    """Append the grammar notes so recurring mistakes become visible over time."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps({
                "at": time.strftime("%Y-%m-%d %H:%M"),
                "original": original[:300],
                "fix": result["fix"][:300],
                "notes": result["notes"],
            }) + "\n")
    except OSError:
        pass                          # logging must never break a correction


def _rule_key(note):
    """Group notes that describe the same rule, so counts are meaningful."""
    n = note.lower()
    for key, words in {
        "present perfect with a past time word": ("present perfect", "have sent", "yesterday i have"),
        "'having' used for possession": ("having",),
        "subject-verb agreement": ("subject-verb", "subject verb", "i has", "agreement"),
        "wrong verb after 'to' or 'did'": ("didn't got", "did not got", "to came", "base verb", "infinitive"),
        "missing article (a / an / the)": ("article",),
        "'discuss' needs no preposition": ("discuss",),
        "singular / plural": ("plural", "singular", "one of"),
        "'for' not 'since' for duration": ("since", "duration"),
        "tense": ("tense",),
        "spelling": ("spell",),
        "capitalisation": ("capital", "capitalis", "capitaliz"),
    }.items():
        if any(w in n for w in words):
            return key
    return re.sub(r"[:\-–].*$", "", note).strip()[:60] or "other"


def stats():
    if not LOG.exists():
        print("No history yet. Correct a few messages first.")
        return
    entries = []
    for line in LOG.read_text().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not entries:
        print("No history yet.")
        return

    counts = Counter(_rule_key(n) for e in entries for n in e.get("notes", []))
    print(f"\n  {len(entries)} messages corrected, "
          f"first on {entries[0]['at'][:10]}\n")
    if not counts:
        print("  No grammar mistakes recorded. Either you are improving or the\n"
              "  model is being generous.\n")
        return
    print("  Your most frequent mistakes:\n")
    width = max(len(k) for k, _ in counts.most_common(8))
    for rule, n in counts.most_common(8):
        bar = "#" * min(n, 40)
        print(f"    {rule:<{width}}  {n:>3}  {bar}")
    print(f"\n  Full history: {LOG}\n")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "stats":
        stats()
        return 0

    as_json = "--json" in argv
    fast = "--fast" in argv

    # --tone NAME, or the shorthand --formal / --brief. The shorthand exists
    # because the long form is three extra words to type for the two audiences
    # that are not the default.
    tone = "default"
    args, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--json", "--fast"):
            pass
        elif a == "--tone" and i + 1 < len(argv):
            tone = argv[i + 1]
            i += 1
        elif a.startswith("--tone="):
            tone = a.split("=", 1)[1]
        elif a in ("--formal", "--brief"):
            tone = a.lstrip("-")
        else:
            args.append(a)
        i += 1

    if tone not in TONES:
        print(f"error: unknown tone {tone!r}. Choose one of: "
              f"{', '.join(TONES)}", file=sys.stderr)
        return 1

    text = " ".join(args) if args else sys.stdin.read()

    try:
        r = correct(text, fast=fast, tone=tone)
    except SaafError as e:
        if as_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(r))
        return 0

    print()
    if tone != "default":
        # Any tone is a single answer, whichever prompt produced it. Say so, so
        # asking for three and getting one is never a surprise.
        if not fast:
            print(f"  (one answer, written for: {tone})\n")
        print(f"  {r['best']}")
    elif r.get("fast"):
        print(f"  {r['best']}")
    else:
        for i, f in enumerate(("natural", "fix", "short"), 1):
            print(f"  {i}. {r[f]}")
    if r["notes"]:
        print(f"\n  rules you broke: {' | '.join(r['notes'])}")
    for h in r["hints"]:
        print(f"\n  heads up: {h}")
    tone_note = "" if tone == "default" else f" · {tone}"
    print(f"\n  {r['seconds']}s · {MODEL}{tone_note} · nothing left this Mac\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
