# saaf — local grammar and rephrasing helper

**Date:** 2026-08-12
**Status:** Implemented. Amended 2026-08-13 — see Revision below.

## Revision — 2026-08-13

The project was called `polish` until this date. Renamed to **saaf** (Hindi/Urdu for
*clean*) because the old name argued against the design: this document itself
explains that `natural` is deliberately not called `polished` since "polished is
the failure mode". A tool about English also should not share a name with a
language. The rename covered the CLI, the log directory (`~/.saaf/`), the launchd
label (`com.saaf.preload`), and the project directory.

Four design changes, all of which supersede the sections below:

1. **The chooser is gone. One hotkey, `Option+P`, pastes immediately.** The
   three-variant popup and its supporting code (`showResults`, `describe`,
   `LABELS`, `ORDER`, and the row dedupe/merge logic) were deleted — roughly 85
   lines, the most intricate in the project. Their whole purpose was making three
   near-identical sentences distinguishable in a list, which is a problem created
   by offering three options rather than one. The instant path was already the
   common case by this document's own reasoning.
2. **The alert now shows what changed.** `_changes()` was already computed and
   already sent over the wire in fast mode; the Lua layer discarded it and showed
   only the grammar notes. Pasting without a chooser means the correction is never
   previewed, so "what did it just do to my sentence" is the question the alert has
   to answer. `⌘Z` is the revert path — a paste-over-selection is one undo step in
   the host app, so no custom undo was needed.
