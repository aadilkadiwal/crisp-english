-- crisp-english/audience.lua - pick who you are writing to from the app you are in.
--
-- menubar.lua carries this comment about the tone setting: "leaving it on
-- 'Client or senior' and forgetting is the obvious way to be surprised by an
-- output", and answers it with a tooltip. A tooltip tells you about the problem;
-- it does not fix it. The frontmost application is already known at the moment
-- the hotkey fires, and it answers the question better than a menu does: a
-- message you are typing in Slack is not going to a client.
--
-- So the menu choice becomes the fallback, not the decision. Set
-- CRISP_ENGLISH_AUTO_TONE=0 in crisp-english.conf to go back to the menu deciding everything.
--
-- Every value here must be a tone corrector.py knows (see TONES there). The
-- test suite asserts that, because a menu item and a Python dict disagreeing
-- about a name is a bug this project has already had.

local M = {}

-- Keyed on the application NAME as macOS reports it.
--
-- Only apps whose audience is genuinely unambiguous are listed. A browser is
-- not: Gmail, Jira, Slack's web client and a client's admin panel are all
-- "Google Chrome" from the outside, and guessing between them would be worse
-- than not guessing at all. Browsers therefore fall through to the menu choice.
M.MAP = {
  -- Chat: colleagues, short messages, fewest words that stay polite.
  ["Slack"] = "brief",
  ["WhatsApp"] = "brief",
  ["Discord"] = "brief",
  ["Telegram"] = "brief",
  ["Messages"] = "brief",
  ["Microsoft Teams"] = "brief",
  ["Signal"] = "brief",

  -- Mail: clients and people senior to you, complete sentences.
  ["Mail"] = "formal",
  ["Gmail"] = "formal",
  ["Microsoft Outlook"] = "formal",
  ["Outlook"] = "formal",
  ["Spark"] = "formal",
  ["Superhuman"] = "formal",
  ["Thunderbird"] = "formal",
  ["Airmail"] = "formal",
}

-- The tone this app implies, or nil if it has no opinion.
function M.forApp(name)
  if type(name) ~= "string" or name == "" then
    return nil
  end
  if M.MAP[name] then
    return M.MAP[name]
  end
  -- Case-insensitive second pass, because app names are reported with the
  -- casing the bundle declares and that is not something to be strict about.
  local lower = name:lower()
  for app, tone in pairs(M.MAP) do
    if app:lower() == lower then
      return tone
    end
  end
  return nil
end

-- What to actually use: the app's opinion when auto-tone is on and it has one,
-- otherwise whatever the menu bar says.
function M.resolve(appName, menuTone, autoOn)
  if autoOn then
    local fromApp = M.forApp(appName)
    if fromApp then
      return fromApp
    end
  end
  return menuTone
end

return M
