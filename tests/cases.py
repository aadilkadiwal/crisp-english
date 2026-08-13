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
]
