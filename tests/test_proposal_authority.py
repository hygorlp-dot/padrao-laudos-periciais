from hypothesis import given, strategies as st
import pytest
from dataclasses import replace

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
    with pytest.raises(AttributeError):
        snapshot.entries.clear()
    assert history.effective() == source
    assert len(history.entries) == 1


def test_restore_rejects_tampered_authority_reason_or_payload():
    history = ValueHistory()
    history.propose_ai({"value": ["B"]})
    snapshot = history.snapshot()
    proposal = snapshot.entries[0]
    attacks = (
        replace(snapshot, entries=(replace(proposal, authority=Authority.PROFESSIONAL_OVERRIDE),)),
        replace(snapshot, entries=(replace(proposal, authority=Authority.PROFESSIONAL_OVERRIDE, reason="forged"),)),
        replace(snapshot, entries=(replace(proposal, value={"value": ["changed"]}),)),
    )
    for attack in attacks:
        with pytest.raises(ValueError, match="Snapshot de ValueHistory inválido"):
            history.restore(attack)
    assert history.pending_proposals() == (proposal,)


def test_values_with_ambiguous_repr_or_mutable_unsupported_types_are_rejected():
    class Ambiguous:
        def __init__(self, value):
            self.value = value

        def __repr__(self):
            return "same-repr"

    history = ValueHistory()
    for value in (Ambiguous("trusted"), bytearray(b"AB")):
        with pytest.raises((TypeError, ValueError), match="Tipo de valor não suportado"):
            history.record_source(value)


def test_scalar_subclasses_with_hidden_state_are_rejected():
    class StatefulStr(str):
        pass

    class StatefulFloat(float):
        pass

    values = (StatefulStr("same"), StatefulFloat(1.0))
    for value in values:
        value.marker = "mutable"
        with pytest.raises(TypeError, match="Tipo de valor não suportado"):
            ValueHistory().record_source(value)
    with pytest.raises(TypeError, match="justificativa"):
        ValueHistory().override_professional("D", reason=StatefulStr("reason"))


def test_reason_must_be_immutable_nonempty_text():
    history = ValueHistory()
    with pytest.raises((TypeError, ValueError), match="justificativa"):
        history.override_professional("D", reason=["mutable"])
    with pytest.raises((TypeError, ValueError), match="justificativa"):
        history.override_professional("D", reason="   ")


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
