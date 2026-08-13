#!/bin/bash
#
# saaf installer. Safe to run more than once - every step checks before acting.
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
LOADER="dofile(\"$PROJECT/init.lua\")  -- saaf"
PLIST="com.saaf.preload.plist"
MODEL="${SAAF_MODEL:-qwen3:4b}"

step()  { printf "\n${BOLD}%s${RESET}\n" "$1"; }
ok()    { printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
skip()  { printf "  ${DIM}·${RESET} ${DIM}%s${RESET}\n" "$1"; }
warn()  { printf "  ${YELLOW}!${RESET} %s\n" "$1"; }
fail()  { printf "  ${RED}✗${RESET} %s\n" "$1"; exit 1; }

# ---------------------------------------------------------------- uninstall ----
if [ "${1:-}" = "--uninstall" ]; then
  step "Removing saaf"
  launchctl unload -w "$HOME/Library/LaunchAgents/$PLIST" 2>/dev/null && ok "launch agent unloaded" || skip "launch agent was not loaded"
  rm -f "$HOME/Library/LaunchAgents/$PLIST" && ok "launch agent removed"

  if [ -L "$HS_INIT" ] && [ "$(readlink "$HS_INIT")" = "$PROJECT/init.lua" ]; then
    rm -f "$HS_INIT"; ok "removed the symlink at $HS_INIT"
  elif [ -f "$HS_INIT" ] && grep -qF -- "-- saaf" "$HS_INIT"; then
    # Strip only our line; whatever else is in their config is theirs.
    tmp="$(mktemp)"; grep -vF -- "-- saaf" "$HS_INIT" > "$tmp" && mv "$tmp" "$HS_INIT"
    ok "removed the saaf line from your Hammerspoon config"
  else
    skip "nothing of ours in $HS_INIT"
  fi

  printf "\n  Ollama, Hammerspoon, the %s model and your ~/.saaf/ history were left alone.\n" "$MODEL"
  printf "  Remove them yourself if you want: ${DIM}brew uninstall ollama; brew uninstall --cask hammerspoon; ollama rm %s; rm -rf ~/.saaf${RESET}\n\n" "$MODEL"
  exit 0
fi

# ------------------------------------------------------------------- checks ----
step "Checking this Mac"
[ "$(uname -s)" = "Darwin" ] || fail "saaf is macOS only (Hammerspoon and the hotkey layer are Mac-specific)."
ok "macOS $(sw_vers -productVersion) on $(uname -m)"
[ -x /usr/bin/python3 ] || fail "/usr/bin/python3 is missing. Install Xcode command line tools: xcode-select --install"
ok "python3 present (no packages needed - saaf uses only the standard library)"

if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew is not installed. It is the least painful way to get the next two."
  printf "     Install it from ${BOLD}https://brew.sh${RESET} then re-run this script.\n"
  exit 1
fi
ok "Homebrew present"

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
step "Wiring saaf into Hammerspoon"
mkdir -p "$HS_DIR"

if [ -L "$HS_INIT" ] && [ "$(readlink "$HS_INIT")" = "$PROJECT/init.lua" ]; then
  skip "already symlinked to this project"
elif [ -f "$HS_INIT" ] && grep -qF "$PROJECT/init.lua" "$HS_INIT"; then
  skip "your config already loads saaf"
elif [ ! -e "$HS_INIT" ]; then
  # No existing config: a loader line, not a symlink. Leaves the file yours, so
  # anything you add later survives, and saaf can be removed with one line.
  printf '%s\n' "$LOADER" > "$HS_INIT"
  ok "created $HS_INIT that loads saaf"
else
  # THE IMPORTANT CASE. An earlier version of these instructions used
  # `ln -sfn ... ~/.hammerspoon/init.lua`, where -f means force: it silently
  # destroyed whatever Hammerspoon config was already there. Never overwrite.
  backup="$HS_INIT.before-saaf-$(date +%Y%m%d-%H%M%S)"
  cp "$HS_INIT" "$backup"
  printf '\n%s\n' "$LOADER" >> "$HS_INIT"
  ok "appended saaf to your existing config"
  ok "backed the original up to $(basename "$backup")"
  warn "if your config already binds Option+P, one of the two will win - change HOTKEY_KEY in init.lua"
fi

# --------------------------------------------------------------- keep it warm --
step "Keeping the model warm (avoids a 30s wait on first use)"
cp "$PROJECT/$PLIST" "$HOME/Library/LaunchAgents/"
launchctl unload -w "$HOME/Library/LaunchAgents/$PLIST" 2>/dev/null || true
launchctl load -w "$HOME/Library/LaunchAgents/$PLIST" && ok "warm-up job installed (re-warms every 7 hours)"

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
printf "  macOS will not let any program grant itself Accessibility permission, and saaf\n"
printf "  needs it to press ${BOLD}⌘C${RESET} and ${BOLD}⌘V${RESET} for you. Opening the right pane now:\n\n"
printf "     ${BOLD}Tick Hammerspoon${RESET} in the list, then come back.\n"
sleep 2
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || \
  printf "     (open System Settings → Privacy & Security → Accessibility by hand)\n"

cat <<EOF

${BOLD}Done.${RESET}

  Look for a ${BOLD}◆${RESET} in your menu bar - that is saaf, and everything is set from there.
  If it is missing, quit and reopen Hammerspoon.

  ${BOLD}Try it:${RESET} type a bad sentence anywhere, select it, press ${BOLD}⌥ Option + P${RESET}.

  Guide:      open "$PROJECT/docs/how-to-use-saaf.pdf"
  Uninstall:  $PROJECT/install.sh --uninstall

EOF
