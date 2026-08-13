"""Deterministic post-processing. No model involved.

The benchmark showed qwen3:8b emits "do the needful" and "kindly" in roughly a
third of cases even when the prompt bans those exact strings. Instruction-following
is not a reliable enforcement mechanism, so anything that can be checked by rule is
checked here instead: zero latency, no compliance required, and it works identically
on a 4b model as on an 8b one.

Groups 2 and 3 are lifted from the `realtone` skill's zero-tolerance blocklist and
its copula-avoidance / filler-phrase patterns. Group 1 is Indian-English office
filler, which realtone does not cover.

Two kinds of rule:
  SUBSTITUTIONS - a safe, meaning-preserving replacement exists. Applied silently.
  REJECTIONS    - no safe automatic replacement. The variant is regenerated.
"""

import re

# --- Group 1: Indian-English office filler ---------------------------------
# Safe rewrites. "do the needful" has no fixed meaning, so it is a rejection, not
# a substitution - only the model knows what action was actually intended.
SUBSTITUTIONS = {
    r"\brevert back to\b": "reply to",
    r"\brevert back\b": "reply",
    r"\bkindly\b": "please",
    r"\bplease please\b": "please",          # artifact of the line above
    r"\bintimate\b": "inform",
    r"\bprepone\b": "move earlier",
    r"\bsame is (attached|enclosed)\b": r"it is \1",
    r"\bas per your (kind )?(request|instruction)s?\b": "as you asked",

    # --- Group 3: copula avoidance (realtone #8) ---
    r"\bserves as\b": "is",
    r"\bstands as\b": "is",
    r"\bfunctions as\b": "is",

    # --- Group 3: filler phrases (realtone #22) ---
    r"\bin order to\b": "to",
    r"\bdue to the fact that\b": "because",
    r"\bat this point in time\b": "now",
    r"\bat the earliest\b": "as soon as possible",
    r"\bit is important to note that\b": "",
    r"\bit'?s worth noting that\b": "",
    r"\bplease be informed that\b": "",
    r"\bplease do not hesitate to\b": "feel free to",

    # --- Group 5: realtone #29, zombie nouns -------------------------------
    # A noun built from a verb, plus a weak helper verb. The plain verb is
    # shorter and sounds like a person. This is one of the strongest AI tells
    # in short work messages.
    r"\bprovide (?:a )?clarification\b": "clarify",
    r"\bprovide (?:an )?update\b": "update you",
    r"\bprovide (?:an )?explanation\b": "explain",
    r"\bperform (?:a )?review\b": "review",
    r"\bconduct (?:a )?review\b": "review",
    r"\bcarry out (?:a )?review\b": "review",
    r"\bmake (?:a )?decision\b": "decide",
    r"\bgive (?:a )?confirmation\b": "confirm",
    r"\bdo (?:an )?investigation\b": "investigate",
    r"\bhave (?:a )?discussion (?:about|on|regarding)\b": "discuss",
    r"\btake (?:into )?consideration\b": "consider",
    r"\bmake (?:an )?improvement\b": "improve",
    r"\bimplementation of\b": "implementing",
    r"\butilization of\b": "using",

    # --- Group 5: realtone #21, sycophantic openers ------------------------
    r"^\s*Certainly[,.!]?\s*": "",
    r"^\s*Absolutely[,.!]?\s*": "",
    r"^\s*Of course[,.!]?\s*": "",
    r"\bI'?d be happy to\b": "I can",
    r"\bI would be happy to\b": "I can",
    r"\bI would be glad to\b": "I can",

    # --- Group 5: realtone #24, generic positive conclusions ---------------
    # Only removed when it trails the end of the text, so a genuine
    # "looking forward to the demo tomorrow" mid-message survives.
    r"\s*Looking forward to hearing from you[.!]?\s*$": "",
    r"\s*Thanks in advance[.!]?\s*$": "",
    r"\s*Please let me know if you have any (?:further )?questions[.!]?\s*$": "",

    # --- shorthand: model forgets these; regex never does ---
    r"\bpls\b": "please",
    r"\bplz\b": "please",
    r"\bthx\b": "thanks",
    r"\btq\b": "thanks",
    r"\basap\b": "as soon as possible",
    r"\bfyi\b": "for your information",
    r"\bwrt\b": "with respect to",
    r"\bu\b": "you",
    r"\bur\b": "your",
    r"\bpl\b": "please",
}

