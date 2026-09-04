-- crisp-english - correct the selected text with one keystroke.
--
-- Install: symlink or copy this into ~/.hammerspoon/init.lua, then reload
-- Hammerspoon. Grant Accessibility permission when macOS asks, otherwise the
-- copy/paste keystrokes below are silently ignored.
--
-- Press Option+P with text selected. The correction replaces the selection and
-- nothing else happens on screen. Cmd-Z reverts it like any other paste.
-- Set SHOW_ALERTS below to true to see what changed and why.

-- One key, Option+P. ~1.6s.
--
-- P is not a mnemonic - it was chosen under the old name and kept, because a
-- hotkey people already have in their fingers is worth more than a letter that
-- matches the product name.
--
-- There used to be a second hotkey that showed three phrasings in a chooser and
-- let you pick one. It is gone. Most messages need the grammar fixed, not a
-- decision, and making three near-identical sentences distinguishable in a list
-- took more code than the correction itself. What changed is the part that was
-- actually worth reading, and SHOW_ALERTS can put it back on screen. The three
-- variants still exist in the CLI: `./corrector.py "your text"`.
--
-- Not Option+Space: that is bound to Spotlight on this machine.
-- Note this overrides Option+P's normal output, the character pi.
local HOTKEY_MODS = { "alt" }
local HOTKEY_KEY = "p"

-- Enables the `hs` command-line tool, so the config can be reloaded and
-- inspected from a terminal: `hs -c 'hs.reload()'`. Nothing here depends on it;
-- it exists so this file can be tested without clicking through a menu.
require("hs.ipc")

-- Hide Hammerspoon's own hammer from the menu bar.
--
-- Two reasons. It is redundant: crisp-english's icon reports the same "is this loaded and
-- working" that the hammer did, and adds status the hammer never had. And on a
-- notched display it was actively harmful - measured on a 14" screen, the hammer
-- occupied the last slot clear of the notch and pushed crisp-english's icon to x=814,
-- inside the 656-856 notch region, where macOS draws it behind the camera
-- housing: present, correct, and completely invisible. Hiding the hammer moved
-- crisp-english to x=885 and back into view.
--
-- Hammerspoon's own menu is still reachable by launching the app again.
hs.menuIcon(false)

-- Where this file actually lives. Discovered, never assumed.
--
-- This was hardcoded to one absolute path on the author's Mac, which worked on
-- exactly that machine and silently broke on any other - the hotkey would fire,
-- fail to find corrector.py, and report "Could not start python3".
--
-- Two install shapes have to keep working: this file symlinked as
-- ~/.hammerspoon/init.lua, and this file dofile'd from someone's existing
-- Hammerspoon config. debug.getinfo reports whichever path Lua actually loaded;
-- symlinkAttributes turns the first case back into the real directory. Both
-- verified.
local PROJECT = (function()
  local override = os.getenv("CRISP_ENGLISH_DIR")
  if override and override ~= "" then
    return override
  end
  local src = debug.getinfo(1, "S").source:gsub("^@", "")
  local real = hs.fs.symlinkAttributes(src, "target") or src
  return real:match("^(.*)/[^/]+$")
end)()

-- init.lua is symlinked into ~/.hammerspoon/, so Lua's default search path looks
-- there rather than at the real project directory. Point it at the project
-- before anything is required from it.
package.path = PROJECT .. "/?.lua;" .. package.path

-- How to talk to Ollama. Required rather than inlined so menubar.lua and this
-- file cannot drift apart on what "warm" means - they did, and a mismatched
-- num_ctx loads the model twice.
--
-- Not pcall'd, unlike menubar below: the hotkey cannot do its job without
-- Ollama, so a missing ollama.lua is a broken install and should say so loudly
-- rather than degrade into a tool that silently never corrects anything.
local ollama = require("ollama")

-- The settings that come from crisp-english.conf. Required, not pcall'd, for the same
-- reason ollama is: ollama.lua already depends on it, so a missing config.lua is
-- a broken install rather than a missing nicety.
local config = require("config")

