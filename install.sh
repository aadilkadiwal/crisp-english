#!/bin/bash
#
# crisp-english installer. Safe to run more than once - every step checks before acting.
#
#   ./install.sh              install, or repair an existing install
#   ./install.sh --uninstall  undo everything this script did
#
# What it deliberately does NOT do: grant Accessibility permission. macOS forbids
# any program from granting that to itself, and that is a security boundary rather
# than an oversight. The script opens the right settings pane and waits for you.

set -euo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
RED=$'\033[31m'; RESET=$'\033[0m'

# Resolve our own directory, so the project can live anywhere.
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
HS_DIR="$HOME/.hammerspoon"
HS_INIT="$HS_DIR/init.lua"
LOADER="dofile(\"$PROJECT/init.lua\")  -- crisp-english"
PLIST="com.crisp-english.preload.plist"

# Which model to download. Read from crisp-english.conf, the one file every part of
# crisp-english takes its settings from, with the environment still able to override it
# for a one-off install. Same precedence as corrector.py, config.lua, crisp-englishctl
# and the launch agent.
conf_value() {
  local key="$1" default="$2" file value
  for file in "$HOME/.crisp-english/crisp-english.conf" "$PROJECT/crisp-english.conf"; do
    [ -f "$file" ] || continue
    value=$(sed -n "s/^${key}=//p" "$file" | sed 's/[[:space:]]*#.*$//; s/^"//; s/"$//' | tail -1)
    [ -n "$value" ] && { printf '%s' "$value"; return; }
  done
  printf '%s' "$default"
}
MODEL="${CRISP_ENGLISH_MODEL:-$(conf_value CRISP_ENGLISH_MODEL qwen3:4b)}"

# Every name this project has had, newest first. `polish` -> `saaf` (2026-09-03)
# -> `crisp` (2026-09-03) -> `crisp-english` (2026-09-04).
#
# A list rather than one OLD_NAME, because there are now two installs to migrate
# and a machine could be sitting on either. Newest first matters: someone who
# went polish -> saaf -> crisp has state under `.crisp`, and that is the copy
# worth keeping - the older ones are leftovers a previous migration already
# superseded.
#
# Everything each old name left outside the repo is derived from the name here
# rather than written out inline, so the day these are deleted it is one array
# and not a hunt.
OLD_NAMES=("crisp" "saaf")
NEW_NAME="crisp-english"
NEW_STATE="$HOME/.crisp-english"

# Where the command goes on your PATH. A variable, and used by every block that
# touches it - the install step, the uninstall step and the rename migration.
#
# It was a literal in three places, which made the migration reach an absolute
# path nothing could redirect - so exercising the migration against a throwaway
# HOME still deleted the real /usr/local/bin symlink. Overridable, so a dry run
# can be a dry run.
BIN_DIR="${CRISP_ENGLISH_BIN_DIR:-/usr/local/bin}"

