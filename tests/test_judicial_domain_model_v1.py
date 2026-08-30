from __future__ import annotations

from dataclasses import replace
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.backend_contract.judicial_domain import (
    AccessRelation,
    EntityKind,
    JudicialEntity,
    NormalizedProceduralRole,
    ParticipantStatus,
    ProcessParticipant,
    ProcessPole,
    ProceduralContext,
    ProceduralRole,
    RepresentationLink,
    SourceProvenance,
    legacy_singular_party_view,
)


SHA = "0" * 64
ROOT = Path(__file__).resolve().parents[1]


def provenance(occurrence: str = "Parte autora sintética") -> SourceProvenance:
    return SourceProvenance(
        source_system="SYNTHETIC_PJE",
        source_document_id="DOC-SYNTHETIC-001",
        source_sha256=SHA,
        page=1,
        occurrence=occurrence,
    )


def entity(entity_id: str, name: str, kind=EntityKind.NATURAL_PERSON) -> JudicialEntity:
    return JudicialEntity(entity_id, name, kind, (provenance(name),))


def participant(
    participant_id: str,
    entity_id: str,
    pole: ProcessPole,
    normalized: NormalizedProceduralRole,
    *,
    raw_role: str,
    principal: bool = True,
    status: ParticipantStatus = ParticipantStatus.ACTIVE,
    context_id: str = "CTX-001",
) -> ProcessParticipant:
    return ProcessParticipant(
        participant_id=participant_id,
        entity_id=entity_id,
        context_id=context_id,
        pole=pole,
        role=ProceduralRole(raw_role, normalized),
        principal=principal,
        status=status,
        provenance=(provenance(raw_role),),
    )


def valid_context() -> ProceduralContext:
    author = entity("ENT-001", "Pessoa Autora Sintética")
    defendant = entity("ENT-002", "Empresa Ré Sintética", EntityKind.LEGAL_ENTITY)
    lawyer = entity("ENT-003", "Advogada Sintética")
    viewer = entity("ENT-004", "Visualizador Sintético")
    active = participant(
        "PAR-001", author.entity_id, ProcessPole.ACTIVE, NormalizedProceduralRole.CLAIMANT,
        raw_role="AUTOR",
    )
    passive = participant(
        "PAR-002", defendant.entity_id, ProcessPole.PASSIVE, NormalizedProceduralRole.DEFENDANT,
        raw_role="RÉU",
    )
    return ProceduralContext(
        context_id="CTX-001",
        instance_label="PRIMEIRO_GRAU",
        snapshot_id="SNAPSHOT-SYNTHETIC-001",
        entities=(author, defendant, lawyer, viewer),
        participants=(active, passive),
        representation_links=(RepresentationLink(
            link_id="REP-001",
            representative_entity_id=lawyer.entity_id,
            represented_participant_ids=(active.participant_id,),
            representation_role_raw="ADVOGADA",
            provenance=(provenance("Advogada da parte autora"),),
        ),),
        access_relations=(AccessRelation(
            access_id="ACC-001",
            entity_id=viewer.entity_id,
            context_id="CTX-001",
            access_type_raw="VISUALIZADOR",
            provenance=(provenance("Acesso concedido"),),
        ),),
        provenance=(provenance("Contexto processual sintético"),),
    )


def test_relations_preserve_party_representation_and_access_boundaries():
    context = valid_context()

    participant_entities = {item.entity_id for item in context.participants}
    assert "ENT-003" not in participant_entities
    assert "ENT-004" not in participant_entities
    assert context.representation_links[0].representative_entity_id == "ENT-003"
    assert context.access_relations[0].entity_id == "ENT-004"


def test_raw_unknown_role_is_preserved_without_invented_normalization():
    role = ProceduralRole("INTERVENIENTE ATÍPICO", NormalizedProceduralRole.UNKNOWN)
    assert role.raw_label == "INTERVENIENTE ATÍPICO"
    assert role.normalized is NormalizedProceduralRole.UNKNOWN


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: replace(value, provenance=()),
        lambda value: replace(value, entities=value.entities + (value.entities[0],)),
        lambda value: replace(value, participants=value.participants + (replace(value.participants[0], participant_id="PAR-002"),)),
        lambda value: replace(value, participants=(replace(value.participants[0], entity_id="ENT-MISSING"), *value.participants[1:])),
        lambda value: replace(value, participants=(replace(value.participants[0], context_id="CTX-OTHER"), *value.participants[1:])),
        lambda value: replace(value, representation_links=(replace(value.representation_links[0], represented_participant_ids=("PAR-MISSING",)),)),
        lambda value: replace(value, access_relations=(replace(value.access_relations[0], entity_id="ENT-MISSING"),)),
    ],
    ids=["missing-provenance", "duplicate-entity", "duplicate-participant", "dangling-entity", "wrong-context", "dangling-representation", "dangling-access"],
)
def test_context_graph_fails_closed_on_ambiguous_or_dangling_relations(mutation):
    with pytest.raises(ValueError):
        mutation(valid_context())


