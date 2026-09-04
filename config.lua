-- crisp-english/config.lua - read crisp-english.conf, the one file all four languages share.
--
-- Three comments in this project used to open with "THIS NUMBER EXISTS IN FOUR
-- PLACES and they have to agree", followed by a hand-written list of the other
-- three. Python, Lua, shell and launchd cannot share a constant, but they can
-- all read the same KEY=value file, and now they do. See crisp-english.conf.
--
-- Precedence, matching corrector.py's setting(): environment variable, then
-- ~/.crisp-english/crisp-english.conf, then the project's crisp-english.conf, then the default the
-- caller passes in. So a machine-specific override never means editing the repo.
--
-- Pure enough to reason about on its own: no Hammerspoon state, no I/O beyond
-- reading the file it is given.

local M = {}

-- Where this file lives, so the project's own crisp-english.conf can be found whether
-- init.lua was symlinked into ~/.hammerspoon or dofile'd from someone's config.
local PROJECT = (function()
  local src = debug.getinfo(1, "S").source:gsub("^@", "")
  return src:match("^(.*)/[^/]+$")
end)()

-- Parse KEY=value lines. Returns an empty table for a missing file, which is
-- the normal case for the user's optional override.
--
-- The accepted syntax is deliberately the smallest thing Python, Lua and sh can
-- all agree on without any of them being clever: no spaces around "=", no shell
-- expansion, optional quotes, " #" starts a comment.
function M.read(path)
  local settings = {}
  local file = io.open(path, "r")
  if not file then
    return settings
  end
  for line in file:lines() do
    -- strip a trailing comment before anything else
    line = line:gsub("%s+#.*$", "")
    local key, value = line:match("^%s*([A-Za-z_][A-Za-z0-9_]*)%s*=%s*(.-)%s*$")
    if key then
      value = value:gsub('^"(.*)"$', "%1"):gsub("^'(.*)'$", "%1")
      settings[key] = value
    end
  end
  file:close()
  return settings
end

local cache = nil

local function files()
  if not cache then
    cache = M.read(PROJECT .. "/crisp-english.conf")
    -- The user's own file wins over the project's.
    for k, v in pairs(M.read(os.getenv("HOME") .. "/.crisp-english/crisp-english.conf")) do
      cache[k] = v
    end
  end
  return cache
end

function M.get(key, default)
  local fromEnv = os.getenv(key)
  if fromEnv and fromEnv ~= "" then
    return fromEnv
  end
  local value = files()[key]
  if value and value ~= "" then
    return value
  end
  return default
end

function M.number(key, default)
  return tonumber(M.get(key, tostring(default))) or default
end

-- "1", "true", "yes", "on" are true; everything else is false. Matches
-- corrector.py's _flag(), so CRISP_ENGLISH_AUTO_TONE=0 means the same thing on both
-- sides of the process boundary.
function M.flag(key, default)
  local value = tostring(M.get(key, default)):lower()
  return value == "1" or value == "true" or value == "yes" or value == "on"
end

-- No cache-invalidation function on purpose. `crisp-englishctl reload` calls
-- hs.reload(), which re-executes init.lua and re-requires this module from
-- scratch, so an edited crisp-english.conf is picked up with nothing extra to call.

return M