step()  { printf "\n${BOLD}%s${RESET}\n" "$1"; }
ok()    { printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
skip()  { printf "  ${DIM}·${RESET} ${DIM}%s${RESET}\n" "$1"; }
warn()  { printf "  ${YELLOW}!${RESET} %s\n" "$1"; }
fail()  { printf "  ${RED}✗${RESET} %s\n" "$1"; exit 1; }

# ---------------------------------------------------------------- uninstall ----
if [ "${1:-}" = "--uninstall" ]; then
  step "Removing crisp-english"
  launchctl unload -w "$HOME/Library/LaunchAgents/$PLIST" 2>/dev/null && ok "launch agent unloaded" || skip "launch agent was not loaded"
  rm -f "$HOME/Library/LaunchAgents/$PLIST" && ok "launch agent removed"

  # Someone uninstalling may never have run a rename migration, so every name
  # this project has had gets cleaned up, not just the current one.
  for old in "${OLD_NAMES[@]}"; do
    if [ -f "$HOME/Library/LaunchAgents/com.$old.preload.plist" ]; then
      launchctl unload -w "$HOME/Library/LaunchAgents/com.$old.preload.plist" 2>/dev/null || true
      rm -f "$HOME/Library/LaunchAgents/com.$old.preload.plist"
      ok "removed the older com.$old.preload.plist too"
    fi
    if [ -L "$BIN_DIR/${old}ctl" ]; then
      rm -f "$BIN_DIR/${old}ctl" && ok "removed the older $BIN_DIR/${old}ctl"
    fi
  done

  # Only if it is a symlink pointing at THIS checkout; never a file someone else
  # put there under the same name.
  if [ -L "$BIN_DIR/crisp-englishctl" ] \
     && [ "$(readlink "$BIN_DIR/crisp-englishctl")" = "$PROJECT/crisp-englishctl" ]; then
    rm -f "$BIN_DIR/crisp-englishctl" && ok "removed $BIN_DIR/crisp-englishctl"
  else
    skip "no crisp-englishctl of ours in $BIN_DIR"
  fi

  # The loader line, under any name the project has ever used.
  # Anchored to the end of the line, so "-- crisp" does not also match the
  # "-- crisp-english" marker it is a prefix of.
  MARKERS="crisp-english"
  for old in "${OLD_NAMES[@]}"; do MARKERS="$MARKERS|$old"; done

  if [ -L "$HS_INIT" ] && [ "$(readlink "$HS_INIT")" = "$PROJECT/init.lua" ]; then
    rm -f "$HS_INIT"; ok "removed the symlink at $HS_INIT"
  elif [ -f "$HS_INIT" ] && grep -qE -- "-- ($MARKERS)\$" "$HS_INIT"; then
    # Strip only our line, under any of our names; whatever else is in their
    # config is theirs.
    tmp="$(mktemp)"; grep -vE -- "-- ($MARKERS)\$" "$HS_INIT" > "$tmp" && mv "$tmp" "$HS_INIT"
    ok "removed the crisp-english line from your Hammerspoon config"
  else
    skip "nothing of ours in $HS_INIT"
  fi

  printf "\n  Ollama, Hammerspoon, the %s model and your ~/.crisp-english/ history were left alone.\n" "$MODEL"
  printf "  Remove them yourself if you want: ${DIM}brew uninstall ollama; brew uninstall --cask hammerspoon; ollama rm %s; rm -rf ~/.crisp-english${RESET}\n\n" "$MODEL"
  exit 0
fi

# ------------------------------------------------------------------- checks ----
step "Checking this Mac"
[ "$(uname -s)" = "Darwin" ] || fail "crisp-english is macOS only (Hammerspoon and the hotkey layer are Mac-specific)."
ok "macOS $(sw_vers -productVersion) on $(uname -m)"
[ -x /usr/bin/python3 ] || fail "/usr/bin/python3 is missing. Install Xcode command line tools: xcode-select --install"
ok "python3 present (no packages needed - crisp-english uses only the standard library)"

if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew is not installed. It is the least painful way to get the next two."
  printf "     Install it from ${BOLD}https://brew.sh${RESET} then re-run this script.\n"
  exit 1
fi
ok "Homebrew present"

# ---------------------------------------------------------------- migration ----
# Upgrading an install made under any of this project's previous names.
#
# A rename touches four things that live outside the repo, and every one of them
# fails quietly rather than loudly if it is left behind: the history file would be
# orphaned (stats silently start from zero), the old launch agent would keep
# warming the model forever with nothing to uninstall it, and a symlink into a
# directory that has been renamed is simply dangling - Hammerspoon loads no
# config and the menu bar icon never appears, with no error anywhere.
#
# Now a loop over OLD_NAMES rather than one hardcoded name, because there have
# been two renames in two days and a machine can be sitting on either. Newest
# first, and the FIRST old install found with state wins the move - somebody who
# went saaf -> crisp has their real history under ~/.crisp, and ~/.saaf is a
# leftover the earlier migration already superseded.
#
# Every branch is a no-op on a clean machine, so this costs a first-time
# installer nothing.
for old in "${OLD_NAMES[@]}"; do
  old_state="$HOME/.$old"
  old_plist="com.$old.preload.plist"
  found=""
  [ -e "$old_state" ] && found="yes"
  [ -f "$HOME/Library/LaunchAgents/$old_plist" ] && found="yes"
  [ -f "$HS_INIT" ] && grep -qE -- "-- ${old}\$" "$HS_INIT" && found="yes"
  { [ -L "$HS_INIT" ] && [ ! -e "$HS_INIT" ]; } && found="yes"
  [ -L "$BIN_DIR/${old}ctl" ] && found="yes"
  [ -n "$found" ] || continue

  step "Upgrading your existing $old install"

  # 1. The history. Moved, never merged: two logs with overlapping timestamps
  #    would make `stats` count some corrections twice, and a wrong tally is
  #    worse than an extra directory.
  if [ -d "$old_state" ] && [ ! -e "$NEW_STATE" ]; then
    mv "$old_state" "$NEW_STATE"
    ok "moved your correction history to ~/.$NEW_NAME/ ($(wc -l < "$NEW_STATE/mistakes.log" 2>/dev/null | tr -d ' ') corrections kept)"
  elif [ -d "$old_state" ] && [ -e "$NEW_STATE" ]; then
    warn "both $old_state and $NEW_STATE exist - leaving both alone"
    warn "~/.$NEW_NAME/ is the one in use; delete ~/.$old/ yourself once you have looked at it"
  else
    skip "no $old history to move"
  fi

  # 1b. The config file inside it was named after the project too.
  if [ -f "$NEW_STATE/$old.conf" ] && [ ! -f "$NEW_STATE/$NEW_NAME.conf" ]; then
    mv "$NEW_STATE/$old.conf" "$NEW_STATE/$NEW_NAME.conf"
    ok "renamed your settings file to $NEW_NAME.conf"
    # The keys inside it carry the old prefix, and nothing reads those now.
    if grep -q "^$(printf '%s' "$old" | tr 'a-z-' 'A-Z_')_" "$NEW_STATE/$NEW_NAME.conf" 2>/dev/null; then
      sed -i '' "s/^$(printf '%s' "$old" | tr 'a-z-' 'A-Z_')_/CRISP_ENGLISH_/" "$NEW_STATE/$NEW_NAME.conf"
      ok "updated the setting names inside it"
    fi
  fi

  # 2. The old launch agent. Unloaded before the new one is installed, or two
  #    jobs sit there warming the same model on two different schedules.
  if [ -f "$HOME/Library/LaunchAgents/$old_plist" ]; then
    launchctl unload -w "$HOME/Library/LaunchAgents/$old_plist" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/$old_plist"
    ok "retired the old $old_plist warm-up job"
  fi

  # 2b. The old command on PATH. Left behind it is a script pointing into a
  #     directory that may no longer exist, which fails in the least helpful way
  #     possible: command found, then a python traceback.
  if [ -L "$BIN_DIR/${old}ctl" ]; then
    rm -f "$BIN_DIR/${old}ctl"
    ok "removed the old ${old}ctl command (it is ${NEW_NAME}ctl now)"
  fi

  # 3. A symlink into the old project directory. If the directory was renamed
  #    rather than re-cloned the link is dangling, which is indistinguishable
  #    from a broken install and produces no error message at all. Only a
  #    dangling link is removed - one pointing at a real file is someone else's.
  if [ -L "$HS_INIT" ] && [ ! -e "$HS_INIT" ]; then
    rm -f "$HS_INIT"
    ok "cleared a dangling $HS_INIT (it pointed into the old $old directory)"
  fi

  # 4. A loader line in a config that is theirs. Rewritten in place, so their
  #    own Hammerspoon config keeps working and keeps its shape.
  if [ -f "$HS_INIT" ] && grep -qE -- "-- ${old}\$" "$HS_INIT"; then
    backup="$HS_INIT.before-$NEW_NAME-rename-$(date +%Y%m%d-%H%M%S)"
    cp "$HS_INIT" "$backup"
    tmp="$(mktemp)"
    while IFS= read -r line; do
      case "$line" in
        *"-- $old") printf '%s\n' "$LOADER" ;;
        *)          printf '%s\n' "$line" ;;
      esac
    done < "$HS_INIT" > "$tmp"
    mv "$tmp" "$HS_INIT"
    ok "repointed the loader line in your Hammerspoon config"
    ok "backed the original up to $(basename "$backup")"
  fi

  printf "  ${DIM}Your hotkey, audience setting and history all carry over. Only the name changed.${RESET}\n"
