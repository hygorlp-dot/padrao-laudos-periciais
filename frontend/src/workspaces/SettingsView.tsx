import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  assetContentUrl,
  downloadTestDocument,
  getInstallationSettings,
  getSettingHistory,
  removeAsset,
  restoreSetting,
  saveSetting,
  SettingsApiError,
  uploadAsset,
  type AssetRole,
  type Branding,
  type CourtRegistration,
  type DocumentPresentation,
  type ExpertProfileDefault,
  type InstallationOverview,
  type LegalEditorial,
  type ProfilePresentation,
  type SettingKind,
  type SettingPayloads,
  type SettingRevision,
  type TemplateSelection,
} from "../data/installationSettings";
import type { EditorialProfile } from "../data/reportSnapshot";
import { EditorialPanel } from "../ui/EditorialPanel";
import { EDITORIAL_PRESET, editorialSummary } from "../ui/editorialProfile";

// Central de Configurações (#270): fora de qualquer perícia. O que se salva aqui
// vale para perícias criadas depois; cada perícia guarda a sua cópia.

type Save = <K extends SettingKind>(kind: K, payload: SettingPayloads[K], done: string) => Promise<boolean>;

const DATE = new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" });
const SECTIONS = [
  ["perfil", "Perfil profissional"],
  ["identidade", "Identidade visual"],
  ["documento", "Documento Word"],
  ["editorial", "Perfil editorial"],
  ["juridico", "Linguagem jurídica"],
  ["teste", "Documento de teste"],
] as const;

const ASSET_LABELS: Record<Exclude<AssetRole, "DEFAULT_WORD_TEMPLATE">, { label: string; hint: string }> = {
  PRIMARY_LOGO: { label: "Logotipo", hint: "Usado no cabeçalho e na capa." },
  SYMBOL: { label: "Símbolo", hint: "Versão compacta da marca; pode servir de marca d'água." },
  WATERMARK: { label: "Imagem da marca d'água", hint: "Aplicada com transparência leve atrás do texto." },
  SIGNATURE_IMAGE: { label: "Imagem da assinatura", hint: "Aparece acima do nome no fechamento do laudo." },
  PROFESSIONAL_SEAL: { label: "Selo profissional", hint: "Aparece abaixo da identificação no fechamento." },
  BACKGROUND: { label: "Imagem de fundo", hint: "Uso avançado; o produto clareia a imagem para manter a leitura." },
};

const REJECTIONS: Record<string, string> = {
  ASSET_FORMAT_NOT_SUPPORTED: "Use uma imagem PNG ou JPEG.",
  ASSET_FORMAT_MISMATCH: "O conteúdo do arquivo não corresponde à extensão. Exporte a imagem novamente em PNG ou JPEG.",
  ASSET_FILE_TOO_LARGE: "O arquivo é grande demais. Imagens até 5 MB; modelos Word até 20 MB.",
  ASSET_EMPTY_FILE: "O arquivo está vazio.",
  ASSET_IMAGE_UNREADABLE: "Não foi possível ler esta imagem. Exporte-a novamente em PNG ou JPEG.",
  ASSET_DIMENSIONS_OUT_OF_RANGE: "A imagem é pequena demais (mínimo 16 px) ou grande demais (até 25 megapixels).",
  ASSET_ANIMATED_IMAGE: "Imagens animadas não são aceitas.",
  ASSET_COLOR_MODE_NOT_SUPPORTED: "O modo de cor desta imagem não é aceito. Salve em RGB.",
  ASSET_TEMPLATE_INVALID: "Este arquivo não é um modelo Word válido (DOCX ou DOCM).",
};

const SETTING_LABELS: Record<SettingKind, string> = {
  EXPERT_PROFILE_DEFAULT_V1: "perfil profissional",
  EDITORIAL_PROFILE_DEFAULT_V1: "perfil editorial",
  BRANDING_PROFILE_V1: "cores da identidade",
  DOCUMENT_PRESENTATION_PROFILE_V1: "apresentação do documento",
  LEGAL_EDITORIAL_PROFILE_V1: "linguagem jurídica",
  DEFAULT_TEMPLATE_SELECTION_V1: "modelo Word",
};

function failure(error: unknown) {
  if (error instanceof SettingsApiError) {
    if (error.kind === "conflict") return "Esta configuração mudou em outra janela. Os dados foram recarregados; confira e salve de novo.";
    if (error.kind === "rejected") return REJECTIONS[error.code] ?? "O arquivo foi recusado.";
    if (error.kind === "invalid") return "Confira os campos destacados: algum valor está fora do aceito.";
  }
  return "Não foi possível concluir. Nada foi confirmado; tente novamente.";
}

function status(configured: boolean, revision: number | null, createdAt: string | null) {
  if (!configured || revision === null) return "Padrão do produto";
  return `Configurado · revisão ${revision}${createdAt ? ` · ${DATE.format(new Date(createdAt))}` : ""}`;
}

function SettingSection({ id, title, description, state, children, history }: { id: string; title: string; description: ReactNode; state: string; children: ReactNode; history?: ReactNode }) {
  return (
    <section className="settings-section" id={id} aria-labelledby={`${id}-title`}>
      <header className="settings-section__header">
        <h2 id={`${id}-title`} tabIndex={-1}>{title}</h2>
        <p className="settings-section__state">{state}</p>
      </header>
      <div className="settings-section__description">{description}</div>
      {children}
      {history}
    </section>
  );
}

