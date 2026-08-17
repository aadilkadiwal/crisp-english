"""Evaluation set for saaf.

Each case is a real mistake pattern, with checks expressed as properties of the
correction rather than exact strings, because model output varies between runs
and between models.

`must_not_contain` is the important half: it catches the failure modes observed
while benchmarking (uncorrected shorthand, corporate filler, present perfect
paired with a past time word).
"""

BANNED = [
    "kindly", "do the needful", "revert back", "leverage", "circle back",
    "hope this email finds you well", "please be informed", "as per your",
]

CASES = [
    dict(
        id="subject_verb_and_tense",
        text="i has send the mail yesterday, pls check it and let me know if any changes require from my side",
        must_contain=["I sent", "please"],
        must_not_contain=["i has", "has send", "pls", "have sent the mail yesterday"],
        note="subject-verb agreement + past tense + shorthand + passive voice",
    ),
    dict(
        id="verb_after_to_and_article",
        text="hi sir, i am not able to came office today because i have fever. i will do work from home and complete the pending API task",
        must_contain=["come to"],
        must_not_contain=["to came", "came office"],
        note="infinitive after 'to' + missing article before 'office'",
    ),
    dict(
        id="already_correct",
        text="The deployment is done. Please verify and confirm.",
        must_contain=[],
        must_not_contain=BANNED,
        expect_no_notes=True,
        note="control case: correct input must not be churned or inflated",
    ),
    dict(
        id="strip_corporate_filler",
        text="kindly do the needful and revert back to me on this issue asap",
        must_contain=["as soon as possible"],
        must_not_contain=["kindly", "revert back", "asap"],
        expect_hint="needful",
        note=("Filler with a meaning is replaced. 'do the needful' has NO meaning, "
              "so it is deliberately left alone and a hint is shown instead - "
              "measured: retrying the model does not fix it, because there is no "
              "action to recover. Guessing the intent would be worse than asking."),
    ),
    dict(
        id="having_for_possession",
        text="i am having 4 years experience in python and django",
        must_contain=["I have"],
        must_not_contain=["am having", "i am having"],
        note="'having' misused for possession",
    ),
    dict(
        id="present_perfect_with_past_time",
        text="yesterday i have completed the task which you assigned me",
        must_contain=["completed"],
        must_not_contain=["have completed", "i have completed"],
        note="present perfect cannot pair with a past time word",
    ),
    dict(
        id="redundant_that",
        text="can you please tell me that when the meeting will start",
        must_not_contain=["me that when", "that when"],
        note="redundant 'that' before a question word",
    ),
    dict(
        id="did_plus_past_participle",
        text="i didn't got the mail, please send it again",
        must_contain=["didn't get"],
        must_not_contain=["didn't got"],
        note="'did' takes the base verb, not the past form",
    ),
    dict(
        id="discussed_about",
        text="we discussed about the payment issue in yesterday meeting",
        must_not_contain=["discussed about"],
        note="'discuss' is transitive; also missing possessive on 'yesterday'",
    ),
    dict(
        id="one_of_my_colleague",
        text="one of my colleague is on leave so i will handle his tickets",
        must_contain=["colleagues"],
        must_not_contain=["one of my colleague is"],
        note="'one of' requires a plural noun",
    ),
    dict(
        id="myself_introduction",
        text="myself Aadil, i am working as senior software engineer since 4 years",
        must_contain=["I"],
        must_not_contain=["myself Aadil", "since 4 years"],
        note="'myself X' is not an English introduction; duration takes 'for', not 'since'",
    ),
    # --- realtone cases: output must not sound like AI wrote it -------------
    # These check the `natural` variant, not `fix`. Sounding human is a stated
    # requirement, so it is tested, not assumed.
    dict(
        id="no_ai_connectives",
        text="the build is failing. also the tests are slow. i think we should fix the build first",
        must_not_contain=["additionally", "furthermore", "moreover", "that said",
                          "in conclusion"],
        check_field="natural",
        note="AI reaches for signpost connectives where a person just starts the sentence",
    ),
    dict(
        id="no_zombie_nouns",
        text="i will do the review of the PR tomorrow and give confirmation after that",
        must_not_contain=["do the review", "give confirmation", "provide clarification",
                          "make a decision"],
        check_field="natural",
        note="verb-turned-noun plus a weak helper verb is a strong AI tell",
    ),
    dict(
        id="no_invented_signoff",
        text="the staging server is down, i am checking the logs now",
        must_not_contain=["looking forward", "hope this", "do not hesitate",
                          "thanks in advance", "regards", "dear"],
        check_field="natural",
        note="AI adds warm openers and closers the writer never wrote",
    ),
    dict(
        id="no_em_dash_or_curly_quotes",
        text="i checked the API it is returning 500 for some requests not all",
        must_not_contain=["—", "–", "“", "”", "‘", "’"],
        check_field="natural",
        note="realtone Phase 2 hard character checks",
    ),
    dict(
        id="preserve_meaning_no_invention",
        text="the API is failing in staging, i think the token is expired but not sure",
        must_contain=["staging"],
        must_not_contain=BANNED + ["Dear", "Regards", "Best regards"],
        note="must not invent greetings, sign-offs, or certainty the writer did not express",
    ),

    # --- structure: an email is not one line ---------------------------------
    # blocklist.clean() used to flatten a seven-line email into a single line,
    # because its tidy-up regexes were written with \s and \s matches "\n". The
    # model then compounded it by dropping the sign-off entirely.
    dict(
        id="multiline_keeps_paragraphs",
        text=("hi sir,\n\ni has send the report yesterday.\n\n"
              "pls review and let me know.\n\nthanks"),
        min_lines=5,
        must_contain=["thanks"],
        must_not_contain=["pls"],
        check_field="natural",
        note="paragraph breaks are structure the writer chose, not whitespace "
             "to tidy away - and a sign-off he wrote must survive",
    ),
    dict(
        id="sign_off_not_mangled",
        text="pls review the doc and let me know\n\nthanks",
        must_contain=["thanks"],
        must_not_contain=["tanks "],
        check_field="natural",
        note=("measured: the model returned 'tanks' in 5 runs of 6, and rewording "
              "the prompt only got it to 3 of 6. Guarded in blocklist.py instead, "
              "which is what this project does with anything closed-form."),
    ),

    # --- tone cases: audience changes the register, not the meaning ----------
    # Each tone gets a case that asserts what makes it that tone, plus one that
    # asserts the tone did NOT license dropping information. A tone that quietly
    # loses a fact is worse than no tone at all.
    dict(
        id="tone_formal_no_contractions",
        text="i has send the mail yesterday and i will share the report by monday",
        tone="formal",
        must_not_contain=["I'll", "I've", "don't", "can't", "won't", "it's", "I'm"],
        check_field="best",
        note="formal is for a client: complete sentences, no contractions",
    ),
    dict(
        id="tone_formal_keeps_facts",
        text="i has send the invoice for 45000 to priya yesterday, pls confirm receipt",
        tone="formal",
        must_contain=["Priya"],
        # Digits only, so "45,000" passes and "$45,000" does not. The model added
        # a dollar sign in 8 runs out of 8 - a bare number written in Mumbai is
        # not dollars, and inventing the currency is inventing a fact about money.
        must_contain_digits=["45000"],
        must_not_contain=["kindly", "pls", "$", "USD", "dollars"],
        check_field="best",
        note="a change of register must never drop a number or name, and must "
             "never attach a currency the writer did not write",
    ),
    dict(
        id="tone_brief_actually_shorter",
        text=("hi sir, i just wanted to quickly check in with you regarding the "
              "deployment that we discussed about in yesterday meeting, i has "
              "completed the changes and pushed it to staging, so whenever you get "
              "some time please can you kindly review it and let me know your "
              "feedback on the same"),
        tone="brief",
        max_words=30,
        must_not_contain=["kindly", "discussed about"],
        # `best`, not `natural`: brief is served by the three-variant prompt's
        # `short` field, so `natural` is the full-length answer this tone exists
        # to avoid. Asserting on it measured the wrong thing entirely.
        check_field="best",
        note="brief must genuinely cut: 52 words in, and the default register "
             "returns about 37, so anything near that is the tone being ignored",
    ),
    dict(
        id="tone_brief_keeps_the_number",
        text="the build is failing on 3 of the tests, i think it is the token expiry",
        tone="brief",
        must_contain=["3"],
        check_field="best",
        note="shortening is not licence to drop the detail that makes it actionable",
    ),
]

