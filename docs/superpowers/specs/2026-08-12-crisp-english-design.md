# crisp-english — local grammar and rephrasing helper

**Date:** 2026-08-12
**Status:** Implemented. Amended 2026-08-13 and three times on 2026-09-04 — see Revisions below.

## Revision — 2026-09-04 (tests removed)

`tests/` was deleted on request: the unit suites, the Lua suite, the CLI and
migration suites, the runner, and `bench.py`/`cases.py` with them. **Every
reference to a test below this line is history, not a description of the repo.**
There is no `./tests/run.sh`, no `python3 tests/bench.py`, and nothing checks
`voice.md` against `blocklist.py`.

What the code keeps is the *reasons*. Each rule and guard still carries the case
that produced it, because those cases are the argument for the code existing -
"the model returned 'tanks' in 5 runs of 6", "$45,000 in 8 runs out of 8",
"gemma3:4b resident and qwen3:4b not". The seams the tests used are also still
there and still useful: `ollama.findModel()` is a pure function either way,
`blocklist.protected_words(path)` takes a path, `corrector.setting(files=)` takes
an override, and `CRISP_ENGLISH_BIN_DIR` keeps the installer's migration out of
`/usr/local/bin` when you want to try it.

Two things are now unguarded that were specifically worth guarding, so they are
worth knowing about:

- **A syntax error in any `.lua` file takes the ipc port with it.** The file
  never compiles, so `require("hs.ipc")` never runs, and the only symptom is the
  `hs` command reporting a dead message port - indistinguishable from
  Hammerspoon not running. It happened once already, from a rename. Hammerspoon's
  own console names the file and the line; `crisp-englishctl` now points there.
- **`install.sh`'s rename migration moves your history and edits your
  Hammerspoon config, and runs once.** It is a loop over `OLD_NAMES` and every
  branch is a no-op on a clean machine, but nothing exercises it any more.

## Revision — 2026-09-04 (renamed to `crisp-english`)

Renamed from `crisp`, one day after `saaf` -> `crisp`. The argument for the
qualifier is discoverability: `crisp` is a crowded word and there is a well-known
company using it, which matters for a public release. The argument against was
that every surface gets longer - `crisp-englishctl`, `~/.crisp-english/`,
`CRISP_ENGLISH_MODEL`, `com.crisp-english.preload` - and that a repo-only rename
would have bought the same discoverability for nothing. The full rename was
chosen deliberately with that trade understood.

Two things were deliberately NOT renamed:

- **The menu bar `autosaveName`** stays `"crisp"` (menubar.lua). It is the key
  macOS files the icon's saved position under, and the position is the only
  durable fix for the notch problem. Renaming it silently discards a position the
  user set by hand, on every existing install.
- **`CrispError`** and the module filenames (`corrector.py`, `blocklist.py`,
  `config.lua`, ...) - internal identifiers with no external contract. Renaming
  them is churn without a reader.

**What the rename broke, and what it cost to find.** A bare-word replacement of
`crisp` -> `crisp-english` turned `local function crisp()` in init.lua into
`local function crisp-english()`. Lua reads the hyphen as subtraction, so the
file no longer compiled - which meant `require("hs.ipc")` on line 32 never ran,
and the only visible symptom was the `hs` command reporting a dead message port.
That is indistinguishable from Hammerspoon not running, and
`crisp-englishctl`'s own diagnostic for it said "usually transient". Three fixes
came out of it:

1. The function is now `correctSelection()` - named for what it does, so it
   cannot be caught by the next rename.
2. `tests/test_lua.lua` compiles every `.lua` file in the project as its first
   assertion, running inside the already-loaded instance. It tells you the edit
   will not compile while you still have a working ipc port to hear it through.
3. The "not answering" message now says that a config that does not compile
   looks exactly like this, and how to check without ipc.

Also from verifying the rename: `crisp-englishctl status` treated an empty ipc
reply as "no icon", so a dropped call was reported as a missing menu bar item -
a false alarm from the one command that exists because the icon cannot be
trusted. It now distinguishes "could not read" from "no icon". And
`install.sh`'s migration is a loop over `OLD_NAMES` rather than one hardcoded
name, with `tests/test_migration.sh` covering it against a fake HOME: history
moved, settings file renamed and its keys re-prefixed, the user's own
Hammerspoon lines untouched, the older of two installs left on disk, a clean
machine untouched, and the whole thing idempotent. That last one caught a real
bug - `grep -F "-- crisp"` matches the `-- crisp-english` marker it is a prefix
of, so re-running the installer made a fresh backup of the Hammerspoon config
every time, from a script documented as safe to re-run.

