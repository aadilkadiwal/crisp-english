"""Score models against the evaluation set.

Usage:  python3 tests/bench.py qwen3:8b qwen3:4b gemma3:4b
        python3 tests/bench.py --fast-only qwen3:4b
        python3 tests/bench.py --variants-only qwen3:4b

Reports, per model and per mode: pass rate on the mistake cases, time to the
`fix` field (the number the user actually feels), and total time. Prints every
failure with the offending output so a regression is diagnosable, not just
visible.

Two modes are scored, because there are two prompts:

  fast      - one variant, the lean FAST_SYSTEM prompt. This is what the hotkey
              uses, and since the chooser was removed it is the ONLY thing the
              hotkey can use.
  variants  - three variants, the full SYSTEM prompt. CLI only.

Scoring both is the point. This suite used to run `variants` exclusively, which
meant the mode every correction actually goes through was never measured - a
regression in FAST_SYSTEM would have passed a green suite. They are different
prompts, so they need different numbers.
"""

import json
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
from cases import CASES        # noqa: E402
import blocklist               # noqa: E402
import corrector               # noqa: E402

# Send the suite's mistake log somewhere disposable.
#
# corrector.correct() logs every correction so that `corrector.py stats` can show
# recurring mistakes. That is right for real use and wrong here: one benchmark run
# is 32 corrections, so a few runs bury the user's actual writing under test
# sentences and the stats stop describing them. The suite must not write to
# ~/.saaf/.
corrector.LOG = Path("/tmp/saaf-bench-mistakes.log")

# Set SAAF_RAW=1 to score the model alone, without the deterministic layer.
USE_BLOCKLIST = "SAAF_RAW" not in __import__("os").environ

OLLAMA = "http://localhost:11434/api/generate"

SYSTEM = """You correct English for an Indian senior software engineer writing work messages (email, Slack, WhatsApp).

Return JSON with keys in this order: fix, natural, short, notes.

fix      = minimal correction. Change ONLY what is grammatically wrong: verb form,
           tense, articles, plurals, spelling, punctuation. Keep his wording
           everywhere it was already correct. Always expand shorthand:
           pls->please, thx->thanks, u->you, asap->as soon as possible.
natural  = the same message as a real person would type it at work. Correct, but
           NOT polished. It must not read like AI wrote it, which means:
           no "Additionally", "Furthermore", "Moreover", "That said";
           no em dashes; no three-item lists where one item does;
           no "Not only X but also Y"; no "serves as"/"represents" instead of "is";
           no zombie nouns ("provide clarification" -> "clarify",
           "make a decision" -> "decide"); no servile openers
           ("Certainly", "I'd be happy to"); no cheerful ending he did not write
           ("Looking forward to hearing from you"); no "I hope this finds you well".
           Vary sentence length instead of making every sentence the same shape.
           Contractions are good: I'll, don't, can't. Say it and stop.
short    = the same message as briefly as possible while staying polite.
notes    = up to 2 short notes naming the grammar rules he broke. [] if the input
           was already correct.

Grammar rules he breaks often - apply them:
- Present perfect cannot pair with a past time word. "I have sent it yesterday"
  is WRONG; write "I sent it yesterday".
- "did" takes the base verb: "didn't got" -> "didn't get".
- "having" is not used for possession: "I am having 4 years experience" ->
  "I have 4 years of experience".
- "one of" needs a plural noun: "one of my colleague" -> "one of my colleagues".
- Duration takes "for", not "since": "since 4 years" -> "for 4 years".
- "discuss" takes no preposition: "discussed about X" -> "discussed X".
- "myself Aadil" is not an English introduction; write "I am Aadil".
- Do not drop articles: "come to office" -> "come to the office".

NEVER use these: kindly, do the needful, revert back, leverage, circle back,
hope this email finds you well, please be informed.
NEVER add greetings, sign-offs, or facts he did not write. Never add certainty
he did not express."""

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


