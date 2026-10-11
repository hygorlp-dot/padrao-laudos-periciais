import { useEffect, useRef, useState } from "react";

import { navigate } from "../app/router";
import {
  getWorkspaceSettings,
  refreshWorkspaceSettings,
  SettingsApiError,
  type WorkspaceSettingsView,
} from "../data/installationSettings";
import { CapturedSettingsSummary } from "./CapturedSettingsSummary";

// Configurações capturadas por esta perícia (#270). Mudar o padrão da
// instalação não altera a perícia; atualizar é um ato explícito, com as
// diferenças à vista e uma nova revisão no histórico.

const CHANGE_LABELS: Record<string, string> = {
  SETTINGS_NOT_CAPTURED: "Esta perícia ainda não tem cópia das configurações",
  EDITORIAL_PROFILE_DEFAULT_V1: "Perfil editorial",
  BRANDING_PROFILE_V1: "Cores da identidade visual",
  DOCUMENT_PRESENTATION_PROFILE_V1: "Capa, cabeçalho, rodapé, marca d'água ou fundo",
  LEGAL_EDITORIAL_PROFILE_V1: "Linguagem jurídica",
  DEFAULT_TEMPLATE_SELECTION_V1: "Modelo Word",
  "ASSET:PRIMARY_LOGO": "Logotipo",
  "ASSET:SYMBOL": "Símbolo",
  "ASSET:WATERMARK": "Imagem da marca d'água",
  "ASSET:SIGNATURE_IMAGE": "Imagem da assinatura",
  "ASSET:PROFESSIONAL_SEAL": "Selo profissional",
  "ASSET:BACKGROUND": "Imagem de fundo",
  PROFILE_NOT_CAPTURED: "Esta perícia ainda não tem perfil profissional",
};

const PROFILE_FIELDS: Record<string, string> = {
  full_name: "nome", signature_name: "nome na assinatura", professional_title: "título profissional", registration: "registro no conselho",
  professional_council: "conselho", council_state: "UF do conselho", national_registration: "registro nacional",
  court_registration: "cadastros em tribunais", court_registrations: "cadastros em tribunais", contact_line: "contato",
  contact: "contato", presentation: "o que o documento mostra",
};

export function WorkspaceSettingsPanel({ workspaceId }: { workspaceId: string }) {
  return <WorkspaceSettingsContent key={workspaceId} workspaceId={workspaceId} />;
}

