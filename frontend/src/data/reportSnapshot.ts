export type ExpertProfile = { profile_id: string; revision: number; full_name: string; professional_title: string; registration: string; court_registration: string | null; contact_line: string | null };
export type ReportSnapshot = {
  schema_version: "1.0.0"; report_id: string; workspace_id: string; source_snapshot: { workspace_id: string };
  expert_profile: ExpertProfile; editorial_profile: { profile_id: string; font_family: string; body_font_pt: number };
  context_matrix: Array<{ context_id: string; field: string; required: boolean; status: string; source_id: string | null; note: string }>;
  sections: Array<{ section_id: string; kind: string; title: string; order: number; required_by_cpc473: boolean }>;
  claims: Array<{ claim_id: string; section_id: string; text: string; authority: string; provenance: Array<{ provenance_id: string; source_kind: string; source_id: string; source_revision: number }> }>;
  answers: Array<{ answer_id: string; section_id: string; question_id: string; text: string; finding_id: string; evidence_ids: string[]; method_ids: string[]; decision_id: string; claim_ids: string[] }>;
  review_decisions: Array<{ review_id: string; action: string; professional_id: string; reason: string; timestamp: string; supersedes_review_id: string | null }>;
  state: string; coverage: { sections: number; material_claims: number; traceable_claims: number; answers: number; traceable_answers: number; cpc473_required_sections: number; cpc473_present_sections: number; context_required_fields: number; context_present_fields: number; complete: boolean; reasons: string[] };
  upstream_stale: boolean; upstream_stale_reasons: string[];
};
export type ProfileEnvelope = { revision: number; updated_at: string; profile: ExpertProfile };
export type ReportEnvelope = { revision: number; updated_at: string; snapshot: ReportSnapshot };
export class ReportApiError extends Error { constructor(readonly kind: "not-found" | "invalid" | "unavailable") { super(kind); } }
const base = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}`;
async function decode(response: Response) { if (response.status === 404) throw new ReportApiError("not-found"); if (!response.ok) throw new ReportApiError("unavailable"); return response.json(); }
function profileEnvelope(value: unknown): ProfileEnvelope { const item = value as ProfileEnvelope; if (!item || !Number.isInteger(item.revision) || item.revision < 1 || !item.profile?.profile_id) throw new ReportApiError("invalid"); return item; }
function reportEnvelope(value: unknown, workspaceId: string): ReportEnvelope { const item = value as ReportEnvelope; const report = item?.snapshot; if (!Number.isInteger(item?.revision) || item.revision < 1 || report?.schema_version !== "1.0.0" || report.workspace_id !== workspaceId || report.source_snapshot?.workspace_id !== workspaceId || !Array.isArray(report.sections) || !Array.isArray(report.claims) || !Array.isArray(report.answers)) throw new ReportApiError("invalid"); return item; }
export async function getExpertProfile(workspaceId: string, signal?: AbortSignal) { return profileEnvelope(await decode(await fetch(`${base(workspaceId)}/expert-profile`, { method: "GET", credentials: "same-origin", cache: "no-store", signal }))); }
export async function saveExpertProfile(workspaceId: string, profile: ExpertProfile) { return profileEnvelope(await decode(await fetch(`${base(workspaceId)}/expert-profile`, { method: "PUT", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: null, profile }) }))); }
export async function getReportSnapshot(workspaceId: string, signal?: AbortSignal) { return reportEnvelope(await decode(await fetch(`${base(workspaceId)}/report-snapshot`, { method: "GET", credentials: "same-origin", cache: "no-store", signal })), workspaceId); }
export async function startReportSnapshot(workspaceId: string) { return reportEnvelope(await decode(await fetch(`${base(workspaceId)}/report-snapshot`, { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: "{}" })), workspaceId); }
export async function saveReportSnapshot(workspaceId: string, envelope: ReportEnvelope, snapshot: ReportSnapshot) { return reportEnvelope(await decode(await fetch(`${base(workspaceId)}/report-snapshot`, { method: "PUT", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: envelope.revision, snapshot }) })), workspaceId); }