## Revision — 2026-09-04 (loose ends)

Everything flagged in the code review and left open is now closed.

- **The cold-model warning asked the wrong question.** `warnIfCold` in init.lua
  checked `#parsed.models == 0` - "is anything resident" - rather than whether
  crisp-english's own model was. Proved against a live Ollama with gemma3:4b
  loaded and qwen3:4b not: it stayed silent through a load the user then waited
  30s for. The decision is now `ollama.findModel()`, pure and tested (including
  that exact case), and `warnIfCold` is three lines that call `ollama.loaded`.
  This was the third place the same mistake appeared - `crisp-englishctl status`
  had it too.
- **`crisp-englishctl` reported dropped ipc calls as definite faults**, twice: an
  empty geometry reply became "no icon" while the item sat at x=779 showing a
  diamond, and an empty type reply became a red "Config not loaded" while
  `hs -c` returned `table` on three consecutive tries. Both now distinguish
  "could not read" from "broken". `cmd_reload` had the same flaw and reported
  "Still not loaded" for a reload that had worked; it now confirms against the
  load.log timestamp, which is written last on a successful load and cannot be
  dropped - the same reasoning `wait_flag` already used for the toggle.
- **`status` no longer loses its whole detail block to one dropped call.** The
  settings are persisted to `~/.crisp-english/state`, so the hotkey state, the
  audience and the on-screen setting are read from a file. Only "is the config
  loaded" and "where is the icon" still need ipc, and each says so on its own
  line. That matters most in exactly the situation this command exists for.
- **The shipped user guide told people to run a command that does not exist.**
  `install.sh` points at `docs/how-to-use-crisp-english.pdf`, whose content still
  said `crispctl status`, `crispctl on`, `crispctl icon`. Content updated and the
  PDF regenerated from the HTML. It also still claimed the model is kept "warm
  through the working day", which was the 8h keep-alive behaviour removed on
  2026-08-13; corrected to the 1h self-release.
- Small ones: the duplicated whitespace-tidy pair is now `_tidy_spacing()`, the
  `\d+ (days|weeks|months|years) ago` branch of `PAST_MARKER` is gone (`\bago\b`
  in the same alternation already matched every string it did), `install.sh`
  reports the *effective* keep-alive rather than the repo's, `M.timer` says why
  it is assigned and never read, and `run_lua_tests.sh` prints its summary once.

Still open, deliberately: the guide covers none of the newer features
(`crisp-english.conf`, `~/.crisp-english/protect.txt`, `last`/`again`/`forget`,
the automatic audience). Nothing in it is now *wrong*, but it is incomplete.

## Revision — 2026-09-04 (code review)

A code review of the whole project. Ten defects were confirmed by running the code:
five found by reading, three more by the tests written to check those five, and two
by inspecting the JSON contract between `corrector.py` and `init.lua`. Everything
here is covered by `./tests/run.sh` — 208 assertions, of which 127 need neither
Ollama nor Hammerspoon.

### The defects

1. **`crisp-englishctl fix` and `crisp-englishctl stats` were broken through the PATH symlink.**
   `$(dirname "$0")` resolves the *invocation* path, so through the
   `/usr/local/bin/crisp-englishctl` link that `install.sh` creates it looked for
   `corrector.py` in `/usr/local/bin`. The two commands needing nothing but Python
   were the two that only worked by full path — in the script written specifically
   to be reachable when the menu bar is not.
2. **Substitution order was load-bearing and wrong.** `SUBSTITUTIONS` was one dict
   in which `kindly`→`please` and the `please please` collapse both ran before
   `pls` expanded: `"kindly pls check the mail"` → `"Please please check the mail"`.
   It also made `clean()` non-idempotent. Now three ordered phases — shorthand,
   filler, dedupe — which is what the group numbering in the comments always
   described but the code never enforced.
3. **A past time word governed the whole message.** `"I sent the report yesterday.
   I have completed the review."` lost its `have`: correct present perfect in a
   different sentence, rewritten because `yesterday` appeared somewhere in the
   text. Now applied one sentence at a time.
4. **`restore_mangled_words` ate real words.** Edit-distance-1 against a protected
   greeting is not evidence of a typo: `his`→`hi`, `they`→`hey`, `pleased`→`please`
   were all measured. Two preconditions added — the protected word must actually
   have gone *missing* from the output, and a target plus one trailing letter is an
   inflection, not a mistake.