def test_same_entity_may_have_distinct_roles_only_in_explicit_contexts():
    first = valid_context()
    second_participant = participant(
        "PAR-101", "ENT-001", ProcessPole.PASSIVE, NormalizedProceduralRole.RESPONDENT,
        raw_role="AGRAVADO", context_id="CTX-002",
    )
    second = ProceduralContext(
        context_id="CTX-002",
        instance_label="SEGUNDO_GRAU",
        snapshot_id="SNAPSHOT-SYNTHETIC-002",
        entities=(first.entities[0],),
        participants=(second_participant,),
        representation_links=(),
        access_relations=(),
        provenance=(provenance("Novo contexto sintético"),),
    )
    assert first.participants[0].role.normalized is NormalizedProceduralRole.CLAIMANT
    assert second.participants[0].role.normalized is NormalizedProceduralRole.RESPONDENT


def test_legacy_singular_party_fields_are_only_an_unambiguous_projection():
    context = valid_context()
    assert legacy_singular_party_view(context) == {
        "parte_requerente": "Pessoa Autora Sintética",
        "parte_requerida": "Empresa Ré Sintética",
    }

    plural = replace(
        context,
        entities=context.entities + (entity("ENT-005", "Outra Autora Sintética"),),
        participants=context.participants + (
            participant(
                "PAR-003", "ENT-005", ProcessPole.ACTIVE,
                NormalizedProceduralRole.CLAIMANT, raw_role="LITISCONSORTE ATIVO",
            ),
        ),
    )
    assert legacy_singular_party_view(plural) is None


@pytest.mark.parametrize("status", [ParticipantStatus.INACTIVE, ParticipantStatus.SUSPENDED, ParticipantStatus.UNKNOWN])
def test_legacy_projection_rejects_non_active_principal_status(status):
    context = valid_context()
    changed = replace(context.participants[0], status=status)
    assert legacy_singular_party_view(replace(context, participants=(changed, context.participants[1]))) is None


