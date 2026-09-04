#!/usr/bin/env python3
"""crisp-english - correct English in work messages, locally.

    crisp-english "i has send the mail yesterday"     three suggestions, human readable
    crisp-english --fast "..."                        one suggestion, what the hotkey uses
    crisp-english --formal "..."                      for a client or someone senior
    crisp-english --brief "..."                       for Slack or WhatsApp, fewest words
    crisp-english --json "..."                        machine readable, for the hotkey
    crisp-english stats                               your most frequent mistakes
    crisp-english last                                what the last correction changed
    crisp-english again [--brief|--formal]            redo the last one for another audience

Runs entirely on this Mac via Ollama. Nothing is sent anywhere.
"""

import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blocklist  # noqa: E402

PROJECT = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".crisp-english"
LOG = STATE_DIR / "mistakes.log"


# --- configuration -----------------------------------------------------------
# See crisp-english.conf for the format and for why this file exists at all. In short:
# four languages, one set of numbers, and three comments that used to say "THIS
# NUMBER EXISTS IN FOUR PLACES".

def read_config_file(path):
    """Parse KEY=value lines. Returns {} for a missing or unreadable file.

    Deliberately not `exec` or a real parser: the same file is parsed by a Lua
    function and a shell loop, and this is the syntax all three can agree on
    without any of them being clever.
    """
    settings = {}
    try:
        raw = Path(path).read_text()
    except OSError:
        return settings
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        # Strip a trailing comment, then optional quotes. " #" rather than "#",
        # so a value containing a hash is still possible.
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip().strip("\"'")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            settings[key] = value
    return settings


# Project defaults, then the user's own file on top.
CONFIG = dict(read_config_file(PROJECT / "crisp-english.conf"))
CONFIG.update(read_config_file(STATE_DIR / "crisp-english.conf"))


def setting(key, default, files=None):
    """Environment beats the config files, which beat the built-in default.

    An explicit None check rather than `or`, so CRISP_ENGLISH_LOG_TEXT=0 means 0 and not
    "fall through to the default".
    """
    files = CONFIG if files is None else files
    for source in (os.environ, files):
        value = source.get(key)
        if value is not None and value != "":
            return value
    return default


def _flag(key, default):
    return str(setting(key, default)).strip().lower() in ("1", "true", "yes", "on")


MODEL = setting("CRISP_ENGLISH_MODEL", "qwen3:4b")
KEEP_ALIVE = setting("CRISP_ENGLISH_KEEP_ALIVE", "1h")
NUM_CTX = int(setting("CRISP_ENGLISH_NUM_CTX", "2048"))
LOG_TEXT = _flag("CRISP_ENGLISH_LOG_TEXT", "1")
LOG_MAX = int(setting("CRISP_ENGLISH_LOG_MAX", "2000"))

OLLAMA = "http://localhost:11434"

# Two timeouts, because there are two very different waits. A resident model
# answers in ~1.6s; loading one off disk is 15-50s. A single 25s limit was right
# for the first case and cancelled the second just before it would have
# succeeded, which read as a broken tool rather than a slow one.
TIMEOUT_WARM = 25
TIMEOUT_COLD = 90

# Output token budgets. Fast mode asks for one variant instead of three, which is
# genuinely faster rather than just skipping a popup.
NUM_PREDICT_FAST = 200
NUM_PREDICT_FULL = 500

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


class CrispError(Exception):
    """Anything the user needs to be told about, in words they can act on."""


# --- how much text fits ------------------------------------------------------
# The cap used to be a flat 4000 characters, chosen as a round number rather than
# derived from anything. Against num_ctx=2048 the arithmetic does not work: the
# full prompt is ~600-800 tokens, 4000 characters is ~1100, and num_predict is
# 500, which is about 2400 tokens of demand on a 2048-token window. Ollama drops
# tokens from the START of the context when it overflows, and the start is the
# system prompt - so the failure mode is not an error, it is a correction made
# with half its instructions missing.
#
# 3 characters per token is deliberately pessimistic (English averages closer to
# 4), because every error in this estimate has to fall on the safe side.
CHARS_PER_TOKEN = 3
RESERVE_TOKENS = 64          # JSON scaffolding, the tone fragment, rounding


def estimate_tokens(text):
    return len(text) // CHARS_PER_TOKEN + 1


