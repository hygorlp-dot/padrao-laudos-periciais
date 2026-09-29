import { useEffect, useState, type FormEvent } from "react";
import { getSiteLocation, coordinatesText, SiteLocationApiError } from "../data/siteLocation";
import { workspacePath } from "../routes/routeCatalog";
import { navigate } from "../app/router";
import { getPropertyRecord, getPropertyProposals, savePropertyRecord, PropertyApiError, type PropertyEnvelope, type PropertyEvidence, type PropertyProposal } from "../data/propertyRecord";

function Source({ evidence }: { evidence: PropertyEvidence | null }) {
  if (!evidence) return <small className="field-hint">Informado e confirmado pelo perito</small>;
  return <details className="property-source"><summary>Extraído dos autos · {evidence.filename}, p. {evidence.page}</summary><blockquote>{evidence.excerpt}</blockquote><small>{evidence.method.includes("OCR") ? "Leitura por OCR" : "Texto do documento"}</small></details>;
}

function message(error: unknown) {
  if (error instanceof PropertyApiError) {
    if (error.kind === "conflict") return "O cadastro mudou em outra tela. Recarregue os dados salvos antes de confirmar.";
    if (error.kind === "profile-missing") return "Cadastre o perfil mestre do perito para confirmar os dados do imóvel.";
    if (error.kind === "invalid") return "Confira os valores e as fontes selecionadas. Uma proposta alterada precisa ser selecionada novamente.";
  }
  return "Não foi possível concluir. Os dados confirmados continuam preservados. Tente novamente.";
}

export function PropertyPanel({ workspaceId, readOnly = false }: { workspaceId: string; readOnly?: boolean }) {
  return <PropertyContent key={workspaceId} workspaceId={workspaceId} readOnly={readOnly} />;
}

