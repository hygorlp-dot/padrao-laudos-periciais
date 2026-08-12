from hypothesis import given, strategies as st
import pytest

from scripts.backend_contract import Authority, ValueHistory


def test_source_value_is_effective():
    history = ValueHistory()
    source = history.record_source("A")
    assert history.effective() == source


def test_ai_proposal_never_overrides_source_and_remains_pending():
    history = ValueHistory()
    source = history.record_source("A")
    proposal = history.propose_ai("B")
    assert history.effective() == source
    assert history.pending_proposals() == (proposal,)


def test_ai_proposal_alone_has_no_effective_value():
    history = ValueHistory()
    proposal = history.propose_ai("B")
    with pytest.raises(ValueError, match="Nenhum valor efetivo"):
        history.effective()
    assert history.pending_proposals() == (proposal,)


def test_engine_decision_resolves_over_proposal_with_or_without_source():
    for with_source in (False, True):
        history = ValueHistory()
        if with_source:
            history.record_source("A")
        history.propose_ai("B")
        decision = history.decide_engine("C")
        assert history.effective() == decision
        assert history.pending_proposals() == ()


def test_professional_override_remains_highest_and_requires_reason():
    history = ValueHistory()
    history.record_source("A")
    history.propose_ai("B")
    history.decide_engine("C")
    override = history.override_professional("D", reason="Validação do perito")
    assert history.effective() == override
    assert len(history.entries) == 4


def test_snapshot_before_engine_decision_never_promotes_proposal():
    history = ValueHistory()
    source = history.record_source("A")
    history.propose_ai("B")
    snapshot = history.snapshot()
    history.decide_engine("C")
    history.restore(snapshot)
    assert history.effective() == source


def test_restored_history_is_isolated_from_snapshot_container_mutation():
    history = ValueHistory()
    source = history.record_source({"value": ["A"]})
    snapshot = history.snapshot()
    history.decide_engine("C")
    history.restore(snapshot)
    snapshot.clear()
    snapshot.append("invalid entry")
    assert history.effective() == source
    assert len(history.entries) == 1


def test_generic_self_declared_authority_is_not_an_available_api():
    history = ValueHistory()
    assert not hasattr(history, "add")
    proposal = history.propose_ai("B")
    assert proposal.authority is Authority.AI_PROPOSAL
    with pytest.raises(ValueError):
        history.effective()


@given(st.lists(st.text(min_size=1), min_size=1, max_size=8))
def test_any_number_of_ai_proposals_cannot_change_source(proposals):
    history = ValueHistory()
    source = history.record_source("SOURCE")
    for proposal in proposals:
        history.propose_ai(proposal)
    assert history.effective() == source
    assert len(history.pending_proposals()) == len(proposals)
