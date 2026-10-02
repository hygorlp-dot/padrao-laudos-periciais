// Configurações da instalação (#270): padrões fora de qualquer perícia. Uma
// perícia nova copia os padrões vigentes; mudar um padrão nunca altera perícias
// existentes. Todas as chamadas passam pela ponte local, sem rede externa.

import type { EditorialProfile } from "./reportSnapshot";

export type SettingKind =
  | "EXPERT_PROFILE_DEFAULT_V1"
  | "EDITORIAL_PROFILE_DEFAULT_V1"
  | "BRANDING_PROFILE_V1"
  | "DOCUMENT_PRESENTATION_PROFILE_V1"
  | "LEGAL_EDITORIAL_PROFILE_V1"
  | "DEFAULT_TEMPLATE_SELECTION_V1";

export type AssetRole =
  | "PRIMARY_LOGO"
  | "SYMBOL"
  | "WATERMARK"
  | "SIGNATURE_IMAGE"
  | "PROFESSIONAL_SEAL"
  | "BACKGROUND"
  | "DEFAULT_WORD_TEMPLATE";

export type CourtRegistration = { court: string; registration: string; label: string; active: boolean; legacy: boolean };
export type ProfessionalContact = { email: string | null; phone: string | null; office_name: string | null; city: string | null; state: string | null };
export type ProfilePresentation = {
  show_registration_cover: boolean;
  show_registration_signature: boolean;
  show_registration_header: boolean;
  show_court_registration_header: boolean;
  show_phone_header: boolean;
  show_email_header: boolean;
  show_email_footer: boolean;
};
export type ExpertProfileDefault = {
  profile_id: string;
  revision: 1;
  full_name: string;
  professional_title: string;
  registration: string;
  court_registration: string;
  contact_line: string;
  signature_name?: string;
  professional_council?: string;
  council_state?: string;
  national_registration?: string;
  court_registrations?: CourtRegistration[];
  contact?: ProfessionalContact;
  presentation?: ProfilePresentation;
};

export type Branding = { primary_color: string; secondary_color: string; rule_color: string; heading_color: string };
export type Alignment = "LEFT" | "CENTER" | "RIGHT";
export type DocumentPresentation = {
  cover: { enabled: boolean; show_logo: boolean; title: string; subtitle: string | null; show_expert: boolean; show_city_year: boolean; city: string | null };
  header: { enabled: boolean; show_logo: boolean; show_name: boolean; show_title: boolean; logo_width_cm: number; alignment: Alignment; separator_enabled: boolean; separator_thickness_pt: number };
  footer: { page_numbering: "PAGE_X_OF_Y" | "PAGE_X"; institutional_text: string | null };
  watermark: { enabled: boolean; kind: "IMAGE" | "SYMBOL" | "TEXT"; text: string | null; opacity: number; scale: number; rotation_degrees: number; apply_cover: boolean; apply_body: boolean; apply_attachments: boolean };
  background: { kind: "WHITE" | "SOLID" | "IMAGE"; color: string | null; apply_cover: boolean; apply_body: boolean };
};
export type LegalEditorial = {
  profile_id: string;
  check_acronyms: boolean;
  check_latinisms: boolean;
  check_foreign_terms: boolean;
  check_jargon: boolean;
  check_long_sentences: boolean;
  check_long_paragraphs: boolean;
  long_sentence_words: number;
  long_paragraph_words: number;
};
export type TemplateSelection = { mode: "PRODUCT_DEFAULT" | "CUSTOM"; template_sha256: string | null };

export type SettingPayloads = {
  EXPERT_PROFILE_DEFAULT_V1: ExpertProfileDefault | null;
  EDITORIAL_PROFILE_DEFAULT_V1: EditorialProfile;
  BRANDING_PROFILE_V1: Branding;
  DOCUMENT_PRESENTATION_PROFILE_V1: DocumentPresentation;
  LEGAL_EDITORIAL_PROFILE_V1: LegalEditorial;
  DEFAULT_TEMPLATE_SELECTION_V1: TemplateSelection;
};

export type SettingState<K extends SettingKind> = {
  configured: boolean;
  revision: number | null;
  created_at: string | null;
  payload: SettingPayloads[K];
  // Valor que "restaurar o padrão do produto" grava.
  product_default?: SettingPayloads[K] | null;
};

export type InstallationAsset = {
  asset_id: string;
  role: AssetRole;
  filename: string;
  media_type: string;
  byte_size: number;
  sha256: string;
  width: number | null;
  height: number | null;
};

export type Readiness = {
  expert_profile: "CONFIGURED" | "MISSING";
  branding: "CONFIGURED" | "PRODUCT_DEFAULT";
  document: "CONFIGURED" | "PRODUCT_DEFAULT";
  editorial: "CUSTOM" | "PRESET";
  legal_editorial: string;
  template: "PRODUCT_DEFAULT" | "CUSTOM";
};

export type InstallationOverview = {
  settings: { [K in SettingKind]: SettingState<K> };
  assets: Record<AssetRole, { revision: number | null; asset: InstallationAsset | null }>;
  readiness: Readiness;
};

export type SettingRevision = { revision: number; revision_id: string; created_at: string; checksum_sha256: string; payload: unknown };