-- Two optional modules, pcall'd like menubar below. Neither is needed for a
-- correction to happen: without state.lua the settings stop surviving a reload,
-- and without audience.lua the menu choice decides every message. Both are
-- worse tools, not broken ones, and the hotkey must not fail over either.
local okState, persistence = pcall(require, "state")
local okAudience, audience = pcall(require, "audience")

-- Where crisp-english keeps the little state the outside world has to be able to read.
--
-- Two files, on purpose:
--
--   enabled  a single bare word, read by the login warm-up job with `cat`.
--            Kept exactly as it was so an install whose launch agent has not
--            been replaced by a newer install.sh keeps working.
--   state    every setting that has to survive a reload, as KEY=value.
--
-- The warm-up job reads a file rather than asking the running config over
-- `hs -c`, because Hammerspoon's ipc port drops calls and can hang for minutes,
-- and a stuck launch agent is worse than no check at all.
local STATE_DIR = os.getenv("HOME") .. "/.crisp-english"
local ENABLED_FLAG = STATE_DIR .. "/enabled"
local STATE_FILE = STATE_DIR .. "/state"

-- corrector.py creates this too, but the warm-up job runs at login and may well
-- get here first, before any correction has ever been made.
hs.fs.mkdir(STATE_DIR)

local PYTHON = "/usr/bin/python3"
local OLLAMA = "http://localhost:11434"

-- Pick the audience from the frontmost app rather than from the menu. See
-- audience.lua; CRISP_ENGLISH_AUTO_TONE=0 in crisp-english.conf turns it off.
local AUTO_TONE = config.flag("CRISP_ENGLISH_AUTO_TONE", "1")

-- What was set last time crisp-english ran. Absent fields mean "never set", which is
-- different from false, so the defaults below still apply to a fresh install.
local saved = okState and persistence.load(STATE_FILE) or {}

local function orDefault(value, default)
  if value == nil then
    return default
  end
  return value
end

-- How long to wait for the app to put the selection on the clipboard. Slack and
-- Electron apps are slower than native ones; 0.25s is enough for both here.
local COPY_WAIT = 0.25

-- Everything the menubar can see or change lives here, and nowhere else.
--
-- These were plain `local` constants until the menubar existed. They had to move
-- into a shared table because a menubar toggle that needed a file edit and a
-- config reload to take effect would not be a toggle.
--
-- showAlerts = false means silent: the text changes and nothing else happens. The
-- menubar can flip it live, per message, which is the point - you can keep the
-- popups off and still turn them on for the one email that matters.
--
-- What silence costs, so it is a choice and not a surprise:
--   - A cold model takes 15-90s and says nothing. The menubar icon is the tell.
--   - Grammar notes are not shown. They are still logged: `./corrector.py stats`.
--   - Warnings are not shown. "do the needful" gets quietly paraphrased or left
--     alone with nothing pointing it out. This is the one real loss.
local state = {
  enabled = orDefault(saved.enabled, true),
  showAlerts = orDefault(saved.showAlerts, false),
  -- Who the message is going to. Names must match the TONES table in
  -- corrector.py; an unknown one degrades to default there rather than failing,
  -- so a mismatch can never break the hotkey.
  --
  -- "formal" rather than "default", because the menu no longer offers a
  -- do-nothing option and one of the two audiences is always active. Client is
  -- the safer of the two to land on by accident: an over-formal Slack message is
  -- awkward, whereas an 18-word client email can be genuinely too terse.
  --
  -- Restored from disk when there is something to restore. It was a plain field
  -- in this literal, which meant `crisp-englishctl tone slack` was silently undone by
  -- the next `crisp-englishctl reload` or Hammerspoon restart.
  tone = orDefault(saved.tone, "formal"),
  ollama = OLLAMA,
  model = config.get("CRISP_ENGLISH_MODEL", "qwen3:4b"),
  project = PROJECT,
  python = PYTHON,
  -- Did crisp-english start the Ollama app, or was it already running?
  --
  -- Deliberately not persisted. A flag claiming "we started it" that survived a
  -- reload or a reboot would be a lie the first time you turned crisp-english off after
  -- restarting, and it would quit an Ollama that something else - a chat app, a
  -- terminal session, another model entirely - is in the middle of using. Fresh
  -- false on every load is the only value that is always honest.
  ollamaOwned = false,
  onBusyChange = function() end,     -- replaced by the menubar when it attaches
  onChange = function() end,         -- likewise; fires when enabled/model change
}

