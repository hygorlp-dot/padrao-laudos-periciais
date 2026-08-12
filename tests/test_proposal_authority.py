from hypothesis import given, strategies as st
import pytest

from scripts.backend_contract import Authority, ValueHistory


def test_source_value_is_effective():
    history = ValueHistory()
    source = history.add(Authority.SOURCE_VALUE, "A")
    assert history.effective() == source


def test_ai_proposal_never_overrides_source_and_remains_pending():
    history = ValueHistory()
    source = history.add(Authority.SOURCE_VALUE, "A")
    proposal = history.add(Authority.AI_PROPOSAL, "B")
    assert history.effective() == source
    assert history.pending_proposals() == (proposal,)


def test_ai_proposal_alone_has_no_effective_value():
    history = ValueHistory()
    proposal = history.add(Authority.AI_PROPOSAL, "B")
    with pytest.raises(ValueError, match="Nenhum valor efetivo"):
        history.effective()
    assert history.pending_proposals() == (proposal,)


def test_engine_decision_resolves_over_proposal_with_or_without_source():
    for with_source in (False, True):
        history = ValueHistory()
        if with_source:
            history.add(Authority.SOURCE_VALUE, "A")
        history.add(Authority.AI_PROPOSAL, "B")
        decision = history.add(Authority.ENGINE_DECISION, "C")
        assert history.effective() == decision
        assert history.pending_proposals() == ()


def test_professional_override_remains_highest_and_requires_reason():
    history = ValueHistory()
    history.add(Authority.SOURCE_VALUE, "A")
    history.add(Authority.AI_PROPOSAL, "B")
    history.add(Authority.ENGINE_DECISION, "C")
    override = history.add(Authority.PROFESSIONAL_OVERRIDE, "D", reason="Validação do perito")
    assert history.effective() == override
    assert len(history.entries) == 4


def test_snapshot_before_engine_decision_never_promotes_proposal():
    history = ValueHistory()
    source = history.add(Authority.SOURCE_VALUE, "A")
    history.add(Authority.AI_PROPOSAL, "B")
    snapshot = history.snapshot()
    history.add(Authority.ENGINE_DECISION, "C")
    history.restore(snapshot)
    assert history.effective() == source


@given(st.lists(st.text(min_size=1), min_size=1, max_size=8))
def test_any_number_of_ai_proposals_cannot_change_source(proposals):
    history = ValueHistory()
    source = history.add(Authority.SOURCE_VALUE, "SOURCE")
    for proposal in proposals:
        history.add(Authority.AI_PROPOSAL, proposal)
    assert history.effective() == source
    assert len(history.pending_proposals()) == len(proposals)