function WorkspaceSettingsContent({ workspaceId }: { workspaceId: string }) {
  const [view, setView] = useState<WorkspaceSettingsView | null>(null);
  const [failed, setFailed] = useState(false);
  const [version, setVersion] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [includeProfile, setIncludeProfile] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const operation = useRef(false);
  const confirmation = useRef<HTMLDivElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const [message, setMessage] = useState<{ kind: "status" | "alert"; text: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getWorkspaceSettings(workspaceId, controller.signal).then(
      (value) => { if (!controller.signal.aborted) { setView(value); setFailed(false); } },
      () => { if (!controller.signal.aborted) setFailed(true); },
    );
    return () => controller.abort();
  }, [workspaceId, version]);

  useEffect(() => {
    if (confirming) confirmation.current?.querySelector<HTMLElement>("input, button")?.focus();
  }, [confirming]);

  if (failed) {
    return (
      <section className="analysis-section workspace-settings" aria-labelledby="workspace-settings-title">
        <h3 id="workspace-settings-title">Configurações desta perícia</h3>
        <p role="alert">Não foi possível ler as configurações desta perícia.</p>
        <button type="button" className="text-action" onClick={() => setVersion((value) => value + 1)}>Tentar novamente</button>
      </section>
    );
  }
  if (!view) return <p role="status">Consultando as configurações desta perícia…</p>;

  const { differences } = view;
  if (differences === null) {
    return (
      <section className="analysis-section workspace-settings" aria-labelledby="workspace-settings-title">
        <h3 id="workspace-settings-title">Configurações desta perícia</h3>
        <CapturedSettingsSummary key={view.revision} workspaceId={workspaceId} snapshot={view.snapshot} revision={view.revision} />
        <p className="field-hint">{view.revision ? `Cópia das configurações tirada em ${new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(new Date(view.updated_at ?? ""))} (revisão ${view.revision}).` : "Perícia criada antes das configurações centrais."}</p>
        <p role="status">As Configurações da instalação não puderam ser abertas agora. Esta perícia continua com a cópia dela; a comparação e a atualização voltam quando as Configurações abrirem.</p>
      </section>
    );
  }
  const settingsChanges = differences.settings_changes;
  const profileChanges = differences.profile_changes;
  const upToDate = settingsChanges.length === 0 && profileChanges.length === 0;
  const snapshotRevision = differences.snapshot_revision;
  const profileRevision = differences.profile_revision;

  async function apply() {
    if (operation.current || uncertain) return;
    operation.current = true;
    setBusy(true);
    setMessage(null);
    try {
      const next = await refreshWorkspaceSettings(workspaceId, {
        include_profile: includeProfile,
        expected_snapshot_revision: snapshotRevision,
        expected_profile_revision: includeProfile ? profileRevision : null,
      });
      setView(next);
      setConfirming(false);
      const profileKept = !includeProfile && (next.differences?.profile_changes.length ?? 0) > 0;
      setMessage({ kind: "status", text: includeProfile ? "Configurações e perfil atualizados. Um laudo já aprovado precisa ser revisado de novo." : profileKept ? "Configurações atualizadas; o perfil profissional desta perícia não mudou. A versão anterior continua no histórico." : "Configurações atualizadas; a versão anterior continua no histórico." });
    } catch (error) {
      // A resposta pode se perder depois da gravação. Observar antes de oferecer outro comando.
      try {
        setView(await getWorkspaceSettings(workspaceId));
        setConfirming(false);
        setIncludeProfile(false);
        setMessage({ kind: "alert", text: error instanceof SettingsApiError && error.kind === "conflict" ? "Esta configuração mudou em outra janela. Os dados foram recarregados. Confira e salve novamente." : "A resposta da atualização não foi confirmada. As configurações da perícia foram recarregadas; confira o resultado antes de continuar." });
      } catch {
        setUncertain(true);
        setMessage({ kind: "alert", text: "Não foi possível confirmar o resultado da atualização. Recarregue as configurações desta perícia antes de tentar outra atualização." });
      }
    } finally {
      operation.current = false;
      setBusy(false);
      title.current?.focus();
    }
  }

  return (
    <section className="analysis-section workspace-settings" aria-labelledby="workspace-settings-title">
      <h3 id="workspace-settings-title" ref={title} tabIndex={-1}>Configurações desta perícia</h3>
      <p className="field-hint">
        {view.revision ? `Cópia das configurações tirada em ${new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(new Date(view.updated_at ?? ""))} (revisão ${view.revision}).` : "Perícia criada antes das configurações centrais."}{" "}
        Mudanças em <a className="text-action" href="/configuracoes" onClick={navigate}>Configurações</a> não alteram esta perícia sozinhas.
      </p>
      <CapturedSettingsSummary key={view.revision} workspaceId={workspaceId} snapshot={view.snapshot} revision={view.revision} />
      {upToDate ? (
        <p className="settings-confirmation">Igual às configurações atuais.</p>
      ) : (
        <>
          <p>Há configurações mais recentes disponíveis.</p>
          <p className="field-hint">Uma atualização confirmada adotará as mudanças abaixo. As revisões anteriores e os documentos já emitidos serão preservados.</p>
          <ul className="workspace-settings__changes">
            {settingsChanges.map((item) => <li key={item}>{CHANGE_LABELS[item] ?? "Outra configuração capturada"}</li>)}
            {profileChanges.length ? <li>Perfil profissional: {[...new Set(profileChanges.map((item) => CHANGE_LABELS[item] ?? PROFILE_FIELDS[item] ?? "identificação"))].join(", ")}</li> : null}
          </ul>
          {confirming ? (
            <div className="workspace-settings__confirm" ref={confirmation} role="group" aria-label="Confirmar atualização">
              {profileChanges.length ? (
                <label className="checkbox-label">
                  <input type="checkbox" checked={includeProfile} disabled={busy} onChange={(event) => setIncludeProfile(event.target.checked)} />
                  Atualizar também o perfil profissional desta perícia (um laudo já aprovado volta para revisão)
                </label>
              ) : null}
              <div className="action-row">
                <button type="button" className="primary-action" aria-busy={busy} disabled={busy || uncertain || (settingsChanges.length === 0 && !includeProfile)} onClick={() => void apply()}>Confirmar atualização</button>
                <button type="button" className="text-action" disabled={busy} onClick={() => { setConfirming(false); setIncludeProfile(false); title.current?.focus(); }}>Cancelar</button>
              </div>
            </div>
          ) : (
            <button type="button" className="text-action" disabled={busy || uncertain} onClick={() => setConfirming(true)}>Atualizar a partir das configurações</button>
          )}
        </>
      )}
      {message ? <p className={message.kind === "alert" ? "field-error" : "settings-confirmation"} role={message.kind === "alert" ? "alert" : "status"}>{message.text}</p> : null}
      {uncertain ? <button type="button" className="text-action" disabled={busy} onClick={async () => {
        if (operation.current) return;
        operation.current = true;
        setBusy(true);
        try { setView(await getWorkspaceSettings(workspaceId)); setUncertain(false); setConfirming(false); setIncludeProfile(false); setMessage({ kind: "status", text: "Configurações recarregadas. Confira o resultado da atualização." }); }
        catch { setMessage({ kind: "alert", text: "As configurações desta perícia continuam indisponíveis para conferência. Tente recarregar novamente." }); }
        finally { operation.current = false; setBusy(false); title.current?.focus(); }
      }}>Recarregar configurações desta perícia</button> : null}
    </section>
  );
}
