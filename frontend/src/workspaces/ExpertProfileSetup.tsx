import { useEffect, useRef, useState, type FormEvent } from "react";
import { getExpertProfile, saveExpertProfile, ReportApiError, type ExpertProfile } from "../data/reportSnapshot";
import { listWorkspaces, type Workspace } from "../data/workspaces";
import { useRefreshExpertIdentity } from "../data/expertIdentity";

const FIELDS = [
  ["full_name", "Nome completo"], ["professional_title", "Título profissional"],
  ["registration", "Registro profissional"], ["court_registration", "Cadastro no tribunal"],
  ["contact_line", "Contato profissional"],
] as const;
type Identity = Pick<ExpertProfile, typeof FIELDS[number][0]>;
const empty: Identity = { full_name: "", professional_title: "", registration: "", court_registration: "", contact_line: "" };

export function ExpertProfileSetup({ workspaceId, onSaved, submitLabel = "Salvar perfil do perito" }: { workspaceId: string; onSaved: () => void | Promise<void>; submitLabel?: string }) {
  const [profile, setProfile] = useState<Identity>(empty);
  const [sources, setSources] = useState<Workspace[] | null>(null);
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const refreshExpert = useRefreshExpertIdentity();
  useEffect(() => () => request.current?.abort(), []);
  async function discover() {
    setBusy(true); setError("");
    try { setSources((await listWorkspaces()).filter((workspace) => workspace.workspace_id !== workspaceId)); }
    catch { setError("Não foi possível localizar perfis cadastrados. Você pode preencher os dados abaixo."); }
    finally { setBusy(false); }
  }
  async function choose(id: string) {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setSource(id); setError("");
    if (!id) return;
    setBusy(true);
    try {
      const saved = await getExpertProfile(id, controller.signal);
      if (!controller.signal.aborted) setProfile(Object.fromEntries(FIELDS.map(([field]) => [field, saved.profile[field]])) as Identity);
    } catch { if (!controller.signal.aborted) setError("Esta perícia não tem um perfil disponível. Escolha outra ou informe os dados."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function confirm(event: FormEvent) {
    event.preventDefault(); setError("");
    if (Object.values(profile).some((value) => !value.trim())) { setError("Complete todos os campos obrigatórios do perfil mestre."); return; }
    setBusy(true);
    try {
      await saveExpertProfile(workspaceId, { profile_id: "EXPERT-PROFILE-001", revision: 1, ...Object.fromEntries(FIELDS.map(([field]) => [field, profile[field].trim()])) as Identity });
      refreshExpert(); await onSaved();
    } catch { setError("Não foi possível salvar o perfil. Reabra a seção se ele já foi cadastrado em outra tela."); }
    finally { setBusy(false); }
  }
  return <form className="property-panel" onSubmit={(event) => void confirm(event)}>
    <button className="text-action" type="button" disabled={busy} onClick={() => void discover()}>Reutilizar perfil cadastrado</button>
    {sources && <><label>Perícia de origem do perfil<select value={source} disabled={busy} onChange={(event) => void choose(event.target.value)}><option value="">Selecione uma perícia</option>{sources.map((workspace) => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.name}</option>)}</select></label><p className="field-hint">Somente a identificação profissional será reaproveitada. Confira os dados antes de salvar.</p>{sources.length === 0 && <p>Nenhuma outra perícia disponível.</p>}</>}
    <div className="property-grid">{FIELDS.map(([field, label]) => <label key={field}>{label}<input required disabled={busy} value={profile[field]} onChange={(event) => setProfile({ ...profile, [field]: event.target.value })}/></label>)}</div>
    {error && <p role="alert">{error}</p>}
    <button className="primary-action" type="submit" disabled={busy}>{busy ? "Salvando…" : submitLabel}</button>
  </form>;
}

export function ExpertProfilePanel({ workspaceId }: { workspaceId: string }) {
  return <ProfileContent key={workspaceId} workspaceId={workspaceId} />;
}
function ProfileContent({ workspaceId }: { workspaceId: string }) {
  const [opened, setOpened] = useState(false);
  const [profile, setProfile] = useState<ExpertProfile | null>(null);
  const [status, setStatus] = useState("loading");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    getExpertProfile(workspaceId, controller.signal).then((value) => { if (!controller.signal.aborted) { setProfile(value.profile); setStatus("ready"); } }, (error) => { if (!controller.signal.aborted) setStatus(error instanceof ReportApiError && error.kind === "not-found" ? "missing" : "error"); });
    return () => controller.abort();
  }, [workspaceId, opened, version]);
  return <details className="analysis-section property-panel" onToggle={(event) => setOpened(event.currentTarget.open)}><summary><strong>Perfil do perito</strong><span>Identificação profissional utilizada em todas as etapas</span></summary>
    {opened && status === "loading" && <p role="status">Carregando perfil…</p>}
    {status === "error" && <p role="alert">Não foi possível abrir o perfil. Reabra esta seção para tentar novamente.</p>}
    {status === "ready" && profile && <dl className="property-summary">{FIELDS.map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{profile[field]}</dd></div>)}</dl>}
    {status === "missing" && <ExpertProfileSetup workspaceId={workspaceId} onSaved={() => { setStatus("loading"); setVersion(version + 1); }} />}
  </details>;
}