done

# ------------------------------------------------------------- dependencies ----
step "Installing Ollama and Hammerspoon"
if command -v ollama >/dev/null 2>&1; then skip "ollama already installed"
else brew install ollama && ok "ollama installed"; fi

if [ -d "/Applications/Hammerspoon.app" ]; then skip "Hammerspoon already installed"
else brew install --cask hammerspoon && ok "Hammerspoon installed"; fi

step "Starting Ollama"
if curl -fsS --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  skip "already running"
else
  open -a Ollama 2>/dev/null || true
  for _ in $(seq 1 15); do
    curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 \
    && ok "running" || warn "could not confirm it started; open the Ollama app yourself"
fi

step "Getting the language model ($MODEL)"
if ollama list 2>/dev/null | grep -q "^${MODEL%%:*}"; then
  skip "$MODEL already downloaded"
else
  printf "  This is about 2.5 GB and only happens once.\n"
  ollama pull "$MODEL" && ok "$MODEL downloaded"
fi

# ------------------------------------------------- hammerspoon config (safe) ---
step "Wiring crisp-english into Hammerspoon"
mkdir -p "$HS_DIR"

if [ -L "$HS_INIT" ] && [ "$(readlink "$HS_INIT")" = "$PROJECT/init.lua" ]; then
  skip "already symlinked to this project"