function History({ kind, revision, onRestore, busy }: { kind: SettingKind; revision: number | null; onRestore: (revision: number) => void; busy: boolean }) {
  const [items, setItems] = useState<SettingRevision[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    getSettingHistory(kind, controller.signal).then(
      (value) => { if (!controller.signal.aborted) { setItems(value); setFailed(false); } },
      () => { if (!controller.signal.aborted) setFailed(true); },
    );
    return () => controller.abort();
  }, [kind, open, revision]);
  if (revision === null) return null;
  return (
    <details className="settings-history" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Histórico de {SETTING_LABELS[kind]}</summary>
      {failed ? <p role="alert">Não foi possível carregar o histórico.</p> : null}
      {open && !items && !failed ? <p role="status">Carregando histórico…</p> : null}
      {items ? (
        <ol className="settings-history__list">
          {[...items].reverse().map((item) => (
            <li key={item.revision_id}>
              <span>Revisão {item.revision} · {DATE.format(new Date(item.created_at))}</span>
              {item.revision === revision ? <span className="field-hint">Em uso</span> : (
                <button type="button" className="text-action" disabled={busy} onClick={() => onRestore(item.revision)}>
                  Voltar a esta versão
                </button>
              )}
            </li>
          ))}
        </ol>
      ) : null}
      <p className="field-hint">Voltar a uma versão grava uma nova revisão com o mesmo conteúdo; nada do histórico é apagado.</p>
    </details>
  );
}

// --- Perfil profissional ----------------------------------------------------

const EMPTY_PRESENTATION: ProfilePresentation = { show_registration_cover: true, show_registration_signature: true, show_registration_header: true, show_court_registration_header: false, show_phone_header: false, show_email_header: false, show_email_footer: false };
const EMPTY_PROFILE: ExpertProfileDefault = {
  profile_id: "EXPERT-PROFILE-001", revision: 1, full_name: "", professional_title: "", registration: "", court_registration: "", contact_line: "",
  court_registrations: [], contact: { email: null, phone: null, office_name: null, city: null, state: null }, presentation: EMPTY_PRESENTATION,
};
const UF = /^[A-Z]{2}$/;

function text(value: string | null | undefined) {
  return value ?? "";
}

function optional(value: string) {
  return value.trim() ? value.trim() : null;
}