-- Write both state files. Called by every setter, so no caller has to remember.
--
-- The bare-word file first and on its own: it is what the launch agent reads,
-- and it is the file crisp-englishctl polls to confirm a toggle actually landed, so it
-- must be written before anything that could fail or block.
local function persist()
  local f = io.open(ENABLED_FLAG, "w")
  if f then
    f:write(tostring(state.enabled))
    f:close()
  end
  if okState then
    persistence.save(STATE_FILE, state)
  end
end

-- Longer than corrector.py's worst-case timeout, because this alert is closed
-- explicitly when the task returns. It previously expired after 10s, so a cold
-- model load left the screen blank for the remaining 30s and the tool looked
-- broken at exactly the moment it needed to explain itself.
local WORKING_ALERT_MAX = 95

local inFlight = false

-- Every alert goes through these, so state.showAlerts is the only switch and
-- there is no nil-handling scattered around the call sites.
local function alert(text, seconds)
  if not state.showAlerts then
    return nil
  end
  return hs.alert.show(text, seconds)
end

local function closeAlert(id)
  if id then
    hs.alert.closeSpecific(id)
  end
end

local function notify(title, text)
  hs.notify.new({ title = title, informativeText = text, withdrawAfter = 5 }):send()
end

-- Turning crisp-english on and off, from anywhere.
--
-- This lives here rather than in menubar.lua for the same reason ollama.lua
-- does: menubar.lua is allowed to be missing, and `crisp-englishctl on|off` drives this
-- over the ipc port without any menu existing at all. One function means the
-- menu and the terminal cannot diverge, which is the promise crisp-englishctl makes.
--
-- The on/off flag is crisp-english's own state and never depends on Ollama. If Ollama
-- is uninstalled, broken, or refuses to start, crisp-english still turns ON - the hotkey
-- stays bound and the icon reports a sleeping model. A toggle that silently
-- refused to move because a subprocess failed would be worse than one that
-- moves and then tells you the engine is down.
-- True while an Ollama start-up or teardown is still running.
--
-- This is not defensive padding, it is a bug fix. crisp-englishctl retries a dropped ipc
-- reply, so a single `crisp-englishctl on` can deliver setEnabled(true) three or four
-- times a second apart. The first call found Ollama down, launched it and set
-- ollamaOwned = true; a retry a moment later found Ollama UP - because the first
-- call had just started it - and concluded crisp-english did not own it, resetting the
-- flag to false. The result was an Ollama that crisp-english had started and would then
-- refuse to quit. Clicking the menu item twice does the same thing.
--
-- Ownership can only be decided by the call that actually does the launching, so
-- every other call has to stand aside until that one finishes.
local ollamaBusy = false

local function setEnabled(on)
  on = not not on
  state.enabled = on
  persist()                          -- before anything slow, so the login job agrees
  state.onChange()                   -- flip the icon now, not when Ollama replies

  -- The flag above is always honoured; only the Ollama work is skipped. Turning
  -- the hotkey on and off stays instant and never depends on Ollama.
  if ollamaBusy then
    return
  end
  ollamaBusy = true

  local function done()
    ollamaBusy = false
    state.onChange()
  end

  if on then
    ollama.up(state, function(isUp)
      if isUp then
        -- Already running, so it is not ours to quit later.
        state.ollamaOwned = false
        ollama.warm(state, done)
        return
      end
      ollama.start(state, function(started)
        state.ollamaOwned = started
        if started then
          ollama.warm(state, done)
        else
          notify("crisp-english", "Could not start Ollama. The hotkey is on, but "
                       .. "corrections will fail until Ollama is running.")
          done()
        end
      end)
    end)
    return
  end

  -- Off. Free the memory first, then quit the app only if it is ours.
  --
  -- Waiting for an in-flight correction matters more than it looks: unloading
  -- the model out from under a request that is 1.5s from finishing turns a
  -- successful correction into an error notification, and the user just asked
  -- for silence, not for a failure.
  local function teardown()
    ollama.unload(state, function()
      if state.ollamaOwned then
        ollama.quit()
        state.ollamaOwned = false
      end
      done()
    end)
  end

  if not inFlight then
    return teardown()
  end
  -- Bounded, because inFlight is cleared by a callback that a wedged task might
  -- never reach. corrector.py's own ceiling is 90s; give up a little after that
  -- and tear down anyway rather than leaking a poll forever.
  local deadline = os.time() + 95
  hs.timer.waitUntil(
    function() return (not inFlight) or os.time() > deadline end,
    teardown, 0.2)