elif [ -f "$HS_INIT" ] && grep -qF "$PROJECT/init.lua" "$HS_INIT"; then
  skip "your config already loads crisp-english"
elif [ ! -e "$HS_INIT" ]; then
  # No existing config: a loader line, not a symlink. Leaves the file yours, so
  # anything you add later survives, and crisp-english can be removed with one line.
  printf '%s\n' "$LOADER" > "$HS_INIT"
  ok "created $HS_INIT that loads crisp-english"
elif [ -L "$HS_INIT" ]; then
  # A symlink pointing somewhere that is not this project - most often a second
  # checkout of crisp-english itself. Appending here would follow the link and write into
  # THAT project's init.lua, silently editing a different checkout's source file.
  # Move the link aside instead; whatever it points at is never touched.
  old_target="$(readlink "$HS_INIT")"
  backup="$HS_INIT.before-crisp-english-$(date +%Y%m%d-%H%M%S)"
  mv "$HS_INIT" "$backup"
  printf '%s\n' "$LOADER" > "$HS_INIT"
  ok "created $HS_INIT that loads crisp-english"
  warn "an existing symlink was moved aside; it pointed at $old_target"
  warn "restore it with: mv \"$backup\" \"$HS_INIT\""
else
  # THE IMPORTANT CASE. An earlier version of these instructions used
  # `ln -sfn ... ~/.hammerspoon/init.lua`, where -f means force: it silently
  # destroyed whatever Hammerspoon config was already there. Never overwrite.
  backup="$HS_INIT.before-crisp-english-$(date +%Y%m%d-%H%M%S)"
  cp "$HS_INIT" "$backup"
  printf '\n%s\n' "$LOADER" >> "$HS_INIT"
  ok "appended crisp-english to your existing config"
  ok "backed the original up to $(basename "$backup")"
  warn "if your config already binds Option+P, one of the two will win - change HOTKEY_KEY in init.lua"
fi

# ------------------------------------------------------------ crisp-englishctl on PATH --
# So the tool can be reached when the menu bar icon cannot be.
#
# crisp-englishctl exists because macOS hides the status icon behind the notch at will,
# and the whole point of it is that nothing important lives only in the menu bar.
# Leaving crisp-englishctl itself reachable only by full path reproduced the exact
# problem it was written to solve.
#
# /usr/local/bin because that is where Hammerspoon's own `hs` and Ollama's
# `ollama` already put themselves, and it needs no sudo on a normal Mac.
step "Putting crisp-englishctl on your PATH"
BIN_LINK="$BIN_DIR/crisp-englishctl"
if [ ! -d "$BIN_DIR" ]; then
  warn "$BIN_DIR does not exist - run crisp-englishctl as $PROJECT/crisp-englishctl"
elif [ -L "$BIN_LINK" ] && [ "$(readlink "$BIN_LINK")" = "$PROJECT/crisp-englishctl" ]; then
  skip "already linked"
elif [ -e "$BIN_LINK" ] && [ ! -L "$BIN_LINK" ]; then
  # A real file called crisp-englishctl that we did not put there. Not ours to replace.
  warn "$BIN_LINK exists and is not a symlink - left alone"
  warn "run crisp-englishctl as $PROJECT/crisp-englishctl instead"