function ProfileSection({ overview, busy, save }: { overview: InstallationOverview; busy: boolean; save: Save }) {
  const state = overview.settings.EXPERT_PROFILE_DEFAULT_V1;
  const initial = { ...EMPTY_PROFILE, ...(state.payload ?? {}) };
  const [draft, setDraft] = useState<ExpertProfileDefault>({
    ...initial,
    court_registrations: initial.court_registrations ?? [],
    contact: initial.contact ?? EMPTY_PROFILE.contact,
    presentation: initial.presentation ?? EMPTY_PRESENTATION,
  });
  const [error, setError] = useState("");
  const contact = draft.contact ?? EMPTY_PROFILE.contact!;
  const presentation = draft.presentation ?? EMPTY_PRESENTATION;
  const registrations = draft.court_registrations ?? [];
  const setContact = (key: keyof typeof contact, value: string) => setDraft({ ...draft, contact: { ...contact, [key]: value } });
  const setRegistration = (index: number, change: Partial<CourtRegistration>) =>
    setDraft({ ...draft, court_registrations: registrations.map((item, position) => (position === index ? { ...item, ...change } : item)) });
  const flag = (key: keyof ProfilePresentation, label: string) => (
    <label className="checkbox-label"><input type="checkbox" checked={presentation[key]} disabled={busy} onChange={(event) => setDraft({ ...draft, presentation: { ...presentation, [key]: event.target.checked } })} /> {label}</label>
  );

  function submit() {
    if (!draft.full_name.trim() || !draft.professional_title.trim() || !draft.registration.trim()) {
      setError("Informe nome, título profissional e registro no conselho.");
      return;
    }
    if (registrations.some((item) => !item.registration.trim() || (!item.legacy && !item.court.trim()))) {
      setError("Complete o tribunal e o número de cada cadastro, ou remova o cadastro vazio.");
      return;
    }
    const state = text(contact.state).trim().toUpperCase();
    if (state && !UF.test(state)) {
      setError("UF do endereço profissional: use a sigla com duas letras, como PE.");
      return;
    }
    const councilState = text(draft.council_state).trim().toUpperCase();
    if (councilState && !UF.test(councilState)) {
      setError("UF do conselho: use a sigla com duas letras, como PE.");
      return;
    }
    setError("");
    const cleaned = registrations.map((item) => ({ ...item, court: item.legacy ? "" : item.court.trim(), registration: item.registration.trim(), label: item.label.trim() || "Cadastro de perito" }));
    const active = cleaned.filter((item) => item.active);
    const email = optional(text(contact.email));
    const phone = optional(text(contact.phone));
    const payload: ExpertProfileDefault = {
      profile_id: draft.profile_id || "EXPERT-PROFILE-001", revision: 1,
      full_name: draft.full_name.trim(), professional_title: draft.professional_title.trim(), registration: draft.registration.trim(),
      // Campos antigos derivados da coleção e do contato: uma só fonte de verdade.
      court_registration: (active.length ? active : cleaned).map((item) => (item.legacy ? item.registration : `${item.court} — ${item.registration}`)).join("; ") || "Não informado",
      contact_line: [email, phone].filter(Boolean).join(" · ") || "Não informado",
      presentation,
      contact: { email, phone, office_name: optional(text(contact.office_name)), city: optional(text(contact.city)), state: state || null },
    };
    if (cleaned.length) payload.court_registrations = cleaned;
    if (optional(text(draft.signature_name))) payload.signature_name = text(draft.signature_name).trim();
    if (optional(text(draft.professional_council))) payload.professional_council = text(draft.professional_council).trim();
    if (councilState) payload.council_state = councilState;
    if (optional(text(draft.national_registration))) payload.national_registration = text(draft.national_registration).trim();
    void save("EXPERT_PROFILE_DEFAULT_V1", payload, "Perfil profissional salvo. Vale para as próximas perícias.");
  }

  return (
    <div className="settings-form">
      <fieldset disabled={busy}>
        <legend>Identificação</legend>
        <label>Nome completo<input value={draft.full_name} onChange={(event) => setDraft({ ...draft, full_name: event.target.value })} /></label>
        <label>Nome na assinatura (opcional)<input value={text(draft.signature_name)} onChange={(event) => setDraft({ ...draft, signature_name: event.target.value })} /></label>
        <label>Título profissional<input value={draft.professional_title} placeholder="Ex.: Engenheira civil" onChange={(event) => setDraft({ ...draft, professional_title: event.target.value })} /></label>
        <label>Conselho (opcional)<input value={text(draft.professional_council)} placeholder="Ex.: CREA" onChange={(event) => setDraft({ ...draft, professional_council: event.target.value })} /></label>
        <label>UF do conselho (opcional)<input value={text(draft.council_state)} maxLength={2} onChange={(event) => setDraft({ ...draft, council_state: event.target.value })} /></label>
        <label>Registro no conselho<input value={draft.registration} placeholder="Ex.: CREA-PE 000000" onChange={(event) => setDraft({ ...draft, registration: event.target.value })} /></label>
        <label>Registro nacional (opcional)<input value={text(draft.national_registration)} onChange={(event) => setDraft({ ...draft, national_registration: event.target.value })} /></label>
      </fieldset>
      <fieldset disabled={busy} className="settings-form__collection">
        <legend>Cadastros em tribunais</legend>
        {registrations.length === 0 ? <p className="field-hint">Nenhum cadastro. Adicione um por tribunal em que você atua.</p> : null}
        {registrations.map((item, index) => (
          <div className="settings-form__row" key={index}>
            {item.legacy ? (
              <p className="field-hint">Cadastro informado antes, mantido como foi escrito.</p>
            ) : (
              <label>Tribunal<input value={item.court} placeholder="Ex.: TRF5" onChange={(event) => setRegistration(index, { court: event.target.value })} /></label>
            )}
            <label>Número do cadastro<input value={item.registration} onChange={(event) => setRegistration(index, { registration: event.target.value })} /></label>
            <label>Descrição (opcional)<input value={item.label} placeholder="Ex.: Perita do juízo" onChange={(event) => setRegistration(index, { label: event.target.value })} /></label>
            <label className="checkbox-label"><input type="checkbox" checked={item.active} onChange={(event) => setRegistration(index, { active: event.target.checked })} /> Ativo</label>
            <button type="button" className="text-action" onClick={() => setDraft({ ...draft, court_registrations: registrations.filter((_, position) => position !== index) })}>
              Remover cadastro {index + 1}
            </button>
          </div>
        ))}
        <button type="button" className="text-action" onClick={() => setDraft({ ...draft, court_registrations: [...registrations, { court: "", registration: "", label: "", active: true, legacy: false }] })}>
          Adicionar cadastro
        </button>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>Contato profissional</legend>
        <label>E-mail<input type="email" value={text(contact.email)} onChange={(event) => setContact("email", event.target.value)} /></label>
        <label>Telefone<input value={text(contact.phone)} onChange={(event) => setContact("phone", event.target.value)} /></label>
        <label>Escritório (opcional)<input value={text(contact.office_name)} onChange={(event) => setContact("office_name", event.target.value)} /></label>
        <label>Cidade<input value={text(contact.city)} onChange={(event) => setContact("city", event.target.value)} /></label>
        <label>UF<input value={text(contact.state)} maxLength={2} onChange={(event) => setContact("state", event.target.value)} /></label>
        <p className="field-hint settings-form__wide">Não informe CPF, RG nem endereço residencial: o laudo não precisa deles.</p>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>O que o documento mostra</legend>
        <div className="settings-form__toggles">
          {flag("show_registration_header", "Registro no conselho no cabeçalho")}
          {flag("show_court_registration_header", "Cadastros em tribunais no cabeçalho")}
          {flag("show_phone_header", "Telefone no cabeçalho")}
          {flag("show_email_header", "E-mail no cabeçalho")}
          {flag("show_email_footer", "E-mail no rodapé")}
        </div>
      </fieldset>
      {error ? <p className="field-error" role="alert">{error}</p> : null}
      <div className="action-row">
        <button type="button" className="primary-action" disabled={busy} onClick={submit}>Salvar perfil profissional</button>
      </div>
    </div>
  );
}

// --- Identidade visual ------------------------------------------------------