# Phrases that carry no recoverable meaning. Measured: reissuing the request with
# the phrase named explicitly does NOT fix these, because there is no action to
# substitute - "do the needful" could mean review it, approve it, or deploy it, and
# nothing in the text says which. A model that "fixes" this is guessing at intent.
#
# The correct behaviour is to tell the writer, not to guess. The popup surfaces the
# hint and leaves the sentence alone.
UNFIXABLE = {
    "do the needful":
        "\"do the needful\" does not say what you want. Name the action: "
        "review it, approve it, deploy it.",
    "the needful":
        "\"the needful\" does not say what you want. Name the action.",
    "please do the same":
        "\"do the same\" is unclear unless the action was just stated.",
    "kindly cooperate":
        "\"kindly cooperate\" asks for nothing specific. Say what you need.",
}


# Words with a real meaning but no safe mechanical replacement. realtone is
# explicit: "Don't just swap these for synonyms - restructure the sentence so the
# word isn't needed at all." Restructuring needs the model, so these trigger one
# retry, which is measured to work: "leverage the new API to facilitate faster
# onboarding" -> "use the new API to speed up onboarding".
REJECTIONS = [
    # realtone: Claude-family tells
    "leverage", "utilize", "facilitate", "noteworthy", "nuanced",
    "comprehensive", "robust",
    # realtone: GPT-4 / 4o / 5 era vocabulary
    "delve", "intricate", "meticulous", "pivotal", "underscore", "testament",
    "tapestry", "vibrant", "crucial", "additionally", "furthermore", "moreover",
    "showcasing", "exemplifies", "fosters", "bolsters", "enduring", "garner",
    "interplay", "align with",
    # realtone: phrase blocklist
    "not only", "let's dive in", "let's explore", "let's unpack",
    "here's the thing", "the truth is", "at its core", "in today's",
    "hope this email finds you well", "hope you are doing well",
    "circle back", "touch base", "reach out to", "going forward",
]

# realtone Phase 2 hard character checks. Straight quotes, no em dashes, no emoji.
CHARACTER_FIXES = {
    "—": ", ",     # em dash
    "–": "-",      # en dash
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "…": "...",
    " ": " ",      # non-breaking space
}

EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF☀-➿️⬀-⯿]"
)


# --- Group 4: recurring grammar patterns -----------------------------------
# Benchmarking showed both qwen3:4b and qwen3:8b fail the SAME small set of
# grammar patterns, repeatedly, despite explicit prompt rules naming each one.
# They are recurring and closed-form, so they are rules, not judgment calls.
# Fixing them here is what lets the smaller, cooler-running model be sufficient.

PAST_MARKER = (r"yesterday|last (?:night|week|month|year|monday|tuesday|wednesday"
               r"|thursday|friday|saturday|sunday)|\b\d+ (?:days?|weeks?|months?|"
               r"years?) ago|\bago\b|earlier today|this morning")

# Common irregular past participles, plus the regular -ed case. Dropping the
# auxiliary is the correct fix: "I have sent it yesterday" -> "I sent it yesterday".
PARTICIPLE = (r"sent|done|gone|seen|made|given|taken|written|spoken|come|got|gotten|"
              r"put|read|told|found|left|paid|met|held|kept|built|sold|"
              r"\w+ed")


def _fix_present_perfect_with_past_time(text):
    """'I have sent it yesterday' -> 'I sent it yesterday'.

    Only fires when a past time marker is actually present, so correct present
    perfect ('I have sent it already') is left alone.
    """
    if not re.search(PAST_MARKER, text, re.IGNORECASE):
        return text
    return re.sub(
        rf"\b(?:have|has)\s+({PARTICIPLE})\b",
        lambda m: m.group(1),
        text, flags=re.IGNORECASE)


