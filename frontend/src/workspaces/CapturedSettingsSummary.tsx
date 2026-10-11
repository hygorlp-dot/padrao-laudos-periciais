import { useEffect, useState } from "react";

import type { ExpertProfileDefault, WorkspaceSettingsView } from "../data/installationSettings";
import { getExpertProfile, ReportApiError } from "../data/reportSnapshot";
import { editorialSummary } from "../ui/editorialProfile";

type CapturedProfile = Omit<ExpertProfileDefault, "revision"> & { revision: number };
const ASSETS = { PRIMARY_LOGO: "Logotipo", SYMBOL: "Símbolo", WATERMARK: "Marca d'água", SIGNATURE_IMAGE: "Assinatura", PROFESSIONAL_SEAL: "Selo profissional", BACKGROUND: "Fundo", DEFAULT_WORD_TEMPLATE: "Modelo Word" };

// Somente autoridades da perícia. Nunca preencher este resumo com defaults globais.
export function CapturedSettingsSummary({ workspaceId, snapshot, revision }: { workspaceId: string; snapshot: WorkspaceSettingsView["snapshot"]; revision: number | null }) {
  const [profile, setProfile] = useState<CapturedProfile | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "unavailable">("loading");
  useEffect(() => {
    const controller = new AbortController();
    getExpertProfile(workspaceId, controller.signal).then(
      (value) => { if (!controller.signal.aborted) { setProfile(value.profile); setState("ready"); } },
      (error) => { if (!controller.signal.aborted) { setProfile(null); setState(error instanceof ReportApiError && error.kind === "not-found" ? "missing" : "unavailable"); } },
    );
    return () => controller.abort();
  }, [workspaceId, revision]);
  const presentation = snapshot?.presentation;
  const images = snapshot?.assets.filter((asset) => asset.role !== "DEFAULT_WORD_TEMPLATE") ?? [];
  const customTemplate = snapshot?.assets.find((asset) => asset.role === "DEFAULT_WORD_TEMPLATE");
  return (
    <dl className="workspace-settings__summary" aria-label="Configurações capturadas em uso">
      <div><dt>Perfil profissional</dt><dd>
        {state === "ready" && profile ? <>
          <span>{profile.full_name} · {profile.professional_title} · {profile.registration}</span>
          {profile.court_registrations?.length ? <ul>{profile.court_registrations.map((item, index) => <li key={index}>{item.court ? `${item.court} · ` : ""}{item.registration}{item.label ? ` · ${item.label}` : ""}{item.active ? "" : " · Inativo"}</li>)}</ul> : null}
        </> : state === "missing" ? "Perfil ainda não capturado" : state === "unavailable" ? "Não foi possível consultar o perfil desta perícia" : "Consultando perfil desta perícia…"}
      </dd></div>
      <div><dt>Identidade visual</dt><dd>{snapshot ? <>
        <span>{snapshot.sources?.BRANDING_PROFILE_V1 ? "Cores configuradas" : "Cores do sistema"}</span>
        {images.length ? <ul>{images.map((asset) => <li key={asset.role}>{ASSETS[asset.role]} · {asset.filename}</li>)}</ul> : <span> · Sem imagens de marca</span>}
      </> : "Configurações ainda não capturadas"}</dd></div>
      <div><dt>Documento Word</dt><dd>{snapshot?.template_selection ? snapshot.template_selection.mode === "CUSTOM" ? `Meu modelo Word${customTemplate ? ` · ${customTemplate.filename}` : ""}` : "Modelo padrão do sistema" : "Modelo capturado indisponível"}</dd></div>
      <div><dt>Perfil editorial</dt><dd>{snapshot?.editorial_profile ? editorialSummary(snapshot.editorial_profile) : "Perfil capturado indisponível"}</dd></div>
      <div><dt>Apresentação do documento</dt><dd>{presentation ? <>
        <span>{presentation.cover.enabled ? `Capa · ${presentation.cover.title}` : "Sem capa"}</span>{" · "}
        <span>{presentation.header.enabled ? "Com cabeçalho" : "Sem cabeçalho"}</span>{" · "}
        <span>{presentation.footer.page_numbering === "PAGE_X_OF_Y" ? "Página X de Y" : "Página X"}</span>{" · "}
        <span>{presentation.watermark.enabled ? "Com marca d'água" : "Sem marca d'água"}</span>{" · "}
        <span>{presentation.background.kind === "WHITE" ? "Fundo branco" : presentation.background.kind === "IMAGE" ? "Fundo com imagem" : "Fundo com cor"}</span>
      </> : "Apresentação capturada indisponível"}</dd></div>
    </dl>
  );
}