function contrastRatio(hex: string) {
  const channel = (value: number) => {
    const scaled = value / 255;
    return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = [1, 3, 5].map((index) => channel(parseInt(hex.slice(index, index + 2), 16)));
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return 1.05 / (luminance + 0.05);
}

function AssetRow({ role, overview, busy, run }: { role: Exclude<AssetRole, "DEFAULT_WORD_TEMPLATE">; overview: InstallationOverview; busy: boolean; run: (task: () => Promise<InstallationOverview>, done: string) => Promise<boolean> }) {
  const current = overview.assets[role];
  const input = useRef<HTMLInputElement>(null);
  const { label, hint } = ASSET_LABELS[role];
  return (
    <li className="settings-asset">
      <div className="settings-asset__preview" aria-hidden={current.asset ? undefined : true}>
        {current.asset ? <img key={current.asset.sha256} src={assetContentUrl(role)} alt={`${label} atual`} /> : <span className="settings-asset__empty" />}
      </div>
      <div className="settings-asset__body">
        <strong>{label}</strong>
        <span className="field-hint">{current.asset ? `${current.asset.filename} · ${current.asset.width} × ${current.asset.height} px` : "Nenhuma imagem"}</span>
        <span className="field-hint">{hint}</span>
      </div>
      <div className="settings-asset__actions">
        <input
          ref={input}
          className="visually-hidden"
          type="file"
          accept="image/png,image/jpeg"
          aria-label={`Arquivo para ${label.toLowerCase()}`}
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void run(() => uploadAsset(role, file, current.revision), `${label} atualizado.`);
          }}
        />
        <button type="button" className="text-action" disabled={busy} onClick={() => input.current?.click()}>
          {current.asset ? `Trocar ${label.toLowerCase()}` : `Enviar ${label.toLowerCase()}`}
        </button>
        {current.asset && current.revision !== null ? (
          <button type="button" className="text-action" disabled={busy} onClick={() => void run(() => removeAsset(role, current.revision!), `${label} removido.`)}>
            Remover {label.toLowerCase()}
          </button>
        ) : null}
      </div>
    </li>
  );
}

function IdentitySection({ overview, busy, save, run }: { overview: InstallationOverview; busy: boolean; save: Save; run: (task: () => Promise<InstallationOverview>, done: string) => Promise<boolean> }) {
  const [colors, setColors] = useState<Branding>(overview.settings.BRANDING_PROFILE_V1.payload);
  const legible = contrastRatio(colors.heading_color) >= 4.5;
  const color = (key: keyof Branding, label: string) => (
    <label>{label}<input type="color" value={colors[key].toLowerCase()} disabled={busy} onChange={(event) => setColors({ ...colors, [key]: event.target.value.toUpperCase() })} /></label>
  );
  return (
    <>
      <div className="settings-form">
        <fieldset disabled={busy}>
          <legend>Cores</legend>
          {color("heading_color", "Títulos")}
          {color("primary_color", "Cor principal")}
          {color("secondary_color", "Cor secundária")}
          {color("rule_color", "Linha separadora")}
          {!legible ? <p className="field-error settings-form__wide" role="alert">A cor dos títulos não tem contraste suficiente sobre o papel branco. Escolha um tom mais escuro.</p> : null}
        </fieldset>
        <div className="action-row">
          <button type="button" className="primary-action" disabled={busy || !legible} onClick={() => void save("BRANDING_PROFILE_V1", colors, "Cores salvas.")}>Salvar cores</button>
        </div>
      </div>
      <h3 className="settings-subtitle">Imagens</h3>
      <p className="field-hint">PNG ou JPEG, até 5 MB. As imagens ficam neste computador; cada perícia nova guarda a própria cópia.</p>
      <ul className="settings-assets">
        {(Object.keys(ASSET_LABELS) as Array<keyof typeof ASSET_LABELS>).map((role) => <AssetRow key={role} role={role} overview={overview} busy={busy} run={run} />)}
      </ul>
    </>
  );
}

// --- Documento Word ---------------------------------------------------------

