"""Replay local question proposals and confirm documentary inventory explicitly."""

from dataclasses import dataclass, replace
from hashlib import sha256

from ..case_analysis import PericialQuestion, SourceProvenance
from ..case_intake import DocumentInventoryDecision, extract_questions, inventory_proposals
from .models import PrivateContentId
from .ports import RepositoryConflict, RepositoryIntegrityError


@dataclass(frozen=True, slots=True)
class GetCaseIntake:
    get_analysis: object
    open_document: object
    extractor: object

    def execute(self, workspace_id):
        record, case, _base, _availability, proposals, inventory = self._resolve(workspace_id)
        return record, case, proposals, inventory

    def execute_for_command(self, workspace_id):
        """Base de MUTACAO (mesmo contrato de `GetCaseAnalysis.execute_for_command`).

        A Analise do Caso lida pelo GET e uma projecao da disponibilidade decidida
        pelo perito; gravar essa projecao diverge do predecessor persistido e o Save
        recusa ("source extraction is immutable"). As propostas saem da projecao
        (peca excluida nao propoe nada); a escrita parte do persistido.
        """
        record, _case, base, availability, proposals, _inventory = self._resolve(workspace_id)
        return record, base, availability, proposals

    def _resolve(self, workspace_id):
        record, base, availability = self.get_analysis.execute_for_command(workspace_id)
        case = base.project_effective_availability(availability)
        if case.source_inventory_stale or case.stale_document_ids:
            raise RepositoryConflict("case intake requires current source inventory")
        physical = {}
        pages_by_document = {}
        proposals = []
        for document in case.documents:
            if not document.content_available or document.analysis_revision < 1:
                continue
            if document.storage_content_id not in physical:
                with self.open_document.execute(workspace_id, PrivateContentId.parse(document.storage_content_id)) as opened:
                    if opened.metadata.workspace_id != workspace_id or opened.metadata.checksum_sha256 != document.source_sha256:
                        raise RepositoryIntegrityError("case intake source mismatch")
                    extracted = self.extractor.extract(opened.stream, document_sha256=document.source_sha256)
                    if extracted.document_sha256 != document.source_sha256:
                        raise RepositoryIntegrityError("case intake extracted source mismatch")
                    physical[document.storage_content_id] = extracted.pages
            pages = physical[document.storage_content_id]
            pages_by_document[document.document_id] = pages
            for proposal in extract_questions(document, pages):
                identity = sha256(f"{workspace_id}:{proposal.proposal_id}".encode()).hexdigest()
                proposals.append(replace(proposal, proposal_id=identity))
        return record, case, base, availability, tuple(proposals), inventory_proposals(case.documents, pages_by_document)


@dataclass(frozen=True, slots=True)
class AcceptCaseQuestions:
    get_intake: object
    save_analysis: object
    ids: object

    def execute(self, workspace_id, *, proposal_ids, expected_revision):
        if type(proposal_ids) is not list or not proposal_ids or any(type(v) is not str for v in proposal_ids) or len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("question selection is invalid")
        record, case, availability, proposals = self.get_intake.execute_for_command(workspace_id)
        if type(expected_revision) is not int or record.revision != expected_revision:
            raise RepositoryConflict("question source revision changed")
        candidates = {p.proposal_id: p for p in proposals}
        if not set(proposal_ids) <= candidates.keys():
            raise ValueError("question source proposal is unavailable")
        questions = list(case.questions)
        for identity in proposal_ids:
            proposal = candidates[identity]
            if any(q.source_question == proposal.source and q.text == proposal.text and any(p.source_document_id == proposal.document_id for p in q.provenance) for q in questions):
                continue
            document = next(d for d in case.documents if d.document_id == proposal.document_id)
            token = self.ids.new_uuid().hex.upper()
            span = f"p. {proposal.source.page_start}" + (f"-{proposal.source.page_end}" if proposal.source.page_start != proposal.source.page_end else "")
            source = SourceProvenance(str(workspace_id), document.document_id, document.source_sha256, span, case.source_revision, f"OCCURRENCE-{token}")
            questions.append(PericialQuestion(f"PERICIAL-QUESTION-{token}", proposal.text, (), (), (source,), source_question=proposal.source))
        if tuple(questions) == case.questions:
            return record, case.project_effective_availability(availability)
        updated = replace(case, questions=tuple(questions))
        saved = self.save_analysis.execute(workspace_id, updated, expected_revision, allow_item_append=True)
        return saved, updated.project_effective_availability(availability)


@dataclass(frozen=True, slots=True)
class ConfirmDocumentInventory:
    get_analysis: object
    save_analysis: object
    get_expert_profile: object
    clock: object

    def execute(self, workspace_id, *, values, expected_revision):
        if type(values) is not dict or set(values) != {"category", "status", "source_document_ids", "reason"} or type(values["source_document_ids"]) is not list:
            raise ValueError("document inventory confirmation is invalid")
        record, case, availability = self.get_analysis.execute_for_command(workspace_id)
        if type(expected_revision) is not int or record.revision != expected_revision or case.source_inventory_stale or case.stale_document_ids:
            raise RepositoryConflict("document inventory source revision changed")
        _, profile = self.get_expert_profile.execute(workspace_id)
        decision = DocumentInventoryDecision(**{**values, "source_document_ids": tuple(values["source_document_ids"])}, confirmed_by=profile.profile_id, confirmed_at=self.clock.now().isoformat())
        # Presenca so se apoia em peca disponivel E nao excluida pelo perito (#251).
        available = {d.document_id for d in case.documents if availability.get(d.document_id, d.content_available)}
        if not set(decision.source_document_ids) <= available:
            raise ValueError("document inventory presence requires available source")
        updated = replace(case, document_inventory=tuple(item for item in case.document_inventory if item.category != decision.category) + (decision,))
        saved = self.save_analysis.execute(workspace_id, updated, expected_revision, allow_inventory_confirmation=True)
        return saved, updated.project_effective_availability(availability)
