# Voice

How corrected text should sound.

**This file is the specification, not the implementation.** It used to claim it was
"read by `corrector.py` as part of its system prompt", and it was not — nothing
loaded it, so it was free to drift from the prompt and the rules it described. It is
not loaded now either, on purpose: it is 60 lines, and every line of prompt costs
latency on every correction.

So read it as intent, and `blocklist.py` as fact. The **Rules with a regex behind
them** list at the bottom names the phrases that layer is meant to catch; the prose
above it describes what `SYSTEM` and `FAST_SYSTEM` in `corrector.py` ask the model
for. Nothing checks either automatically — if you change a rule, change this too,
and if the two disagree, `blocklist.py` is what actually runs.

## Who is writing

A senior software engineer in Mumbai writing to colleagues, managers, and clients.
Indian English is the starting point. The goal is correct English that sounds like a
real person typed it in a hurry between two meetings — not like an AI wrote it, and
not like a press release.

## The target: sound human, not AI

Adapted from the user's `realtone` skill, kept to the patterns that actually show up
in short work messages. Long-form rules from that skill (paragraph shape, "read the
last paragraph aloud", abstract-before-concrete) do not apply to a two-line Slack
message and are omitted.

**What makes a work message sound like AI wrote it:**

- Signpost connectives: `Additionally`, `Furthermore`, `Moreover`, `That said`
- Em dashes everywhere, and curly quotes
- Every sentence the same length and shape
- Servile openers: `Certainly`, `I'd be happy to`, `Absolutely`
- Padding that says nothing: `I hope this email finds you well`, `Please be informed`
- Three-item lists where one item would do
- `Not only X but also Y`
- Avoiding the word "is": `serves as`, `represents`, `stands as`
- Zombie nouns: `provide clarification` instead of `clarify`, `perform a review`
  instead of `review`
- Cheerful endings the writer never wrote: `Looking forward to hearing from you!`
- Hedge stacks: `it could potentially possibly be`

**What makes it sound like a person:**

- Mixed sentence lengths. A short one. Then a longer one that carries the detail.
- Plain verbs. `clarify`, not `provide clarification`. `decide`, not `make a decision`.
- "I" where it fits. First person is not unprofessional.
- Contractions are fine: `I'll`, `don't`, `can't`.
- Say the thing and stop. No wrap-up sentence.

## Rules that override everything above

- Say what he meant. Never add facts, numbers, names, or certainty he did not write.
- Never add a greeting or sign-off he did not write. No `Dear`, no `Regards`.
- Keep his words wherever they were already correct. This is a correction, not a
  rewrite competition.
- Match the channel. A WhatsApp line stays a line; it does not become a paragraph.
- Confidence stays where he put it. If he wrote `i think`, keep the doubt.
- No jokes, no opinions he did not express, no edge. Sounding human means sounding
  like a normal person at work, not like a personality.

## Which of these a rule can catch

Benchmarking showed the model ignores prompt-level bans about a third of the time, so
anything closed-form is enforced in `blocklist.py` instead of being asked for. Not
everything above is closed-form:

- `represents` is a legitimate word — "this represents the third delay" is fine.
  Rewriting it mechanically would break correct sentences, so it stays prompt-level
  guidance and is deliberately absent from the list below.
- "Every sentence the same shape", "three-item lists" and hedge stacks are judgments
  about a whole message, not string matches. Prompt-level, and unverifiable by rule.

Everything else is a rule, and the rules are tested.

## Rules with a regex behind them

`blocklist.py` is meant to catch every phrase below — by rewriting it, by rejecting
the variant and regenerating, or by warning about it. Verify one by hand:

```bash
python3 -c "import blocklist; print(blocklist.clean('kindly do the needful'))"
python3 blocklist.py            # runs its own sample inputs
```

`That said` was on this list and enforced nowhere until the two were compared by
hand, which is the failure mode to watch for.

```text
kindly
revert back
do the needful
pls
asap
Additionally
Furthermore
Moreover
That said
Not only
leverage
utilize
delve
circle back
touch base
hope this email finds you well
Certainly
Absolutely
I'd be happy to
Please be informed that
Looking forward to hearing from you
serves as
stands as
functions as
in order to
provide clarification
perform a review
do the review
make a decision
give confirmation
```
