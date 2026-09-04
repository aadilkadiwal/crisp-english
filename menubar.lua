-- crisp-english menubar - status and controls, without a popup.
--
-- This exists because running silent removed every signal the tool used to give.
-- "Nothing happened" became both the look of success and the symptom of every
-- failure, and a sleeping model took 30s with nothing to say so. A menubar icon
-- answers both by being there when you look at it rather than interrupting you,
-- which was the actual problem with the alerts - not the information in them.
--
-- One property worth knowing: if Hammerspoon dies, the icon disappears. A missing
-- icon is the signal. Nothing inside Hammerspoon could report that.
--
-- Interface: attach(state) where state is the table init.lua owns. This file only
-- reads and writes fields on it; it knows nothing about clipboards or hotkeys.

-- Ollama lives in its own module now. This file used to hold its own copies of
-- the /api/ps and /api/generate calls, which is how the warm-up here and the
-- one in corrector.py were free to disagree about num_ctx.
local ollama = require("ollama")

local M = {}

-- Icon vocabulary.
--
-- Still four distinguishable glyphs rather than colour, which is unreadable at
-- menubar size and invisible to some people. What changed is that they now say
-- something: this was ○ ◇ ◆ ◈, a hollow-to-solid diamond family whose state
-- logic was fine and whose meaning was nil. Nothing about a diamond suggests
-- English, or text, or correction.
--
-- A letter, marked. macOS itself flags a word that needs attention by putting a
-- line under it, so an underlined A is that idiom in a single character, and an
-- A reads as "text" before it reads as anything else. The underline appearing is
-- the ready signal - it is the mark the tool exists to make.
--
-- What was rejected, and why:
--
--   SF Symbols (textformat.abc.dottedunderline is literally the system's
--     spell-check icon). hs.image.imageFromName in Hammerspoon 1.1.1 returns
--     nil for every SF Symbol name tried; it resolves only classic NSImage
--     names. Not available, rather than not wanted.
--   A pencil (✎ asleep, ✏ ready). Measured at menu bar size the filled pencil
--     renders as an unclear sideways shape. Good idea, bad glyph.
--   ✅ and 🖋, which are colour emoji: they measure 39px against 29-33px for a
--     text glyph, and colour is what this vocabulary avoids.
--   "abc" with an underline, the honest version of the spell-check idiom, at
--     43px. Too wide for a bar where macOS already hides the icon behind the
--     notch given half a chance.
--
-- Widths measured in the real menu bar via bar:frame().w, since a glyph that
-- falls back to emoji gets wider and that is how you find out.
local ICON = {
  disabled = "⊘",     -- off; the hotkey does nothing
  cold     = "A",     -- on, but the model is asleep: the next one takes ~30s
  warm     = "A̲",     -- on and hot: the next one takes ~1.5s (A + U+0332)
  busy     = "⋯",     -- correcting right now
}

-- Who the message is going to. Names must match TONES in corrector.py.
--
-- Two audiences, not three. The "Colleague" option was removed deliberately: it
-- was the do-nothing default, and having it meant most corrections went out
-- without anyone deciding who was going to read them. One of these two is always
-- active, so the choice is always made.
--
-- corrector.py still has a "default" tone - the CLI uses it, and it is the base
-- prompt both of these build on. It is simply not offered here.
local TONES = {
  -- complete sentences, no contractions
  { id = "formal", label = "Client or senior" },
  -- fewest words that stay polite
  { id = "brief",  label = "Slack / WhatsApp" },
}

local function toneLabel(id)
  for _, t in ipairs(TONES) do
    if t.id == id then return t.label end
  end
  return id
end