3. **Cold start is handled rather than hidden.** `keep_alive` is 8h but the
   launchd `StartInterval` was 86400, so nothing re-warmed the model between login
   and the next day; `launchctl list` showed exit status 7 (curl "failed to
   connect") from a single login attempt that fired before Ollama was listening.
   The interval is now 25200 (7h), under the TTL. `corrector.py` picks its timeout
   from `/api/ps` — 25s warm, 90s cold — instead of cancelling a load at 25s that
   was going to succeed, and the working alert says it is warming.
4. **The benchmark scores both prompts.** `tests/bench.py` only ever ran the
   three-variant path, so `FAST_SYSTEM` — now the only prompt the hotkey can use —
   was never measured. Two consequences surfaced immediately: `check()` recomputed
   hints from one output field instead of asserting on `result["hints"]`, missing
   that hints are derived from the original text too; and the suite logged its 32
   corrections per run into `~/.saaf/mistakes.log`, burying real usage under test
   sentences. Both fixed. Current scores below.

### Measured after these changes (2026-08-13, `qwen3:4b`)

| Mode | Passed | Median |
|---|---|---|
| `fast` — the only path the hotkey uses | **16/16** | **1.2 s** |
| `variants` — CLI only | 16/16 | 2.2 s |

Fast mode is twice as quick, because a shorter prompt and one variant instead of
three is fewer tokens in and fewer out. Reproduce with
`python3 tests/bench.py qwen3:4b`.

### Still stale below this line

The three-variant path, its prompt, and its schema all remain in `corrector.py`
and are still exercised by the suite — only the *hotkey* dropped to one variant.
Two references in the original text were never built: `bin/polish` (there is no
shell wrapper; `corrector.py` is executable directly) and `tests/fixtures.yaml`
(the cases live in `tests/cases.py`). Streaming is specified as required below and
is not implemented; at 1.2s to a complete answer it buys nothing and is not
planned. `⌥Space` in the data-flow diagram is now `Option+P`, and the preloader
warms `qwen3:4b`, not `qwen3:8b`.

## Problem

Writing work messages (email, Slack, WhatsApp) means switching to ChatGPT, pasting
text, copying the result, and switching back — many times a day. The round trip is
slower than the writing itself, and work text goes to a third party.

## Goal

Correct a selected piece of text in any macOS app with one keystroke, offering a
choice of three phrasings, entirely on-device.

Success means the ChatGPT round trip stops happening, and recurring mistakes become
visible over time instead of being silently patched.

## Non-goals

- Live underlines while typing. Desktop apps do not expose their text fields for
  this; LanguageTool's free browser extension already covers the browser-only case.
- Cloud models. Work text stays on the machine.
- Translation, tone personas beyond the three below, or long-document editing.

## Environment (verified 2026-08-12)

| Fact | Value |
|---|---|
| OS | macOS 26.5.1 |
| Chip / RAM | Apple M4 / 16 GB |
| Model | **`qwen3:4b`** — 2.5 GB, chosen on benchmark evidence (below) |
| Rejected: `qwen3:8b` | Equal quality, 1.7x slower, twice the RAM. No reason to pay for it. |
| Rejected: `gpt-oss:20b` | 13 GB, not viable in 16 GB alongside work apps |
| Rejected: `gemma3:4b` | **Silently deletes content** — see below. Disqualified on safety. |
| Rejected: LanguageTool | Purpose-built, but misses the Indian-English patterns that matter here |
| Hotkey layer | Hammerspoon (to be installed via `brew install --cask hammerspoon`) |

### Measured performance

Established by benchmark against `tests/cases.py`, not estimated. Final state:

| Model | Passed | `fix` ready | All three done | Size |
|---|---|---|---|---|
| **`qwen3:4b` + blocklist** | **16/16** | **0.9 s** | **2.3 s** | 2.5 GB |
| `qwen3:8b` + blocklist | 11/12 † | 1.5 s | 4.5 s | 5.2 GB |
| `qwen3:4b` raw | 8/12 † | 1.2 s | 3.1 s | 2.5 GB |
| `qwen3:8b` raw | 9/12 † | 1.9 s | 5.7 s | 5.2 GB |
| `gemma3:4b` raw | 7/12 † | 1.4 s | 3.7 s | 3.3 GB |

† scored against the 12-case set, before the four `realtone` cases were added.
The 16/16 row is the current suite. Re-run `python3 tests/bench.py <model>` to
compare any model on equal terms.

`qwen3:4b` matches the 8b on quality once the deterministic layer is in place, at
1.7x the speed and half the memory, so it is the default.

Cold model load remains 15–50 s, which is what the login preloader exists to hide.

### Why `gemma3:4b` is disqualified

It silently drops content, which is disqualifying regardless of score:

- `"The deployment is done. Please verify and confirm."` → `"Please verify and
  confirm."` — first sentence lost.
- `"hi sir, i am not able to came office today because i have fever. i will do work
  from home and complete the pending API task"` → `"I am not able to come office
  today because I have a fever."` — greeting and entire second sentence lost.

It also invented grammar notes for already-correct input. A tool that quietly
deletes half a message is worse than no tool.

### Why the deterministic layer is worth more than the model choice

Raw model scores were 8/12 and 9/12; both models failed the *same small set* of
patterns despite explicit prompt rules naming each one. Moving those patterns into
`blocklist.py` took both models to 11/12. The mistakes are recurring and closed-form,
so rules beat prompting — and this is what makes the smaller, cooler-running model
sufficient.

Two conclusions drive the architecture: streaming is required, because 11 s of
spinner is unusable while 4.3 s to the most-used option is fine; and the model must
be preloaded at login, because a 50 s first correction would kill the habit.

### `num_ctx` must be set explicitly — the largest single win

Ollama otherwise honours the model's advertised maximum context. `qwen3:4b`
advertises 262144 tokens, which reserves **42 GB**, does not fit in 16 GB, and
silently spills inference onto the CPU:

| `num_ctx` | Memory | Processor |
|---|---|---|
| default (262144) | 42 GB | 74% CPU / 26% GPU |
| **2048** | **2.9 GB** | **100% GPU** |

CPU inference is both the slowest path and the heaviest battery drain, so this
single option matters more for responsiveness and battery life than the choice
between a 4b and an 8b model. A work message never needs more than a few hundred
tokens of context. `num_ctx: 2048` is mandatory in every request.

## Architecture

Three units with one job each.

### 1. `corrector.py` — correction logic

No UI, no clipboard, no hotkeys. Text in, variants out.

- Input: a string.
- Output: streams `fix`, `polished`, `short`, `notes` as each completes.
- Talks to `http://localhost:11434/api/generate` with `stream: true`,
  `think: false`, `keep_alive: "30m"`, `temperature: 0.2`, and a JSON schema in
  `format` so field order and shape are guaranteed by the API rather than parsed
  hopefully.
- Also the CLI entry point, exposed on `PATH` as `saaf` via a thin shell wrapper
  in `bin/saaf`:
  - `saaf "my text"` — prints all variants. This is the test surface.
  - `saaf stats` — prints recurring mistakes from the log (see below).

  Both subcommands live in `corrector.py`; `bin/saaf` only execs it.

Field order in the schema is load-bearing: `fix` is generated first because it is
the most-used variant and streaming makes earlier fields available sooner.

### 1b. `blocklist.py` — deterministic post-processing

No model involved. Runs on every variant before it reaches the popup.

Benchmarking established that `qwen3:8b` emits `do the needful` and `kindly` in
roughly a third of cases **even when the prompt bans those exact strings**. Prompt
instructions are not an enforcement mechanism. So every rule that can be expressed
as a rule lives here instead:

Three tiers, because measurement showed two was not enough:

1. **Substitute** — a safe meaning-preserving replacement exists. Applied silently,
   0 ms: `kindly`→`please`, `revert back to`→`reply to`, `pls`→`please`,
   `asap`→`as soon as possible`, `intimate`→`inform`, `serves as`→`is`,
   `due to the fact that`→`because`, `provide clarification`→`clarify`.
   Also the recurring grammar patterns (see below) and `realtone`'s Phase 2
   character checks: zero em dashes, straight quotes, no emoji, no boldface.

2. **Retry** — the word has a real meaning but no safe swap, so the request is
   reissued with the offending word named. Measured to work:
   `leverage the new API to facilitate faster onboarding` →
   `use the new API to speed up onboarding`. One retry only, and it is kept only if
   it genuinely reduced violations. This covers `realtone`'s zero-tolerance
   vocabulary (`leverage`, `utilize`, `comprehensive`, `robust`, `crucial`, …).

3. **Hint** — the phrase carries no recoverable meaning, so *nothing* can fix it.
   The sentence is left untouched and the popup shows advice instead.

   Measured: reissuing the request does **not** remove `do the needful`, on either
   model, even when the phrase is named explicitly. That is correct behaviour, not a
   failure — `do the needful` could mean review it, approve it, or deploy it, and
   nothing in the text says which. A tool that "fixes" it is guessing at intent and
   may send the wrong instruction to a colleague. So the popup says: *"'do the
   needful' does not say what you want. Name the action: review it, approve it,
   deploy it."*

   This is the one place where saaf teaches rather than corrects, and it is the
   right call: silently guessing intent is worse than asking.

### Recurring grammar patterns are rules, not judgment

Both models failed the *same* small set of grammar patterns despite explicit prompt
rules naming each one. They are recurring and closed-form, so they moved into tier 1:
present perfect with a past time word (drop the auxiliary), `myself Aadil`→`I am
Aadil`, `since 4 years`→`for 4 years`, `am having`+possession→`have`,
`discussed about`→`discussed`, `didn't got`→`didn't get`, `to came`→`to come`,
`one of my colleague`→`colleagues`, dropped article before `office`.

Each rule is deliberately narrow, because a false positive rewrites text that was
already correct — worse than a miss. `we are having a meeting` is correct English and
must survive; an early version broke it, which is why `meeting`, `call`, and `lunch`
are excluded from the possession-noun list.

This layer is what makes a smaller model viable. Weak instruction-following stops
mattering for any category enforced here; the model only has to get grammar right.

Source of the vocabulary lists: the user's own `realtone` skill (groups 2 and 3).
Group 1, Indian-English office filler, is not covered by `realtone` and is original
to this project.

### 2. `init.lua` — hotkey and popup (Hammerspoon)

- Binds ⌥Space globally.
- Stashes the current clipboard, sends ⌘C to capture the selection, reads it back.
- Opens the chooser immediately and fills rows in as `corrector.py` streams them,
  so the popup is never a blank spinner.
- On pick: writes the choice to the clipboard, sends ⌘V, then restores the
  original clipboard contents.

### 3. `com.saaf.preload.plist` — login preloader

A launchd agent that at login sends a one-token request to `qwen3:8b` with a long
`keep_alive`, so the model is resident before first use.

### Data flow

```
select text → ⌥Space → stash clipboard → ⌘C → read selection
  → corrector.py streams from Ollama
  → chooser fills: [1] fix ~4.3s · [2] polished ~6.3s · [3] short ~7.7s
  → press 1/2/3 → clipboard = choice → ⌘V → restore original clipboard
```

## The three variants

- **fix** — minimal correction. Grammar, spelling, tense, articles, punctuation
  only. Shorthand always expanded (`pls`→`please`, `thx`→`thanks`, `u`→`you`,
  `asap`→`as soon as possible`). Wording that was already correct is left alone.
- **natural** — the message as a real person would type it at work. Correct but
  deliberately *not* polished: it must not read like AI wrote it. Named `natural`
  rather than `polished` because "polished" is the failure mode — polished is what
  AI output sounds like. Target defined in `voice.md`, derived from the user's
  `realtone` skill.
- **short** — the same message as briefly as possible while staying polite.
- **notes** — up to two short notes naming the grammar rules broken. Empty when the
  input was already correct.

### Sounding human is a tested requirement, not an aspiration

`tests/cases.py` includes four cases asserting on the `natural` variant: no AI
signpost connectives (`Additionally`, `Furthermore`, `Moreover`), no zombie nouns
(`provide clarification`, `make a decision`), no invented greeting or sign-off, and
no em dashes or curly quotes. These are the `realtone` patterns that actually occur
in short work messages.

Long-form `realtone` rules are deliberately omitted: paragraph shape uniformity,
"read the last paragraph aloud", and abstract-before-concrete have nothing to
measure in a two-line Slack message. `realtone`'s own instruction to match register
is what authorises leaving them out.

### Prompt constraints

Both of these were added in response to observed failures during benchmarking, so
they must survive into implementation:

- Never use present perfect with a past time word. The model produced *"I have sent
  the mail yesterday"* until told explicitly.
- Banned strings anywhere in output: `kindly`, `do the needful`, `revert back`,
  `leverage`, `circle back`, `hope this email finds you well`, `please be informed`.
  The model produced *"Kindly verify"* despite a general "no corporate filler"
  instruction; the explicit banned list fixed it.

Never add greetings or sign-offs the user did not write, and never invent facts.

## Mistake log

Each run appends its `notes` to `~/.saaf/mistakes.log` as one JSON object per
line. `saaf stats` reads the log and prints the most frequent recurring mistakes.

This exists because the stated problem is inaccurate English, not just unpolished
messages — the log is what turns per-message patching into actual improvement.

## Error handling

| Condition | Behaviour |
|---|---|
| Ollama not reachable | Popup: "Ollama not running" with an option to start it |
| Empty selection | Brief alert, no popup, nothing pasted |
| Model still loading | Popup shows a loading row; the preloader makes this rare |
| Exceeds 25 s | Cancel, show error, leave clipboard untouched |
| Input over 2000 chars | Proceed, but warn in the popup that it will be slower |
| Invalid JSON | Prevented by schema enforcement; fallback presents raw text as one option |

The original clipboard is restored on every exit path, including cancellation and
error. A grammar helper that eats your clipboard will not get used twice.

## Testing

`tests/fixtures.yaml` holds real mistake patterns with asserted properties of the
correction:

- subject-verb agreement — *"i has send"*
- present perfect with past time word — *"have sent ... yesterday"*
- missing articles — *"come to office"*
- shorthand expansion — *"pls"*, *"thx"*
- already-correct input — must return empty `notes` and leave `fix` unchanged
- banned-word check — no output contains any banned string

Assertions target properties (shorthand expanded, banned words absent, `notes`
empty for correct input) rather than exact strings, since model output varies.
`corrector.py` is tested directly; the Hammerspoon layer is verified by hand.