def max_chars(fast):
    """Characters of input that fit in num_ctx, for the prompt actually used."""
    system = FAST_SYSTEM if fast else SYSTEM
    predict = NUM_PREDICT_FAST if fast else NUM_PREDICT_FULL
    room = NUM_CTX - estimate_tokens(system) - predict - RESERVE_TOKENS
    return max(room, 0) * CHARS_PER_TOKEN


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
        "keep_alive": KEEP_ALIVE,
        "format": FAST_SCHEMA if fast else SCHEMA,
        "options": {
            "temperature": 0.2,
            "num_predict": NUM_PREDICT_FAST if fast else NUM_PREDICT_FULL,
            "num_ctx": NUM_CTX,
        },
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        raw = json.load(urllib.request.urlopen(req, timeout=timeout))["response"]
    # socket.timeout FIRST, and by that name.
    #
    # /usr/bin/python3 - which init.lua hardcodes, because it is the only python
    # guaranteed to exist on a Mac - is 3.9, and there socket.timeout is neither
    # TimeoutError (that alias arrived in 3.10) nor URLError. Both handlers below
    # therefore missed it, and every read timeout escaped as an unhandled
    # exception: the user got a Python traceback in a "crisp-english failed" notification
    # at exactly the moment the tool needed to explain itself. Verified against
    # a stalling server that never answered.
    except socket.timeout:
        if timeout >= TIMEOUT_COLD:
            raise CrispError(
                f"Model did not finish loading in {timeout:g}s. Run "
                f"`ollama run {MODEL}` once, then try again.")
        raise CrispError(
            f"Model took longer than {timeout:g}s. Try shorter text.")
    except urllib.error.URLError as e:
        # A connect timeout arrives wrapped in URLError instead of raw.
        if isinstance(e.reason, socket.timeout):
            raise CrispError("Ollama did not answer in time. Is it still running?")
        raise CrispError(f"Cannot reach Ollama. Is it running? ({e.reason})")
    except OSError as e:
        raise CrispError(f"Cannot reach Ollama. Is it running? ({e})")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise CrispError("Model returned unreadable output. Try again.")


def _polish(original, text):
    """Model output -> shippable text. The deterministic layer, in order.

    Order matters: undo model typos first, so clean() then fixes the case of
    anything restored, and the currency check sees the final wording.
    """
    return blocklist.strip_invented_currency(
        original, blocklist.clean(
            blocklist.restore_mangled_words(original, text or "")))


def _retry_extra(bad):
    named = ", ".join(f'"{b}"' for b in bad)
    return (f"\n\nYour previous attempt used {named}, which is forbidden. "
            "Rewrite so those words are not needed at all. Do not swap them for "
            "synonyms, restructure the sentence.")


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
        raise CrispError("Nothing selected.")
    limit = max_chars(fast)
    if len(text) > limit:
        raise CrispError(
            f"Text is {len(text)} characters and the model's context fits "
            f"{limit}. Select less and try again.")
    reachable, warm = _ollama_state()
    if not reachable:
        raise CrispError("Ollama is not running. Start it with: ollama serve")
    timeout = TIMEOUT_WARM if warm else TIMEOUT_COLD

    t0 = time.time()

    if fast:
        r = _request(text, fast=True, timeout=timeout, tone=tone)
        best = _polish(text, r.get("natural", "")) or text

        # Group 5 enforcement, in the mode that actually ships.
        #
        # This block used to exist only below, in the three-variant path - which
        # the hotkey cannot reach. So the single mechanism for removing AI
        # vocabulary ("leverage", "additionally", "delve") was absent from every
        # correction anyone actually makes. One retry, only when a violation is
        # found, so the common case costs nothing.
        bad = blocklist.violations(best)
        if bad:
            try:
                retry = _request(text, fast=True, timeout=TIMEOUT_WARM, tone=tone,
                                 extra=_retry_extra(bad))
                candidate = _polish(text, retry.get("natural", ""))
                if candidate and len(blocklist.violations(candidate)) < len(bad):
                    best, r = candidate, retry
            except CrispError:
                pass                  # the first attempt is still usable

        out = {
            "fix": best, "natural": best, "short": best,
            "notes": _plausible_notes(r.get("notes", []), text),
            "hints": list(dict.fromkeys(
                blocklist.hints(best) + blocklist.hints(text))),
            # "best" is what the alert describes; "natural" is kept because
            # an older init.lua reads that key. Same list in fast mode.
            "changes": {"natural": _changes(text, best, limit=4),
                        "best": _changes(text, best, limit=4)},
            "best": best,
            "seconds": round(time.time() - t0, 2),
            "tone": tone,
            "fast": True,
        }
        # Instant mode is the common path, so it must feed the mistake log too -
        # otherwise `crisp-english stats` would only ever see the corrections you paused
        # to choose between.
        _log(text, out)
        return out

    result = _request(text, timeout=timeout, tone=tone)

    for f in FIELDS:
        result[f] = _polish(text, result.get(f, ""))

    # One retry for words that have a real meaning but no safe swap. Measured to
    # work: "leverage the API to facilitate onboarding" -> "use the API to speed up
    # onboarding". Phrases with no recoverable meaning are handled as hints instead.
    bad = sorted({v for f in FIELDS for v in blocklist.violations(result[f])})
    if bad:
        try:
            retry = _request(text, timeout=TIMEOUT_WARM, tone=tone,
                             extra=_retry_extra(bad))
            for f in FIELDS:
                retry[f] = _polish(text, retry.get(f, ""))
            if len(blocklist.violations(retry["fix"])) < len(blocklist.violations(result["fix"])):
                result = retry
        except CrispError:
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
    # What the alert should describe: the text that will actually be pasted,
    # diffed against what the user wrote.
    #
    # The three entries above are for the CLI, which prints all three variants
    # and wants to show what each ADDS to `fix`. The hotkey pastes exactly one of
    # them and never shows the others, so a diff against a sibling variant is the
    # wrong comparison - and for the brief tone it is empty, because `natural` and
    # `fix` are the same string while `best` is `short`. That meant a Slack
    # correction with alerts on explained nothing at all, in the one register the
    # app now selects on its own.
    result["changes"]["best"] = _changes(text, result["best"], limit=4)
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
    for n in notes or []:
        if not isinstance(n, str) or not n.strip():
            continue
        quoted = re.findall(r"['\"]([^'\"]{2,40})['\"]", n)
        # Keep notes that quote nothing (they describe a rule generally), and notes
        # where at least one quoted fragment really appears in what the user wrote.
        if quoted and not any(q.lower() in low for q in quoted):
            continue
        kept.append(n.strip())
    return kept[:2]


