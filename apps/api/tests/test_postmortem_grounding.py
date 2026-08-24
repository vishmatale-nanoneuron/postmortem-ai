from hypothesis import given, settings, strategies as st

from app.services.postmortem import (
    UNSUPPORTED,
    EvidenceEntry,
    bound_evidence_by_chars,
    ground_draft,
    parse_model_json,
)

EVIDENCE = [
    EvidenceEntry(id="e1", occurred_at=1, source="alert", summary="Latency spiked", detail=None, authorized_by="ops"),
    EvidenceEntry(id="e2", occurred_at=2, source="deploy", summary="Release 1.2 shipped", detail=None, authorized_by="ops"),
]


def test_a_fully_cited_claim_is_kept_intact() -> None:
    response = {
        "summary": {"text": "Latency rose after the release.", "citations": [1, 2]},
        "root_cause": {"text": "", "citations": []},
        "detection": {"text": "", "citations": []},
        "resolution": {"text": "", "citations": []},
    }
    draft = ground_draft(response, EVIDENCE)
    assert draft.summary == "Latency rose after the release."
    assert draft.cited_evidence_ids == ["e1", "e2"]


def test_an_uncited_claim_becomes_unsupported() -> None:
    response = {"summary": {"text": "Something happened.", "citations": []}}
    draft = ground_draft(response, EVIDENCE)
    assert draft.summary == UNSUPPORTED
    assert draft.unsupported_claims_dropped == 1


def test_an_out_of_range_citation_is_not_trusted() -> None:
    response = {"summary": {"text": "Made up.", "citations": [9]}}
    draft = ground_draft(response, EVIDENCE)
    assert draft.summary == UNSUPPORTED


def test_malformed_citation_shapes_never_count_as_support() -> None:
    for malformed in (None, "1", ["1"], [0], [-1], [True], {}):
        response = {"summary": {"text": "Claim.", "citations": malformed}}
        draft = ground_draft(response, EVIDENCE)
        assert draft.summary == UNSUPPORTED, f"citations={malformed!r} should not be trusted"


def test_an_uncited_action_is_dropped_entirely() -> None:
    response = {"actions": [{"title": "Fix it", "rationale": "Because", "owner": "ops", "citations": []}]}
    draft = ground_draft(response, EVIDENCE)
    assert draft.actions == []
    assert draft.unsupported_claims_dropped == 1


def test_a_surviving_action_is_bound_to_its_first_cited_evidence() -> None:
    response = {"actions": [{"title": "Fix it", "rationale": "Because", "owner": "ops", "citations": [2, 1]}]}
    draft = ground_draft(response, EVIDENCE)
    assert len(draft.actions) == 1
    assert draft.actions[0].evidence_id == "e1"


def test_empty_evidence_list_makes_every_section_unsupported() -> None:
    response = {"summary": {"text": "Anything.", "citations": [1]}}
    draft = ground_draft(response, [])
    assert draft.summary == UNSUPPORTED
    assert draft.root_cause == UNSUPPORTED


def test_parse_model_json_tolerates_a_code_fence() -> None:
    raw = '```json\n{"summary": {"text": "x", "citations": [1]}}\n```'
    assert parse_model_json(raw) == {"summary": {"text": "x", "citations": [1]}}


def test_parse_model_json_raises_on_non_json() -> None:
    import pytest

    with pytest.raises(Exception):
        parse_model_json("not json at all")


# Property test: ground_draft can only ever produce UNSUPPORTED or a
# substring of text the model itself supplied -- it can never invent new
# text. This is checked against adversarial input shapes, not just the
# fixed examples above.
claim_strategy = st.one_of(
    st.none(),
    st.text(max_size=50),
    st.dictionaries(
        keys=st.sampled_from(["text", "citations"]),
        values=st.one_of(
            st.text(max_size=50),
            st.lists(st.one_of(st.integers(min_value=-5, max_value=10), st.text(max_size=5), st.booleans()), max_size=5),
            st.none(),
        ),
    ),
)


@settings(max_examples=300)
@given(section=claim_strategy)
def test_grounding_only_ever_removes_never_adds_property(section: object) -> None:
    response = {"summary": section}
    draft = ground_draft(response, EVIDENCE)
    if draft.summary != UNSUPPORTED:
        assert isinstance(section, dict)
        raw_text = section.get("text")
        assert isinstance(raw_text, str)
        assert draft.summary in raw_text or draft.summary == raw_text.strip()


def _make_entry(occurred_at: int, summary_len: int) -> EvidenceEntry:
    return EvidenceEntry(
        id=f"e{occurred_at}",
        occurred_at=occurred_at,
        source="alert",
        summary="x" * summary_len,
        detail=None,
        authorized_by="ops",
    )


def test_bound_evidence_by_chars_keeps_everything_under_budget() -> None:
    entries = [_make_entry(i, 10) for i in range(1, 6)]
    bounded = bound_evidence_by_chars(entries, max_chars=10_000)
    assert bounded == entries


def test_bound_evidence_by_chars_keeps_the_most_recent_not_the_oldest() -> None:
    # Ten entries, each renders to ~120 chars; a budget of 250 fits ~2.
    entries = [_make_entry(i, 100) for i in range(1, 11)]
    bounded = bound_evidence_by_chars(entries, max_chars=250)
    assert len(bounded) < len(entries)
    # Kept entries are the most recent (highest occurred_at), in
    # chronological order.
    assert [entry.occurred_at for entry in bounded] == sorted(entry.occurred_at for entry in bounded)
    assert bounded[-1].occurred_at == 10


def test_bound_evidence_by_chars_always_keeps_at_least_one_entry() -> None:
    # A single entry far larger than the budget must still survive --
    # otherwise drafting would silently get zero evidence instead of a
    # real (if large) request.
    entries = [_make_entry(1, 5_000)]
    bounded = bound_evidence_by_chars(entries, max_chars=100)
    assert len(bounded) == 1


def test_bound_evidence_by_chars_handles_empty_input() -> None:
    assert bound_evidence_by_chars([], max_chars=1_000) == []
