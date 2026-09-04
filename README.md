# crisp-english

Fix the English in your work messages with one keystroke. On your Mac. Nothing leaves it.

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
git clone <this-repo> crisp-english
cd crisp-english
./install.sh
```

The installer handles everything it can: installs Ollama and Hammerspoon if missing,
downloads the model (~2.5 GB, once), wires crisp-english into Hammerspoon **without overwriting an
existing config**, sets up a warm-up job, and runs a real correction to prove it works.
It is safe to re-run — every step checks before acting.

**One step cannot be automated.** macOS forbids any program from granting itself
Accessibility permission, and crisp-english needs it to press `⌘C` / `⌘V` for you. The installer
opens the right pane; tick **Hammerspoon** in the list.

Then look for **A̲** in your menu bar.

You do not need it, though — `⇧⌥P` toggles crisp-english on and off from anywhere, and
`crisp-englishctl` is on your `PATH`.

To remove: `./install.sh --uninstall`

## The menu bar

| Icon | Meaning |
|------|---------|
| `A̲` | Ready — next correction ~1.5s |
| `A` | Model asleep — next one ~30s (menu offers *Wake it now*) |
| `⋯` | Correcting right now |
| `⊘` | Switched off |
| *none* | Hammerspoon isn't running — **or macOS is hiding the icon behind the notch** |

The underline is the whole vocabulary: macOS marks a word that needs attention by
putting a line under it, and that line appearing under the `A` means crisp-english is
warm and the next correction is fast. No colour — it would be unreadable at that size
and invisible to some people.

### If the icon disappears

macOS decides where status icons sit, and on a notched Mac it will happily park this one
under the camera housing where it cannot be seen or clicked. That is not a bug you can
fix from inside the app, so crisp-english is built so you never need the icon:

```bash
⇧⌥P                 toggle crisp-english on/off, from any app
crisp-englishctl on         same thing, from any terminal
crisp-englishctl status     is it loaded, is the model warm, where is the icon
crisp-englishctl icon       try to shove the icon back out of the notch
```

`⇧⌥P` works even while crisp-english is **off** — `⌥P` deliberately does not, because a
disabled hotkey that still fired would be worse than a missing one. It shows a brief
`crisp-english on` / `crisp-english off` on screen, since when the icon is invisible that is the only
confirmation you get.

If you Command-drag the icon clear of the notch once, macOS remembers the position.

Click it for: **Turn crisp-english off**, model status, **Writing for** (below), **Show what
changed on screen** (off by default — tick it and each correction shows what it edited
and which rule you broke), today's count, your recurring mistakes, **Free the memory
now**, **Start Ollama**, start at login, and reload.

## Memory

The model is 2.9 GB, and on a 16 GB Mac that is worth caring about. crisp-english holds it only
while you are actually writing.

| When | What happens |
|---|---|
| You turn crisp-english **on** | Ollama is started if it isn't running, and the model loaded |
| You turn crisp-english **off** | The model is released. Ollama is quit **only if crisp-english started it** |
| Your Mac sleeps | The model is released. Ollama is left alone |
| An hour with no corrections | Ollama releases the model itself (`keep_alive`) |

The rule about quitting is the important one: if Ollama was already running when you
turned crisp-english on — because you use it for something else — crisp-english will never quit it. It
only ever puts back what it took.

Turning crisp-english on and off never depends on Ollama. If Ollama is missing or refuses to
start, crisp-english still turns on; the hotkey stays live and tells you the engine is down.

**What it costs.** Reloading a released model takes about **1.3s**, because macOS keeps
the weights in its file cache — measured on an M4. The 15–50s cold load people warn about
only happens when that cache is gone, essentially after a reboot. Releasing 2.9 GB of
resident memory in exchange for a second is a good trade, which is why this is the
default rather than a setting.

`crisp-englishctl unload` does the same thing by hand, without turning crisp-english off.

## Writing for

Every correction is written for one of two readers — there is no neutral option, so
the choice always gets made. 52 words in:

| Audience | Out | Result |
|---|---|---|
| Client or senior | 37 w | Hi sir, I just wanted to check in about the deployment we discussed yesterday. I completed the changes and pushed it to staging… — no contractions |
| Slack / WhatsApp | **18 w** | Hi sir, I've completed the deployment changes and pushed to staging. Please review when you get a chance. |

**The app you are typing in picks for you.** Slack, WhatsApp, Teams, Messages,
Discord and Telegram get *Slack / WhatsApp*; Mail, Outlook, Spark and Superhuman get
*Client or senior*. Anywhere else — including a browser, where Gmail and a client's
admin panel are both just "Google Chrome" — the menu choice decides. So a Slack reply
is never sent in client English because you set the menu last Tuesday and forgot.

Set `CRISP_ENGLISH_AUTO_TONE=0` in `crisp-english.conf` to always use the menu choice. `crisp-englishctl
status` shows which audience the *next* correction would use, and for which app.

Slack mode takes about a second longer: it uses a slower pass that shortens reliably
(16–18 words every time) instead of a fast one that gave 50, 28, 50 on the same input.

## Terminal

```bash
crisp-englishctl status                                   # everything, at a glance
crisp-englishctl on | off                                 # also starts / releases Ollama
crisp-englishctl unload                                   # free the model's RAM, stay on
crisp-englishctl tone client | slack                      # the fallback audience
crisp-englishctl fix "i has send the mail"                # correct a sentence right here
crisp-englishctl last                                     # what the last correction changed
crisp-englishctl again slack                              # redo that one for the other reader
crisp-englishctl stats                                    # last 30 days vs before
crisp-englishctl forget                                   # delete the history

