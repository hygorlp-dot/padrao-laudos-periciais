import unittest
import re
from pathlib import Path
from dataclasses import dataclass

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

    def test_invalid_transition_is_rejected_without_state_change(self):
        machine = CaseStateMachine()
        with self.assertRaises(DomainError):
            machine.transition(CaseState.PAT_FINAL)
        self.assertEqual(machine.state, CaseState.CRIADO)


class RevisionAndAuthorityTest(unittest.TestCase):
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

    def test_professional_override_is_explicit_and_effective(self):
        history = ValueHistory()
        history.add(Authority.SOURCE_VALUE, "alegado")
        history.add(Authority.AI_PROPOSAL, "proposto")
        history.add(Authority.ENGINE_DECISION, "decidido")
        override = history.add(Authority.PROFESSIONAL_OVERRIDE, "validado", reason="Decisão técnica do perito")
        self.assertEqual(history.effective().value, "validado")
        self.assertEqual(override.reason, "Decisão técnica do perito")
        self.assertEqual(len(history.entries), 4)

    def test_professional_override_requires_reason(self):
        with self.assertRaises(ValueError):
            ValueHistory().add(Authority.PROFESSIONAL_OVERRIDE, "x")


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
