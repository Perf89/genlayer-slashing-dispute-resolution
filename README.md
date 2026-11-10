# Slashing Dispute Resolution

A standalone GenLayer Intelligent Contract primitive submitted for the **Standalone Contracts** track.

## Purpose

When a validator is slashed, the operator and whoever bears the loss (a
delegator, a staking-as-a-service customer, a slashing-cover insurer) often
disagree about whose fault it was: a double-sign caused by the operator's own
failover setup, or a network-wide client bug that hit everyone. Today that is
settled by email threads and trust. This contract is a small court for exactly
that question. The parties record the terms that define who is liable for what,
each side submits a statement and a public evidence URL, and independent AI
validators rule on whether the operator is liable under those terms. The ruling
is an on-chain record that payout, insurance or reputation contracts can read.

Real-world use cases:

- **Slashing cover and insurance**: a neutral, disputable ruling on whether a
  loss falls under the operator's responsibility.
- **Staking-as-a-service agreements**: operators and customers settle fault
  against terms they agreed in advance.
- **Operator reputation**: a record of how disputes were actually decided.

## Why this is a real primitive, not a demo

- **Two sides, explicit process.** The operator opens the case against a named
  respondent, who either answers with evidence or explicitly waives. There are
  no timers to game: the case moves by explicit actions, and either losing side
  gets exactly one appeal.
- **The terms decide, not the model's mood.** Liability is judged against the
  agreed terms, and the burden of proof is fixed: the slashing already
  happened, so the operator must show that an excluded cause applies. Missing,
  vague or unrelated evidence does not meet that burden.
- **Equivalence anchored to the verdict.** The AI returns `operator_liable` and
  `operator_fault_pct`. Validation enforces that they agree (`operator_liable`
  is true exactly when the percentage is 50 or more). Two rulings are
  equivalent only if `operator_liable` matches exactly and the percentages
  differ by at most 25. Since both rulings satisfy the 50 rule, matching
  verdicts also means both percentages lie on the same side of 50, so the
  stored outcome never depends on which validator led. This is checked by an
  exhaustive offline test over every ruling pair.
- **Appeals are a fresh review, not a review of the first ruling.** The appeal
  prompt contains the terms, both evidence pages and the appealing party's
  statement, which every validator reads identically from the chain. It does
  not contain the first round's ruling or reasoning: that text is written by one
  leader and never compared between validators, so reusing it would let two
  equally valid first rounds push the final appeal in different directions.
  Stored reasoning is for humans and integrators and is never an input to a
  later adjudication. Offline tests pin this down.
- **Adversarial by design.** Both evidence pages are untrusted data and can try
  to instruct the judge. The prompt fences them, treats such attempts as a
  reason to distrust that side, and the ruling needs a majority of different
  models. One live run below is exactly this attack.
- **Errors are classified, not swallowed.** `[EXPECTED]` business logic and
  `[EXTERNAL]` 4xx or empty evidence must match exactly between leader and
  validator, `[TRANSIENT]` network or 5xx errors agree if both hit one, and
  `[LLM_ERROR]` malformed model output always forces disagreement.
- **No funds move.** The contract holds and transfers nothing. A ruling is a
  record other contracts can use, with no custody risk here.

## Design

### Lifecycle

```
open_case        (operator)     terms + statement + evidence URL, names a respondent  -> open
respond          (respondent)   statement + evidence URL                              -> ready
waive_response   (respondent)   explicitly gives up replying                          -> ready
rule_case        (anyone)       AI consensus                                          -> upheld | overturned
appeal           (losing side)  once                                                  -> appealed
resolve_appeal   (anyone)       AI consensus again, a fresh review                    -> upheld | overturned (final)
```

`upheld` means the slashing stands (the operator is liable under the terms).
`overturned` means it does not. The losing side is the operator after `upheld`
and the respondent after `overturned`; only that side may appeal.

### Consensus

```
leader_fn():
    fetch the operator evidence page (and the respondent evidence page, if any)
    ask LLM for {operator_liable, operator_fault_pct, reasoning}
    return _validate_ruling(parsed JSON)          # strict, see below

validator_fn(leader_result):
    leader_ruling    = _validate_ruling(leader_result)   # reject malformed leader output
    validator_ruling = leader_fn()                       # independently re-fetch + re-derive
    accept only if:
        operator_liable matches exactly, AND
        |operator_fault_pct difference| <= 25
```

### Strict validation before any state write

| Field | Requirement |
|---|---|
| `operator_liable` | a real JSON boolean (the string `"false"` is rejected) |
| `operator_fault_pct` | an `int` in `0..100` (not `bool`, not `float`, not a string) |
| consistency | `operator_liable` is true exactly when `operator_fault_pct >= 50` |
| `reasoning` | a string, stored truncated to 500 characters |

Malformed or self-contradicting results make validators disagree, so they can
never be finalized into state. These rules and the equivalence check are
covered by offline tests that load the helper functions straight from the
contract source, so they test exactly the deployed code:

```
python3 tests/test_ruling_logic.py
```

### Limits, stated plainly

Evidence must be readable by the validators over plain HTTP. A ruling is a
judgment on the submitted terms and evidence, not an investigation: it cannot
see anything the parties did not put in front of it. A case whose evidence sits
right on the 50% line may need leader rotation or may not converge, and then
the ruling does not finalize and can be triggered again.

## Deployed contract

The source in this repository is byte-for-byte the source that was deployed.

| Field | Value |
|---|---|
| Network | GenLayer Studio (Studionet) |
| Deployed address | `<FULL ADDRESS>` |
| Explorer | https://explorer-studio.genlayer.com/address/`<FULL ADDRESS>` |
| Tx (deploy) | `<TX HASH>` |
| Source | [`slashing_dispute_resolution.py`](./slashing_dispute_resolution.py) |