5. **Read timeouts arrived as tracebacks.** `/usr/bin/python3` (which `init.lua`
   hardcodes) is 3.9, where `socket.timeout` is neither `TimeoutError` nor
   `URLError` — so both handlers missed it and the carefully worded cold-load
   message was unreachable. The user saw a Python stack trace in a "crisp-english failed"
   notification at the exact moment the tool needed to explain itself.
6. **`strip_invented_currency` deleted a currency the writer *had* written**, if
   they wrote it singular: `"i paid 5 dollar"` → `"I paid 5"`. Exact-string
   membership; now stemmed, so `dollar`/`dollars` and `Rs`/`Rs.` are one word.
7. **`i.e.` became `I. E.`** — the pronoun rule and the sentence-capitaliser both
   fired inside abbreviations. `e.g.` and `etc.` too. Abbreviations are now lifted
   out for the duration of `clean()` and restored verbatim.
8. **`crisp-englishctl` hardcoded `qwen3:4b`** while everything else honoured
   `CRISP_ENGLISH_MODEL`, so with a different model `crisp-englishctl warm` warmed the wrong one
   and `crisp-englishctl unload` freed nothing. `crisp-englishctl status` also reported whichever
   model was resident *first*, so it could say "warm" while something else
   entirely was loaded and crisp-english still faced a cold start.
9. **The alert described the wrong text.** `summarize()` in `init.lua` reads
   `changes.natural`, but for the brief tone the pasted text is the `short`
   variant and `natural` is byte-identical to `fix` — so its diff is empty and a
   Slack correction with alerts on explained nothing. `corrector.py` now also
   sends `changes.best`, diffed against what the user actually wrote, and
   `summarize` is exposed as `crispEnglishState.summarize` so it can be tested at all.
10. **`last` reached past the corrections it had not recorded.** With
    `CRISP_ENGLISH_LOG_TEXT=0` it walked back to an older entry that still had text and
    presented it as "the last correction" — a wrong answer, and message text
    shown to someone who had just asked for message text not to be kept.

### The design changes

11. **Group 5 is now enforced in the mode that ships.** The `REJECTIONS` retry —
    the only mechanism removing `leverage`, `additionally`, `delve` — sat below
    the early return in `correct()`, so it existed only in the three-variant CLI
    path. Every correction anyone actually makes went without it.
12. **`crisp-english.conf`: one file, four languages.** Three separate comments in this
    project opened with "THIS NUMBER EXISTS IN FOUR PLACES and they have to agree",
    each listing the other three by hand. Python, Lua, shell and launchd cannot
    share a constant, but they can all parse `KEY=value`, and now do —
    `corrector.py`, `config.lua`, `crisp-englishctl` and the plist (whose project path
    `install.sh` substitutes at install time).
13. **The input cap is derived, not round.** 4000 characters against `num_ctx=2048`
    does not fit: full prompt ~800 tokens + ~1100 + `num_predict` 500. Ollama drops
    from the *start* of the context on overflow, and the start is the system
    prompt — so the failure was not an error but a correction made with half its
    instructions missing. `max_chars()` now computes the budget from `num_ctx`.
14. **Tone and `showAlerts` survive a reload.** `enabled` was persisted with care;
    the other two were fields in a table literal, so `crisp-englishctl tone slack`
    followed by `crisp-englishctl reload` silently reverted to "Client or senior".
    `state.lua` persists all three, and `setTone`/`setAlerts` mean the menu and
    the terminal cannot diverge.
15. **The clipboard restore no longer races the paste.** 0.15s to restore against
    `COPY_WAIT` of 0.25s gave Slack *less* time to read the correction than to
    produce the selection. Losing that race pastes the previous clipboard contents
    into a colleague's DM. Now 0.6s, named and explained.
16. **`tests/bench.py` had a second copy of the prompt, already drifted** — it
    banned "That said", three-item lists and "I hope this finds you well", none of
    which are in the shipped prompt. So `CRISP_ENGLISH_RAW`, whose job is scoring the bare
    model against the real prompt, scored a prompt that existed nowhere else. It
    now imports `corrector.SYSTEM`.
17. **`voice.md` claimed to be read into the system prompt.** Nothing loaded it, so
    it was free to drift from the rules it described — and had: `That said` was
    named there and enforced nowhere. It is now explicitly the specification, and
    its "Enforced mechanically" list is parsed by `tests/test_voice.py` and checked
    against `blocklist.py`. A phrase added to the document fails the suite until a
    rule backs it up.

### Dead code removed

