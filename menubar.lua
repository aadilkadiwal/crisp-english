-- saaf menubar - status and controls, without a popup.
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

local M = {}

-- Icon vocabulary. Deliberately four distinguishable glyphs rather than colour,
-- which is unreadable at menubar size and invisible to some people.
local ICON = {
  disabled = "○",   -- off; the hotkey does nothing
  cold     = "◇",   -- on, but the model is asleep: the next one takes ~30s
  warm     = "◆",   -- on and hot: the next one takes ~1.5s
  busy     = "◈",   -- correcting right now
}

-- Who the message is going to. Names must match TONES in corrector.py.
-- Ordered by how often they are wanted, not alphabetically.
local TONES = {
  { id = "default", label = "Colleague",
    hint = "normal work register - contractions, brief" },
  { id = "formal",  label = "Client or senior",
    hint = "complete sentences, no contractions" },
  { id = "brief",   label = "Slack / WhatsApp",
    hint = "fewest words that stay polite" },
}

local function toneLabel(id)
  for _, t in ipairs(TONES) do
    if t.id == id then return t.label end
  end
  return id
end

function M.attach(state)
  local bar = hs.menubar.new()
  if not bar then
    return nil                       -- no menubar available; nothing else to do
  end

  local warm, busy = false, false

  local function icon()
    if not state.enabled then return ICON.disabled end
    if busy then return ICON.busy end
    return warm and ICON.warm or ICON.cold
  end

  local function render()
    bar:setTitle(icon())
    if not state.enabled then
      bar:setTooltip("saaf - off")
      return
    end
    -- The tone is in the tooltip because leaving it on "Client or senior" and
    -- forgetting is the obvious way to be surprised by an output. Hovering
    -- answers it without opening the menu.
    bar:setTooltip(string.format("saaf - %s - writing for: %s",
      warm and "ready" or "model asleep, next one is slow",
      toneLabel(state.tone)))
  end

  -- Ask Ollama what is resident. Async, so a hung or absent Ollama never stalls
  -- the menubar or the hotkey.
  local function refreshWarm(done)
    hs.http.asyncGet(state.ollama .. "/api/ps", nil, function(status, body)
      local isWarm = false
      if status == 200 and body then
        local ok, parsed = pcall(hs.json.decode, body)
        if ok and type(parsed) == "table" and parsed.models then
          for _, m in ipairs(parsed.models) do
            if m.name == state.model or m.model == state.model then
              isWarm = true
              break
            end
          end
        end
      end
      warm = isWarm
      render()
      if done then done(isWarm) end
    end)
  end

  -- Ollama reachable at all? Distinct from warm: not running vs running-but-cold
  -- need different menu entries, because only one of them is fixable by waiting.
  local function ollamaUp(done)
    hs.http.asyncGet(state.ollama .. "/api/tags", nil, function(status)
      done(status == 200)
    end)
  end

  local function warmNow()
    -- Same options corrector.py sends. Ollama keys its loaded-model cache on
    -- these, so a mismatch would load the model a SECOND time and waste the
    -- warm-up entirely.
    local body = hs.json.encode({
      model = state.model, prompt = "hi", stream = false, think = false,
      keep_alive = "8h", options = { num_predict = 1, num_ctx = 2048 },
    })
    hs.http.asyncPost(state.ollama .. "/api/generate", body,
      { ["Content-Type"] = "application/json" },
      function() refreshWarm() end)
    render()
  end

  local function startOllama()
    hs.execute("open -a Ollama")
    -- Give it time to bind the port, then warm the model so the first correction
    -- after a cold boot is not also a cold load.
    hs.timer.doAfter(4, function()
      ollamaUp(function(up)
        if up then warmNow() end
      end)
    end)
  end

  -- Count today's corrections out of the log corrector.py already writes. Cheap,
  -- and only done when the menu is opened.
  local function todayCount()
    local today = os.date("%Y-%m-%d")
    local f = io.open(os.getenv("HOME") .. "/.saaf/mistakes.log", "r")
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
    local out = "/tmp/saaf-stats.txt"
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
      { title = state.enabled and "Turn saaf off" or "Turn saaf on",
        fn = function()
          state.enabled = not state.enabled
          render()
        end },
      { title = "-" },
    }

    if state.enabled then
      table.insert(menu, {
        title = warm and "Model: ready" or "Model: asleep (next one takes ~30s)",
        disabled = true,
      })
      if not warm then
        table.insert(menu, { title = "   Wake it now", fn = warmNow })
      end
      -- Writing for, as a submenu. A submenu rather than three top-level rows
      -- because the current choice matters more than the options: the parent row
      -- always shows which one is active without opening anything.
      local toneMenu = {}
      for _, t in ipairs(TONES) do
        table.insert(toneMenu, {
          title = t.label .. "   -   " .. t.hint,
          checked = (state.tone == t.id),
          fn = function()
            state.tone = t.id
            render()
          end,
        })
      end
      table.insert(menu, { title = "Writing for: " .. toneLabel(state.tone),
                           menu = toneMenu })

      table.insert(menu, {
        title = "Show what changed on screen",
        checked = state.showAlerts,
        fn = function() state.showAlerts = not state.showAlerts end,
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
    table.insert(menu, { title = "Reload saaf", fn = function() hs.reload() end })
    return menu
  end)

  -- Let init.lua drive the busy glyph. A poll would lag behind a 1.5s correction
  -- badly enough to be worse than showing nothing.
  state.onBusyChange = function(isBusy)
    busy = isBusy
    render()
    if not isBusy then refreshWarm() end   -- a correction just warmed the model
  end

  render()
  refreshWarm()
  -- 30s is well inside the 8h keep_alive, so the icon is never stale for long,
  -- and one localhost GET twice a minute costs nothing measurable.
  M.timer = hs.timer.doEvery(30, function() refreshWarm() end)

  return {
    refresh = refreshWarm,
    startOllama = startOllama,
    bar = bar,
  }
end

return M
