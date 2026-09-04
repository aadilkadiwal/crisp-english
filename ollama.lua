-- crisp-english/ollama.lua - the one place that knows how to talk to and control Ollama.
--
-- Split out of menubar.lua because the menu bar is optional and Ollama is not.
-- init.lua guarantees the hotkey keeps working if menubar.lua is missing or
-- throws, so anything the hotkey path depends on cannot live in that file. Both
-- now call in here instead of each keeping their own copy of the HTTP calls.
--
-- Everything is async. A hung or absent Ollama must never stall the hotkey, and
-- `open -a Ollama` on a cold machine takes seconds.
--
-- Interface: every function takes the state table init.lua owns, and reads only
-- two fields from it - state.ollama (base URL) and state.model. It writes
-- nothing. Deciding what to do with the answers is the caller's job.

local config = require("config")

local M = {}

-- How long Ollama keeps the model resident after the last request, and the
-- context size every request must agree on.
--
-- These two numbers used to be literals here, in corrector.py, in crisp-englishctl and
-- in the plist, with a comment in each of the four naming the other three. They
-- now come from crisp-english.conf, which is the only way four languages can actually
-- share a value rather than promise to.
--
-- Why 1h: it was 8h, paired with a launch agent that re-warmed every 7h. Those
-- two numbers together meant the model never unloaded: 2.9GB of a 16GB machine
-- held permanently, overnight and on battery, whether or not anything was
-- corrected that day. The measured cost was 148k pageouts and other apps
-- swapping. 1h means the model releases itself an hour after you stop writing,
-- and the first correction after a gap pays a cold load. Corrections cluster,
-- so that is a handful of cold loads a day rather than one per message.
M.KEEP_ALIVE = config.get("CRISP_ENGLISH_KEEP_ALIVE", "1h")

-- Ollama keys its loaded-model cache on the options, so warming with a
-- different num_ctx loads the model a SECOND time and wastes the warm-up
-- entirely - the thing this module exists to avoid.
M.NUM_CTX = config.number("CRISP_ENGLISH_NUM_CTX", 2048)

local WARM_OPTIONS = { num_predict = 1, num_ctx = M.NUM_CTX }

local JSON_HEADERS = { ["Content-Type"] = "application/json" }

-- Is Ollama listening at all? Distinct from `loaded` below: "not running" and
-- "running but cold" are different problems, and only one of them is fixed by
-- waiting.
function M.up(state, done)
  hs.http.asyncGet(state.ollama .. "/api/tags", nil, function(status)
    done(status == 200)
  end)
end

-- Is OUR model in this /api/ps response? Returns the entry, or nil.
--
-- Pure, and separate, because the question is subtle enough to get wrong twice.
-- "Is anything resident" is not the same as "is our model resident", and both
-- init.lua and crisp-englishctl had asked the first one while reporting the
-- second: measured with gemma3:4b loaded and qwen3:4b not, both said warm and
-- the user then waited 30s for a load nothing had warned about.
function M.findModel(parsed, model)
  if type(parsed) ~= "table" or type(parsed.models) ~= "table" then
    return nil
  end
  for _, m in ipairs(parsed.models) do
    -- Ollama reports the name under `name` or `model` depending on the endpoint.
    if m.name == model or m.model == model then
      return m
    end
  end
  return nil
end

-- Is state.model resident, when does Ollama intend to drop it, and how much is
-- it holding?
--
-- Calls back with (isLoaded, minutesLeft, gigabytes). The last two are nil when
-- they cannot be worked out, which callers must treat as "unknown" rather than
-- "expired" or "nothing" - guessing wrong there would report memory as free
-- while it is still held. The size comes from Ollama rather than a constant
-- because it depends on which model is configured, and CRISP_ENGLISH_MODEL can
-- change it.
function M.loaded(state, done)
  hs.http.asyncGet(state.ollama .. "/api/ps", nil, function(status, body)
    if status ~= 200 or not body then
      return done(false, nil, nil)
    end
    local ok, parsed = pcall(hs.json.decode, body)
    if not ok then
      return done(false, nil, nil)
    end
    local m = M.findModel(parsed, state.model)
    if not m then
      return done(false, nil, nil)
    end
    local gb = tonumber(m.size) and (tonumber(m.size) / 1e9) or nil
    done(true, M.minutesLeft(m.expires_at), gb)
  end)
end

-- Minutes until an Ollama expires_at timestamp, or nil if it cannot be read.
--
-- The timestamp is ISO8601 with an offset ("2026-09-04T03:51:37.6+05:30"). The
-- server is on localhost, so its offset is our offset, which means the wall
-- clock fields can be handed straight to os.time() as local time and the offset
-- ignored. That shortcut is only safe because the server cannot be remote.
function M.minutesLeft(expiresAt)
  if type(expiresAt) ~= "string" then return nil end
  local y, mo, d, h, mi, s = expiresAt:match(
    "^(%d+)-(%d+)-(%d+)T(%d+):(%d+):(%d+)")
  if not y then return nil end
  local expiry = os.time({
    year = tonumber(y), month = tonumber(mo), day = tonumber(d),
    hour = tonumber(h), min = tonumber(mi), sec = tonumber(s),
  })
  if not expiry then return nil end
  local left = math.floor(os.difftime(expiry, os.time()) / 60)
  return left >= 0 and left or 0
end

-- Load the model into memory and start its keep_alive clock.
function M.warm(state, done)
  local body = hs.json.encode({
    model = state.model, prompt = "hi", stream = false, think = false,
    keep_alive = M.KEEP_ALIVE, options = WARM_OPTIONS,
  })
  hs.http.asyncPost(state.ollama .. "/api/generate", body, JSON_HEADERS,
    function(status) if done then done(status == 200) end end)
end

-- Drop the model from memory now, without touching the Ollama server itself.
--
-- keep_alive 0 is Ollama's documented way to evict: it expires the model
-- immediately rather than killing anything, so a request that arrives a moment
-- later simply reloads it. Nothing else Ollama is serving is affected.
function M.unload(state, done)
  local body = hs.json.encode({
    model = state.model, prompt = "", keep_alive = 0,
  })
  hs.http.asyncPost(state.ollama .. "/api/generate", body, JSON_HEADERS,
    function(status) if done then done(status == 200) end end)
end

-- Launch the Ollama app and wait for it to bind the port.
--
-- Polled rather than slept: the old code waited a flat 4 seconds, which was too
-- long on a warm machine and not long enough on a cold one. Calls back with
-- whether it actually came up, so the caller can say so instead of assuming.
function M.start(state, done)
  hs.execute("open -a Ollama")
  local tries = 0
  local timer
  timer = hs.timer.doEvery(1, function()
    tries = tries + 1
    M.up(state, function(isUp)
      if isUp or tries >= 20 then
        timer:stop()
        if done then done(isUp) end
      end
    end)
  end)
end

-- Quit the Ollama application. Only ever called when crisp-english was the one that
-- started it.
--
-- SIGTERM via killall, not AppleScript. The polite version -
--   osascript -e 'tell application "Ollama" to quit'
-- was tried first and does not work: Ollama answers it with error -128, "User
-- cancelled", and keeps running. It appears not to implement the quit event at
-- all, so the tool would have reported success and silently left 2.9GB held.
--
-- killall sends SIGTERM, which is a request to exit rather than a kill, so the
-- app still gets to shut down cleanly. Verified: the parent takes `ollama serve`
-- and llama-server with it, and port 11434 stops listening.
function M.quit()
  local _, ok = hs.execute("killall Ollama 2>/dev/null")
  return ok == true
end

return M