24. Six things nothing called: `docs/superpowers/specs/benchmark-2026-08-12.py`
    (54 lines, superseded by `tests/bench.py`, still returning a `polished` field
    this document argues against by name), `config.lua`'s `M.PROJECT` export and
    `M.reload()` — whose premise was wrong, since `hs.reload()` re-requires the
    module and rebuilds the cache anyway — `state.lua`'s `M.path()`,
    `blocklist.py`'s `passes()`, and a Lua assertion that `os.date()` had not
    returned nil, which it cannot. Four of the six were speculative API added
    earlier the same day: a module looking like it ought to have a function is
    not a reason for the function to exist.

### What was added

18. **Unit tests, which the project had none of.** `blocklist.py` is the layer
    justified by "the model ignores prompt bans a third of the time, so rules do
    the enforcing" — and its only coverage was `bench.py`, which needs Ollama,
    takes minutes, and asks a stochastic model to prove a regex works. Six of the
    ten defects above are pure-function bugs in that file. The Lua layer, which
    this document previously listed as untested, now has 62 assertions running
    inside a live Hammerspoon; `crisp-englishctl` has 19, driven as a black box through a
    symlink.
19. **The app picks the audience.** `menubar.lua` carried a comment worrying that
    "leaving it on Client or senior and forgetting is the obvious way to be
    surprised by an output", and answered it with a tooltip. The frontmost
    application is known when the hotkey fires and answers it better. Browsers are
    deliberately excluded: Gmail and a client's admin panel are both "Google
    Chrome" from the outside.
20. **`crisp-englishctl last` and `crisp-englishctl again`.** Corrections land silently, so what
    was replaced was never visible, and `⌘Z` is unreliable in Electron apps.
    `again` re-runs the same text for the other audience — the actual recovery
    from a client email that came back too terse.
21. **`~/.crisp-english/protect.txt`.** Names, products, repos and clients: exactly what a
    4B model corrects most confidently, and what no list shipped in a repo can
    know. Reuses the `restore_mangled_words` machinery.
22. **`stats` shows a trend.** A total cannot show improvement — a rule broken
    thirty times in June and never since still tops an all-time chart, so the
    feature built to show what you get wrong showed what you *used* to get wrong.
    Two columns, last 30 days against everything before, and rules you have
    stopped breaking are marked.
23. **The log is bounded and optional.** It had no ceiling and held 300 characters
    of every message forever, which sits awkwardly beside "nothing leaves this
    Mac" — that file is the one place messages accumulate. Now capped at
    `CRISP_ENGLISH_LOG_MAX`, with `CRISP_ENGLISH_LOG_TEXT=0` to keep rule names only and
    `crisp-englishctl forget` to delete it.

## Revision — 2026-08-13

The project was called `polish` until this date. Renamed to **saaf** (Hindi/Urdu for
*clean*) because the old name argued against the design: this document itself
explains that `natural` is deliberately not called `polished` since "polished is
the failure mode". A tool about English also should not share a name with a
language. The rename covered the CLI, the log directory, the launchd label, and
the project directory.

**Renamed again to `crisp-english` on 2026-09-03**, ahead of a public release. `saaf` was
opaque to anyone who does not read Hindi or Urdu — unpronounceable on sight, and
silent about what the tool does. `crisp-english` describes the output instead of the
mechanism, which is what the tool is actually for: 52 words in, 18 out. It also
drops an unintended implication — *clean* frames the writing as dirty, *crisp-english*
frames it as sharpened. Same coverage as before: CLI (`crisp-englishctl`), log directory
(`~/.crisp-english/`), launchd label (`com.crisp-english.preload`), the Lua globals (`crispEnglishState`,
`crispEnglishCorrect`), the env vars (`CRISP_ENGLISH_DIR`, `CRISP_ENGLISH_MODEL`, `CRISP_ENGLISH_RAW`), and the
project directory. `install.sh` migrates an existing `saaf` install in place.

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
   corrections per run into `~/.crisp-english/mistakes.log`, burying real usage under test
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
- Also the CLI entry point, exposed on `PATH` as `crisp-english` via a thin shell wrapper
  in `bin/crisp-english`:
  - `crisp-english "my text"` — prints all variants. This is the test surface.
  - `crisp-english stats` — prints recurring mistakes from the log (see below).

  Both subcommands live in `corrector.py`; `bin/crisp-english` only execs it.

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

   This is the one place where crisp-english teaches rather than corrects, and it is the
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

### 3. `com.crisp-english.preload.plist` — login preloader

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

Each run appends its `notes` to `~/.crisp-english/mistakes.log` as one JSON object per
line. `crisp-english stats` reads the log and prints the most frequent recurring mistakes.

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
