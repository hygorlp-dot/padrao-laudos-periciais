import unittest
import re
from pathlib import Path
from dataclasses import dataclass, replace
from types import MappingProxyType

from scripts.backend_contract import (
    ArtifactStatus,
    AuditEvent,
    AuditLog,
    Authority,
    CapabilityRegistry,
    CapabilityStatus,
    CaseId,
    CaseRecord,
    CaseState,
    CaseStateMachine,
    DependencyGraph,
    DomainError,
    ErrorCategory,
    ErrorContract,
    EvidenceLimitation,
    InvariantRegistry,
    Job,
    JobStatus,
    MigrationRegistry,
    RevisionSource,
    RevisionStore,
    RollbackError,
    UnitOfWork,
    ValueHistory,
    default_invariants,
)


class CaseIdentityAndStateTest(unittest.TestCase):
    def test_case_id_is_stable_uuid_and_cnj_is_not_identity(self):
        case_id = CaseId.new()
        self.assertEqual(case_id, CaseId.parse(str(case_id)))
        self.assertNotEqual(str(case_id), "0000000-00.0000.0.00.0000")

    def test_invalid_case_id_is_rejected(self):
        with self.assertRaises(ValueError):
            CaseId.parse("processo-judicial-123")

    def test_cnj_is_attribute_and_does_not_define_case_identity(self):
        first = CaseRecord.create("0000000-00.0000.0.00.0000")
        second = CaseRecord.create("0000000-00.0000.0.00.0000")
        self.assertNotEqual(first.case_id, second.case_id)
        self.assertEqual(first.cnj_number, second.cnj_number)

    def test_valid_transition(self):
        machine = CaseStateMachine()
        self.assertEqual(machine.transition(CaseState.AUTOS_IMPORTADOS), CaseState.AUTOS_IMPORTADOS)
        self.assertEqual(machine.history[0].operation, "ADVANCE")
        self.assertEqual(machine.history[0].reason, "AVANCO_NORMAL")

    def test_invalid_transition_is_rejected_without_state_change(self):
        machine = CaseStateMachine()
        with self.assertRaises(DomainError):
            machine.transition(CaseState.PAT_FINAL)
        self.assertEqual(machine.state, CaseState.CRIADO)
        self.assertEqual(machine.history, ())

    def test_authorized_reopen_requires_previous_state_and_reason(self):
        machine = CaseStateMachine()
        machine.transition(CaseState.AUTOS_IMPORTADOS)
        machine.transition(CaseState.AUTOS_ANALISADOS)
        machine.reopen(CaseState.AUTOS_IMPORTADOS, "Autos complementares recebidos")
        self.assertEqual(machine.state, CaseState.AUTOS_IMPORTADOS)
        record = machine.history[-1]
        self.assertEqual((record.origin, record.destination), (CaseState.AUTOS_ANALISADOS, CaseState.AUTOS_IMPORTADOS))
        self.assertEqual(record.reason, "Autos complementares recebidos")
        self.assertTrue(record.timestamp)

    def test_reopen_without_reason_or_with_arbitrary_jump_is_rejected(self):
        machine = CaseStateMachine(CaseState.DELIMITADO)
        with self.assertRaises(DomainError):
            machine.reopen(CaseState.AUTOS_ANALISADOS, "")
        with self.assertRaises(DomainError):
            machine.reopen(CaseState.AUTOS_IMPORTADOS, "Salto indevido")
        self.assertEqual(machine.history, ())

    def test_unit_of_work_rolls_back_state_and_transition_history(self):
        machine = CaseStateMachine()
        uow = UnitOfWork(machine)

        def failing_transition():
            machine.transition(CaseState.AUTOS_IMPORTADOS)
            raise RuntimeError("falha simulada")

        with self.assertRaises(RuntimeError):
            uow.execute(failing_transition)
        self.assertEqual(machine.state, CaseState.CRIADO)
        self.assertEqual(machine.history, ())

    def test_unit_of_work_attempts_every_restore_when_one_participant_fails(self):
        class Participant:
            def __init__(self, name, fail_restore=False):
                self.name = name
                self.value = "before"
                self.fail_restore = fail_restore

            def snapshot(self):
                return self.value

            def restore(self, snapshot):
                if self.fail_restore:
                    raise RuntimeError(f"restore-{self.name}")
                self.value = snapshot

        for failing_index in range(3):
            participants = [
                Participant(str(index), fail_restore=index == failing_index)
                for index in range(3)
            ]
            uow = UnitOfWork(*participants)

            def fail_operation():
                for participant in participants:
                    participant.value = "dirty"
                raise ValueError("operation")

            with self.assertRaises(RollbackError) as captured:
                uow.execute(fail_operation)
            self.assertIsInstance(captured.exception.original_error, ValueError)
            self.assertEqual(len(captured.exception.restore_errors), 1)
            for index, participant in enumerate(participants):
                expected = "dirty" if index == failing_index else "before"
                self.assertEqual(participant.value, expected)

    def test_unit_of_work_rejects_participants_without_reversible_contract(self):
        class SnapshotOnly:
            def snapshot(self):
                return "state"

        for participant in ({"before"}, SnapshotOnly(), object()):
            with self.assertRaisesRegex(TypeError, "participante reversível"):
                UnitOfWork(participant)

    def test_unit_of_work_rolls_back_before_reraising_base_exception(self):
        values = ["before"]
        uow = UnitOfWork(values)

        def cancelled():
            values[:] = ["dirty"]
            raise SystemExit(7)

        with self.assertRaises(SystemExit):
            uow.execute(cancelled)
        self.assertEqual(values, ["before"])

    def test_unit_of_work_builtin_subclasses_ignore_noncallable_protocol_shadows(self):
        class OddList(list):
            snapshot = None

        class OddDict(dict):
            restore = None

        values = OddList(["before"])
        mapping = OddDict(value="before")
        uow = UnitOfWork(values, mapping)

        def failing_change():
            values[:] = ["dirty"]
            mapping["value"] = "dirty"
            raise RuntimeError("rollback")

        with self.assertRaisesRegex(RuntimeError, "rollback"):
            uow.execute(failing_change)
        self.assertEqual(values, ["before"])
        self.assertEqual(mapping, {"value": "before"})