end

-- How long to leave the correction on the clipboard before handing the
-- clipboard back.
--
-- This was 0.15s, and that was a race the user loses in exactly the app crisp-english is
-- most used in. COPY_WAIT above is 0.25s because Electron apps are slow to WRITE
-- the pasteboard - but reading it is at least as slow, and the old delay gave
-- Slack 100ms LESS to read the correction than it had been given to produce the
-- selection. When Slack lost, Cmd-V pasted whatever was on the clipboard
-- beforehand: someone else's text, into a colleague's DM.
--
-- 0.6s is well past both, and costs nothing that is visible - the paste has
-- already happened; this is only about when the old contents come back.
local PASTE_SETTLE = 0.6

-- Restore the clipboard the user had before we borrowed it. A grammar helper that
-- eats your clipboard does not get used twice, so this runs on every exit path.
local function withClipboard(fn)
  local saved = hs.pasteboard.getContents()
  local savedTypes = hs.pasteboard.contentTypes()
  local ok, err = pcall(fn)
  hs.timer.doAfter(PASTE_SETTLE, function()
    if saved ~= nil then
      hs.pasteboard.setContents(saved)
    elseif savedTypes and #savedTypes > 0 then
      hs.pasteboard.clearContents()
    end
  end)
  if not ok then
    notify("crisp-english failed", tostring(err))
  end
end

local function paste(text)
  hs.pasteboard.setContents(text)
  -- A short delay: the pasteboard write must land before Cmd-V reads it.
  hs.timer.doAfter(0.05, function()
    hs.eventtap.keyStroke({ "cmd" }, "v", 0)
  end)
end

-- What to show after the text has already been replaced.
--
-- The changes are the point. Pasting without a chooser means you never saw the
-- correction before it landed, so the alert has to answer "what did it just do to
-- my sentence" - and corrector.py already computes exactly that and sends it in
-- the JSON. The old code threw it away and showed only the grammar notes.
local function summarize(result)
  local lines = {}

  -- `best`, not `natural`. corrector.py computes both: `natural` is a diff
  -- against the `fix` variant, for the CLI that prints all three, and `best` is
  -- a diff of the text actually being pasted against what the user wrote.
  --
  -- Reading `natural` was wrong for the brief tone, where `best` is the `short`
  -- variant and `natural` is byte-identical to `fix` - so its change list is
  -- empty and the alert had nothing to show. That is the register Slack and
  -- WhatsApp now select automatically, so it was the common case.
  --
  -- Falls back to `natural` so an older corrector.py still says something.
  local changes = (result.changes or {}).best
    or (result.changes or {}).natural or {}
  local parts = {}
  for i, c in ipairs(changes) do
    if i > 4 then break end
    -- corrector.py writes "old -> new"; the arrow reads better in an alert.
    table.insert(parts, (c:gsub(" %-> ", " \u{2192} ")))
  end
  if #parts > 0 then
    table.insert(lines, table.concat(parts, "    "))
  end

  for _, n in ipairs(result.notes or {}) do
    table.insert(lines, n)
  end
  -- A phrase nothing can fix. Louder than a note, because no correction happened
  -- and the sentence still needs a human.
  for _, h in ipairs(result.hints or {}) do
    table.insert(lines, h)
  end

  -- Which audience produced this. Worth a word now that the app can choose it:
  -- if Slack silently gets "brief" while the menu says "Client or senior", the
  -- alert is the only place that difference is visible.
  local written = result.tone and result.tone ~= "default"
    and ("  \u{00B7}  " .. result.tone) or ""
  table.insert(lines, "\u{2318}Z to revert" .. written)
  return table.concat(lines, "\n")