def _request(model, text, extra_instruction=""):
    """One streamed request. Returns (parsed, seconds_to_fix, seconds_total)."""
    body = {
        "model": model, "system": SYSTEM + extra_instruction,
        "prompt": text, "stream": True,
        "think": False, "keep_alive": "30m", "format": SCHEMA,
        "options": {
            "temperature": 0.2,
            "num_predict": 500,
            # Ollama otherwise honours the model's advertised maximum context.
            # qwen3:4b advertises 262144, which reserves 42GB, does not fit in
            # 16GB, and silently spills inference onto the CPU - the slowest and
            # most battery-hungry outcome. A work message never needs more than
            # a few hundred tokens of context.
            "num_ctx": 2048,
        },
    }
    req = urllib.request.Request(
        OLLAMA, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    buf, t_fix = "", None
    for line in urllib.request.urlopen(req, timeout=300):
        buf += json.loads(line).get("response", "")
        if t_fix is None and '"natural"' in buf:
            t_fix = time.time() - t0        # `fix` is fully written once the next key starts
    return json.loads(buf), t_fix or (time.time() - t0), time.time() - t0


def correct(model, text, fast=False, tone="default"):
    """Run the REAL corrector, so the suite tests what actually ships.

    This used to hold its own copy of the prompt and retry logic, which meant a
    passing suite proved nothing about corrector.py - the two had already drifted
    apart. Delegating here is the point: if corrector.py regresses, these tests
    fail.

    `_request` above is kept only for the SAAF_RAW mode, which scores a bare
    model with no deterministic layer, for model comparison.
    """
    if not USE_BLOCKLIST:
        return _request(model, text)

    corrector.MODEL = model                 # score whichever model was asked for
    result = corrector.correct(text, fast=fast, tone=tone)
    secs = result.get("seconds", 0)
    return result, secs, secs


def check(case, result):
    """Property checks. Returns list of failure strings."""
    fails = []
    # realtone cases assert on the `natural` variant; grammar cases on `fix`
    field = case.get("check_field", "fix")
    fix, low = result[field], result[field].lower()
    for s in case.get("must_contain", []):
        if s.lower() not in low:
            fails.append(f"missing {s!r}")
    for s in case.get("must_not_contain", []):
        if s.lower() in low:
            fails.append(f"still has {s!r}")
    if case.get("expect_no_notes") and result["notes"]:
        fails.append(f"invented notes for correct input: {result['notes']}")
    if "expect_hint" in case:
        # Assert on the hints the user is actually shown, not on hints recomputed
        # from one output field. corrector.py derives them from the ORIGINAL text
        # as well as the correction, precisely so that a model which paraphrases
        # "do the needful" away still gets flagged. Recomputing from the output
        # alone missed that and reported a failure the user would never see.
        got = " ".join(result.get("hints") or []).lower()
        if case["expect_hint"].lower() not in got:
            fails.append(f"no hint about {case['expect_hint']!r} (got {got or 'none'})")
    # auto-fixable filler must not survive in ANY variant. "do the needful" is
    # excluded here on purpose: it is unfixable by design and checked via
    # expect_hint instead.
    for f in ("fix", "natural", "short"):
        for b in ["kindly", "revert back", "circle back", "leverage", "utilize"]:
            if b in result[f].lower():
                fails.append(f"banned {b!r} in {f}")
    # Numbers survive reformatting: the model writes 45000 as "45,000", which is
    # the same fact. Compare digits only, so formatting passes and a dropped or
    # altered number still fails.
    for s in case.get("must_contain_digits", []):
        if s not in re.sub(r"[^0-9]", "", fix):
            fails.append(f"missing the number {s!r}")

    # Structure, not wording: a multi-paragraph message must come back with its
    # paragraphs. A substring check cannot see this at all.
    if "min_lines" in case and len(fix.splitlines()) < case["min_lines"]:
        fails.append(f"{len(fix.splitlines())} lines, expected >= {case['min_lines']}"
                     " (paragraphs were flattened)")

    # The brief tone is the one assertion that cannot be a substring check: it is
    # about how much was cut, not which words survived.
    if "max_words" in case and len(fix.split()) > case["max_words"]:
        fails.append(f"{len(fix.split())} words, expected <= {case['max_words']}")
    if not fix.strip():
        fails.append("empty fix")
    return fails


def run_suite(model, fast):
    """Score one model in one mode. Returns a summary dict, or None if unavailable."""
    label = f"{model} [{'fast' if fast else 'variants'}]"
    print(f"\n{'=' * 72}\n  {label}\n{'=' * 72}")
    try:
        correct(model, "warmup", fast=fast)     # absorb cold-load into an untimed call
    except Exception as e:
        print(f"  UNAVAILABLE: {e}")
        return None

    # Tone cases are scored once, in the fast pass.
    #
    # corrector.correct() routes each tone to whichever prompt serves it best and
    # overrides the caller's `fast` argument to do so, which means a tone case
    # returns the same answer in either pass. Running them twice would report the
    # identical result under two headings and inflate both totals.
    cases = [c for c in CASES if fast or c.get("tone", "default") == "default"]
    skipped = len(CASES) - len(cases)
    if skipped:
        print(f"  {skipped} tone case(s) skipped: scored in the fast pass only\n")

    passed, fix_times, tot_times = 0, [], []
    for case in cases:
        try:
            r, t_fix, t_tot = correct(model, case["text"], fast=fast,
                                      tone=case.get("tone", "default"))
        except Exception as e:
            print(f"  ✗ {case['id']:32} ERROR {e}")
            continue
        fix_times.append(t_fix)
        tot_times.append(t_tot)
        shown = case.get("check_field", "fix")
        fails = check(case, r)
        if fails:
            print(f"  ✗ {case['id']:32} {t_fix:4.1f}s  {'; '.join(fails)}")
            print(f"      {shown:8} : {r[shown]}")
        else:
            passed += 1
            print(f"  ✓ {case['id']:32} {t_fix:4.1f}s  {r[shown][:70]}")

    if not fix_times:
        return None
    return dict(label=label, passed=passed, total=len(cases),
                fix=statistics.median(fix_times),
                tot=statistics.median(tot_times))


def main(argv):
    modes = [False, True]                       # variants, then fast
    if "--fast-only" in argv:
        modes = [True]
    elif "--variants-only" in argv:
        modes = [False]
    models = [a for a in argv if not a.startswith("--")] or ["qwen3:4b"]

    if not USE_BLOCKLIST and True in modes:
        # `_request` has no fast path - raw mode exists to score a bare model
        # against the full prompt, which is the variants prompt.
        print("  note: SAAF_RAW has no fast mode; scoring variants only.")
        modes = [False]

    summary = []
    for model in models:
        for fast in modes:
            s = run_suite(model, fast)
            if s:
                summary.append(s)

    print(f"\n{'=' * 72}\n  SUMMARY (median times)\n{'=' * 72}")
    print(f"  {'model [mode]':26} {'passed':>10}  {'fix ready':>10}  {'all done':>10}")
    for s in summary:
        print(f"  {s['label']:26} {s['passed']:>4}/{s['total']:<5}  "
              f"{s['fix']:>9.1f}s  {s['tot']:>9.1f}s")
    print("\n  In fast mode there is only one variant, so the two time columns\n"
          "  are the same number by definition.\n")


if __name__ == "__main__":
    main(sys.argv[1:])