function DocumentSection({ overview, busy, save, run }: { overview: InstallationOverview; busy: boolean; save: Save; run: (task: () => Promise<InstallationOverview>, done: string) => Promise<boolean> }) {
  const [draft, setDraft] = useState<DocumentPresentation>(overview.settings.DOCUMENT_PRESENTATION_PROFILE_V1.payload);
  const selection = overview.settings.DEFAULT_TEMPLATE_SELECTION_V1;
  const template = overview.assets.DEFAULT_WORD_TEMPLATE;
  const templateInput = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const set = <S extends keyof DocumentPresentation>(section: S, change: Partial<DocumentPresentation[S]>) => setDraft({ ...draft, [section]: { ...draft[section], ...change } });
  const check = <S extends keyof DocumentPresentation>(section: S, key: keyof DocumentPresentation[S] & string, label: string) => (
    <label className="checkbox-label"><input type="checkbox" checked={Boolean(draft[section][key])} onChange={(event) => set(section, { [key]: event.target.checked } as Partial<DocumentPresentation[S]>)} /> {label}</label>
  );
  const opacityPercent = Math.round(draft.watermark.opacity * 100);
  const custom = selection.payload.mode === "CUSTOM";

  function submit() {
    if (!draft.cover.title.trim()) { setError("Informe o título da capa."); return; }
    if (draft.watermark.enabled && draft.watermark.kind === "TEXT" && !text(draft.watermark.text).trim()) { setError("Informe o texto da marca d'água."); return; }
    if (draft.background.kind === "SOLID" && !draft.background.color) { setError("Escolha a cor do fundo."); return; }
    setError("");
    void save("DOCUMENT_PRESENTATION_PROFILE_V1", {
      ...draft,
      cover: { ...draft.cover, title: draft.cover.title.trim(), subtitle: optional(text(draft.cover.subtitle)), city: optional(text(draft.cover.city)) },
      footer: { ...draft.footer, institutional_text: optional(text(draft.footer.institutional_text)) },
      watermark: { ...draft.watermark, text: draft.watermark.kind === "TEXT" ? optional(text(draft.watermark.text)) : null },
      background: { ...draft.background, color: draft.background.kind === "SOLID" ? draft.background.color : null },
    }, "Apresentação do documento salva.");
  }

  function chooseTemplate(next: TemplateSelection) {
    void save("DEFAULT_TEMPLATE_SELECTION_V1", next, next.mode === "CUSTOM" ? "Modelo Word personalizado em uso para as próximas perícias." : "Modelo padrão do produto em uso para as próximas perícias.");
  }

  return (
    <>
      <div className="settings-form">
        <fieldset disabled={busy || custom}>
          <legend>Capa</legend>
          <div className="settings-form__toggles">
            {check("cover", "enabled", "Usar capa")}
            {check("cover", "show_logo", "Logotipo na capa")}
            {check("cover", "show_expert", "Nome do perito na capa")}
            {check("cover", "show_city_year", "Cidade e ano na capa")}
          </div>
          <label>Título<input value={draft.cover.title} onChange={(event) => set("cover", { title: event.target.value })} /></label>
          <label>Subtítulo (opcional)<input value={text(draft.cover.subtitle)} onChange={(event) => set("cover", { subtitle: event.target.value })} /></label>
          <label>Cidade (opcional)<input value={text(draft.cover.city)} placeholder="Usa a cidade do contato" onChange={(event) => set("cover", { city: event.target.value })} /></label>
          <p className="field-hint settings-form__wide">A capa sempre identifica o processo, o juízo e os polos. Com muitas partes, ela resume e remete à relação completa no item 1.</p>
        </fieldset>
        <fieldset disabled={busy || custom}>
          <legend>Cabeçalho</legend>
          <div className="settings-form__toggles">
            {check("header", "enabled", "Usar cabeçalho")}
            {check("header", "show_logo", "Logotipo")}
            {check("header", "show_name", "Nome do perito")}
            {check("header", "show_title", "Título profissional")}
            {check("header", "separator_enabled", "Linha separadora")}
          </div>
          <label>Largura do logotipo (cm)<input type="number" min={0.8} max={6} step={0.1} value={draft.header.logo_width_cm} onChange={(event) => set("header", { logo_width_cm: Number(event.target.value) })} /></label>
          <label>Alinhamento<select value={draft.header.alignment} onChange={(event) => set("header", { alignment: event.target.value as DocumentPresentation["header"]["alignment"] })}><option value="LEFT">À esquerda</option><option value="CENTER">Centralizado</option><option value="RIGHT">À direita</option></select></label>
          <label>Espessura da linha (pt)<input type="number" min={0.25} max={3} step={0.25} value={draft.header.separator_thickness_pt} onChange={(event) => set("header", { separator_thickness_pt: Number(event.target.value) })} /></label>
          <p className="field-hint settings-form__wide">Registro, cadastros, telefone e e-mail no cabeçalho seguem as escolhas do perfil profissional.</p>
        </fieldset>
        <fieldset disabled={busy || custom}>
          <legend>Rodapé</legend>
          <label>Numeração<select value={draft.footer.page_numbering} onChange={(event) => set("footer", { page_numbering: event.target.value as DocumentPresentation["footer"]["page_numbering"] })}><option value="PAGE_X_OF_Y">Página X de Y</option><option value="PAGE_X">Página X</option></select></label>
          <label>Texto institucional (opcional)<input value={text(draft.footer.institutional_text)} maxLength={160} onChange={(event) => set("footer", { institutional_text: event.target.value })} /></label>
        </fieldset>
        <fieldset disabled={busy || custom}>
          <legend>Marca d'água</legend>
          <div className="settings-form__toggles">
            {check("watermark", "enabled", "Usar marca d'água")}
            {check("watermark", "apply_cover", "Na capa")}
            {check("watermark", "apply_body", "No corpo do laudo")}
          </div>
          <label>Origem<select value={draft.watermark.kind} onChange={(event) => set("watermark", { kind: event.target.value as DocumentPresentation["watermark"]["kind"] })}><option value="SYMBOL">Símbolo</option><option value="IMAGE">Imagem da marca d'água</option><option value="TEXT">Texto</option></select></label>
          {draft.watermark.kind === "TEXT" ? <label>Texto<input value={text(draft.watermark.text)} maxLength={60} onChange={(event) => set("watermark", { text: event.target.value })} /></label> : null}
          <label>Intensidade: {opacityPercent}%<input type="range" min={2} max={30} step={1} value={opacityPercent} aria-valuetext={`${opacityPercent}%`} onChange={(event) => set("watermark", { opacity: Number(event.target.value) / 100 })} /></label>
          <label>Tamanho na página: {Math.round(draft.watermark.scale * 100)}%<input type="range" min={20} max={100} step={5} value={Math.round(draft.watermark.scale * 100)} onChange={(event) => set("watermark", { scale: Number(event.target.value) / 100 })} /></label>
          <label>Rotação (graus)<input type="number" min={-60} max={60} step={5} value={draft.watermark.rotation_degrees} onChange={(event) => set("watermark", { rotation_degrees: Math.round(Number(event.target.value)) })} /></label>
          {draft.watermark.enabled && opacityPercent > 15 ? <p className="field-warning settings-form__wide" role="status">Acima de 15% a marca d'água pode atrapalhar a leitura e a impressão. Confira no documento de teste.</p> : null}
        </fieldset>
        <fieldset disabled={busy || custom}>
          <legend>Fundo da página</legend>
          <label>Fundo<select value={draft.background.kind} onChange={(event) => set("background", { kind: event.target.value as DocumentPresentation["background"]["kind"], color: event.target.value === "SOLID" ? draft.background.color ?? "#F4F6F8" : null })}><option value="WHITE">Branco</option><option value="SOLID">Cor clara</option><option value="IMAGE">Imagem (avançado)</option></select></label>
          {draft.background.kind === "SOLID" ? <label>Cor<input type="color" value={(draft.background.color ?? "#F4F6F8").toLowerCase()} onChange={(event) => set("background", { color: event.target.value.toUpperCase() })} /></label> : null}
          <div className="settings-form__toggles">
            {check("background", "apply_cover", "Na capa")}
            {check("background", "apply_body", "No corpo do laudo")}
          </div>
          <p className="field-hint settings-form__wide">Só cores claras são aceitas, para o texto preto continuar legível e o laudo imprimir bem.</p>
        </fieldset>
        {error ? <p className="field-error" role="alert">{error}</p> : null}
        <div className="action-row">
          <button type="button" className="primary-action" disabled={busy || custom} onClick={submit}>Salvar apresentação do documento</button>
        </div>
      </div>

      <h3 className="settings-subtitle">Modelo Word</h3>
      <div className="settings-template" role="radiogroup" aria-label="Modelo Word das próximas perícias">
        <label className="settings-choice">
          <input type="radio" name="template-mode" checked={!custom} disabled={busy} onChange={() => chooseTemplate({ mode: "PRODUCT_DEFAULT", template_sha256: null })} />
          <span><strong>Modelo padrão do produto</strong><span className="field-hint">Usa a capa, o cabeçalho, o rodapé e as imagens configurados acima.</span></span>
        </label>
        <label className="settings-choice">
          <input type="radio" name="template-mode" checked={custom} disabled={busy || !template.asset} onChange={() => template.asset && chooseTemplate({ mode: "CUSTOM", template_sha256: template.asset.sha256 })} />
          <span><strong>Modelo Word personalizado</strong><span className="field-hint">Modelos Word personalizados preservam a identidade visual e a formatação existentes no arquivo.</span></span>
        </label>
      </div>
      <div className="action-row">
        <input
          ref={templateInput}
          className="visually-hidden"
          type="file"
          accept=".docx,.docm,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-word.document.macroEnabled.12"
          aria-label="Arquivo do modelo Word personalizado"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void run(() => uploadAsset("DEFAULT_WORD_TEMPLATE", file, template.revision), "Modelo Word enviado. Escolha-o acima para usar nas próximas perícias.");
          }}
        />
        <button type="button" className="text-action" disabled={busy} onClick={() => templateInput.current?.click()}>
          {template.asset ? `Trocar modelo Word (${template.asset.filename})` : "Enviar modelo Word"}
        </button>
      </div>
      {custom ? <p className="field-hint">Com o modelo personalizado, capa, cabeçalho, rodapé, marca d'água e fundo vêm do seu arquivo; os ajustes acima ficam guardados para quando voltar ao modelo do produto.</p> : null}
    </>
  );
}