end

-- Upgrade the working alert if the model is not resident yet.
--
-- Cold load is 15-50s against ~1.6s warm, and the difference between "slow" and
-- "broken" is entirely whether the tool said so. Runs async and in parallel with
-- the request, so a hung or missing Ollama never blocks the hotkey.
-- Through ollama.loaded, not its own /api/ps call.
--
-- This used to hold a second copy of that fetch-and-parse, and the copy asked a
-- different question: `#parsed.models == 0`, i.e. "is anything resident", rather
-- than "is OUR model resident". Measured against a live Ollama with gemma3:4b
-- loaded and qwen3:4b not:
--
--   warnIfCold would warn: false   |   our model actually resident: false
--
-- So the one case the warning exists for - a cold load you are about to wait
-- 30s through - was silent whenever some other model happened to be in memory.
-- ollama.loaded answers the right question and is tested; there is no reason for
-- this file to know the shape of that JSON at all.
local function warnIfCold(replaceAlert)
  ollama.loaded(state, function(isWarm)
    if not isWarm then
      replaceAlert("crisp-english - warming the model, this first one takes ~30s")
    end
  end)
end

-- Who is this message for? Answered from the app you are typing in, not from a
-- menu you set last Tuesday. See audience.lua for why browsers are excluded and
-- how to switch this off.
--
-- Read at the moment the hotkey fires, before the async copy: the frontmost app
-- is the one holding the selection, and it must not be re-read later, after an
-- alert or a notification may have changed focus.
local function audienceFor(appName)
  if not okAudience then
    return state.tone
  end
  return audience.resolve(appName, state.tone, AUTO_TONE)
end

