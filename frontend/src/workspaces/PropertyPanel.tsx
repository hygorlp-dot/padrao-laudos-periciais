import { useEffect, useState, type FormEvent } from "react";
import { getSiteLocation, coordinatesText, SiteLocationApiError } from "../data/siteLocation";
import { workspacePath } from "../routes/routeCatalog";
import { navigate } from "../app/router";
import { getPropertyRecord, getPropertyProposals, savePropertyRecord, PropertyApiError, type PropertyEnvelope, type PropertyEvidence, type PropertyProposal, type PropertyValueCluster } from "../data/propertyRecord";

function Source({ evidence }: { evidence: PropertyEvidence | null }) {
  if (!evidence) return <small className="field-hint">Informado e confirmado pelo perito</small>;
  const reading = evidence.method.includes("OCR") ? "Leitura por OCR" : "Texto do documento";
  const how = evidence.method.startsWith("LABEL_") ? "campo identificado no documento" : evidence.method.startsWith("CONTEXT_BOUND_") ? "trecho que se refere ao imóvel objeto" : "padrão do tipo de documento";
  return <details className="property-source"><summary>Extraído dos autos · {evidence.filename}, p. {evidence.page}</summary><blockquote>{evidence.excerpt}</blockquote><small>{reading} · {how}</small></details>;
}

const CONFIDENCE_LABELS: Record<PropertyValueCluster["confidence"], string> = { HIGH: "alta", MEDIUM: "média", LOW: "baixa" };
const RANK_LABELS: Record<string, string> = {
  A: "matrícula ou registro", B: "contrato", C: "termo de entrega", D: "laudo ou parecer técnico",
  E: "petição inicial", F: "contestação", G: "outra peça", H: "contexto possível",
};

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

// #288: um valor com todas as suas evidências; "Usar" grava a melhor delas.
function ClusterCard({ cluster, label, disabled, onUse }: { cluster: PropertyValueCluster; label: string; disabled: boolean; onUse: (cluster: PropertyValueCluster) => void }) {
  return <div className="property-cluster">
    <strong>{cluster.display_value}</strong>
    <small>Consistência documental: {CONFIDENCE_LABELS[cluster.confidence]} · melhor fonte: {RANK_LABELS[cluster.best_rank] ?? "outra peça"}</small>
    <small>{plural(cluster.source_count, "ocorrência", "ocorrências")} · {plural(cluster.document_count, "peça", "peças")}</small>
    {cluster.strength === "POSSIBLE" ? <small className="field-warning">Possível informação encontrada — confira a fonte</small> : null}
    {cluster.evidences.slice(0, 2).map((item) => <Source key={item.proposal_id} evidence={item.evidence} />)}
    {cluster.evidences.length > 2 ? <details className="property-more-sources"><summary>Ver mais {plural(cluster.evidences.length - 2, "fonte", "fontes")}</summary>{cluster.evidences.slice(2).map((item) => <Source key={item.proposal_id} evidence={item.evidence} />)}</details> : null}
    <button type="button" className="text-action" disabled={disabled} aria-label={`${label}: ${cluster.display_value}`} onClick={() => onUse(cluster)}>{label}</button>
  </div>;
}

