export type ParticipantPole = "ACTIVE" | "PASSIVE" | "OTHER";
export type ParticipantOrigin = "SOURCE" | "MANUAL" | "LEGACY_PROCESS_CASE";
export type ParticipantReviewState = "PROPOSED" | "CONFIRMED" | "REJECTED";
export type PersonType = "NATURAL_PERSON" | "LEGAL_ENTITY" | "PUBLIC_ENTITY" | "AUTHORITY" | "UNKNOWN";

export type ParticipantSource = {
  content_id: string;
  source_sha256: string;
  filename: string;
  page: number;
  source_start: number;
  source_end: number;
  excerpt: string;
  extraction_mode: "NATIVE_TEXT" | "OCR";
  logical_document_id: string | null;
};

export type ParticipantRepresentative = {
  name: string;
  role_label: string;
  registration: string | null;
  provenance: ParticipantSource[];
};

export type Participant = {
  participant_id: string;
  name: string;
  pole: ParticipantPole;
  procedural_role: string;
  source_role_label: string;
  person_type: PersonType;
  representatives: ParticipantRepresentative[];
  provenance: ParticipantSource[];
  origin: ParticipantOrigin;
  review_state: ParticipantReviewState;
  decided_at: string | null;
  edited: boolean;
};

export type ParticipantsView = {
  revision: number | null;
  updated_at: string | null;
  legacy_projection: boolean;
  participants: Participant[];
  proposals: Participant[];
  pending_documents: string[];
  interrupted_pages: { filename: string; page: number }[];
  stale_participant_ids: string[];
};

export type ParticipantDraft = {
  name: string;
  pole: ParticipantPole;
  procedural_role: string;
  source_role_label: string;
  person_type: PersonType;
  representatives: { name: string; role_label: string; registration: string | null }[];
};

export type ParticipantAction =
  | { action: "CONFIRM" | "REJECT"; payload: { proposal_id: string } }
  | { action: "ADD_MANUAL"; payload: { participant: ParticipantDraft } }
  | { action: "EDIT"; payload: { participant_id: string; participant: ParticipantDraft } }
  | { action: "REMOVE" | "RESTORE"; payload: { participant_id: string } }
  | { action: "REORDER"; payload: { participant_ids: string[] } };

export class ParticipantsApiError extends Error {
  constructor(readonly kind: "conflict" | "invalid" | "unavailable") {
    super(kind);
    this.name = "ParticipantsApiError";
  }
}

export const POLE_LABELS: Record<ParticipantPole, string> = {
  ACTIVE: "Polo ativo",
  PASSIVE: "Polo passivo",
  OTHER: "Outros participantes",
};

export const ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: "CLAIMANT", label: "Parte autora" },
  { value: "DEFENDANT", label: "Parte ré" },
  { value: "INTERESTED_THIRD_PARTY", label: "Terceiro interessado" },
  { value: "ASSISTANT", label: "Assistente" },
  { value: "COSTS_LEGIS", label: "Fiscal da ordem jurídica" },
  { value: "AMICUS_CURIAE", label: "Amicus curiae" },
  { value: "VICTIM", label: "Vítima" },
  { value: "OTHER", label: "Outro papel" },
  { value: "UNKNOWN", label: "Papel não identificado" },
];

export const PERSON_TYPE_OPTIONS: { value: PersonType; label: string }[] = [
  { value: "UNKNOWN", label: "Não informado" },
  { value: "NATURAL_PERSON", label: "Pessoa física" },
  { value: "LEGAL_ENTITY", label: "Pessoa jurídica" },
  { value: "PUBLIC_ENTITY", label: "Ente público" },
  { value: "AUTHORITY", label: "Autoridade" },
];

export function roleLabel(participant: Pick<Participant, "origin" | "procedural_role" | "source_role_label">) {
  if (participant.origin !== "SOURCE") return participant.source_role_label;
  return ROLE_OPTIONS.find((item) => item.value === participant.procedural_role && item.value !== "UNKNOWN" && item.value !== "OTHER")?.label
    ?? participant.source_role_label.toLowerCase();
}

const base = (workspace: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspace)}/process-participants`;

async function read(response: Response): Promise<ParticipantsView> {
  if (response.status === 409) throw new ParticipantsApiError("conflict");
  if (response.status === 400 || response.status === 422) throw new ParticipantsApiError("invalid");
  if (!response.ok) throw new ParticipantsApiError("unavailable");
  const value = await response.json();
  if (
    !value
    || !Array.isArray(value.participants)
    || !Array.isArray(value.proposals)
    || !Array.isArray(value.pending_documents)
    || !Array.isArray(value.interrupted_pages)
    || !Array.isArray(value.stale_participant_ids)
    || typeof value.legacy_projection !== "boolean"
    || (value.revision !== null && (!Number.isInteger(value.revision) || value.revision < 1))
  ) {
    throw new ParticipantsApiError("unavailable");
  }
  return value as ParticipantsView;
}

export async function getParticipants(workspace: string, signal?: AbortSignal) {
  return read(await fetch(base(workspace), { credentials: "same-origin", cache: "no-store", signal }));
}

export async function decideParticipants(workspace: string, revision: number | null, decision: ParticipantAction, signal?: AbortSignal) {
  return read(await fetch(`${base(workspace)}/decisions`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: decision.action, expected_revision: revision, payload: decision.payload }),
    signal,
  }));
}
