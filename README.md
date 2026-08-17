# saaf

Fix the English in your work messages with one keystroke. On your Mac. Nothing leaves it.

*saaf (साफ़) — Hindi/Urdu for **clean**.*

```
hi sir, i has send the mail yesterday and i am having fever so i will work from home
                                    ↓  ⌥P
Hi sir, I sent the email yesterday and I have a fever so I'll work from home.
```

Select text anywhere — Slack, Mail, WhatsApp Web, Notes — press `⌥P`, and the corrected
sentence replaces it. About a second and a half. No account, no API key, no network
request beyond `localhost`: the language model runs on your own machine.

---

## Install

```bash
git clone <this-repo> saaf
cd saaf
./install.sh
```

The installer handles everything it can: installs Ollama and Hammerspoon if missing,
downloads the model (~2.5 GB, once), wires saaf into Hammerspoon **without overwriting an
existing config**, sets up a warm-up job, and runs a real correction to prove it works.
It is safe to re-run — every step checks before acting.

**One step cannot be automated.** macOS forbids any program from granting itself
Accessibility permission, and saaf needs it to press `⌘C` / `⌘V` for you. The installer
opens the right pane; tick **Hammerspoon** in the list.

Then look for **◆** in your menu bar.

To remove: `./install.sh --uninstall`

## The menu bar

| Icon | Meaning |
|------|---------|
| `◆` | Ready — next correction ~1.5s |
| `◇` | Model asleep — next one ~30s (menu offers *Wake it now*) |
| `◈` | Correcting right now |
| `○` | Switched off |
| *none* | Hammerspoon isn't running |

Click it for: **Turn saaf off**, model status, **Writing for** (below), **Show what
changed on screen** (off by default — tick it and each correction shows what it edited
and which rule you broke), today's count, your recurring mistakes, **Start Ollama**,
start at login, and reload.

## Writing for

Every correction is written for one of two readers — there is no neutral option, so
the choice always gets made. Pick from the menu, or use a flag. 52 words in:

| Audience | Out | Result |
|---|---|---|
| Client or senior *(default)* | 37 w | Hi sir, I just wanted to check in about the deployment we discussed yesterday. I completed the changes and pushed it to staging… — no contractions |
| Slack / WhatsApp | **18 w** | Hi sir, I've completed the deployment changes and pushed to staging. Please review when you get a chance. |

*Client* is the default because it is the safer one to hit by accident: an over-formal
Slack message is awkward, an 18-word client email can be too blunt.

Slack mode takes about a second longer: it uses a slower pass that shortens reliably
(16–18 words every time) instead of a fast one that gave 50, 28, 50 on the same input.

## Terminal

```bash
./corrector.py "i am having 4 years experience"   # three phrasings
./corrector.py --fast "..."                       # the one the hotkey uses
./corrector.py --formal "..."                     # for a client or someone senior
./corrector.py --brief "..."                      # for Slack, fewest words
./corrector.py stats                              # your recurring mistakes
```

`stats` reads `~/.saaf/mistakes.log`, which is a plain text file on your machine and
nowhere else. Delete it whenever you like.

## How it works

```
your selection ──⌘C──▶ Hammerspoon ──▶ corrector.py ──▶ Ollama (qwen3:4b)
       ▲                                                        │
       └────────────────── ⌘V ◀───── corrected sentence ◀───────┘
```

Two layers, deliberately. The **model** handles grammar, which needs judgement. A **fixed
rule list** (`blocklist.py`) handles office filler that doesn't — `kindly` → `please`,
`revert back` → `reply`, `asap` → `as soon as possible`. Benchmarking showed the model
ignores those instructions about a third of the time even when told explicitly; rules
can't forget. That split is why a small, fast model is enough.

One thing is never auto-fixed: **"do the needful"** could mean review, approve, deploy or
pay. Rather than guess and send a colleague the wrong instruction, saaf flags it and
leaves the sentence to you.

It pastes rather than retypes, so `⌘Z` undoes a correction like any other paste. Your
clipboard is borrowed for ~250 ms and handed straight back.

## Files

| File | Job |
|------|-----|
| `corrector.py` | Correction logic and CLI. Knows nothing about hotkeys. |
| `blocklist.py` | Deterministic substitutions, retries and warnings. |
| `init.lua` | Hammerspoon: hotkey, clipboard, paste. |
| `menubar.lua` | Status icon and controls. |
| `install.sh` | Installer / uninstaller. |
| `voice.md` | How corrected text should sound. |
| `tests/bench.py` | Scores a model against `tests/cases.py`, both prompt modes. |
| `docs/how-to-use-saaf.pdf` | Full guide, written for someone new to all of this. |

## Testing

```bash
python3 tests/bench.py qwen3:4b            # both modes
python3 tests/bench.py --fast-only qwen3:4b
```

Current: **16/16 both modes** — `fast` (what the hotkey uses) at ~1.2 s, `variants` at
~2.2 s. The suite logs to `/tmp`, never to your real `~/.saaf/mistakes.log`.

## Requirements

macOS · [Homebrew](https://brew.sh) · ~3 GB disk · Apple Silicon recommended
(built and measured on an M4 with 16 GB).