// --- Linguagem jurídica -----------------------------------------------------

const SOURCES = [
  ["Recomendação CNJ nº 144/2023", "recomendatória"],
  ["Lei nº 15.263/2025, art. 5º", "obrigatória para a administração pública"],
  ["Manual Justiça Plural, capítulo 4", "institucional"],
  ["Orientações do TRF5 sobre linguagem simples", "institucional"],
] as const;

function LegalSection({ overview, busy, save }: { overview: InstallationOverview; busy: boolean; save: Save }) {
  const [draft, setDraft] = useState<LegalEditorial>(overview.settings.LEGAL_EDITORIAL_PROFILE_V1.payload);
  const check = (key: keyof LegalEditorial & `check_${string}`, label: string) => (
    <label className="checkbox-label"><input type="checkbox" checked={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: event.target.checked })} /> {label}</label>
  );
  return (
    <div className="settings-form">
      <fieldset disabled={busy}>
        <legend>Avisos da pré-verificação</legend>
        <div className="settings-form__toggles">
          {check("check_acronyms", "Sigla sem o nome por extenso na primeira vez")}
          {check("check_latinisms", "Expressões latinas")}
          {check("check_foreign_terms", "Termos estrangeiros")}
          {check("check_jargon", "Expressões rebuscadas")}
          {check("check_long_sentences", "Frases longas")}
          {check("check_long_paragraphs", "Parágrafos longos")}
        </div>
        <label>Frase longa a partir de (palavras)<input type="number" min={25} max={90} value={draft.long_sentence_words} onChange={(event) => setDraft({ ...draft, long_sentence_words: Math.round(Number(event.target.value)) })} /></label>
        <label>Parágrafo longo a partir de (palavras)<input type="number" min={80} max={400} value={draft.long_paragraph_words} onChange={(event) => setDraft({ ...draft, long_paragraph_words: Math.round(Number(event.target.value)) })} /></label>
        <p className="field-hint settings-form__wide">São avisos com sugestão; o texto nunca é reescrito sozinho. Pendências como [INFORMAÇÃO NECESSÁRIA] sempre impedem a emissão do Word final, com qualquer escolha aqui.</p>
      </fieldset>
      <div className="action-row">
        <button type="button" className="primary-action" disabled={busy} onClick={() => void save("LEGAL_EDITORIAL_PROFILE_V1", draft, "Linguagem jurídica salva.")}>Salvar linguagem jurídica</button>
      </div>
      <h3 className="settings-subtitle">Fontes do perfil de referência</h3>
      <dl className="settings-sources">
        {SOURCES.map(([name, nature]) => (
          <div key={name}><dt>{name}</dt><dd>Natureza: {nature}</dd></div>
        ))}
      </dl>
    </div>
  );
}