-- Named correctSelection, not after the product.
--
-- It was `local function crisp()`, and the rename to crisp-english turned that
-- into `crisp-english()` - which Lua parses as a subtraction, so the file failed
-- to compile and `require("hs.ipc")` on line 32 never ran. The symptom was not a
-- Lua error anyone could see: it was the `hs` command reporting a dead message
-- port, which reads exactly like Hammerspoon not running.
--
-- A function named after the project is a function that breaks on the next
-- rename. This one is named for what it does.
local function correctSelection()
  if inFlight then
    return                         -- ignore a second press while one is running
  end
  if not state.enabled then
    -- Switched off from the menubar. Stay bound rather than unbinding the hotkey,
    -- so Option+P keeps being swallowed instead of suddenly typing a pi into
    -- whatever you were writing.
    return
  end

  -- Captured now, while the app holding the selection is still frontmost.
  local front = hs.application.frontmostApplication()
  local tone = audienceFor(front and front:name() or nil)

  local saved = hs.pasteboard.getContents()

  -- Copy the selection. hs.eventtap is why Accessibility permission is required.
  hs.pasteboard.clearContents()
  hs.eventtap.keyStroke({ "cmd" }, "c", 0)

  hs.timer.doAfter(COPY_WAIT, function()
    local original = hs.pasteboard.getContents()
    if saved ~= nil then
      hs.pasteboard.setContents(saved)   -- give the clipboard back immediately
    end

    if original == nil or original:gsub("%s", "") == "" then
      notify("crisp-english", "Select some text first.")
      return
    end

    inFlight = true
    state.onBusyChange(true)
    local working = nil
    if state.showAlerts then
      hs.alert.closeAll()
      working = alert("crisp-english - correcting...", WORKING_ALERT_MAX)
      local function replaceAlert(text)
        if not inFlight then
          return                   -- the request already finished; leave it alone
        end
        closeAlert(working)
        working = alert(text, WORKING_ALERT_MAX)
      end
      -- Skipped entirely when silent: its only effect is to reword an alert, so
      -- there is no reason to spend an HTTP round trip on it.
      warnIfCold(replaceAlert)
    end

    -- corrector.py is a separate process on purpose: the correction logic knows
    -- nothing about hotkeys or clipboards, so it stays testable on its own.
    -- --fast asks for one variant instead of three, which is genuinely quicker
    -- rather than just skipping a popup: fewer output tokens, shorter generation.
    local argv = { PROJECT .. "/corrector.py", "--json", "--fast" }
    if tone and tone ~= "default" then
      table.insert(argv, "--tone")
      table.insert(argv, tone)
    end
    table.insert(argv, original)     -- the text must stay the last argument

    local task = hs.task.new(PYTHON, function(exitCode, stdout, stderr)
      inFlight = false
      state.onBusyChange(false)
      closeAlert(working)

      if exitCode ~= 0 then
        local err = (stderr ~= "" and stderr) or stdout
        notify("crisp-english failed", (err:gsub("%s+$", "")))
        return
      end

      local ok, result = pcall(hs.json.decode, stdout)
      if not ok or type(result) ~= "table" then
        notify("crisp-english failed", "Could not read the result.")
        return
      end
      if result.error then
        notify("crisp-english", result.error)
        return
      end

      local best = result.best
      if not best or best == "" or best == original then
        alert("crisp-english - already correct", 1.5)
        return
      end

      withClipboard(function() paste(best) end)

      if state.showAlerts then
        -- After the text is in place, so reading it never slows the paste down.
        hs.timer.doAfter(0.4, function()
          local seconds = (#(result.hints or {}) > 0) and 6 or 4
          alert(summarize(result), seconds)
        end)
      end
    end, argv)

    if not task then
      inFlight = false
      state.onBusyChange(false)
      closeAlert(working)
      notify("crisp-english failed", "Could not start python3.")
      return
    end
    task:start()
  end)
end

hs.hotkey.bind(HOTKEY_MODS, HOTKEY_KEY, correctSelection)

-- A second hotkey, whose only job is getting back in.
--
-- Option+P is deliberately swallowed while crisp-english is off, so it cannot switch
-- crisp-english back on. And macOS hides the menu bar icon behind the notch on its own
-- (see the autosaveName comment in menubar.lua), so there were situations with
-- no way back at all except typing a full path into a terminal - which made
-- "off" a state you could enter by accident and not find your way out of.
--
-- Shift+Option+P rather than a new letter: it is the same key you already press,
-- and it cannot be reached by fumbling Option+P.
local TOGGLE_MODS = { "alt", "shift" }
local TOGGLE_KEY = "p"

-- Global for the same reason crispEnglishCorrect is: Hammerspoon will not fire its own
-- hotkeys from a synthetic event, so a binding is otherwise untestable except by
-- hand.  hs -c 'crispEnglishToggle()'
function crispEnglishToggle()
  setEnabled(not state.enabled)
  -- Unconditional, unlike every other alert here, which respects
  -- state.showAlerts. Those are optional because the corrected text on screen is
  -- itself the confirmation. This one is the ONLY feedback available in exactly
  -- the case it exists for: the icon cannot be seen, so nothing else can say
  -- which way the switch just went.
  hs.alert.closeAll()
  hs.alert.show(state.enabled and "crisp-english on" or "crisp-english off", 1.2)
  return state.enabled
end

hs.hotkey.bind(TOGGLE_MODS, TOGGLE_KEY, crispEnglishToggle)

-- Deliberately global, so the whole flow can be driven without a keypress:
--   hs -c 'crispEnglishCorrect()'
-- Hammerspoon does not fire its own hotkeys from synthetic events, so without
-- this the only way to exercise this file is by hand - which is why the design
-- doc lists the hotkey layer as untested. Now it can be scripted.
crispEnglishCorrect = correctSelection

-- Exposed for the same reason as crispEnglishCorrect: this is what the alert says, and
-- it was silently saying nothing for the brief tone. A renderer nobody can call
-- is a renderer nobody can check.
--   hs -c 'crispEnglishState.summarize({changes={best={"a -> b"}}, tone="brief"})'
state.summarize = summarize

-- Same reasoning: lets the state be inspected and driven from a terminal, e.g.
--   hs -c 'crispEnglishState.showAlerts = true'
-- which is also the quickest way to check the menubar actually attached, since
-- attaching is what replaces the onBusyChange no-op.
crispEnglishState = state

-- The toggle, hung on the state table so `crisp-englishctl on|off` can call it over the
-- ipc port: `hs -c 'crispEnglishState.setEnabled(false)'`. Assigned here rather than
-- inside the table literal because it closes over inFlight and notify.
state.setEnabled = setEnabled

-- Setters for the two settings that used to be written by hand.
--
-- The menubar did `state.tone = t.id` and crisp-englishctl did `crispEnglishState.tone="formal"`
-- over the ipc port. Neither persisted, and nothing validated the name - so the
-- two ways of changing the setting could disagree, and both forgot it on reload.
-- Same reasoning as setEnabled living here: one function means the menu and the
-- terminal cannot mean different things.
state.setTone = function(name)
  if name ~= "formal" and name ~= "brief" and name ~= "default" then
    return false, "unknown audience: " .. tostring(name)
  end
  state.tone = name
  persist()
  state.onChange()
  return true
end

state.setAlerts = function(on)
  state.showAlerts = not not on
  persist()
  state.onChange()
  return state.showAlerts
end

-- Is the audience being taken from the frontmost app? Read by crisp-englishctl status,
-- so the answer to "why did my Slack message come back terse" is one command.
state.autoTone = AUTO_TONE
state.audienceFor = audienceFor

-- Free the model when the Mac sleeps.
--
-- This is the whole feature in one line, and the only part of it with no cost:
-- closing the lid releases 2.9GB immediately instead of holding it all night on
-- battery. Nothing is done on wake - the next correction loads the model, and if
-- there is no next correction there is nothing to pay for.
--
-- Stored on `state` rather than a file-local so it is reachable from the global
-- crispEnglishState and cannot be garbage collected out from under us, which is the
-- documented way Hammerspoon watchers quietly stop firing.
-- Named and hung on state rather than written inline, for the same reason
-- crispEnglishCorrect is global: a callback macOS alone can fire is a callback nobody
-- can test. Hammerspoon will not deliver a synthetic sleep event, so without
-- this the only way to exercise it would be to actually sleep the machine.
--   hs -c 'crispEnglishState.onSleep()'
state.onSleep = function()
  ollama.unload(state)
end

state.sleepWatcher = hs.caffeinate.watcher.new(function(event)
  if event == hs.caffeinate.watcher.systemWillSleep then
    state.onSleep()
  end
end)
state.sleepWatcher:start()

-- The menubar. Loaded last, because it reads the state above and hooks
-- onBusyChange, and it must not be able to affect whether the hotkey works: if
-- this file is missing or throws, the correction path carries on without it.
local ok, menubar = pcall(require, "menubar")
if ok and menubar then
  local attached = pcall(menubar.attach, state)
  if not attached then
    notify("crisp-english", "Menubar failed to load. The hotkey still works.")
  end
else
  notify("crisp-english", "menubar.lua not found. The hotkey still works.")
end

-- No startup alert any more: the menubar icon is a better answer to "did the
-- config load" than a box that vanishes after two seconds. No icon means it did
-- not - which is the one thing Hammerspoon could never tell you from the inside.
--
-- Except that "no icon" has two causes: the config failed, or the icon is there
-- and macOS is hiding it behind the notch because the menu bar is full. This
-- line distinguishes them. It is the last statement in the file, so the file
-- reaching it proves everything above ran.
do
  -- ~/.crisp-english/ rather than /tmp: macOS sweeps /tmp files untouched for ~3 days,
  -- so after a week of uptime the canary vanished and stopped meaning anything.
  persist()

  local f = io.open(os.getenv("HOME") .. "/.crisp-english/load.log", "w")
  if f then
    f:write(string.format("%s  loaded ok\nproject=%s\nmenubar=%s\ntone=%s\n",
      os.date("%Y-%m-%d %H:%M:%S"), tostring(PROJECT),
      tostring(package.loaded["menubar"] ~= nil), tostring(state.tone)))
    f:close()
  end
end
