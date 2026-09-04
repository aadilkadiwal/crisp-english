"""Deterministic post-processing. No model involved.

The benchmark showed qwen3:8b emits "do the needful" and "kindly" in roughly a
third of cases even when the prompt bans those exact strings. Instruction-following
is not a reliable enforcement mechanism, so anything that can be checked by rule is
checked here instead: zero latency, no compliance required, and it works identically
on a 4b model as on an 8b one.

Because this file is the part of crisp-english that is supposed to be reliable, it
is the part where a mistake is silent: a bad regex does not raise, it just quietly
rewrites somebody's sentence. Every rule below carries the case that produced it,
so a rule can be judged without re-deriving why it exists.

THE GROUPS. These were previously numbers in comments only, out of order in the
file, with Group 2 never labelled at all. They are now the actual structure:

  Group 1  SHORTHAND   pls -> please. Expanded FIRST, so later groups see real words.
  Group 2  FILLER      Indian-English office filler, realtone copula avoidance,
                       filler phrases, zombie nouns, servile openers, invented
                       endings. Safe, meaning-preserving substitutions.
  Group 3  DEDUPE      repairs the damage groups 1 and 2 do to each other. LAST of
                       the substitution phases, by definition.
  Group 4  GRAMMAR     recurring closed-form grammar patterns both models failed.
  Group 5  REJECTIONS  words with meaning but no safe swap: one model retry.
  Group 6  UNFIXABLE   phrases with no recoverable meaning: a hint, never a rewrite.

Phase order is load-bearing, which is why it is a list and not a dict any more.
Measured: as a single dict, "kindly pls check" returned "Please please check the
mail" - `kindly`->`please` and the `please please` collapse both ran before `pls`
expanded into a second `please`, leaving nothing to tidy it. That also made clean()
non-idempotent, i.e. running it twice gave a different answer than running it once.

Two kinds of rule:
  SUBSTITUTIONS - a safe, meaning-preserving replacement exists. Applied silently.
  REJECTIONS    - no safe automatic replacement. The variant is regenerated.
"""

import re
from pathlib import Path

# --- Group 1: shorthand ------------------------------------------------------
# Expanded before anything else, so a rule written about "please" sees the word
# and not "pls". The model forgets these; a regex never does.
SHORTHAND = {
    r"\bpls\b": "please",
    r"\bplz\b": "please",
    r"\bpl\b": "please",
    r"\bthx\b": "thanks",
    r"\btq\b": "thanks",
    r"\basap\b": "as soon as possible",
    r"\bfyi\b": "for your information",
    r"\bwrt\b": "with respect to",
    r"\bu\b": "you",
    r"\bur\b": "your",
}

# --- Group 2: filler ---------------------------------------------------------
# Indian-English office filler, plus the realtone patterns that show up in short
# work messages. "do the needful" has no fixed meaning, so it is a Group 6 hint,
# not a substitution - only the writer knows what action was intended.
FILLER = {
    # Indian-English office filler
    r"\brevert back to\b": "reply to",
    r"\brevert back\b": "reply",
    r"\bkindly\b": "please",
    r"\bintimate\b": "inform",
    r"\bprepone\b": "move earlier",
    r"\bsame is (attached|enclosed)\b": r"it is \1",
    r"\bas per your (kind )?(request|instruction)s?\b": "as you asked",

    # realtone #8: copula avoidance
    r"\bserves as\b": "is",
    r"\bstands as\b": "is",
    r"\bfunctions as\b": "is",

    # realtone #22: filler phrases
    r"\bin order to\b": "to",
    r"\bdue to the fact that\b": "because",
    r"\bat this point in time\b": "now",
    r"\bat the earliest\b": "as soon as possible",
    r"\bit is important to note that\b": "",
    r"\bit'?s worth noting that\b": "",
    r"\bplease be informed that\b": "",
    r"\bplease do not hesitate to\b": "feel free to",

    # realtone #29: zombie nouns.
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

    # realtone #21: sycophantic openers
    r"^\s*Certainly[,.!]?\s*": "",
    r"^\s*Absolutely[,.!]?\s*": "",
    r"^\s*Of course[,.!]?\s*": "",
    r"\bI'?d be happy to\b": "I can",
    r"\bI would be happy to\b": "I can",
    r"\bI would be glad to\b": "I can",

    # realtone #24: generic positive conclusions.
    # Only removed when it trails the end of the text, so a genuine
    # "looking forward to the demo tomorrow" mid-message survives.
    r"\s*Looking forward to hearing from you[.!]?\s*$": "",
    r"\s*Thanks in advance[.!]?\s*$": "",
    r"\s*Please let me know if you have any (?:further )?questions[.!]?\s*$": "",
}