elif [ ! -w "$BIN_DIR" ]; then
  warn "$BIN_DIR is not writable by you"
  printf "     Link it yourself: ${DIM}sudo ln -sfn \"%s/crisp-englishctl\" \"%s\"${RESET}\n" "$PROJECT" "$BIN_LINK"
else
  # -f covers a link left by an older checkout; only ever a link named crisp-englishctl.
  ln -sfn "$PROJECT/crisp-englishctl" "$BIN_LINK" && ok "crisp-englishctl → $BIN_LINK"
fi

# ------------------------------------------------------------ user dictionary --
# Words only this writer uses - names, products, repos, clients. A 4b model
# "corrects" these with great confidence, and no list shipped in a repo can know
# them. Created with comments and left empty, so it is discoverable rather than
# documented-only.
step "Setting up your word list"
mkdir -p "$NEW_STATE"
PROTECT="$NEW_STATE/protect.txt"
if [ -f "$PROTECT" ]; then
  skip "$PROTECT already exists ($(grep -cvE '^\s*(#|$)' "$PROTECT" | tr -d ' ') words)"
else
  cat > "$PROTECT" <<'WORDS'
# Words crisp-english must never "correct": names, products, repos, clients.
# One per line. Lines starting with # are ignored. Takes effect immediately.
#
# Add your own, for example:
#   Aadil
#   Pixeldust
WORDS
  ok "created $PROTECT (add names and product words to it)"
fi

# --------------------------------------------------------------- keep it warm --
step "Warming the model at login (so the first correction of the day is fast)"
# The plist reads the model and the timings out of crisp-english.conf at run time, but it
# cannot know where crisp-english was cloned to - so the path is substituted here, into
# the installed copy only. The repo's own copy keeps the placeholder.
sed "s|__CRISP_PROJECT__|$PROJECT|g" "$PROJECT/$PLIST" \
  > "$HOME/Library/LaunchAgents/$PLIST"
launchctl unload -w "$HOME/Library/LaunchAgents/$PLIST" 2>/dev/null || true
launchctl load -w "$HOME/Library/LaunchAgents/$PLIST" && ok "warm-up job installed (once at login; skipped while crisp-english is off)"
if [ -f "$PROJECT/crisp-english.conf" ]; then
  # conf_value, not a bare sed on the project file: this line was reporting the
  # repo's value even when ~/.crisp-english/crisp-english.conf overrode it, and
  # it did not strip trailing comments either.
  ok "settings from crisp-english.conf (model: $MODEL, keep-alive: $(conf_value CRISP_ENGLISH_KEEP_ALIVE 1h))"
fi

# --------------------------------------------------------------------- check ---
step "Testing the correction engine"
if out="$("$PROJECT/corrector.py" --fast "i has send the mail yesterday" 2>&1)"; then
  printf "  input:  ${DIM}i has send the mail yesterday${RESET}\n"
  printf "  output: ${GREEN}%s${RESET}\n" "$(printf '%s' "$out" | sed -n '2p' | sed 's/^  *//')"
  ok "engine works"
else
  fail "engine test failed:\n$out"
fi

# ------------------------------------------------------------- accessibility ---
step "One thing only you can do"
open -a Hammerspoon 2>/dev/null || true
printf "  macOS will not let any program grant itself Accessibility permission, and crisp-english\n"
printf "  needs it to press ${BOLD}⌘C${RESET} and ${BOLD}⌘V${RESET} for you. Opening the right pane now:\n\n"
printf "     ${BOLD}Tick Hammerspoon${RESET} in the list, then come back.\n"
sleep 2
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || \
  printf "     (open System Settings → Privacy & Security → Accessibility by hand)\n"

cat <<EOF

${BOLD}Done.${RESET}

  Look for a ${BOLD}◆${RESET} in your menu bar - that is crisp-english, and everything is set from there.
  If it is missing, quit and reopen Hammerspoon.

  ${BOLD}Try it:${RESET} type a bad sentence anywhere, select it, press ${BOLD}⌥ Option + P${RESET}.

  ${BOLD}Lost the icon?${RESET} ${BOLD}⇧⌥ Shift + Option + P${RESET} toggles crisp-english on and off,
              and ${BOLD}crisp-englishctl${RESET} works from any terminal.

  Guide:      open "$PROJECT/docs/how-to-use-crisp-english.pdf"
  Uninstall:  $PROJECT/install.sh --uninstall

EOF
