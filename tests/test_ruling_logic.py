"""
Offline tests for the pure logic in slashing_dispute_resolution.py.

Plain Python, no GenLayer runtime needed: the helper functions
(_validate_ruling, _parse_llm_json, _rulings_agree, _status_for,
_losing_party) are loaded straight from the contract source, so these tests
always exercise the exact code that gets deployed.

    python3 tests/test_ruling_logic.py
"""
import json
import pathlib
import typing

SRC = (pathlib.Path(__file__).parent.parent / "slashing_dispute_resolution.py").read_text()
start = SRC.index('ERROR_EXPECTED = "[EXPECTED]"')
end = SRC.index("@allow_storage")
ns = {"json": json, "typing": typing}
exec(SRC[start:end], ns)
validate = ns["_validate_ruling"]
parse = ns["_parse_llm_json"]
agree = ns["_rulings_agree"]
status_for = ns["_status_for"]
losing_party = ns["_losing_party"]
THRESHOLD = ns["LIABILITY_THRESHOLD"]


def ruling(pct=80, liable=None, reasoning="ok"):
    if liable is None:
        liable = pct >= THRESHOLD
    return {"operator_liable": liable, "operator_fault_pct": pct, "reasoning": reasoning}


def rejects(case):
    try:
        validate(case)
    except ValueError:
        return True
    return False


# --- strict validation of the AI ruling -------------------------------------

def test_accepts_well_formed():
    assert validate(ruling()) == ruling()
    assert validate(ruling(pct=0))["operator_liable"] is False
    assert validate(ruling(pct=100))["operator_liable"] is True


def test_liable_must_be_a_real_boolean():
    for bad in ("true", "false", "False", 0, 1, None):
        assert rejects({"operator_liable": bad, "operator_fault_pct": 80, "reasoning": "x"}), bad


def test_pct_must_be_int_in_range():
    for bad in (True, False, 80.5, "80", None, -1, 101):
        assert rejects({"operator_liable": True, "operator_fault_pct": bad, "reasoning": "x"}), bad


def test_liable_and_pct_must_not_contradict_each_other():
    assert rejects(ruling(pct=90, liable=False))
    assert rejects(ruling(pct=10, liable=True))
    # the boundary belongs to "liable"
    assert validate(ruling(pct=50, liable=True))["operator_liable"] is True
    assert rejects(ruling(pct=50, liable=False))
    assert validate(ruling(pct=49, liable=False))["operator_liable"] is False
    assert rejects(ruling(pct=49, liable=True))


def test_reasoning_must_be_string_and_is_truncated():
    for bad in (5, None, ["a"], {"a": 1}):
        assert rejects({"operator_liable": True, "operator_fault_pct": 80, "reasoning": bad}), bad
    assert len(validate(ruling(reasoning="x" * 900))["reasoning"]) == 500


def test_missing_fields_and_wrong_container():
    for field in ("operator_liable", "operator_fault_pct", "reasoning"):
        case = ruling()
        del case[field]
        assert rejects(case), field
    assert rejects([True, 80, "x"])
    assert rejects("not a dict")


# --- parsing of the raw model output ----------------------------------------

def test_parse_accepts_text_fenced_text_and_objects():
    assert parse('{"a": 1}') == {"a": 1}
    assert parse('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse({"a": 1}) == {"a": 1}


def test_parse_rejects_garbage():
    for bad in (None, 5, 1.5, True):
        try:
            parse(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    try:
        parse("not json at all")
    except ValueError:
        return
    raise AssertionError("accepted invalid JSON")


# --- the equivalence check between two validators' rulings ------------------

def test_agree_when_verdict_matches_and_percentages_are_close():
    assert agree(ruling(pct=80), ruling(pct=100))
    assert agree(ruling(pct=80), ruling(pct=55))      # exactly at tolerance
    assert agree(ruling(pct=10, reasoning="a"), ruling(pct=10, reasoning="completely different"))


def test_disagree_when_percentages_drift_too_far():
    assert not agree(ruling(pct=100), ruling(pct=74))  # same verdict, 26 apart
    assert not agree(ruling(pct=0), ruling(pct=26))


def test_disagree_when_the_verdict_differs():
    assert not agree(ruling(pct=50), ruling(pct=49))   # opposite verdicts, 1 apart
    assert not agree(ruling(pct=60), ruling(pct=40))   # opposite verdicts, 20 apart
    assert not agree(ruling(pct=90), ruling(pct=5))


def test_invariant_accepted_rulings_always_share_the_same_verdict():
    # Exhaustive over every valid ruling pair: whenever two rulings are
    # accepted as equivalent, the case outcome is identical, in either order.
    accepted = checked = 0
    for p1 in range(0, 101):
        for p2 in range(0, 101):
            a, b = ruling(pct=p1), ruling(pct=p2)
            checked += 1
            ab = agree(a, b)
            assert ab == agree(b, a)
            if ab:
                accepted += 1
                assert status_for(a) == status_for(b), (p1, p2)
    assert checked == 101 * 101 and accepted > 0


# --- verdict and appeal mapping ---------------------------------------------

def test_status_mapping():
    assert status_for(ruling(pct=100)) == "upheld"
    assert status_for(ruling(pct=50)) == "upheld"
    assert status_for(ruling(pct=49)) == "overturned"
    assert status_for(ruling(pct=0)) == "overturned"


def test_the_losing_party_is_the_one_who_may_appeal():
    assert losing_party("upheld") == "claimant"        # operator is liable, operator loses
    assert losing_party("overturned") == "respondent"  # operator cleared, respondent loses


# --- regressions from earlier GenLayer contracts ----------------------------

def test_no_response_format_argument():
    code = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("#"))
    assert "response_format=" not in code


def test_no_value_transfer_in_this_contract():
    assert "emit_transfer" not in SRC
    assert "get_contract_at(" not in SRC


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} tests passed")