# --- Group 3: dedupe ---------------------------------------------------------
# Groups 1 and 2 can both produce the same word next to itself: `kindly` and
# `pls` are two different inputs that mean "please". This phase runs after both,
# which is the whole reason the phases are ordered.
#
# Deliberately a closed set of words rather than a general "same word twice"
# rule: English has legitimate doubles ("had had", "that that"), and eating one
# of those is a worse failure than leaving a stutter in.
DEDUPE = {
    r"\b(please)\s+please\b": r"\1",
    r"\b(thanks)\s+thanks\b": r"\1",
    r"\b(you)\s+you\b": r"\1",
    r"\b(your)\s+your\b": r"\1",
}

# Substitution phases, in the order they must run.
PHASES = (("shorthand", SHORTHAND), ("filler", FILLER), ("dedupe", DEDUPE))


# --- Group 6: unfixable ------------------------------------------------------
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


# --- Group 5: rejections -----------------------------------------------------
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
    # "that said" was named in voice.md and in the benchmark's prompt, and was
    # enforced by neither, until the two were compared.
    "that said",
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
    " ": " ",      # non-breaking space
}

EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF☀-➿⬀-⯿]"
)


# --- abbreviations are not sentence ends -------------------------------------
# The full stop inside "i.e." is punctuation, not the end of a sentence, and the
# `i` inside it is not the pronoun. Both passes below used to fire on it:
# measured, "i.e. the deploy is done" became "I. E. The deploy is done", and
# "e.g." became "e. G.".
#
# Rather than teach every pass about abbreviations, they are lifted out into
# placeholders for the duration of clean() and put back verbatim afterwards. The
# writer's own capitalisation survives, which is the point - it is their text.
#
# A closed list, because guessing at abbreviations is how "No." (number) starts
# eating "no.". These are the ones that actually appear in work messages.
ABBREVIATIONS = [
    "i.e.", "e.g.", "etc.", "a.m.", "p.m.", "vs.", "approx.", "et al.",
]

# \x00 cannot appear in text pasted from an app, and survives every regex below
# because it is neither a word character nor whitespace nor punctuation any rule
# matches.
_MARK = "\x00{}\x00"


def _protect_abbreviations(text):
    """Replace abbreviations with placeholders. Returns (text, originals)."""
    found = []

    def take(match):
        found.append(match.group(0))
        return _MARK.format(len(found) - 1)

    for abbr in ABBREVIATIONS:
        text = re.sub(rf"(?<![A-Za-z]){re.escape(abbr)}", take, text,
                      flags=re.IGNORECASE)
    return text, found


def _restore_abbreviations(text, found):
    for i, original in enumerate(found):
        text = text.replace(_MARK.format(i), original)
    return text


# --- Group 4: recurring grammar patterns -------------------------------------
# Benchmarking showed both qwen3:4b and qwen3:8b fail the SAME small set of
# grammar patterns, repeatedly, despite explicit prompt rules naming each one.
# They are recurring and closed-form, so they are rules, not judgment calls.
# Fixing them here is what lets the smaller, cooler-running model be sufficient.

# `\bago\b` covers every "N days ago" form on its own, so the explicit
# "\d+ (days|weeks|months|years) ago" branch that used to sit here was dead
# alternation in a regex that runs on every correction.
PAST_MARKER = (r"yesterday|last (?:night|week|month|year|monday|tuesday|wednesday"
               r"|thursday|friday|saturday|sunday)|\bago\b|earlier today"
               r"|this morning")

# Common irregular past participles, plus the regular -ed case. Dropping the
# auxiliary is the correct fix: "I have sent it yesterday" -> "I sent it yesterday".
PARTICIPLE = (r"sent|done|gone|seen|made|given|taken|written|spoken|come|got|gotten|"
              r"put|read|told|found|left|paid|met|held|kept|built|sold|"
              r"\w+ed")

# A sentence, for the purposes of the rule below: text up to and including a
# sentence-ending mark, or up to a line break. Both matter - a message written as
# two lines is two statements even without full stops.
_SENTENCE = re.compile(r"[^.!?\n]*(?:[.!?]+|\n|$)")


