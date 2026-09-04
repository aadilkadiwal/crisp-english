-- crisp-english/state.lua - the settings that have to survive a reload.
--
-- `enabled` was already persisted, with care, because the login warm-up job has
-- to know whether crisp-english is switched off. Nothing else was, and that was an
-- inconsistency with teeth: `crisp-englishctl tone slack` followed by `crisp-englishctl reload`
-- silently went back to "Client or senior", and so did every Hammerspoon
-- restart, because state.tone was a field in a table literal. A setting you can
-- change from three places and that resets without telling you is worse than a
-- setting you cannot change.
--
-- Same KEY=value format as crisp-english.conf, for the same reason: crisp-englishctl reads this
-- file with grep and cut, and the launch agent with sh. `enabled` is written
-- first so those one-liners stay one-liners.
--
-- ~/.crisp-english/enabled (a single bare word) is still written by init.lua alongside
-- this, so an install whose launch agent has not been replaced keeps working.

local M = {}

-- Tones this file is allowed to load. A state file written by a future version
-- must not put a name into the running config that corrector.py would degrade
-- to default and the menu would show a checkmark against nothing.
local KNOWN_TONES = { formal = true, brief = true, default = true }

-- Every function takes the path. init.lua owns where the file lives, next to the
-- bare-word `enabled` flag it also writes, so this module does not need to know.
function M.save(path, state)
  local file = io.open(path, "w")
  if not file then
    return false
  end
  -- Order matters: `enabled` first, see the header.
  file:write(string.format("enabled=%s\ntone=%s\nshowAlerts=%s\n",
    tostring(not not state.enabled),
    tostring(state.tone or "formal"),
    tostring(not not state.showAlerts)))
  file:close()
  return true
end

-- Returns a table with only the fields that were actually present and valid, so
-- a caller can tell "absent" from "false" and fall back to its own default.
function M.load(path)
  local out = {}
  local file = io.open(path, "r")
  if not file then
    return out
  end
  for line in file:lines() do
    local key, value = line:match("^([A-Za-z_]+)=(.*)$")
    if key == "enabled" or key == "showAlerts" then
      if value == "true" then
        out[key] = true
      elseif value == "false" then
        out[key] = false
      end
    elseif key == "tone" and KNOWN_TONES[value] then
      out[key] = value
    end
  end
  file:close()
  return out
end

return M
