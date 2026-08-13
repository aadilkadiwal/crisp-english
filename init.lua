-- saaf - correct the selected text with one keystroke.
--
-- Install: symlink or copy this into ~/.hammerspoon/init.lua, then reload
-- Hammerspoon. Grant Accessibility permission when macOS asks, otherwise the
-- copy/paste keystrokes below are silently ignored.
--
-- Press Option+P with text selected. The correction replaces the selection and
-- nothing else happens on screen. Cmd-Z reverts it like any other paste.
-- Set SHOW_ALERTS below to true to see what changed and why.

-- One key, "P" for saaf. ~1.6s.
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
-- Two reasons. It is redundant: saaf's icon reports the same "is this loaded and
-- working" that the hammer did, and adds status the hammer never had. And on a
-- notched display it was actively harmful - measured on a 14" screen, the hammer
-- occupied the last slot clear of the notch and pushed saaf's icon to x=814,
-- inside the 656-856 notch region, where macOS draws it behind the camera
-- housing: present, correct, and completely invisible. Hiding the hammer moved
-- saaf to x=885 and back into view.
--
-- Hammerspoon's own menu is still reachable by launching the app again.
hs.menuIcon(false)

-- Where this file actually lives. Discovered, never assumed.
--
-- This was hardcoded to ~/Desktop/Project/Personal/saaf, which worked on exactly
-- one machine and silently broke on any other - the hotkey would fire, fail to
-- find corrector.py, and report "Could not start python3".
--
-- Two install shapes have to keep working: this file symlinked as
-- ~/.hammerspoon/init.lua, and this file dofile'd from someone's existing
-- Hammerspoon config. debug.getinfo reports whichever path Lua actually loaded;
-- symlinkAttributes turns the first case back into the real directory. Both
-- verified.
local PROJECT = (function()
  local override = os.getenv("SAAF_DIR")
  if override and override ~= "" then
    return override
  end
  local src = debug.getinfo(1, "S").source:gsub("^@", "")
  local real = hs.fs.symlinkAttributes(src, "target") or src
  return real:match("^(.*)/[^/]+$")
end)()

local PYTHON = "/usr/bin/python3"
local OLLAMA = "http://localhost:11434"

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
  enabled = true,
  showAlerts = false,
  -- Who the message is going to. Names must match the TONES table in
  -- corrector.py; an unknown one degrades to default there rather than failing,
  -- so a mismatch can never break the hotkey.
  tone = "default",
  ollama = OLLAMA,
  model = os.getenv("SAAF_MODEL") or "qwen3:4b",
  project = PROJECT,
  python = PYTHON,
  onBusyChange = function() end,     -- replaced by the menubar when it attaches
}

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

-- Restore the clipboard the user had before we borrowed it. A grammar helper that
-- eats your clipboard does not get used twice, so this runs on every exit path.
local function withClipboard(fn)
  local saved = hs.pasteboard.getContents()
  local savedTypes = hs.pasteboard.contentTypes()
  local ok, err = pcall(fn)
  hs.timer.doAfter(0.15, function()
    if saved ~= nil then
      hs.pasteboard.setContents(saved)
    elseif savedTypes and #savedTypes > 0 then
      hs.pasteboard.clearContents()
    end
  end)
  if not ok then
    notify("saaf failed", tostring(err))
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

  local changes = (result.changes or {}).natural or {}
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

  table.insert(lines, "\u{2318}Z to revert")
  return table.concat(lines, "\n")
end

-- Upgrade the working alert if the model is not resident yet.
--
-- Cold load is 15-50s against ~1.6s warm, and the difference between "slow" and
-- "broken" is entirely whether the tool said so. Runs async and in parallel with
-- the request, so a hung or missing Ollama never blocks the hotkey.
local function warnIfCold(replaceAlert)
  hs.http.asyncGet(OLLAMA .. "/api/ps", nil, function(status, body)
    if status ~= 200 or not body then
      return
    end
    local ok, parsed = pcall(hs.json.decode, body)
    if not ok or type(parsed) ~= "table" then
      return
    end
    if not parsed.models or #parsed.models == 0 then
      replaceAlert("saaf - warming the model, this first one takes ~30s")
    end
  end)
end

local function saaf()
  if inFlight then
    return                         -- ignore a second press while one is running
  end
  if not state.enabled then
    -- Switched off from the menubar. Stay bound rather than unbinding the hotkey,
    -- so Option+P keeps being swallowed instead of suddenly typing a pi into
    -- whatever you were writing.
    return
  end

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
      notify("saaf", "Select some text first.")
      return
    end

    inFlight = true
    state.onBusyChange(true)
    local working = nil
    if state.showAlerts then
      hs.alert.closeAll()
      working = alert("saaf - correcting...", WORKING_ALERT_MAX)
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
    if state.tone and state.tone ~= "default" then
      table.insert(argv, "--tone")
      table.insert(argv, state.tone)
    end
    table.insert(argv, original)     -- the text must stay the last argument

    local task = hs.task.new(PYTHON, function(exitCode, stdout, stderr)
      inFlight = false
      state.onBusyChange(false)
      closeAlert(working)

      if exitCode ~= 0 then
        local err = (stderr ~= "" and stderr) or stdout
        notify("saaf failed", (err:gsub("%s+$", "")))
        return
      end

      local ok, result = pcall(hs.json.decode, stdout)
      if not ok or type(result) ~= "table" then
        notify("saaf failed", "Could not read the result.")
        return
      end
      if result.error then
        notify("saaf", result.error)
        return
      end

      local best = result.best
      if not best or best == "" or best == original then
        alert("saaf - already correct", 1.5)
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
      notify("saaf failed", "Could not start python3.")
      return
    end
    task:start()
  end)
end

hs.hotkey.bind(HOTKEY_MODS, HOTKEY_KEY, saaf)

-- Deliberately global, so the whole flow can be driven without a keypress:
--   hs -c 'saafCorrect()'
-- Hammerspoon does not fire its own hotkeys from synthetic events, so without
-- this the only way to exercise this file is by hand - which is why the design
-- doc lists the hotkey layer as untested. Now it can be scripted.
saafCorrect = saaf

-- Same reasoning: lets the state be inspected and driven from a terminal, e.g.
--   hs -c 'saafState.showAlerts = true'
-- which is also the quickest way to check the menubar actually attached, since
-- attaching is what replaces the onBusyChange no-op.
saafState = state

-- The menubar. Loaded last, because it reads the state above and hooks
-- onBusyChange, and it must not be able to affect whether the hotkey works: if
-- this file is missing or throws, the correction path carries on without it.
--
-- init.lua is symlinked into ~/.hammerspoon/, so Lua's default search path looks
-- there rather than at the real project directory. Point it at the project first.
package.path = PROJECT .. "/?.lua;" .. package.path
local ok, menubar = pcall(require, "menubar")
if ok and menubar then
  local attached = pcall(menubar.attach, state)
  if not attached then
    notify("saaf", "Menubar failed to load. The hotkey still works.")
  end
else
  notify("saaf", "menubar.lua not found. The hotkey still works.")
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
  local f = io.open("/tmp/saaf-load.log", "w")
  if f then
    f:write(string.format("%s  loaded ok\nproject=%s\nmenubar=%s\ntone=%s\n",
      os.date("%Y-%m-%d %H:%M:%S"), tostring(PROJECT),
      tostring(package.loaded["menubar"] ~= nil), tostring(state.tone)))
    f:close()
  end
end