def _fix_present_perfect_with_past_time(text):
    """'I have sent it yesterday' -> 'I sent it yesterday'.

    Applied one sentence at a time. Measured before that: a single `yesterday`
    anywhere in the message stripped the auxiliary from every present perfect in
    it, so "I sent the report yesterday. I have completed the review." lost a
    `have` from a sentence that was already correct. A past time word governs its
    own sentence and nothing else.
    """
    def fix_one(match):
        chunk = match.group(0)
        if not chunk or not re.search(PAST_MARKER, chunk, re.IGNORECASE):
            return chunk
        return re.sub(rf"\b(?:have|has)\s+({PARTICIPLE})\b",
                      lambda m: m.group(1), chunk, flags=re.IGNORECASE)

    return _SENTENCE.sub(fix_one, text)


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

    # Dropped article before common workplace nouns.
    #
    # The preposition form was here already. The verb forms were the gap, and the
    # project's own test case walked straight into it: "not able to came office"
    # became "to come office", because by the time the article rule ran the word
    # before `office` was a verb, not a preposition. Split in two because the
    # verbs disagree about "to" - you come TO the office but you reach THE office.
    r"\b(to|at|in|from)\s+office\b": r"\1 the office",
    r"\b(come|go|coming|going|return|returning)\s+office\b": r"\1 to the office",
    r"\b(reach|reaching|leave|leaving|visit|visiting|join|joining)\s+office\b":
        r"\1 the office",

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


def _tidy_spacing(text):
    r"""Close up the gaps a deletion leaves behind.

    [^\S\n] rather than \s throughout: a newline is structure the writer put
    there, not whitespace to be tidied away. Written once and called twice -
    clean() and strip_invented_currency() both delete words and both need
    exactly this, and they carried a copy each.

    A raw docstring, because \S in a plain one is an invalid escape sequence and
    Python 3.14 warns about it. /usr/bin/python3 is 3.9 and said nothing.
    """
    text = re.sub(r"[^\S\n]{2,}", " ", text)           # runs of spaces/tabs
    text = re.sub(r"[^\S\n]+([,.!?;:])", r"\1", text)  # space before punctuation
    return text


def clean(text):
    """Apply every safe, meaning-preserving fix. Returns cleaned text.

    Idempotent: clean(clean(x)) == clean(x).
    A rule that keeps firing on its own output is a rule that will eventually eat
    the sentence, and the phase ordering above is what makes that hold.
    """
    text, abbreviations = _protect_abbreviations(text)

    for bad, good in CHARACTER_FIXES.items():
        text = text.replace(bad, good)
    text = EMOJI.sub("", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)        # realtone #14: no boldface

    # Groups 1, 2 and 3, in that order. See PHASES.
    for _name, rules in PHASES:
        for pattern, replacement in rules.items():
            if "\\1" in replacement or "\\g" in replacement:
                # A backreference cannot go through _match_case: the replacement
                # is a template, not a literal word.
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            else:
                text = re.sub(pattern,
                              lambda m: _match_case(replacement, m.group(0)),
                              text, flags=re.IGNORECASE)

    # Group 4. These use backreferences, so they are applied directly rather
    # than through _match_case.
    for pattern, replacement in GRAMMAR_FIXES.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = _fix_present_perfect_with_past_time(text)

    # standalone "i" is always "I". The abbreviations are in placeholders, so the
    # `i` in "i.e." is out of reach here.
    text = re.sub(r"\bi\b", "I", text)

    # Tidy up damage from deletions - WITHOUT touching line breaks.
    #
    # These used to be written with \s, which matches "\n". The result was that
    # cleaning a seven-line email returned a single line: `\s{2,} -> " "` turns
    # every blank line into a space. An email is one of the three things this
    # tool is for, so silently destroying its paragraphs was not a small bug.
    # [^\S\n] is "whitespace but not a newline".
    text = _tidy_spacing(text)
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
    text = text[:1].upper() + text[1:] if text else text
    return _restore_abbreviations(text, abbreviations)


# Currency markers the model likes to add to a bare number.
CURRENCY_SYMBOLS = ["$", "₹", "€", "£", "¥"]
CURRENCY_WORDS = ["USD", "INR", "EUR", "GBP", "Rs.", "Rs", "dollars", "rupees",
                  "euros", "pounds", "dollar", "rupee", "euro", "pound"]