# --- the mistake log ---------------------------------------------------------

def _log(original, result):
    """Append the grammar notes so recurring mistakes become visible over time.

    Two things this deliberately does that it did not before:

      - it rotates. The log had no ceiling, so it grew for as long as crisp-english was
        installed, and stats() reads all of it on every call.
      - it can hold notes only. CRISP_ENGLISH_LOG_TEXT=0 keeps the rule names and drops
        the message text, for anyone who would rather crisp-english's promise that
        nothing leaves the Mac not be paired with a permanent transcript of
        everything they wrote. `last` and `again` need the text, and say so.
    """
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": time.strftime("%Y-%m-%d %H:%M"),
            "notes": result.get("notes", []),
            "tone": result.get("tone", "default"),
        }
        if LOG_TEXT:
            entry["original"] = original[:1000]
            entry["fix"] = result.get("fix", "")[:1000]
        with LOG.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        _rotate()
    except OSError:
        pass                          # logging must never break a correction


def _rotate():
    """Keep the newest LOG_MAX entries and drop the rest."""
    try:
        lines = LOG.read_text().splitlines()
    except OSError:
        return
    if len(lines) <= LOG_MAX:
        return
    LOG.write_text("\n".join(lines[-LOG_MAX:]) + "\n")


def _entries():
    """Every readable log entry, oldest first."""
    try:
        raw = LOG.read_text()
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue                  # a torn line from a killed write
    return out


def last_correction():
    """The most recent correction, or None if there is nothing usable.

    Returns None when CRISP_ENGLISH_LOG_TEXT=0, because then the last correction's text
    was never kept. Not "the last one that happens to have text": reaching back
    past the corrections it did not record and presenting an older one as the
    last is a wrong answer, and it puts message text in front of someone who
    just asked for message text not to be kept. Callers report the difference.
    """
    if not LOG_TEXT:
        return None
    for entry in reversed(_entries()):
        if entry.get("original"):
            return entry
    return None


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


