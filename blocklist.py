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
    # "do the review" was the gap: perform/conduct/carry-out were all covered,
    # but "do" is the verb the model actually reaches for, and it failed 5 runs
    # out of 5. The "of" form comes first so "do the review of the PR" becomes
    # "review the PR" rather than "review of the PR".
    r"\bdo (?:the|a) review of\b": "review",
    r"\bdo (?:the|a) review\b": "review",
    r"\bdo (?:the|a) check of\b": "check",
    r"\bdo (?:the|a) testing of\b": "test",
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

    # Tidy up damage from deletions - WITHOUT touching line breaks.
    #
    # These used to be written with \s, which matches "\n". The result was that
    # cleaning a seven-line email returned a single line: `\s{2,} -> " "` turns
    # every blank line into a space. An email is one of the three things this
    # tool is for, so silently destroying its paragraphs was not a small bug.
    # [^\S\n] is "whitespace but not a newline".
    text = re.sub(r"[^\S\n]{2,}", " ", text)          # runs of spaces/tabs
    text = re.sub(r"[^\S\n]+([,.!?;:])", r"\1", text)  # space before punctuation
    text = re.sub(r"[^\S\n]+\n", "\n", text)           # trailing space on a line
    text = re.sub(r"\n{3,}", "\n\n", text)             # at most one blank line
    text = re.sub(r"^[^\S\n]*[,;:][^\S\n]*", "", text)
    # Capitalise after a sentence end only on the SAME line, so a line break is
    # never silently closed up into the previous sentence.
    text = re.sub(r"([.!?])([^\S\n]*)([a-z])",
                  lambda m: f"{m.group(1)} {m.group(3).upper()}", text)
    # ...and separately capitalise the start of every line, which the rule above
    # can no longer reach now that it stops at a newline. Without this, a new
    # paragraph after "yesterday.\n\n" stayed lowercase.
    text = re.sub(r"(^|\n)([^\S\n]*)([a-z])",
                  lambda m: m.group(1) + m.group(2) + m.group(3).upper(), text)
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


# Currency markers the model likes to add to a bare number.
CURRENCY_SYMBOLS = ["$", "₹", "€", "£", "¥"]
CURRENCY_WORDS = ["USD", "INR", "EUR", "GBP", "Rs.", "Rs", "dollars", "rupees",
                  "euros", "pounds"]


def strip_invented_currency(original, corrected):
    """Remove a currency the writer never wrote.

    Measured: for "i has send the invoice for 45000", the model returned
    "$45,000" in 8 runs out of 8, in every tone. That is not a formatting
    choice - it is a claim about the money, and for an invoice written in
    Mumbai it is the wrong claim. "Never invent a name, date, or number" has to
    cover the currency attached to the number, or the rule protects nothing.

    Prompting was not considered: this file exists because benchmarking showed
    the model ignores prompt-level bans about a third of the time. A wrong
    currency in an invoice is not a failure worth being wrong about a third of
    the time.

    Only markers ABSENT from the original are stripped, so a writer who typed
    "$45,000" or "Rs 45000" keeps exactly what they typed.
    """
    out = corrected
    for sym in CURRENCY_SYMBOLS:
        if sym not in original and sym in out:
            out = out.replace(sym, "")
    low = original.lower()
    for word in CURRENCY_WORDS:
        if word.lower() not in low:
            out = re.sub(rf"\s*\b{re.escape(word)}\b", "", out, flags=re.IGNORECASE)
    # deletions leave doubled spaces and orphaned space-before-punctuation.
    # [^\S\n] rather than \s, for the same reason as in clean(): a newline is
    # structure the writer put there, not whitespace to be tidied away.
    out = re.sub(r"[^\S\n]{2,}", " ", out)
    out = re.sub(r"[^\S\n]+([,.!?;:])", r"\1", out)
    return out.strip()


# Words the model has no business rewriting: greetings, sign-offs and courtesies
# are the writer's own voice, not grammar. Closed set on purpose - see below.
PROTECTED_WORDS = [
    "thanks", "thank", "regards", "cheers", "hi", "hello", "hey",
    "sir", "madam", "please", "sorry", "welcome",
]


def _edit_distance_one(a, b):
    """True if one insertion, deletion or substitution turns a into b."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    skipped = False
    while i < len(short) and j < len(long):
        if short[i] != long[j]:
            if skipped:
                return False
            skipped = True
            j += 1
        else:
            i += 1
            j += 1
    return True


def restore_mangled_words(original, corrected):
    """Undo typos the model introduced into words it should not have touched.

    Measured: for a message ending in "thanks", the model returned "tanks" in 5
    runs out of 6. Rewording the prompt took it to 3 out of 6, which is the usual
    ceiling for prompting in this project and not good enough - a tool that
    misspells a word the writer spelled correctly is worse than no tool.

    Deliberately narrow. A blanket "restore any near-miss word" rule would undo
    real corrections, because good edits are near-misses too: mail -> email is a
    single insertion and is exactly what should happen. So this only guards a
    closed set of greetings and sign-offs, which carry no grammar to fix and are
    the writer's voice rather than the writer's mistakes.
    """
    originals = set(re.findall(r"[a-z]+", original.lower()))
    if not originals:
        return corrected

    def repair(match):
        word = match.group(0)
        low = word.lower()
        if low in originals:
            return word                    # the writer wrote it; leave it alone
        for target in PROTECTED_WORDS:
            if target in originals and _edit_distance_one(low, target):
                return _match_case(target, word)
        return word

    return re.sub(r"[A-Za-z]+", repair, corrected)


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
