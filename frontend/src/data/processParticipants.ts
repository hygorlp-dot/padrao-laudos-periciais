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
  // Papel como o laudo o escreve, com acentuação.
  role_text?: string;
};

export type ParticipantsView = {
  revision: number | null;
  updated_at: string | null;
  legacy_projection: boolean;
  participants: Participant[];
  proposals: Participant[];
  pending_documents: string[];
  interrupted_pages: { filename: string; page: number }[];
  unread_pages: { filename: string; page: number }[];
  stale_participant_ids: string[];
  legacy_blocked_poles: ParticipantPole[];
  duplicates: { proposal_id: string; matches_id: string; matches_name: string }[];
  proposals_unavailable: boolean;
  process_record_saved: boolean;
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
  constructor(readonly kind: "conflict" | "process_required" | "invalid" | "unavailable") {
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

export function roleLabel(participant: Pick<Participant, "origin" | "procedural_role" | "source_role_label" | "role_text">) {
  if (participant.origin !== "SOURCE") return participant.source_role_label;
  if (participant.role_text) return participant.role_text;
  return ROLE_OPTIONS.find((item) => item.value === participant.procedural_role && item.value !== "UNKNOWN" && item.value !== "OTHER")?.label
    ?? participant.source_role_label.toLowerCase();
}

const base = (workspace: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspace)}/process-participants`;

async function errorCode(response: Response) {
  try {
    const value = await response.json();
    return typeof value?.error?.code === "string" ? value.error.code : "";
  } catch {
    return "";
  }
}

async function read(response: Response): Promise<ParticipantsView> {
  if (response.status === 409) {
    throw new ParticipantsApiError((await errorCode(response)) === "PROCESS_RECORD_REQUIRED" ? "process_required" : "conflict");
  }
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
  return {
    ...value,
    legacy_blocked_poles: Array.isArray(value.legacy_blocked_poles) ? value.legacy_blocked_poles : [],
    duplicates: Array.isArray(value.duplicates) ? value.duplicates : [],
    unread_pages: Array.isArray(value.unread_pages) ? value.unread_pages : [],
    proposals_unavailable: value.proposals_unavailable === true,
    process_record_saved: value.process_record_saved !== false,
  } as ParticipantsView;
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