GRAMMAR_FIXES = {
    # "myself Aadil" is not an English introduction
    r"\bmyself\s+([A-Z][a-z]+)": r"I am \1",
    r"^\s*myself\b": "I am",

    # duration takes "for", not "since"
    r"\bsince\s+(\d+|a|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(year|month|week|day)s?\b": r"for \1 \2s",

    # "having" is not used for possession.
    # Deliberately narrow: "we are having a meeting/call/lunch" is CORRECT English
    # (a scheduled activity, not possession), so those nouns are excluded. A false
    # positive here rewrites text that was already fine, which is worse than a miss.
    # A lookahead, not a fixed slot, because the noun can sit several words later:
    # "I am having 4 years of experience" as well as "I am having doubt".
    r"\bam\s+having\b(?=[^.!?]*?\b(?:experience|doubt|doubts|question|questions|"
    r"problem|problems|issue|issues|fever|headache|cold|idea|access|permission)\b)":
        "have",
    r"\b(?:is|are)\s+having\b(?=[^.!?]*?\b(?:experience|doubt|doubts|question|"
    r"questions|problem|problems|issue|issues|fever|headache|cold|idea|access|"
    r"permission)\b)": "has",

    # "N years experience" needs "of"
    r"\b(\d+)\s+(year|month)s?\s+experience\b": r"\1 \2s of experience",

    # discuss / reply take no preposition here
    r"\bdiscussed?\s+about\b": "discussed",
    r"\bdiscussing\s+about\b": "discussing",

    # "one of my X" needs a plural
    r"\bone of (?:my|our|the)\s+(colleague|friend|client|team member|developer)\b":
        r"one of my \1s",

    # "did" takes the base verb
    r"\bdidn'?t\s+got\b": "didn't get",
    r"\bdidn'?t\s+went\b": "didn't go",
    r"\bdidn'?t\s+came\b": "didn't come",
    r"\bdid\s+not\s+got\b": "did not get",

    # "to" takes the base verb
    r"\bto\s+came\b": "to come",
    r"\bto\s+went\b": "to go",
    r"\bto\s+sent\b": "to send",

    # dropped article before common workplace nouns
    r"\b(to|at|in|from)\s+office\b": r"\1 the office",

    # redundant 'that' before a question word
    r"\b(tell|ask|know|explain)\s+(me|him|her|us|them)?\s*that\s+(when|where|why|how|what)\b":
        r"\1 \2 \3",
}


def _match_case(replacement, original):
    """Keep the original capitalisation so mid-sentence fixes don't look wrong."""
    # An ALL-CAPS original is an abbreviation, not emphasis. Expanding "ASAP" to
    # "AS SOON AS POSSIBLE" reads as shouting, and "As soon as possible" carries a
    # stray capital into the middle of a sentence. Return it plain; the
    # sentence-capitalisation pass in clean() fixes it if it lands first.
    if original.isupper() and len(original) > 1:
        return replacement.upper() if " " not in replacement else replacement
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def clean(text):
    """Apply every safe, meaning-preserving fix. Returns cleaned text."""
    for bad, good in CHARACTER_FIXES.items():
        text = text.replace(bad, good)
    text = EMOJI.sub("", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)        # realtone #14: no boldface

    for pattern, replacement in SUBSTITUTIONS.items():
        text = re.sub(pattern,
                      lambda m: _match_case(replacement, m.group(0)),
                      text, flags=re.IGNORECASE)

    # grammar patterns use backreferences, so they are applied directly rather
    # than through _match_case
    for pattern, replacement in GRAMMAR_FIXES.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = _fix_present_perfect_with_past_time(text)

    # sentences must start with a capital, and standalone "i" is always "I"
    text = re.sub(r"\bi\b", "I", text)

    # tidy up damage from deletions
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"^\s*[,;:]\s*", "", text)
    text = re.sub(r"([.!?])\s*([a-z])",
                  lambda m: f"{m.group(1)} {m.group(2).upper()}", text)
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def violations(text):
    """Words a model retry can plausibly remove. Empty list means the text passes."""
    low = text.lower()
    return [w for w in REJECTIONS if re.search(rf"\b{re.escape(w)}", low)]


def hints(text):
    """Advice for phrases no tool can fix, because they carry no meaning.

    Returned to the popup as a warning line. The sentence is left untouched: only
    the writer knows what action was intended.
    """
    low = text.lower()
    matched = [p for p in UNFIXABLE if re.search(rf"\b{re.escape(p)}", low)]
    # "do the needful" also matches "the needful"; report only the most specific
    # phrase so the popup does not show the same advice twice.
    specific = [p for p in matched
                if not any(p != q and p in q for q in matched)]
    return list(dict.fromkeys(UNFIXABLE[p] for p in specific))


def passes(text):
    return not violations(text) and not hints(text)


if __name__ == "__main__":
    samples = [
        "Kindly do the needful and revert back to me on this issue asap",
        "Pls check the mail, I will intimate u once the deploy is done \U0001F44D",
        "This serves as a comprehensive solution — it will leverage our robust API",
        "I sent the mail yesterday. Please check it.",
    ]
    for s in samples:
        c = clean(s)
        v = violations(c)
        print(f"\nin   : {s}\nout  : {c}\nretry: {v if v else 'not needed - passes'}")
