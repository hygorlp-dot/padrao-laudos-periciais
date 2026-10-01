import { FormEvent, useEffect, useState } from "react";
import { getInspectionReuseCandidates, reuseInspectionRecords, startSuccessorInspectionSession, type InspectionEnvelope, type ReuseCandidate } from "../data/inspectionSession";

const KIND_LABEL: Record<string, string> = {
  OBSERVATION: "Observação", MEASUREMENT: "Medição", PHOTO: "Fotografia",
  STATEMENT: "Declaração", ACCESS_OCCURRENCE: "Acesso", LIMITATION: "Limitação",
};

const key = (item: ReuseCandidate) => `${item.source_record_id}|${item.target_item_id}`;

// Sucessão da vistoria (#252, opção B estrita): a vistoria anterior continua no
// histórico; a nova nasce vazia e só recebe o que o perito escolher, registro a
// registro. O estado dos itens nunca é trazido.
export function InspectionSuccessionPanel({ workspaceId, envelope, disabled, onSaved }: { workspaceId: string; envelope: InspectionEnvelope; disabled: boolean; onSaved: (value: InspectionEnvelope) => void }) {
  const { snapshot, revision } = envelope;
  const [location, setLocation] = useState(snapshot.location_context);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<ReuseCandidate[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (snapshot.upstream_stale || disabled) return;
    const controller = new AbortController();
    getInspectionReuseCandidates(workspaceId, controller.signal).then(
      (value) => { if (!controller.signal.aborted && value.revision === revision) { setCandidates(value.candidates); setChosen(new Set()); } },
      () => { if (!controller.signal.aborted) setCandidates([]); },
    );
    return () => controller.abort();
  }, [workspaceId, revision, snapshot.upstream_stale, disabled]);

  if (snapshot.upstream_stale) {
    const start = async (event: FormEvent) => {
      event.preventDefault(); setBusy(true); setError(null);
      try { onSaved(await startSuccessorInspectionSession(workspaceId, revision, { responsible_professional: snapshot.responsible_professional, location_context: location, participant_references: [] })); }
      catch { setError("Não foi possível iniciar a nova vistoria. Confira se o planejamento atual está aprovado e tente novamente."); }
      finally { setBusy(false); }
    };
    return <section className="inspection-succession" aria-labelledby="inspection-succession-title">
      <h3 id="inspection-succession-title">Nova vistoria sobre o planejamento atual</h3>
      <p>Esta vistoria e todos os seus registros permanecem no histórico, sem alteração. A nova vistoria começa sem registros; em seguida você poderá escolher quais registros desta reaproveitar.</p>
      <form onSubmit={start}>
        <label>Local e contexto<input value={location} onChange={(event) => setLocation(event.target.value)} required disabled={busy || disabled}/></label>
        {error && <p role="alert">{error}</p>}
        <button className="primary-action" type="submit" disabled={busy || disabled || !location.trim()}>{busy ? "Iniciando…" : "Iniciar nova vistoria"}</button>
      </form>
    </section>;
  }
  // Ofertas de outra revisao (ou com edicao offline em curso) nao sao exibidas.
  if (disabled || !candidates.length) return null;
  const reuse = async () => {
    setBusy(true); setError(null);
    try {
      const selections = candidates.filter((item) => chosen.has(key(item))).map((item) => ({ source_record_id: item.source_record_id, target_item_id: item.target_item_id }));
      onSaved(await reuseInspectionRecords(workspaceId, revision, selections));
    } catch { setError("Não foi possível reaproveitar os registros. Reabra a vistoria e tente novamente."); }
    finally { setBusy(false); }
  };
  return <section className="inspection-succession" aria-labelledby="inspection-reuse-title">
    <h3 id="inspection-reuse-title">Registros da vistoria anterior</h3>
    <p>Só os registros marcados entram nesta vistoria, com data, conteúdo e foto originais. O estado dos itens não muda: cada item continua exigindo a sua conferência.</p>
    <ul className="inspection-reuse-list">{candidates.map((item) => <li key={key(item)}><label><input type="checkbox" checked={chosen.has(key(item))} disabled={busy || disabled} onChange={(event) => setChosen((current) => { const next = new Set(current); if (event.target.checked) next.add(key(item)); else next.delete(key(item)); return next; })}/><span><strong>{KIND_LABEL[item.record_kind] ?? item.record_kind}</strong> — {item.summary}</span><small>Para: {item.target_item_title}{item.captured_at ? ` · registrado em ${new Date(item.captured_at).toLocaleString("pt-BR")}` : ""}</small></label></li>)}</ul>
    {error && <p role="alert">{error}</p>}
    <button className="secondary-action" type="button" onClick={reuse} disabled={busy || disabled || chosen.size === 0}>{busy ? "Reaproveitando…" : "Reaproveitar selecionados"}</button>
  </section>;
}