class RevisionAndAuthorityTest(unittest.TestCase):
    def test_revision_store_rejects_ai_or_unknown_authority_as_current(self):
        store = RevisionStore()
        for source in (RevisionSource.AI, "AI_PROPOSAL"):
            with self.assertRaisesRegex(ValueError, "fonte de revis"):
                store.append("PAT-001", {"conclusao": "proposta"}, source)
        self.assertEqual(store.history("PAT-001"), ())

    def test_revision_store_append_is_atomic_when_payload_is_invalid(self):
        store = RevisionStore()
        current = store.append("PAT-001", {"valor": 1}, RevisionSource.SOURCE)
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaisesRegex(ValueError, "c.clico"):
            store.append("PAT-001", cyclic, RevisionSource.ENGINE)
        self.assertEqual(store.history("PAT-001"), (current,))
        self.assertIs(store.history("PAT-001")[0].status, ArtifactStatus.CURRENT)

        empty_store = RevisionStore()
        with self.assertRaisesRegex(ValueError, "c.clico"):
            empty_store.append("PAT-NEW", cyclic, RevisionSource.SOURCE)
        self.assertEqual(empty_store.snapshot().histories, ())

    def test_revision_store_restore_is_defensive_and_validated(self):
        store = RevisionStore()
        source = store.append("PAT-001", {"valor": 1}, RevisionSource.SOURCE)
        snapshot = store.snapshot()
        store.append("PAT-001", {"valor": 2}, RevisionSource.ENGINE)
        store.restore(snapshot)
        self.assertEqual(store.history("PAT-001"), (source,))
        with self.assertRaisesRegex(ValueError, "Snapshot de RevisionStore"):
            store.restore({"PAT-001": ["forged"]})
        self.assertEqual(store.history("PAT-001"), (source,))

    def test_revision_store_snapshot_is_instance_bound_and_immutable(self):
        first, second = RevisionStore(), RevisionStore()
        first.append("PAT-001", {"valor": 1}, RevisionSource.SOURCE)
        snapshot = first.snapshot()
        self.assertIsInstance(snapshot.histories, tuple)
        with self.assertRaisesRegex(ValueError, "Snapshot de RevisionStore"):
            second.restore(snapshot)

    def test_revision_store_restores_nested_payload_and_uow_rolls_back_all_participants(self):
        store = RevisionStore()
        original = store.append(
            "PAT-001",
            {"causa": {"fatores": ["água"], "detalhes": {"origem": "interna"}}},
            RevisionSource.SOURCE,
        )
        graph = DependencyGraph()
        graph.add_artifact("PAT-001")
        audit = AuditLog()
        uow = UnitOfWork(store, graph, audit)

        def failing_change():
            store.append("PAT-001", {"causa": "alterada"}, RevisionSource.ENGINE)
            graph.mark_stale("PAT-001")
            audit.append(AuditEvent.create("UPDATED", "COR-NESTED", "Falha sintética"))
            raise RuntimeError("rollback")

        with self.assertRaisesRegex(RuntimeError, "rollback"):
            uow.execute(failing_change)
        self.assertEqual(store.history("PAT-001"), (original,))
        self.assertIs(graph.status("PAT-001"), ArtifactStatus.CURRENT)
        self.assertEqual(audit.events, ())

    def test_revision_store_rejects_every_signed_field_tampering_atomically(self):
        store = RevisionStore()
        original = store.append("PAT-001", {"valor": 1}, RevisionSource.SOURCE)
        snapshot = store.snapshot()
        artifact_id, history = snapshot.histories[0]
        revision = history[0]
        attacks = (
            replace(revision, revision_id="forged"),
            replace(revision, artifact_id="PAT-999"),
            replace(revision, revision=2),
            replace(revision, created_at="forged"),
            replace(revision, supersedes=revision.revision_id),
            replace(revision, status=ArtifactStatus.SUPERSEDED),
            replace(revision, source=RevisionSource.ENGINE),
            replace(revision, source=RevisionSource.PROFESSIONAL),
            replace(revision, payload=MappingProxyType({"valor": "forged"})),
        )
        for forged in attacks:
            attack = replace(snapshot, histories=((artifact_id, (forged,)),))
            with self.assertRaisesRegex(ValueError, "Snapshot de RevisionStore"):
                store.restore(attack)
            self.assertEqual(store.history("PAT-001"), (original,))

    def test_revision_store_rejects_duplicate_cross_artifact_and_self_reference(self):
        store = RevisionStore()
        first = store.append("PAT-001", {"valor": 1}, RevisionSource.SOURCE)
        second = store.append("PAT-001", {"valor": 2}, RevisionSource.ENGINE)
        store.append("PAT-002", {"valor": 3}, RevisionSource.SOURCE)
        snapshot = store.snapshot()
        duplicate = replace(second, revision_id=first.revision_id, supersedes=first.revision_id)
        self_reference = replace(second, supersedes=second.revision_id)
        cross_artifact = replace(snapshot.histories[1][1][0], revision_id=first.revision_id)
        attacks = (
            replace(snapshot, histories=(("PAT-001", (first, duplicate)), snapshot.histories[1])),
            replace(snapshot, histories=(("PAT-001", (first, self_reference)), snapshot.histories[1])),
            replace(snapshot, histories=(snapshot.histories[0], ("PAT-002", (cross_artifact,)))),
        )
        for attack in attacks:
            with self.assertRaisesRegex(ValueError, "Snapshot de RevisionStore"):
                store.restore(attack)

    def test_revision_history_is_append_only(self):
        store = RevisionStore()
        first = store.append("PAT-001", {"situacao": "INCONCLUSIVA"}, RevisionSource.ENGINE)
        second = store.append("PAT-001", {"situacao": "ANOMALIA"}, RevisionSource.PROFESSIONAL)
        self.assertEqual(second.supersedes, first.revision_id)
        history = store.history("PAT-001")
        self.assertEqual(history[0].status, ArtifactStatus.SUPERSEDED)
        self.assertEqual(len(history), 2)

    def test_old_revision_cannot_be_mutated(self):
        store = RevisionStore()
        revision = store.append("PAT-001", {"valor": 1}, RevisionSource.SOURCE)
        with self.assertRaises(TypeError):
            revision.payload["valor"] = 2

    def test_revision_payload_is_deeply_immutable_and_defensive(self):
        original = {"causa": {"fatores": ["água"], "tags": {"umidade"}}}
        revision = RevisionStore().append("PAT-001", original, RevisionSource.ENGINE)
        original["causa"]["fatores"].append("vento")
        original["causa"]["tags"].add("externa")
        self.assertEqual(revision.payload["causa"]["fatores"], ("água",))
        self.assertEqual(revision.payload["causa"]["tags"], frozenset({"umidade"}))
        with self.assertRaises(TypeError):
            revision.payload["causa"]["novo"] = True
        with self.assertRaises(AttributeError):
            revision.payload["causa"]["fatores"].append("x")

    def test_professional_override_is_explicit_and_effective(self):
        history = ValueHistory()
        history.record_source("alegado")
        history.propose_ai("proposto")
        history.decide_engine("decidido")
        override = history.override_professional("validado", reason="Decisão técnica do perito")
        self.assertEqual(history.effective().value, "validado")
        self.assertEqual(override.reason, "Decisão técnica do perito")
        self.assertEqual(len(history.entries), 4)

    def test_professional_override_requires_reason(self):
        with self.assertRaises(ValueError):
            ValueHistory().override_professional("x", reason="")

    def test_value_history_entries_and_nested_values_are_immutable(self):
        original = {"classificacao": ["ANOMALIA"]}
        history = ValueHistory()
        history.decide_engine(original)
        override = history.override_professional(
            {"classificacao": ["INCONCLUSIVA"]},
            reason="Validação profissional",
        )
        original["classificacao"].append("ALTERADA")
        self.assertEqual(history.entries[0].value["classificacao"], ("ANOMALIA",))
        self.assertEqual(history.effective(), override)
        with self.assertRaises(AttributeError):
            history.entries.append(override)
        with self.assertRaises(TypeError):
            del history.entries[0]
        with self.assertRaises(AttributeError):
            override.value["classificacao"].append("x")