export class SettingsApiError extends Error {
  constructor(readonly kind: "conflict" | "invalid" | "rejected" | "unavailable", readonly code = "") {
    super(kind);
    this.name = "SettingsApiError";
  }
}

const BASE = "/app-api/v1/installation";

async function code(response: Response) {
  try {
    const value = await response.json();
    return typeof value?.error?.code === "string" ? value.error.code : "";
  } catch {
    return "";
  }
}

async function failed(response: Response): Promise<never> {
  if (response.status === 409) throw new SettingsApiError("conflict", await code(response));
  if (response.status === 422) throw new SettingsApiError("rejected", await code(response));
  if (response.status === 400) throw new SettingsApiError("invalid", await code(response));
  throw new SettingsApiError("unavailable");
}

async function overview(response: Response): Promise<InstallationOverview> {
  if (!response.ok) return failed(response);
  const value = await response.json();
  if (!value || typeof value.settings !== "object" || typeof value.assets !== "object" || typeof value.readiness !== "object") {
    throw new SettingsApiError("unavailable");
  }
  return value as InstallationOverview;
}

function json(method: string, body: unknown): RequestInit {
  return { method, credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export async function getInstallationSettings(signal?: AbortSignal) {
  return overview(await fetch(`${BASE}/settings`, { credentials: "same-origin", cache: "no-store", signal }));
}

export async function saveSetting<K extends SettingKind>(kind: K, expectedRevision: number | null, payload: SettingPayloads[K]) {
  return overview(await fetch(`${BASE}/settings/${kind}`, json("PUT", { expected_revision: expectedRevision, payload })));
}

export async function getSettingHistory(kind: SettingKind, signal?: AbortSignal): Promise<SettingRevision[]> {
  const response = await fetch(`${BASE}/settings/${kind}/history`, { credentials: "same-origin", cache: "no-store", signal });
  if (!response.ok) return failed(response);
  const value = await response.json();
  if (!Array.isArray(value?.items)) throw new SettingsApiError("unavailable");
  return value.items as SettingRevision[];
}

export async function restoreSetting(kind: SettingKind, revision: number, expectedRevision: number) {
  return overview(await fetch(`${BASE}/settings/${kind}/restore`, json("POST", { revision, expected_revision: expectedRevision })));
}

export async function uploadAsset(role: AssetRole, file: File, expectedRevision: number | null) {
  return overview(await fetch(`${BASE}/assets/${role}`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": file.type || "application/octet-stream", "X-Document-Filename": file.name, "X-Expected-Revision": expectedRevision === null ? "none" : String(expectedRevision) },
    body: file,
  }));
}

export async function removeAsset(role: AssetRole, expectedRevision: number) {
  return overview(await fetch(`${BASE}/assets/${role}/removal`, json("POST", { expected_revision: expectedRevision })));
}

// O servidor responde com no-store; a tela troca a imagem pelo hash (key) do ativo.
export function assetContentUrl(role: AssetRole) {
  return `${BASE}/assets/${role}/content`;
}

const DOCM = "application/vnd.ms-word.document.macroenabled.12";

// O formato segue o modelo em uso: um modelo DOCM gera documento DOCM.
export async function downloadTestDocument(): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${BASE}/test-document`, { credentials: "same-origin", cache: "no-store" });
  if (!response.ok) return failed(response);
  const macro = (response.headers.get("Content-Type") ?? "").split(";", 1)[0].trim().toLowerCase() === DOCM;
  return { blob: await response.blob(), filename: macro ? "documento-de-teste.docm" : "documento-de-teste.docx" };
}

// --- Configurações capturadas por uma perícia ------------------------------

export type WorkspaceSettingsDifferences = {
  snapshot_revision: number | null;
  profile_revision: number | null;
  settings_changes: string[];
  profile_changes: string[];
};

export type WorkspaceSettingsView = {
  revision: number | null;
  updated_at: string | null;
  snapshot: { reason: string; assets: Array<{ role: AssetRole; filename: string }> } | null;
  // null: as Configurações da instalação estão indisponíveis; o snapshot da perícia continua válido.
  differences: WorkspaceSettingsDifferences | null;
};

const workspaceBase = (workspaceId: string) => `/app-api/v1/workspaces/${encodeURIComponent(workspaceId)}/settings-snapshot`;

async function workspaceView(response: Response): Promise<WorkspaceSettingsView> {
  if (!response.ok) return failed(response);
  const value = await response.json();
  if (!value || typeof value.differences !== "object" || (value.differences !== null && !Array.isArray(value.differences.settings_changes))) throw new SettingsApiError("unavailable");
  return value as WorkspaceSettingsView;
}

export async function getWorkspaceSettings(workspaceId: string, signal?: AbortSignal) {
  return workspaceView(await fetch(workspaceBase(workspaceId), { credentials: "same-origin", cache: "no-store", signal }));
}

export async function refreshWorkspaceSettings(workspaceId: string, value: { include_profile: boolean; expected_snapshot_revision: number | null; expected_profile_revision: number | null }) {
  return workspaceView(await fetch(`${workspaceBase(workspaceId)}/refresh`, json("POST", value)));
}