function FieldClusters({ clusters, disabled, onUse }: { clusters: PropertyValueCluster[]; disabled: boolean; onUse: (cluster: PropertyValueCluster) => void }) {
  if (!clusters.length) return null;
  const strong = clusters.filter((item) => item.strength === "STRONG");
  const possible = clusters.filter((item) => item.strength !== "STRONG");
  // Divergência forte nunca fica escondida nem vira "proposta principal".
  if (strong.length > 1) {
    return <>
      <div className="property-divergence" role="group" aria-label="Valores divergentes encontrados">
        <p className="field-warning">Valores divergentes encontrados ({strong.length}). Confira as fontes antes de escolher.</p>
        <div className="property-cluster-grid">{strong.map((cluster) => <ClusterCard key={cluster.cluster_id} cluster={cluster} label="Usar este valor" disabled={disabled} onUse={onUse} />)}</div>
      </div>
      {possible.length ? <details className="property-candidates"><summary>Outros valores encontrados ({possible.length})</summary>{possible.map((cluster) => <ClusterCard key={cluster.cluster_id} cluster={cluster} label="Usar este valor" disabled={disabled} onUse={onUse} />)}</details> : null}
    </>;
  }
  const [main, ...others] = strong.length ? [strong[0], ...possible] : possible;
  return <>
    <div className="property-main-proposal"><small>Proposta encontrada nos autos</small><ClusterCard cluster={main} label="Usar esta proposta" disabled={disabled} onUse={onUse} /></div>
    {others.length ? <p className="field-warning" role="status">Há {plural(others.length, "outro valor", "outros valores")} para este campo nos autos. Confira antes de usar.</p> : null}
    {others.length ? <details className="property-candidates"><summary>Outros valores encontrados ({others.length})</summary>{others.map((cluster) => <ClusterCard key={cluster.cluster_id} cluster={cluster} label="Usar este valor" disabled={disabled} onUse={onUse} />)}</details> : null}
  </>;
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
  const [clusters, setClusters] = useState<PropertyValueCluster[] | null>(null);
  const [pending, setPending] = useState<string[]>([]);
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
    try { const found = await getPropertyProposals(workspaceId); setProposals(found.proposals); setClusters(found.clusters ?? null); setPending(found.pendingDocuments); }
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
      {pending.length > 0 && <p role="status">Leitura em andamento: {pending.join(", ")}. Busque de novo quando terminar.</p>}
      {proposals?.length === 0 && <p role="status">Nenhuma proposta foi encontrada automaticamente. As informações ainda podem existir nos documentos. Revise os materiais ou preencha manualmente.</p>}
      {proposals && proposals.length > 0 && <p role="status">{clusters ? `Propostas encontradas nos autos para ${plural(new Set(clusters.map((item) => item.field)).size, "campo", "campos")}.` : `${proposals.length} proposta(s) encontrada(s).`} Nada é salvo sem a sua confirmação; confira a fonte de cada valor.</p>}
      {proposals && proposals.length > 0 && !clusters && <p role="status" className="field-warning">Os valores repetidos não puderam ser agrupados nesta versão; cada fonte aparece separada.</p>}
      <div className="property-grid">{record.fields.map((field) => {
        const prior = record.record.values.find((item) => item.field === field.field);
        const candidates = proposals?.filter((proposal) => proposal.field === field.field) ?? [];
        const fieldClusters = clusters?.filter((cluster) => cluster.field === field.field) ?? [];
        const choice = candidates.find((proposal) => proposal.proposal_id === selected[field.field]);
        const use = (cluster: PropertyValueCluster) => { setDraft({ ...draft, [field.field]: cluster.display_value }); setSelected({ ...selected, [field.field]: cluster.evidences[0].proposal_id }); setSaved(false); };
        return <div className="property-field" key={field.field}>
          <label>{field.label}<input value={draft[field.field] ?? ""} inputMode={field.kind === "decimal" ? "decimal" : undefined} placeholder={field.kind === "date" ? "DD/MM/AAAA" : undefined} disabled={busy !== null} onChange={(event) => { setDraft({ ...draft, [field.field]: event.target.value }); setSelected({ ...selected, [field.field]: null }); setSaved(false); }} /></label>
          {choice ? <><small>Proposta selecionada · confirme para salvar</small><Source evidence={choice.evidence} /></> : prior && draft[field.field] === prior.value ? <Source evidence={prior.evidence} /> : null}
          {prior && record.stale_fields.includes(field.field) && <p role="alert" className="field-warning">A peça que sustentava este valor foi excluída da análise. Confirme o dado por outra fonte ou remova-o antes de usá-lo no laudo.</p>}
          {clusters ? <FieldClusters clusters={fieldClusters} disabled={busy !== null} onUse={use} /> : null}
          {!clusters && candidates.length > 0 && <details className="property-candidates"><summary>{candidates.length} proposta(s) nos documentos{candidates.some((item) => item.state === "CONFLICTING") ? " · valores divergentes" : ""}</summary>{candidates.map((candidate) => <div className="property-candidate" key={candidate.proposal_id}><strong>{candidate.value}</strong>{candidate.strength === "POSSIBLE" ? <small className="field-warning">Possível informação encontrada — confira a fonte</small> : null}<Source evidence={candidate.evidence} /><button type="button" className="text-action" disabled={busy !== null} onClick={() => { setDraft({ ...draft, [field.field]: candidate.value }); setSelected({ ...selected, [field.field]: candidate.proposal_id }); setSaved(false); }}>Usar esta proposta</button></div>)}</details>}
        </div>;
      })}</div>
      <p className="field-hint">{location} <a href={workspacePath(workspaceId, "planejamento")} onClick={navigate}>Abrir localização no planejamento</a></p>
      {saved && <p role="status">Dados do imóvel confirmados e salvos.</p>}
      <button className="primary-action" type="submit" disabled={busy !== null}>{busy === "save" ? "Salvando…" : "Confirmar dados do imóvel"}</button>
    </form>}
  </details>;
}