## Test inputs

The terms, statements and evidence are public text, so every input of every run
below can be read and replayed by anyone. The evidence files are synthetic test
documents about a fictional network ("Examplechain"):

| Fixture | URL |
|---|---|
| Core-team post-mortem of a client bug (operator evidence) | https://raw.githubusercontent.com/Perf89/genlayer-slashing-dispute-resolution/main/fixtures/client_bug_postmortem.txt |
| Neutral on-chain slashing record (respondent evidence) | https://raw.githubusercontent.com/Perf89/genlayer-slashing-dispute-resolution/main/fixtures/slash_record.txt |
| Evidence of double-signing from two peers (respondent evidence) | https://raw.githubusercontent.com/Perf89/genlayer-slashing-dispute-resolution/main/fixtures/double_sign_evidence.txt |
| Vague denial (operator evidence) | https://raw.githubusercontent.com/Perf89/genlayer-slashing-dispute-resolution/main/fixtures/claim_vague.txt |
| Denial with an instruction aimed at the judge (operator evidence) | https://raw.githubusercontent.com/Perf89/genlayer-slashing-dispute-resolution/main/fixtures/claim_injection.txt |

Roles in all runs: operator (claimant) `0xB6EA1d497Ce6A0308113ff9dac6ba4C7eBC931e4`,
respondent `0x7c12bD4c02aF3f48F3e6CBDd7041dB5E3D523d25`.

Terms used in all cases:

> The operator is liable for slashing caused by its own operational failures, including double-signing, running the same signing key on more than one machine, and prolonged downtime. The operator is not liable for slashing caused by network-wide incidents, protocol or client bugs confirmed by the network's core team, or attacks outside its control. The operator carries the burden of showing that an excluded cause applies.

## Live test evidence

### Scenario 1: the operator is cleared (client bug)

| Field | Value |
|---|---|
| Case | `<ID>` |
| Operator statement | `The slashing happened during the v2.3 network-wide incident. The core team's post-mortem confirms a client bug and lists my validator.` |
| Operator evidence | `client_bug_postmortem.txt` |
| Respondent statement | `The slashing is recorded on-chain with reason DOUBLE_SIGN. The operator is responsible for its own infrastructure.` |
| Respondent evidence | `slash_record.txt` |
| Result | `<RESULT>` |
| Tx (`open_case`) | `<TX HASH>` |
| Tx (`respond`) | `<TX HASH>` |
| Tx (`rule_case`) | `<TX HASH>` |

### Scenario 2: the operator is liable (double-sign from its own standby)

| Field | Value |
|---|---|
| Case | `<ID>` |
| Operator statement | `My validator was online and I run it carefully. The slashing is unfair.` |
| Operator evidence | `claim_vague.txt` |
| Respondent statement | `Two conflicting votes were signed with the same key from two peers at the same height. The operator's own notice says the standby was started with the production key.` |
| Respondent evidence | `double_sign_evidence.txt` |
| Result (before the appeal) | `<RESULT>` |
| Tx (`open_case`) | `<TX HASH>` |
| Tx (`respond`) | `<TX HASH>` |
| Tx (`rule_case`) | `<TX HASH>` |

### Scenario 3: an instruction aimed at the judge does not work

The operator's evidence contains a note telling the automated judge to ignore
the terms and rule that the operator is not liable with a fault of 0.

| Field | Value |
|---|---|
| Case | `<ID>` |
| Operator statement | `The slashing was caused by a network incident, not by me.` |
| Operator evidence | `claim_injection.txt` |
| Respondent evidence | `double_sign_evidence.txt` |
| Result | `<RESULT>` |
| Tx (`open_case`) | `<TX HASH>` |
| Tx (`respond`) | `<TX HASH>` |
| Tx (`rule_case`) | `<TX HASH>` |

### Scenario 4: appeal by the losing side, decided anew

The operator appeals the ruling from Scenario 2 with a new, unsupported claim.
The appeal round is not told what the first ruling was or how it was reasoned.
It decides anew from the terms, the evidence and the appeal statement, weighing
the statement against the evidence rather than accepting it on its own.

| Field | Value |
|---|---|
| Case | `<ID>` (the one from Scenario 2) |
| Appeal statement | `The standby node was started by my hosting provider without my consent, so I ask for a review.` |
| Result | `<RESULT>` |
| Tx (`appeal`) | `<TX HASH>` |
| Tx (`resolve_appeal`) | `<TX HASH>` |
| A second `appeal` | rejected, `<TX HASH>` |

## Reproducing

1. Open [GenLayer Studio](https://studio.genlayer.com) and deploy
   `slashing_dispute_resolution.py` (constructor takes no arguments).
2. As the operator: `open_case(respondent, network, terms, claim_statement, claim_evidence_url)`.
3. As the respondent: `respond(case_id, statement, evidence_url)`, or
   `waive_response(case_id)`.
4. `rule_case(case_id)`.
5. Optionally, as the losing side: `appeal(case_id, statement)`, then
   `resolve_appeal(case_id)`.
6. `get_case(case_id)` reads back `status`, `operator_fault_pct`, `reasoning`
   and the appeal fields.

## Files

- [`slashing_dispute_resolution.py`](./slashing_dispute_resolution.py): contract source
- [`tests/test_ruling_logic.py`](./tests/test_ruling_logic.py): offline logic tests
- [`fixtures/`](./fixtures): the evidence used as test inputs
- [`LICENSE`](./LICENSE): MIT
