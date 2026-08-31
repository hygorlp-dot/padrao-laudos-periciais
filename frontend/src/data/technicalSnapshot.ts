export type DecisionAction = "APPROVE" | "MODIFY" | "REJECT";
export type TechnicalSnapshot = {
  schema_version: "1.0.0"; snapshot_id: string; workspace_id: string;
  source_snapshot: { workspace_id: string; case_analysis_snapshot_id: string; case_analysis_revision: number; case_analysis_digest: string; inspection_session_id: string; inspection_session_revision: number; inspection_session_digest: string; source_revision: number };
  evidence_items: Array<{ evidence_id: string; proposition: string; assessment_id: string }>;
  source_links: Array<{ link_id: string; evidence_id: string; source_kind: string; source_id: string; source_revision: number; provenance: string }>;
  evidence_assessments: Array<{ assessment_id: string; evidence_id: string; why_relevant: string; supported_proposition: string; limitation_ids: string[]; contrary_evidence_ids: string[]; source_link_ids: string[]; review_state: "PENDING" | "APPROVED" | "REJECTED"; reviewer: string | null; reviewed_at: string | null }>;
  method_applications: Array<{ method_application_id: string; method_identity: string; selection_authority: string; procedure: string; parameters: string[]; input_ids: string[]; output_ids: string[]; limitation_ids: string[]; normative_references: string[]; execution_revision: number }>;
  method_inputs: Array<{ input_id: string; method_application_id: string; evidence_id: string; role: string }>;
  method_outputs: Array<{ output_id: string; method_application_id: string; description: string; provenance: string }>;
  finding_proposals: Array<{ proposal_id: string; technical_proposition: string; origin: "SOURCE_VALUE" | "ENGINE_DECISION" | "AI_PROPOSAL" | "PROFESSIONAL_PROPOSAL"; method_application_ids: string[]; supporting_evidence_ids: string[]; contrary_evidence_ids: string[]; limitation_ids: string[]; uncertainty_ids: string[]; scope: string }>;
  findings: Array<{ finding_id: string; proposal_id: string; decision_id: string; technical_proposition: string; scope: string }>;
  dependencies: Array<{ dependency_id: string; finding_id: string; depends_on_finding_id: string; rationale: string }>; conflicts: Array<{ conflict_id: string; proposal_id: string; contrary_evidence_ids: string[]; status: "UNRESOLVED" | "RESOLVED"; resolution_reasoning: string | null; decision_id: string | null }>;
  limitations: Array<{ limitation_id: string; owner_kind: string; owner_id: string; kind: string; description: string }>;
  uncertainties: Array<{ uncertainty_id: string; proposal_id: string; kind: string; description: string; impact: string }>;
  question_links: Array<{ link_id: string; question_id: string; finding_id: string; relevance: string }>;
  decisions: Array<{ decision_id: string; proposal_id: string; action: DecisionAction; professional_id: string; reason: string; modified_proposition: string | null; timestamp: string; supersedes_decision_id: string | null }>;
  coverage: { evidence_items: number; approved_evidence: number; method_applications: number; finding_proposals: number; effective_findings: number; unresolved_conflicts: number; complete: boolean; reasons: string[] };
  upstream_stale: boolean; upstream_stale_reasons: string[];
};
export type TechnicalEnvelope = { revision: number; updated_at: string; snapshot: TechnicalSnapshot };
export class TechnicalSnapshotApiError extends Error { constructor(readonly kind: "not-found" | "invalid" | "unavailable") { super(kind); } }
const endpoint = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/technical-snapshot`;
function parse(value: unknown, workspaceId: string): TechnicalEnvelope {
  if (!value || typeof value !== "object") throw new TechnicalSnapshotApiError("invalid");
  const envelope = value as TechnicalEnvelope; const snapshot = envelope.snapshot;
  const arrays = ["evidence_items", "source_links", "evidence_assessments", "method_applications", "method_inputs", "method_outputs", "finding_proposals", "findings", "dependencies", "conflicts", "limitations", "uncertainties", "question_links", "decisions", "upstream_stale_reasons"] as const;
  if (!Number.isInteger(envelope.revision) || envelope.revision < 1 || !snapshot || snapshot.schema_version !== "1.0.0" || typeof snapshot.snapshot_id !== "string" || snapshot.workspace_id !== workspaceId || snapshot.source_snapshot?.workspace_id !== workspaceId || arrays.some((name) => !Array.isArray(snapshot[name]))) throw new TechnicalSnapshotApiError("invalid");
  return envelope;
}
async function decode(response: Response, workspaceId: string) { if (response.status === 404) throw new TechnicalSnapshotApiError("not-found"); if (!response.ok) throw new TechnicalSnapshotApiError("unavailable"); return parse(await response.json(), workspaceId); }
export async function getTechnicalSnapshot(workspaceId: string, signal?: AbortSignal) { return decode(await fetch(endpoint(workspaceId), { method: "GET", cache: "no-store", credentials: "same-origin", signal }), workspaceId); }
export async function startTechnicalSnapshot(workspaceId: string) { return decode(await fetch(endpoint(workspaceId), { method: "POST", cache: "no-store", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: "{}" }), workspaceId); }
export async function saveTechnicalSnapshot(workspaceId: string, expectedRevision: number, snapshot: TechnicalSnapshot) { return decode(await fetch(endpoint(workspaceId), { method: "PUT", cache: "no-store", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: expectedRevision, snapshot }) }), workspaceId); }