function identityState(overview: InstallationOverview) {
  const images = (Object.keys(ASSET_LABELS) as Array<keyof typeof ASSET_LABELS>).filter((role) => overview.assets[role].asset).length;
  const colors = overview.settings.BRANDING_PROFILE_V1.configured;
  if (!colors && images === 0) return "Padrão do produto";
  const parts = [colors ? "cores próprias" : "cores do produto", images ? `${images} ${images === 1 ? "imagem" : "imagens"}` : "sem imagens"];
  return `Configurada · ${parts.join(" · ")}`;
}

// --- Página -----------------------------------------------------------------

export function SettingsView() {
  const [overview, setOverview] = useState<InstallationOverview | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "status" | "alert"; text: string } | null>(null);
  const [generation, setGeneration] = useState(0);
  const [testState, setTestState] = useState<"idle" | "busy" | "failed" | "done">("idle");

  useEffect(() => {
    const controller = new AbortController();
    getInstallationSettings(controller.signal).then(
      (value) => { if (!controller.signal.aborted) { setOverview(value); setLoadError(false); } },
      () => { if (!controller.signal.aborted) setLoadError(true); },
    );
    return () => controller.abort();
  }, [version]);

  async function run(task: () => Promise<InstallationOverview>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      setOverview(await task());
      setMessage({ kind: "status", text: done });
      return true;
    } catch (error) {
      setMessage({ kind: "alert", text: failure(error) });
      if (error instanceof SettingsApiError && error.kind === "conflict") {
        setVersion((value) => value + 1);
        // Recarregado do servidor: os formulários recomeçam do valor gravado.
        setGeneration((value) => value + 1);
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  const save: Save = (kind, payload, done) => run(() => saveSetting(kind, overview?.settings[kind].revision ?? null, payload), done);

  async function testDocument() {
    setTestState("busy");
    try {
      const blob = await downloadTestDocument();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "documento-de-teste.docx";
      link.click();
      URL.revokeObjectURL(url);
      setTestState("done");
    } catch {
      setTestState("failed");
    }
  }

  if (loadError) {
    return (
      <section className="status-state status-state--error" role="alert">
        <span className="state-mark" aria-hidden="true">!</span>
        <div>
          <h2>Não foi possível abrir as configurações</h2>
          <p>As configurações salvas continuam guardadas neste computador.</p>
          <button className="text-action" type="button" onClick={() => setVersion((value) => value + 1)}>Tentar novamente</button>
        </div>
      </section>
    );
  }
  if (!overview) {
    return (
      <section className="status-state status-state--loading" role="status" aria-live="polite">
        <span className="state-rule" aria-hidden="true" />
        <div><h2>Carregando configurações</h2><p>Consultando as configurações deste computador.</p></div>
      </section>
    );
  }

  const readiness = overview.readiness;
  const settings = overview.settings;
  const restore = (kind: SettingKind) => (revision: number) => void run(() => restoreSetting(kind, revision, settings[kind].revision ?? 0), "Versão anterior restaurada como nova revisão.").then((ok) => { if (ok) setGeneration((value) => value + 1); });
  const editorialPreset = (settings.EDITORIAL_PROFILE_DEFAULT_V1.product_default as EditorialProfile | null | undefined) ?? EDITORIAL_PRESET;
  const legacyGeometry = (settings.EDITORIAL_PROFILE_DEFAULT_V1 as { legacy_geometry?: EditorialProfile }).legacy_geometry;

  return (
    <div className="settings-view" key={generation}>
      <p className="settings-lead">
        O que você salva aqui vale para as perícias criadas a partir de agora. Cada perícia guarda uma cópia das configurações do dia em que foi criada e não muda sozinha.
      </p>
      <dl className="settings-readiness" aria-label="Situação das configurações">
        <div><dt>Perfil profissional</dt><dd data-state={readiness.expert_profile === "MISSING" ? "missing" : "ok"}>{readiness.expert_profile === "MISSING" ? "Falta preencher" : "Preenchido"}</dd></div>
        <div><dt>Identidade visual</dt><dd>{readiness.branding === "CONFIGURED" ? "Configurada" : "Padrão do produto"}</dd></div>
        <div><dt>Documento Word</dt><dd>{readiness.template === "CUSTOM" ? "Modelo personalizado" : readiness.document === "CONFIGURED" ? "Configurado" : "Padrão do produto"}</dd></div>
        <div><dt>Perfil editorial</dt><dd>{readiness.editorial === "CUSTOM" ? "Personalizado" : "Padrão do produto"}</dd></div>
        <div><dt>Linguagem jurídica</dt><dd>Sistema Pericial — CNJ/TRF5</dd></div>
      </dl>

      <nav className="settings-index" aria-label="Seções das configurações">
        <ol>{SECTIONS.map(([id, label]) => <li key={id}><a href={`#${id}`}>{label}</a></li>)}</ol>
      </nav>

      <div className="settings-message" aria-live="polite">
        {message ? <p className={message.kind === "alert" ? "field-error" : "settings-confirmation"} role={message.kind === "alert" ? "alert" : "status"}>{message.text}</p> : null}
      </div>

      <SettingSection
        id="perfil" title="Perfil profissional"
        description={<p>Identificação usada nas perícias novas: cabeçalho, capa e fechamento do laudo.</p>}
        state={status(settings.EXPERT_PROFILE_DEFAULT_V1.configured, settings.EXPERT_PROFILE_DEFAULT_V1.revision, settings.EXPERT_PROFILE_DEFAULT_V1.created_at)}
        history={<History kind="EXPERT_PROFILE_DEFAULT_V1" revision={settings.EXPERT_PROFILE_DEFAULT_V1.revision} busy={busy} onRestore={restore("EXPERT_PROFILE_DEFAULT_V1")} />}
      >
        <ProfileSection overview={overview} busy={busy} save={save} />
      </SettingSection>

      <SettingSection
        id="identidade" title="Identidade visual"
        description={<p>Cores e imagens do seu escritório no laudo gerado pelo modelo do produto.</p>}
        state={identityState(overview)}
        history={<History kind="BRANDING_PROFILE_V1" revision={settings.BRANDING_PROFILE_V1.revision} busy={busy} onRestore={restore("BRANDING_PROFILE_V1")} />}
      >
        <IdentitySection overview={overview} busy={busy} save={save} run={run} />
      </SettingSection>

      <SettingSection
        id="documento" title="Documento Word"
        description={<p>Capa, cabeçalho, rodapé, marca d'água e fundo do Word, ou um modelo Word seu.</p>}
        state={settings.DEFAULT_TEMPLATE_SELECTION_V1.payload.mode === "CUSTOM" ? "Modelo Word personalizado" : status(settings.DOCUMENT_PRESENTATION_PROFILE_V1.configured, settings.DOCUMENT_PRESENTATION_PROFILE_V1.revision, settings.DOCUMENT_PRESENTATION_PROFILE_V1.created_at)}
        history={<History kind="DOCUMENT_PRESENTATION_PROFILE_V1" revision={settings.DOCUMENT_PRESENTATION_PROFILE_V1.revision} busy={busy} onRestore={restore("DOCUMENT_PRESENTATION_PROFILE_V1")} />}
      >
        <DocumentSection overview={overview} busy={busy} save={save} run={run} />
      </SettingSection>

      <SettingSection
        id="editorial" title="Perfil editorial"
        description={<p>{editorialSummary(settings.EDITORIAL_PROFILE_DEFAULT_V1.payload)}. Cada laudo começa com este perfil e pode ajustá-lo na etapa Laudo.</p>}
        state={status(settings.EDITORIAL_PROFILE_DEFAULT_V1.configured, settings.EDITORIAL_PROFILE_DEFAULT_V1.revision, settings.EDITORIAL_PROFILE_DEFAULT_V1.created_at)}
        history={<History kind="EDITORIAL_PROFILE_DEFAULT_V1" revision={settings.EDITORIAL_PROFILE_DEFAULT_V1.revision} busy={busy} onRestore={restore("EDITORIAL_PROFILE_DEFAULT_V1")} />}
      >
        <EditorialPanel
          profile={settings.EDITORIAL_PROFILE_DEFAULT_V1.payload}
          preset={editorialPreset}
          editable busy={busy} collapsible={false}
          hint={<p className="field-hint">Perfil editorial de referência; vale para o modelo do produto. Um modelo Word próprio mantém a formatação do seu arquivo.</p>}
          onSave={(profile) => save("EDITORIAL_PROFILE_DEFAULT_V1", profile, "Perfil editorial salvo.")}
          alternatives={legacyGeometry ? [{ label: "Aplicar geometria do laudo legado aprovado", profile: legacyGeometry }] : []}
        />
      </SettingSection>

      <SettingSection
        id="juridico" title="Linguagem jurídica"
        description={<p>Perfil editorial de referência “Sistema Pericial — CNJ/TRF5”: avisos de linguagem simples antes da emissão do laudo.</p>}
        state={status(settings.LEGAL_EDITORIAL_PROFILE_V1.configured, settings.LEGAL_EDITORIAL_PROFILE_V1.revision, settings.LEGAL_EDITORIAL_PROFILE_V1.created_at)}
        history={<History kind="LEGAL_EDITORIAL_PROFILE_V1" revision={settings.LEGAL_EDITORIAL_PROFILE_V1.revision} busy={busy} onRestore={restore("LEGAL_EDITORIAL_PROFILE_V1")} />}
      >
        <LegalSection overview={overview} busy={busy} save={save} />
      </SettingSection>

      <SettingSection id="teste" title="Documento de teste" description={<p>Gera um Word com dados fictícios, pelo mesmo caminho do laudo real, para você conferir a aparência. Nada é gravado em nenhuma perícia.</p>} state="Dados fictícios">
        <div className="action-row">
          <button type="button" className="primary-action" disabled={testState === "busy"} onClick={() => void testDocument()}>
            {testState === "busy" ? "Gerando documento…" : "Gerar documento de teste"}
          </button>
          {testState === "done" ? <span className="settings-confirmation" role="status">Documento de teste baixado.</span> : null}
          {testState === "failed" ? <span className="field-error" role="alert">As configurações atuais não geraram um Word válido. Revise as imagens e o modelo e tente de novo.</span> : null}
        </div>
      </SettingSection>
    </div>
  );
}