./corrector.py "i am having 4 years experience"   # three phrasings
./corrector.py --fast "..."                       # the one the hotkey uses
./corrector.py --formal "..."                     # for a client or someone senior
./corrector.py --brief "..."                      # for Slack, fewest words
```

`last` and `again` exist because corrections land silently: you never see what was
replaced, and `⌘Z` is not reliable in every Electron app. `again` re-runs the **same
text** for the other audience, so an email that came back too terse is one command
from formal without retyping it.

## Settings

One file, `crisp-english.conf`, read by all four languages crisp-english is written in — Python, Lua,
shell and launchd. Override any of it per-machine without touching the repo:

```bash
mkdir -p ~/.crisp-english && echo 'CRISP_ENGLISH_MODEL=qwen3:8b' >> ~/.crisp-english/crisp-english.conf
crisp-englishctl reload
```

| Setting | Default | What it does |
|---|---|---|
| `CRISP_ENGLISH_MODEL` | `qwen3:4b` | Which model. Also what the login warm-up loads. |
| `CRISP_ENGLISH_KEEP_ALIVE` | `1h` | How long Ollama holds the model after you stop writing. |
| `CRISP_ENGLISH_NUM_CTX` | `2048` | Context size. The input cap is derived from it. |
| `CRISP_ENGLISH_AUTO_TONE` | `1` | Let the app pick the audience. |
| `CRISP_ENGLISH_LOG_TEXT` | `1` | Keep message text in the log. `0` keeps rule names only. |
| `CRISP_ENGLISH_LOG_MAX` | `2000` | Corrections kept before the oldest are dropped. |

Precedence: environment variable → `~/.crisp-english/crisp-english.conf` → `crisp-english.conf` → built-in.

### Words crisp-english must not touch

`~/.crisp-english/protect.txt`, one word or phrase per line. Names, products, repos, clients —
the things a 4B model "corrects" with the most confidence. The installer creates it
empty with instructions inside.

## Your history

`~/.crisp-english/mistakes.log` is a plain text file on your machine and nowhere else. It is
also the one place your messages accumulate, so:

- `crisp-englishctl stats` shows the **last 30 days against everything before**, because a
  total cannot show improvement — a rule you fixed in June still tops an all-time
  chart.
- It is capped at `CRISP_ENGLISH_LOG_MAX` entries; the oldest fall off.
- `CRISP_ENGLISH_LOG_TEXT=0` keeps the rule names and drops the text. `stats` still works;
  `last` and `again` stop, and say so rather than showing you an older message.
- `crisp-englishctl forget` deletes the lot.

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
pay. Rather than guess and send a colleague the wrong instruction, crisp-english flags it and
leaves the sentence to you.

It pastes rather than retypes, so `⌘Z` undoes a correction like any other paste. Your
clipboard is borrowed for about half a second and handed straight back.

## Files

| File | Job |
|------|-----|
| `corrector.py` | Correction logic and CLI. Knows nothing about hotkeys. |
| `blocklist.py` | Deterministic substitutions, retries and warnings. |
| `crisp-english.conf` | Every setting, read by Python, Lua, shell and launchd alike. |
| `init.lua` | Hammerspoon: hotkey, clipboard, paste, on/off. |
| `menubar.lua` | Status icon and controls. |
| `ollama.lua` | Start, warm, release and quit Ollama. Knows nothing about menus. |
| `config.lua` | Reads `crisp-english.conf` for the Lua side. |
| `audience.lua` | Which reader an app implies. |
| `state.lua` | The settings that survive a reload. |
| `crisp-englishctl` | Everything the menu does, from a terminal. |
| `install.sh` | Installer / uninstaller. |
| `voice.md` | How corrected text should sound, and the banned list `blocklist.py` implements. |
| `docs/how-to-use-crisp-english.html` | Full guide, written for someone new to all of this. Open it in a browser. |

## Requirements

macOS · [Homebrew](https://brew.sh) · ~3 GB disk · Apple Silicon recommended
(built and measured on an M4 with 16 GB).