function PropertyContent({ workspaceId, readOnly }: { workspaceId: string; readOnly: boolean }) {
  const [opened, setOpened] = useState(readOnly);
  const [loadVersion, setLoadVersion] = useState(0);
  const [record, setRecord] = useState<PropertyEnvelope | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Record<string, string | null>>({});
  const [proposals, setProposals] = useState<PropertyProposal[] | null>(null);
  const [busy, setBusy] = useState<"search" | "save" | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [location, setLocation] = useState("");
  useEffect(() => {
    if (!opened || readOnly) return;
    const controller = new AbortController();
    getSiteLocation(workspaceId, controller.signal).then((value) => {
      if (!controller.signal.aborted) setLocation(value.location.state === "CONFIRMED" ? coordinatesText(value.location) : "Localização ainda não confirmada.");
    }, (failure) => { if (!controller.signal.aborted) setLocation(failure instanceof SiteLocationApiError && failure.kind === "not-found" ? "Localização ainda não cadastrada." : "Não foi possível consultar a localização."); });
    return () => controller.abort();
  }, [workspaceId, opened, readOnly]);
  useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    getPropertyRecord(workspaceId, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setRecord(value); setDraft(Object.fromEntries(value.record.values.map((item) => [item.field, item.value]))); setSelected({}); setError("");
    }, (failure) => { if (!controller.signal.aborted) setError(message(failure)); });
    return () => controller.abort();
  }, [workspaceId, opened, loadVersion]);
  async function search() {
    setBusy("search"); setError("");
    try { setProposals(await getPropertyProposals(workspaceId)); }
    catch (failure) { setError(message(failure)); }
    finally { setBusy(null); }
  }
  async function confirm(event: FormEvent) {
    event.preventDefault();
    if (!record) return;
    const changes = record.fields.filter(({ field }) => (draft[field] ?? "").trim() !== (record.record.values.find((item) => item.field === field)?.value ?? "") || Boolean(selected[field])).map(({ field }) => ({ field, value: draft[field]?.trim() || null, proposal_id: selected[field] ?? null }));
    if (!changes.length) return;
    setBusy("save"); setError(""); setSaved(false);
    try { const value = await savePropertyRecord(workspaceId, record.revision, changes); setRecord(value); setDraft(Object.fromEntries(value.record.values.map((item) => [item.field, item.value]))); setSelected({}); setSaved(true); }
    catch (failure) { setError(message(failure)); }
    finally { setBusy(null); }
  }
  if (readOnly && error) return <p role="alert">Não foi possível carregar o cadastro do imóvel nesta etapa. Os demais dados continuam disponíveis.</p>;
  if (readOnly) return record?.record.values.length ? <section className="analysis-section property-summary"><h3>Imóvel confirmado</h3><dl>{record.record.values.map((value) => <div key={value.field}><dt>{record.fields.find((field) => field.field === value.field)?.label}</dt><dd>{value.value}{record.stale_fields.includes(value.field) ? <small className="field-warning"> · fonte excluída da análise</small> : null}</dd></div>)}</dl><p className="field-hint">Para alterar, abra Imóvel na etapa Processo. As coordenadas são confirmadas na localização.</p></section> : null;
  return <details className="analysis-section property-panel" onToggle={(event) => { if (event.currentTarget.open) setOpened(true); }}>
    <summary><strong>Imóvel</strong><span>Cadastro único para a vistoria e o laudo</span></summary>
    <p>O proprietário pode ser diferente da parte autora. Confirme somente o que estiver identificado; deixe os dados ausentes em branco.</p>
    {error && <div role="alert"><p>{error}</p><button type="button" className="text-action" disabled={busy !== null} onClick={() => setLoadVersion((value) => value + 1)}>Recarregar dados salvos</button></div>}
    {!record && !error && opened && <p role="status">Carregando cadastro do imóvel…</p>}
    {record && <form onSubmit={(event) => void confirm(event)}>
      <button className="text-action" type="button" disabled={busy !== null} onClick={() => void search()}>{busy === "search" ? "Lendo os documentos…" : "Buscar informações nos documentos"}</button>
      {proposals?.length === 0 && <p role="status">Não foram encontrados campos explícitos nos materiais lidos. Isso não confirma a ausência da informação nos autos.</p>}
      <div className="property-grid">{record.fields.map((field) => {
        const prior = record.record.values.find((item) => item.field === field.field);
        const candidates = proposals?.filter((proposal) => proposal.field === field.field) ?? [];
        const choice = candidates.find((proposal) => proposal.proposal_id === selected[field.field]);
        return <div className="property-field" key={field.field}>
          <label>{field.label}<input value={draft[field.field] ?? ""} inputMode={field.kind === "decimal" ? "decimal" : undefined} placeholder={field.kind === "date" ? "DD/MM/AAAA" : undefined} disabled={busy !== null} onChange={(event) => { setDraft({ ...draft, [field.field]: event.target.value }); setSelected({ ...selected, [field.field]: null }); setSaved(false); }} /></label>
          {choice ? <><small>Proposta selecionada · confirme para salvar</small><Source evidence={choice.evidence} /></> : prior && draft[field.field] === prior.value ? <Source evidence={prior.evidence} /> : null}
          {prior && record.stale_fields.includes(field.field) && <p role="alert" className="field-warning">A peça que sustentava este valor foi excluída da análise. Confirme o dado por outra fonte ou remova-o antes de usá-lo no laudo.</p>}
          {candidates.length > 0 && <details className="property-candidates"><summary>{candidates.length} proposta(s) nos documentos{candidates.some((item) => item.state === "CONFLICTING") ? " · valores divergentes" : ""}</summary>{candidates.map((candidate) => <div className="property-candidate" key={candidate.proposal_id}><strong>{candidate.value}</strong><Source evidence={candidate.evidence} /><button type="button" className="text-action" disabled={busy !== null} onClick={() => { setDraft({ ...draft, [field.field]: candidate.value }); setSelected({ ...selected, [field.field]: candidate.proposal_id }); setSaved(false); }}>Usar esta proposta</button></div>)}</details>}
        </div>;
      })}</div>
      <p className="field-hint">{location} <a href={workspacePath(workspaceId, "planejamento")} onClick={navigate}>Abrir localização no planejamento</a></p>
      {saved && <p role="status">Dados do imóvel confirmados e salvos.</p>}
      <button className="primary-action" type="submit" disabled={busy !== null}>{busy === "save" ? "Salvando…" : "Confirmar dados do imóvel"}</button>
    </form>}
  </details>;
}