# --- keep the tested path the shipped path ----------------------------------
#
# The menu bar no longer offers the default register, so the hotkey always sends
# either "formal" or "brief". The six assertions below were only ever checked
# against the default, which means that after removing Colleague they would have
# gone on passing while covering nothing anybody uses - the same gap the fast-mode
# benchmark caught earlier, in a new place.
#
# Re-run them in the register that now ships. Derived rather than copied, so a
# change to the original assertion cannot silently stop applying here.
#
# `formal` is the higher-risk register for most of these: a model asked to sound
# professional is far more tempted to add "Best regards" than one asked to sound
# like a colleague.
_SHIPPED_REGISTER_IDS = [
    "no_ai_connectives",
    "no_zombie_nouns",
    "no_invented_signoff",
    "no_em_dash_or_curly_quotes",
    "multiline_keeps_paragraphs",
    "sign_off_not_mangled",
]

for _case in [c for c in CASES if c["id"] in _SHIPPED_REGISTER_IDS]:
    _derived = dict(_case)
    _derived["id"] = _case["id"] + "__formal"
    _derived["tone"] = "formal"
    _derived["check_field"] = "best"      # the field the user is handed
    _derived["note"] = (
        "derived: the same assertion in the register the hotkey actually uses. "
        "See _SHIPPED_REGISTER_IDS.")
    CASES.append(_derived)