def _currency_stem(word):
    """Fold the spellings of one currency onto a single token.

    "Rs" and "Rs." are the same word, and so are "dollar" and "dollars". Measured
    before this existed: a writer who typed "5 dollar" had their own word deleted,
    because the membership test was exact-string and "dollar" is not "dollars".
    """
    return word.lower().rstrip(".").rstrip("s")


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
    "$45,000", "Rs 45000" or "5 dollar" keeps exactly what they typed.
    """
    out = corrected
    for sym in CURRENCY_SYMBOLS:
        if sym not in original and sym in out:
            out = out.replace(sym, "")

    written = {_currency_stem(w) for w in re.findall(r"[A-Za-z.]+", original)}
    for word in CURRENCY_WORDS:
        if _currency_stem(word) not in written:
            out = re.sub(rf"\s*\b{re.escape(word)}\b", "", out, flags=re.IGNORECASE)
    # Deletions leave doubled spaces and orphaned space-before-punctuation.
    return _tidy_spacing(out).strip()


# Words the model has no business rewriting: greetings, sign-offs and courtesies
# are the writer's own voice, not grammar. Closed set on purpose - see below.
PROTECTED_WORDS = [
    "thanks", "thank", "regards", "cheers", "hi", "hello", "hey",
    "sir", "madam", "please", "sorry", "welcome",
]

# Words only this writer uses: names, products, repos, clients, transliterated
# words. A 4b model "corrects" these with great confidence, and no closed list
# shipped in a repo can know them.
#
# One word or phrase per line, # for comments. Read once and cached, because this
# runs on the hotkey path.
USER_WORDS_FILE = Path.home() / ".crisp-english" / "protect.txt"
_user_words_cache = None


def user_words(path=None):
    """Words from the user's own dictionary. Empty list if there is no file."""
    global _user_words_cache
    if path is None and _user_words_cache is not None:
        return _user_words_cache
    target = Path(path) if path else USER_WORDS_FILE
    words = []
    try:
        for line in target.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                words.append(line.lower())
    except OSError:
        words = []                    # no dictionary is the normal case
    if path is None:
        _user_words_cache = words
    return words


def protected_words(path=None):
    return PROTECTED_WORDS + user_words(path)


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


def _is_inflection(candidate, target):
    """True if candidate is target plus one trailing letter.

    "his" is "hi" + s. "pleased" is "please" + d. "thanks" is "thank" + s. All
    three are ordinary English words that edit distance alone cannot tell apart
    from a typo, and all three were measured being destroyed: "handle his
    tickets" became "handle hi tickets".
    """
    return (len(candidate) == len(target) + 1
            and candidate.startswith(target)
            and candidate[-1].isalpha())


def restore_mangled_words(original, corrected, protect_path=None):
    """Undo typos the model introduced into words it should not have touched.

    Measured: for a message ending in "thanks", the model returned "tanks" in 5
    runs out of 6. Rewording the prompt took it to 3 out of 6, which is the usual
    ceiling for prompting in this project and not good enough - a tool that
    misspells a word the writer spelled correctly is worse than no tool.

    Deliberately narrow, and narrowed twice. A blanket "restore any near-miss
    word" rule undoes real corrections, because good edits are near-misses too:
    mail -> email is a single insertion and is exactly what should happen. So the
    guarded set is closed: greetings, sign-offs, and the writer's own dictionary.

    Even inside that set, edit distance is not sufficient evidence of a typo. Two
    further conditions, both from measured corruptions:

      1. Something has to be missing. If the writer wrote "hi" and "hi" is still
         in the output, then "his" is a word the model needed, not a mangled
         greeting. Measured: "hi sir, handle the tickets of ramesh" came back as
         "handle hi tickets", and "hey team" turned "they are looking" into "hey
         are looking".
      2. It must not be an inflection. "pleased" is "please" with a letter on the
         end, and turning it back into "please" produced "I am please to send it".
    """
    originals = set(re.findall(r"[a-z]+", original.lower()))
    if not originals:
        return corrected

    kept = set(re.findall(r"[a-z]+", corrected.lower()))
    guarded = [w for w in protected_words(protect_path)
               if w in originals and w not in kept]
    if not guarded:
        return corrected              # nothing the writer wrote has gone missing

    def repair(match):
        word = match.group(0)
        low = word.lower()
        if low in originals:
            return word                    # the writer wrote it; leave it alone
        for target in guarded:
            if _is_inflection(low, target):
                continue                   # a real word, not a typo of `target`
            if _edit_distance_one(low, target):
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


if __name__ == "__main__":
    samples = [
        "Kindly do the needful and revert back to me on this issue asap",
        "Pls check the mail, I will intimate u once the deploy is done \U0001F44D",
        "This serves as a comprehensive solution — it will leverage our robust API",
        "I sent the mail yesterday. Please check it.",
        "kindly pls check the mail",
        "The API is live, i.e. the deploy is done",
    ]
    for s in samples:
        c = clean(s)
        v = violations(c)
        print(f"\nin   : {s}\nout  : {c}\nretry: {v if v else 'not needed - passes'}")