class DependencyAndUnitOfWorkTest(unittest.TestCase):
    def test_dependency_invalidation_is_transitive(self):
        graph = DependencyGraph()
        for artifact in ("OBS-001", "PAT-001", "RED-001", "QUE-001"):
            graph.add_artifact(artifact)
        graph.add_dependency("OBS-001", "PAT-001")
        graph.add_dependency("PAT-001", "RED-001")
        graph.add_dependency("RED-001", "QUE-001")
        self.assertEqual(graph.invalidate_dependents("OBS-001"), {"PAT-001", "RED-001", "QUE-001"})
        self.assertEqual(graph.status("QUE-001"), ArtifactStatus.STALE)

    def test_orphan_dependency_is_rejected(self):
        graph = DependencyGraph()
        graph.add_artifact("OBS-001")
        with self.assertRaises(DomainError):
            graph.add_dependency("OBS-001", "PAT-999")

    def test_dependency_cycle_is_rejected(self):
        graph = DependencyGraph()
        graph.add_artifact("OBS-001")
        graph.add_artifact("PAT-001")
        graph.add_dependency("OBS-001", "PAT-001")
        with self.assertRaises(DomainError):
            graph.add_dependency("PAT-001", "OBS-001")

    def test_stale_artifact_cannot_be_read_as_current(self):
        graph = DependencyGraph()
        graph.add_artifact("PAT-001")
        graph.mark_stale("PAT-001")
        with self.assertRaises(DomainError):
            graph.require_current("PAT-001")

    def test_unit_of_work_rolls_back_update_invalidation_and_audit(self):
        store = RevisionStore()
        graph = DependencyGraph()
        graph.add_artifact("OBS-001")
        graph.add_artifact("PAT-001")
        graph.add_dependency("OBS-001", "PAT-001")
        store.append("OBS-001", {"texto": "anterior"}, RevisionSource.SOURCE)
        audit = AuditLog()
        uow = UnitOfWork(store, graph, audit)

        def failing_update():
            store.append("OBS-001", {"texto": "sintético"}, RevisionSource.SOURCE)
            raise RuntimeError("falha simulada")

        with self.assertRaises(RuntimeError):
            uow.execute_material_change(
                failing_update, graph, "OBS-001", audit,
                AuditEvent.create("UPDATED", "COR-001", "Atualização sintética"),
            )
        self.assertEqual(len(store.history("OBS-001")), 1)
        self.assertEqual(store.history("OBS-001")[0].payload["texto"], "anterior")
        self.assertEqual(graph.status("PAT-001"), ArtifactStatus.CURRENT)
        self.assertEqual(audit.events, ())

    def test_material_change_commits_update_invalidation_and_audit_together(self):
        store, graph, audit = RevisionStore(), DependencyGraph(), AuditLog()
        for artifact in ("OBS-001", "PAT-001"):
            graph.add_artifact(artifact)
        graph.add_dependency("OBS-001", "PAT-001")
        uow = UnitOfWork(store, graph, audit)
        event = AuditEvent.create("UPDATED", "COR-001", "Atualização sintética")
        result, invalidated = uow.execute_material_change(
            lambda: store.append("OBS-001", {"texto": "novo"}, RevisionSource.SOURCE),
            graph, "OBS-001", audit, event,
        )
        self.assertEqual(result.artifact_id, "OBS-001")
        self.assertEqual(invalidated, {"PAT-001"})
        self.assertEqual(audit.events, (event,))