def test_synthetic_fixture_satisfies_closed_serialization_contract():
    schema = json.loads((ROOT / "schemas/judicial-domain-model-v1.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads((ROOT / "tests/fixtures/judicial-domain-model-v1.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(fixture)
    assert {item["entity_id"] for item in fixture["participants"]} == {"ENT-001", "ENT-002"}
    assert fixture["representation_links"][0]["representative_entity_id"] == "ENT-003"
    assert fixture["access_relations"][0]["entity_id"] == "ENT-004"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["participants"][0].pop("provenance"),
        lambda value: value["participants"][0]["role"].update(normalized="INVENTED_ROLE"),
        lambda value: value["entities"][0].update(adapter_specific_party_type="AUTOR_PJE"),
        lambda value: value["access_relations"][0].update(participant_id="PAR-001"),
        lambda value: value.update(parte_requerente="Pessoa Autora Sintética"),
    ],
    ids=["missing-provenance", "invented-role", "adapter-flattening", "access-participation-flattening", "legacy-authority"],
)
def test_serialization_contract_rejects_semantic_flattening(mutate):
    schema = json.loads((ROOT / "schemas/judicial-domain-model-v1.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads((ROOT / "tests/fixtures/judicial-domain-model-v1.json").read_text(encoding="utf-8"))
    candidate = copy.deepcopy(fixture)
    mutate(candidate)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(candidate)


@pytest.mark.parametrize(
    ("pole", "normalized", "raw_role"),
    [
        (ProcessPole.ACTIVE, NormalizedProceduralRole.PROSECUTOR_PARTY, "MINISTÉRIO PÚBLICO AUTOR"),
        (ProcessPole.OTHER, NormalizedProceduralRole.COSTS_LEGIS, "FISCAL DA ORDEM JURÍDICA"),
        (ProcessPole.THIRD, NormalizedProceduralRole.INTERESTED_THIRD_PARTY, "TERCEIRO INTERESSADO"),
        (ProcessPole.THIRD, NormalizedProceduralRole.AMICUS_CURIAE, "AMICUS CURIAE"),
        (ProcessPole.THIRD, NormalizedProceduralRole.ASSISTANT, "ASSISTENTE"),
        (ProcessPole.OTHER, NormalizedProceduralRole.AUTHORITY, "AUTORIDADE COATORA"),
        (ProcessPole.UNKNOWN, NormalizedProceduralRole.UNKNOWN, "RÓTULO SINTÉTICO NÃO MAPEADO"),
    ],
)
def test_minimum_role_matrix_preserves_raw_and_normalized_dimensions(pole, normalized, raw_role):
    item = participant("PAR-900", "ENT-900", pole, normalized, raw_role=raw_role, principal=False)
    assert item.role.raw_label == raw_role
    assert item.role.normalized is normalized


@pytest.mark.parametrize(("active_count", "passive_count"), [(1, 1), (2, 1), (1, 2), (2, 2)])
def test_participant_cardinality_matrix_is_plural_without_flattening(active_count, passive_count):
    entities = []
    participants = []
    for index in range(active_count + passive_count):
        number = index + 1
        entity_id = f"ENT-{number:03d}"
        entities.append(entity(entity_id, f"Parte Sintética {number}"))
        is_active = index < active_count
        participants.append(participant(
            f"PAR-{number:03d}", entity_id,
            ProcessPole.ACTIVE if is_active else ProcessPole.PASSIVE,
            NormalizedProceduralRole.CLAIMANT if is_active else NormalizedProceduralRole.DEFENDANT,
            raw_role="AUTOR" if is_active else "RÉU",
        ))
    context = ProceduralContext(
        "CTX-001", "PRIMEIRO_GRAU", "SNAPSHOT-SYNTHETIC-001",
        tuple(entities), tuple(participants), (), (), (provenance(),),
    )
    assert sum(item.pole is ProcessPole.ACTIVE for item in context.participants) == active_count
    assert sum(item.pole is ProcessPole.PASSIVE for item in context.participants) == passive_count
    assert (legacy_singular_party_view(context) is not None) is (active_count == passive_count == 1)


def test_representation_is_many_to_many_and_never_changes_participant_cardinality():
    first_party = entity("ENT-001", "Parte Sintética Um")
    second_party = entity("ENT-002", "Parte Sintética Dois")
    public_counsel = entity("ENT-003", "Procuradoria Sintética", EntityKind.PUBLIC_ENTITY)
    defender = entity("ENT-004", "Defensoria Sintética", EntityKind.PUBLIC_ENTITY)
    first = participant(
        "PAR-001", "ENT-001", ProcessPole.ACTIVE, NormalizedProceduralRole.CLAIMANT,
        raw_role="AUTOR",
    )
    second = participant(
        "PAR-002", "ENT-002", ProcessPole.ACTIVE, NormalizedProceduralRole.CLAIMANT,
        raw_role="LITISCONSORTE ATIVO",
    )
    context = ProceduralContext(
        "CTX-001", "PRIMEIRO_GRAU", "SNAPSHOT-SYNTHETIC-001",
        (first_party, second_party, public_counsel, defender),
        (first, second),
        (
            RepresentationLink(
                "REP-001", "ENT-003", ("PAR-001", "PAR-002"), "PROCURADORIA",
                (provenance("Procuradoria de ambas as partes"),),
            ),
            RepresentationLink(
                "REP-002", "ENT-004", ("PAR-001",), "DEFENSORIA",
                (provenance("Defensoria da primeira parte"),),
            ),
        ),
        (), (provenance(),),
    )
    assert len(context.participants) == 2
    assert {item.representative_entity_id for item in context.representation_links} == {"ENT-003", "ENT-004"}


def test_relation_order_and_irrelevant_access_do_not_change_legacy_projection():
    context = valid_context()
    reordered = replace(
        context,
        entities=tuple(reversed(context.entities)),
        participants=tuple(reversed(context.participants)),
    )
    extra_access = AccessRelation(
        "ACC-002", "ENT-003", "CTX-001", "CONSULTA SINTÉTICA",
        (provenance("Consulta sem participação"),),
    )
    augmented = replace(reordered, access_relations=(*reordered.access_relations, extra_access))
    assert legacy_singular_party_view(augmented) == legacy_singular_party_view(context)
