import { type FormEvent, useEffect, useState } from "react";

import { confirmSiteLocation, coordinatesText, getSiteLocation, proposeSiteLocation, SiteLocationApiError, type SiteLocationEnvelope, type SiteLocationRefusal } from "../data/siteLocation";

const REFUSAL_TEXT: Record<SiteLocationRefusal, string> = {
  SHORT_LINK_REQUIRES_NETWORK: "Links curtos (maps.app.goo.gl) só revelam as coordenadas pela internet, e o sistema não os consulta. Abra o link no navegador, copie o endereço completo da barra (com @ ou !3d) ou as coordenadas do ponto e cole aqui.",
  NO_COORDINATES: "Não encontramos coordenadas no texto. Cole um link completo do Google Maps ou do OpenStreetMap, ou as coordenadas, por exemplo -23.550520, -46.633308.",
  UNSUPPORTED_LINK: "Este link não é do Google Maps nem do OpenStreetMap. Cole as coordenadas do ponto.",
  OUT_OF_RANGE: "As coordenadas estão fora do intervalo válido (latitude de -90 a 90, longitude de -180 a 180).",
};

const FORMAT_TEXT: Record<string, string> = {
  GOOGLE_MAPS_PLACE: "pino do local no Google Maps",
  GOOGLE_MAPS_QUERY: "coordenadas do link do Google Maps",
  GOOGLE_MAPS_VIEWPORT: "centro do mapa no Google Maps",
  OPENSTREETMAP: "OpenStreetMap",
  GEO_URI: "endereço geo:",
  DECIMAL: "coordenadas decimais",
  DEGREES_MINUTES_SECONDS: "graus, minutos e segundos",
};

type State = { kind: "loading" } | { kind: "empty" } | { kind: "ready"; value: SiteLocationEnvelope } | { kind: "error" };

export function SiteLocationPanel({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [input, setInput] = useState("");
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getSiteLocation(workspaceId, controller.signal)
      .then((value) => setState({ kind: "ready", value }))
      .catch((error: unknown) => { if (!controller.signal.aborted) setState(error instanceof SiteLocationApiError && error.kind === "not-found" ? { kind: "empty" } : { kind: "error" }); });
    return () => controller.abort();
  }, [workspaceId]);

  const current = state.kind === "ready" ? state.value : null;
  const showForm = state.kind === "empty" || editing;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!input.trim()) return;
    setBusy(true); setRefusal(null);
    try {
      setState({ kind: "ready", value: await proposeSiteLocation(workspaceId, current?.revision ?? null, input, address, note) });
      setEditing(false); setInput("");
    } catch (error) {
      setRefusal(error instanceof SiteLocationApiError && error.kind === "refused" && error.reason ? REFUSAL_TEXT[error.reason] : "Não foi possível guardar a localização. Recarregue a página e tente novamente.");
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    if (!current) return;
    setBusy(true); setRefusal(null);
    try { setState({ kind: "ready", value: await confirmSiteLocation(workspaceId, current.revision) }); }
    catch { setRefusal("Não foi possível confirmar. Confira se o perfil do perito está configurado e recarregue a página."); }
    finally { setBusy(false); }
  };

  const copy = async () => {
    if (!current) return;
    try { await navigator.clipboard.writeText(`${current.location.latitude.toFixed(6)}, ${current.location.longitude.toFixed(6)}`); setCopied(true); } catch { setCopied(false); }
  };

  if (state.kind === "loading") return <section className="planning-section site-location" aria-busy="true"><h3>Localização do imóvel</h3><p className="field-hint">Carregando…</p></section>;
  if (state.kind === "error") return <section className="planning-section site-location" role="alert"><h3>Localização do imóvel</h3><p>Não foi possível carregar a localização. Verifique o serviço local.</p></section>;

  return <section className="planning-section site-location" aria-labelledby="site-location-title">
    <h3 id="site-location-title">Localização do imóvel</h3>
    <p className="field-hint">O link ou as coordenadas são lidos neste computador. Nada é enviado a serviços de mapa, e o link colado não é guardado: só as coordenadas.</p>
    {current && !editing && <div className="site-location__current">
      <dl>
        <dt>Coordenadas (WGS 84)</dt><dd className="data">{coordinatesText(current.location)}</dd>
        {current.location.address_label && <><dt>Endereço</dt><dd>{current.location.address_label}</dd></>}
        <dt>Origem</dt><dd>{FORMAT_TEXT[current.location.input_format] ?? current.location.input_format}</dd>
        <dt>Situação</dt><dd><span className="status-pill" data-tone={current.location.state === "CONFIRMED" ? "done" : "warn"}>{current.location.state === "CONFIRMED" ? "Confirmada pelo perito" : "Aguardando sua confirmação"}</span></dd>
      </dl>
      {current.location.input_format === "GOOGLE_MAPS_VIEWPORT" && current.location.state === "PROPOSED" && <p className="inline-note">O link trazia só o centro do mapa, não o pino do local. Confira se o ponto corresponde ao imóvel antes de confirmar.</p>}
      <div className="action-row">
        {current.location.state === "PROPOSED" && <button className="primary-action" type="button" disabled={busy} onClick={() => void confirm()}>{busy ? "Confirmando…" : "Confirmar localização"}</button>}
        <button className="secondary-action" type="button" disabled={busy} onClick={() => { setEditing(true); setAddress(current.location.address_label ?? ""); setNote(current.location.note ?? ""); setRefusal(null); }}>Alterar localização</button>
        <button className="text-action" type="button" onClick={() => void copy()}>{copied ? "Coordenadas copiadas" : "Copiar coordenadas"}</button>
      </div>
      {current.location.state === "CONFIRMED" && <p className="field-hint">Para citar no laudo, use "Inserir localização" na seção Vistoria.</p>}
    </div>}
    {showForm && <form className="site-location__form" onSubmit={submit} aria-label="Informar localização">
      <label>Link do mapa ou coordenadas<textarea required value={input} placeholder="Link do Google Maps ou do OpenStreetMap, ou -23.550520, -46.633308" onChange={(event) => setInput(event.target.value)} disabled={busy} /></label>
      <label>Endereço ou referência (opcional)<input value={address} onChange={(event) => setAddress(event.target.value)} disabled={busy} /></label>
      <label>Observação (opcional)<input value={note} onChange={(event) => setNote(event.target.value)} disabled={busy} /></label>
      <div className="action-row">
        <button className="primary-action" type="submit" disabled={busy || !input.trim()}>{busy ? "Lendo…" : "Ler localização"}</button>
        {editing && <button className="text-action" type="button" disabled={busy} onClick={() => { setEditing(false); setRefusal(null); }}>Cancelar</button>}
      </div>
      {current?.location.state === "CONFIRMED" && <p className="field-hint">Uma nova localização volta a aguardar sua confirmação.</p>}
    </form>}
    {refusal && <p className="inline-alert" role="alert">{refusal}</p>}
  </section>;
}