class InvariantsCapabilitiesJobsAndErrorsTest(unittest.TestCase):
    def test_default_invariants_reject_category_conversion(self):
        registry = InvariantRegistry(default_invariants())
        violations = registry.validate({"allegation_as_observation": True})
        self.assertIn("ALEGACAO_NAO_E_CONSTATACAO", {v.code for v in violations})

    def test_stale_invariant_and_professional_history(self):
        registry = InvariantRegistry(default_invariants())
        violations = registry.validate({"stale_used_as_current": True, "override_erases_history": True})
        self.assertEqual({v.code for v in violations}, {"STALE_NAO_E_ATUAL", "OVERRIDE_PRESERVA_HISTORICO"})

    def test_capability_registry_distinguishes_software_from_evidence(self):
        registry = CapabilityRegistry()
        registry.register("EXPORT_WORD", CapabilityStatus.NOT_IMPLEMENTED, "Renderer ainda ausente")
        self.assertEqual(registry.require("EXPORT_WORD").status, CapabilityStatus.NOT_IMPLEMENTED)
        limitation = EvidenceLimitation("CAUSA", "Evidência causal insuficiente")
        self.assertNotIsInstance(limitation, type(registry.require("EXPORT_WORD")))

    def test_missing_capability_is_rejected(self):
        with self.assertRaises(DomainError):
            CapabilityRegistry().require("INEXISTENTE")

    def test_job_progress_is_validated(self):
        with self.assertRaises(ValueError):
            Job.new(progress=101)
        job = Job.new()
        self.assertEqual(job.status, JobStatus.QUEUED)

    def test_error_contract_is_structured(self):
        error = ErrorContract.create(
            error_code="DOMAIN.INVALID_STATE",
            severity="ERROR",
            category=ErrorCategory.DOMAIN,
            message="Transição inválida",
            recoverable=True,
            suggested_action="Retornar ao estado anterior",
            case_id=str(CaseId.new()),
        )
        self.assertTrue(error.correlation_id)
        self.assertEqual(error.category, ErrorCategory.DOMAIN)

    def test_invalid_error_severity_is_rejected(self):
        with self.assertRaises(ValueError):
            ErrorContract.create(
                error_code="DOMAIN.X", severity="FATAL", category="DOMAIN",
                message="x", recoverable=False, suggested_action="y",
            )


class MigrationTest(unittest.TestCase):
    def test_migrations_run_sequentially(self):
        migrations = MigrationRegistry(current_version=3)
        migrations.register(1, 2, lambda d: {**d, "schema_version": 2, "novo": True})
        migrations.register(2, 3, lambda d: {**d, "schema_version": 3})
        migrated = migrations.migrate({"schema_version": 1})
        self.assertEqual(migrated["schema_version"], 3)
        self.assertTrue(migrated["novo"])

    def test_incompatible_or_missing_migration_is_rejected(self):
        migrations = MigrationRegistry(current_version=3)
        with self.assertRaises(DomainError):
            migrations.migrate({"schema_version": 1})
        with self.assertRaises(DomainError):
            migrations.migrate({"schema_version": 4})


class PrivacyFixtureTest(unittest.TestCase):
    def test_fixtures_do_not_contain_formatted_cpf(self):
        fixture_root = Path(__file__).parent / "fixtures"
        cpf = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
        matches = [str(path) for path in fixture_root.rglob("*.json") if cpf.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