def stats_report(entries, now=None, window_days=30):
    """Split each rule's count into recent and older. Pure; tested directly.

    A single all-time total cannot answer the question the log exists for. A rule
    you broke thirty times in June and never since still tops the chart, so the
    feature built to show what you get wrong shows what you USED to get wrong.
    Two columns and a "fixed" marker turn the same data into a trend.
    """
    now = time.time() if now is None else now
    cutoff = now - window_days * 86400
    recent, older = Counter(), Counter()
    for entry in entries:
        try:
            when = time.mktime(time.strptime(entry.get("at", "")[:10], "%Y-%m-%d"))
        except (ValueError, TypeError):
            when = 0                  # undateable entries are history
        bucket = recent if when >= cutoff else older
        for note in entry.get("notes", []):
            bucket[_rule_key(note)] += 1

    rows = []
    for rule in set(recent) | set(older):
        rows.append({
            "rule": rule,
            "recent": recent[rule],
            "older": older[rule],
            "improved": recent[rule] == 0 and older[rule] > 0,
        })
    # What is still happening first; that is what there is anything to do about.
    rows.sort(key=lambda r: (-r["recent"], -r["older"], r["rule"]))
    return {
        "rows": rows,
        "total": len(entries),
        "window_days": window_days,
        "first": entries[0].get("at", "")[:10] if entries else None,
    }


def stats(window_days=30):
    entries = _entries()
    if not entries:
        print("No history yet. Correct a few messages first.")
        return
    report = stats_report(entries, window_days=window_days)
    print(f"\n  {report['total']} messages corrected, "
          f"first on {report['first']}\n")
    if not report["rows"]:
        print("  No grammar mistakes recorded. Either you are improving or the\n"
              "  model is being generous.\n")
        return

    rows = report["rows"][:8]
    width = max(len(r["rule"]) for r in rows)
    print(f"  {'':<{width}}  {'last ' + str(window_days) + 'd':>8}  before\n")
    for r in rows:
        bar = "#" * min(r["recent"], 30)
        mark = "  fixed" if r["improved"] else ""
        print(f"  {r['rule']:<{width}}  {r['recent']:>8}  {r['older']:>6}  "
              f"{bar}{mark}")
    fixed = [r["rule"] for r in report["rows"] if r["improved"]]
    if fixed:
        print(f"\n  Not seen in the last {window_days} days: {len(fixed)} "
              f"rule{'s' if len(fixed) > 1 else ''} you used to break.")
    print(f"\n  Full history: {LOG}\n")


def _print_last():
    entry = last_correction()
    if not entry:
        if not LOG_TEXT:
            print("Message text is not being logged (CRISP_ENGLISH_LOG_TEXT=0), so there\n"
                  "is no previous correction to show.", file=sys.stderr)
            return 1
        print("No history yet.", file=sys.stderr)
        return 1
    print(f"\n  {entry['at']}  ·  written for: {entry.get('tone', 'default')}\n")
    # Labels that do not carry the product name, so they stay aligned through
    # the next rename. "crisp sent:" lined up with "you wrote :"; the rename
    # made it "crisp-english sent:" and the column went with it.
    print(f"  you wrote : {entry['original']}")
    print(f"  corrected : {entry.get('fix', '')}")
    if entry.get("notes"):
        print(f"\n  rules you broke: {' | '.join(entry['notes'])}")
    print()
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "stats":
        stats()
        return 0
    if argv[0] == "last":
        return _print_last()

    as_json = "--json" in argv
    fast = "--fast" in argv

    # --tone NAME, or the shorthand --formal / --brief. The shorthand exists
    # because the long form is three extra words to type for the two audiences
    # that are not the default.
    tone = "default"
    tone_given = False
    args, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--json", "--fast"):
            pass
        elif a == "--tone" and i + 1 < len(argv):
            tone, tone_given = argv[i + 1], True
            i += 1
        elif a.startswith("--tone="):
            tone, tone_given = a.split("=", 1)[1], True
        elif a in ("--formal", "--brief"):
            tone, tone_given = a.lstrip("-"), True
        else:
            args.append(a)
        i += 1

    if tone not in TONES:
        print(f"error: unknown tone {tone!r}. Choose one of: "
              f"{', '.join(TONES)}", file=sys.stderr)
        return 1

    # `again` redoes the previous correction, optionally for another audience.
    # The point is the second half: a message that came back too formal is one
    # command away from the other register, without retyping it.
    if args and args[0] == "again":
        entry = last_correction()
        if not entry:
            print("No previous correction to redo." if LOG_TEXT else
                  "Message text is not being logged (CRISP_ENGLISH_LOG_TEXT=0), so there\n"
                  "is nothing to redo.", file=sys.stderr)
            return 1
        text = entry["original"]
        if not tone_given:
            tone = entry.get("tone", "default")
            if tone not in TONES:
                tone = "default"
    else:
        text = " ".join(args) if args else sys.stdin.read()

    try:
        r = correct(text, fast=fast, tone=tone)
    except CrispError as e:
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