function M.attach(state)
  -- The autosaveName is the whole reason this is not hs.menubar.new().
  --
  -- macOS decides where a status item sits, based on the total width of
  -- everything to its right - which changes as other apps come and go. On a
  -- notched display that means the icon drifts in and out of the notch on its
  -- own: measured at x=885, then 1014, then 746, then 814 across a fortnight,
  -- with 656-856 being invisible. Hiding Hammerspoon's own hammer bought
  -- headroom but not stability.
  --
  -- With an autosaveName, macOS remembers a position the user sets by
  -- Command-dragging the icon. Drag it clear of the notch once and it stays
  -- there. That is the only durable fix available from this side.
  -- "crisp", not "crisp-english", and it must stay that way.
  --
  -- This string is the key macOS files the icon's saved position under. The
  -- position is the ONLY durable fix for the notch problem - drag the icon clear
  -- once and it stays - and changing the name throws it away, silently, sending
  -- the icon back to wherever macOS feels like putting it. The rename is not
  -- worth costing every existing install its position.
  local bar = hs.menubar.new(true, "crisp")
  if not bar then
    return nil                       -- no menubar available; nothing else to do
  end

  local warm, busy = false, false
  -- Minutes until Ollama drops the model, or nil when it cannot be read.
  -- Shown in the menu because "is crisp-english holding my RAM right now" became a
  -- real question the moment the model started unloading itself.
  local freesIn, heldGB = nil, nil

  local function icon()
    if not state.enabled then return ICON.disabled end
    if busy then return ICON.busy end
    return warm and ICON.warm or ICON.cold
  end

  local function render()
    bar:setTitle(icon())
    if not state.enabled then
      bar:setTooltip("crisp-english - off")
      return
    end
    -- The tone is in the tooltip because leaving it on "Client or senior" and
    -- forgetting is the obvious way to be surprised by an output. Hovering
    -- answers it without opening the menu.
    --
    -- With auto-tone on, the honest answer names the fallback rather than the
    -- audience: the app you are typing in may well override it a second later.
    bar:setTooltip(string.format("crisp-english - %s - writing for: %s%s",
      warm and "ready" or "model asleep, next one is slow",
      toneLabel(state.tone),
      state.autoTone and " (unless the app says otherwise)" or ""))
  end

  -- Ask Ollama what is resident. Async, so a hung or absent Ollama never stalls
  -- the menubar or the hotkey.
  local function refreshWarm(done)
    ollama.loaded(state, function(isWarm, minutesLeft, gb)
      warm, freesIn, heldGB = isWarm, minutesLeft, gb
      render()
      if done then done(isWarm) end
    end)
  end

  local function warmNow()
    ollama.warm(state, function() refreshWarm() end)
    render()
  end

  -- Drop the model without turning crisp-english off. The hotkey keeps working; the next
  -- correction just pays a cold load. This is here because the menu is where
  -- someone notices the machine is tight, and making them turn the whole tool
  -- off to reclaim the memory would be a worse trade than waiting 30s once.
  local function unloadNow()
    ollama.unload(state, function() refreshWarm() end)
  end

  local function startOllama()
    ollama.start(state, function(up)
      if up then warmNow() else refreshWarm() end
    end)
  end

  -- Count today's corrections out of the log corrector.py already writes. Cheap,
  -- and only done when the menu is opened.
  local function todayCount()
    local today = os.date("%Y-%m-%d")
    local f = io.open(os.getenv("HOME") .. "/.crisp-english/mistakes.log", "r")
    if not f then return 0 end
    local n = 0
    for line in f:lines() do
      if line:find(today, 1, true) then n = n + 1 end
    end
    f:close()
    return n
  end

  -- Show `corrector.py stats` in a real text window rather than an alert: the
  -- output is an aligned bar chart, and hs.alert is not monospaced so it would
  -- render as ragged nonsense.
  local function showStats()
    local out = "/tmp/crisp-english-stats.txt"
    hs.task.new(state.python, function(_, stdout, stderr)
      local f = io.open(out, "w")
      if f then
        f:write((stdout ~= "" and stdout) or stderr or "no output")
        f:close()
        hs.execute("open -t " .. out)
      end
    end, { state.project .. "/corrector.py", "stats" }):start()
  end

  bar:setMenu(function()
    local menu = {
      -- Not `state.enabled = not state.enabled` any more. setEnabled lives in
      -- init.lua and also starts or releases Ollama, so the menu and
      -- `crisp-englishctl on|off` cannot mean two different things.
      { title = state.enabled and "Turn crisp-english off" or "Turn crisp-english on",
        fn = function() state.setEnabled(not state.enabled) end },
      { title = "-" },
    }

    if state.enabled then
      local modelRow
      if not warm then
        modelRow = "Model: asleep (next one takes ~30s)"
      elseif freesIn and heldGB then
        modelRow = string.format("Model: ready (frees %.1f GB in %d min)",
                                 heldGB, freesIn)
      elseif freesIn then
        modelRow = string.format("Model: ready (frees in %d min)", freesIn)
      else
        modelRow = "Model: ready"
      end
      table.insert(menu, { title = modelRow, disabled = true })
      if warm then
        table.insert(menu, { title = "   Free the memory now", fn = unloadNow })
      else
        table.insert(menu, { title = "   Wake it now", fn = warmNow })
      end
      -- Writing for, as a submenu. A submenu rather than three top-level rows
      -- because the current choice matters more than the options: the parent row
      -- always shows which one is active without opening anything.
      local toneMenu = {}
      for _, t in ipairs(TONES) do
        table.insert(toneMenu, {
          -- Label only. The explanation of what each one does belongs in the
          -- guide, not in a menu you open to make a two-item choice.
          title = t.label,
          -- setTone rather than `state.tone = t.id`: it validates the name,
          -- writes it to ~/.crisp-english/state so it survives a reload, and re-renders.
          -- The direct assignment did none of those, which is why this setting
          -- used to reset itself.
          checked = (state.tone == t.id),
          fn = function() state.setTone(t.id) end,
        })
      end
      if state.autoTone then
        table.insert(toneMenu, { title = "-" })
        table.insert(toneMenu, {
          title = "Slack and Mail choose for themselves",
          disabled = true,
        })
        table.insert(toneMenu, {
          title = "   the choice above is the fallback",
          disabled = true,
        })
      end
      table.insert(menu, { title = "Writing for: " .. toneLabel(state.tone)
                             .. (state.autoTone and "  (auto)" or ""),
                           menu = toneMenu })

      table.insert(menu, {
        title = "Show what changed on screen",
        checked = state.showAlerts,
        fn = function() state.setAlerts(not state.showAlerts) end,
      })
      table.insert(menu, { title = "-" })
      table.insert(menu, {
        title = todayCount() .. " corrections today",
        disabled = true,
      })
      table.insert(menu, { title = "My frequent mistakes...", fn = showStats })
      table.insert(menu, { title = "-" })
    end

    table.insert(menu, {
      title = "Start at login",
      checked = hs.autoLaunch(),
      fn = function() hs.autoLaunch(not hs.autoLaunch()) end,
    })
    table.insert(menu, { title = "Start Ollama", fn = startOllama })
    table.insert(menu, { title = "Reload crisp-english", fn = function() hs.reload() end })
    return menu
  end)

  -- Let init.lua drive the busy glyph. A poll would lag behind a 1.5s correction
  -- badly enough to be worse than showing nothing.
  -- setEnabled flips the icon through this, then again when Ollama answers.
  -- Without it the menu bar would keep showing the old state for the several
  -- seconds it takes to launch Ollama and load a model.
  state.onChange = function()
    render()
    refreshWarm()
  end

  state.onBusyChange = function(isBusy)
    busy = isBusy
    render()
    if not isBusy then refreshWarm() end   -- a correction just warmed the model
  end

  M.bar = bar        -- exposed so the icon can be inspected from `hs -c`
  render()
  refreshWarm()
  -- 30s is well inside the 1h keep_alive, so the icon is never stale for long,
  -- and one localhost GET twice a minute costs nothing measurable.
  -- Stored on M, never read. That is the point: a Hammerspoon timer with no
  -- live reference is garbage collected and quietly stops firing, which is the
  -- same reasoning init.lua documents for state.sleepWatcher.
  M.timer = hs.timer.doEvery(30, function() refreshWarm() end)
end

return M
