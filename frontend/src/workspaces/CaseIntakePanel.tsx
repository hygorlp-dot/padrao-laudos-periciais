import { useState } from "react";
import { acceptCaseQuestions, CASE_ANALYSIS_TEXT_MAX, confirmDocumentInventory, getCaseIntake, type CaseAnalysisEnvelope, type CaseIntake, type InventoryDecision, type InventoryProposal, type QuestionOrigin } from "../data/caseAnalysis";
import { questionOriginLabel } from "../ui/labels";

// Mesma identidade que o servidor usa para nao duplicar: a evidencia literal (numero,
// paginas, trecho e metodo). A origem fica de fora porque e decisao do perito no aceite.
function sameQuestionEvidence(stored: CaseIntake["questions"][number]["source"] | null | undefined, proposed: CaseIntake["questions"][number]["source"]) {
  return !!stored && stored.original_number === proposed.original_number && stored.page_start === proposed.page_start && stored.page_end === proposed.page_end && stored.excerpt === proposed.excerpt && stored.method === proposed.method;
}

function InventoryRow({ proposal, workspaceId, envelope, onSaved }: { proposal: InventoryProposal; workspaceId: string; envelope: CaseAnalysisEnvelope; onSaved: (value: CaseAnalysisEnvelope) => void }) {
  const current = envelope.snapshot.document_inventory?.find((v) => v.category === proposal.category);
  const [status, setStatus] = useState<InventoryDecision["status"] | "">("");
  const [sources, setSources] = useState(proposal.matches.map((v) => v.document_id));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  return <details className="analysis-section"><summary>{proposal.label} · {current ? current.status === "PROFESSIONALLY_CONFIRMED_PRESENT" ? "presença confirmada pelo perito" : "ausência confirmada pelo perito" : proposal.matches.length ? "documento candidato localizado" : "não encontrado no material importado"}</summary>
    {current && <p>{current.reason}</p>}
    {proposal.matches.map((source) => <p key={`${source.document_id}:${source.page}`}>{String(envelope.snapshot.documents.find((d) => d.document_id === source.document_id)?.raw_type ?? "Documento")} · página {source.page} · {source.excerpt}</p>)}
    {!proposal.matches.length && <p>A busca não identificou um documento candidato. Isso não comprova ausência nos autos.</p>}
    <form className="analysis-form" onSubmit={async (event) => { event.preventDefault(); if (!status) return; setBusy(true); setError(false); try { onSaved(await confirmDocumentInventory(workspaceId, envelope.revision, { category: proposal.category, status, source_document_ids: status === "PROFESSIONALLY_CONFIRMED_PRESENT" ? sources : [], reason })); } catch { setError(true); } finally { setBusy(false); } }}>
      <label>Resultado da conferência<select required value={status} disabled={busy} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="">Selecione após conferir</option><option value="PROFESSIONALLY_CONFIRMED_PRESENT">Confirmo documento presente</option><option value="PROFESSIONALLY_CONFIRMED_ABSENT_FROM_CASE">Confirmo ausência após conferir os autos</option></select></label>
      {status === "PROFESSIONALLY_CONFIRMED_PRESENT" && <fieldset><legend>Documentos que comprovam a presença</legend>{envelope.snapshot.documents.filter((d) => d.content_available).map((d) => <label className="checkbox-label" key={String(d.document_id)}><input type="checkbox" checked={sources.includes(String(d.document_id))} disabled={busy} onChange={(e) => setSources((prior) => e.target.checked ? [...prior, String(d.document_id)] : prior.filter((v) => v !== d.document_id))}/>{String(d.raw_type)} · {String(d.page_count_or_span)}</label>)}</fieldset>}
      <label>Fundamentação da conferência<textarea required maxLength={CASE_ANALYSIS_TEXT_MAX} value={reason} disabled={busy} onChange={(e) => setReason(e.target.value)}/></label>
      {error && <p role="alert">Não foi possível confirmar. Confira o perfil profissional e a versão atual da análise.</p>}
      <button className="authority-action" type="submit" disabled={busy || !status || !reason.trim() || (status === "PROFESSIONALLY_CONFIRMED_PRESENT" && sources.length === 0)}>{busy ? "Confirmando…" : "Confirmar situação do documento"}</button>
    </form>
  </details>;
}

export function CaseIntakePanel({ workspaceId, envelope, onSaved }: { workspaceId: string; envelope: CaseAnalysisEnvelope; onSaved: (value: CaseAnalysisEnvelope) => void }) {
  const [intake, setIntake] = useState<CaseIntake | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  // Origem confirmada pelo perito para cada quesito marcado (pre-preenchida com a proposta).
  const [origins, setOrigins] = useState<Record<string, QuestionOrigin>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const stale = envelope.snapshot.source_inventory_stale || envelope.snapshot.stale_document_ids.length > 0;
  return <details className="analysis-section"><summary>Importar quesitos e conferir documentos usuais</summary>
    <p>A busca local propõe trechos dos documentos importados. O texto e a numeração dos quesitos permanecem como estão na fonte; a revisão profissional continua na análise.</p>
    <button className="text-action" type="button" disabled={busy || stale} onClick={async () => { setBusy(true); setError(false); try { const value = await getCaseIntake(workspaceId); if (value.revision !== envelope.revision) throw new Error("stale"); setIntake(value); } catch { setError(true); } finally { setBusy(false); } }}>{busy ? "Lendo documentos locais…" : "Buscar nos documentos importados"}</button>
    {error && <p role="alert">Não foi possível consultar ou aplicar as fontes. Reabra a análise para conferir a versão atual.</p>}
    {intake && <>
      <h3>Quesitos encontrados</h3>
      {!intake.questions.length ? <p>Nenhum bloco numerado com origem explícita foi identificado. A ausência de resultado não comprova que o processo não tenha quesitos.</p> : <p>Confira com os autos: só são propostos blocos numerados sob um título de quesitos com origem explícita, e trechos muito longos ficam de fora. Quesitos ausentes desta lista podem ser adicionados manualmente.</p>}
      {intake.questions.map((q) => { const exists = envelope.snapshot.questions.some((item) => item.text === q.text && sameQuestionEvidence(item.source_question, q.source) && item.provenance.some((p) => p.source_document_id === q.document_id)); const checked = !exists && selected.includes(q.proposal_id); return <div className="analysis-section" key={q.proposal_id}>
        <label className="checkbox-label"><input type="checkbox" disabled={busy || exists} checked={exists || selected.includes(q.proposal_id)} onChange={(e) => setSelected((prior) => e.target.checked ? [...prior, q.proposal_id] : prior.filter((v) => v !== q.proposal_id))}/>{questionOriginLabel(q.source.origin)} · quesito {q.source.original_number}{exists ? " · já adicionado" : ""}</label>
        {q.section_heading && <p className="field-hint">Origem sugerida pelo título “{q.section_heading}”{q.section_page ? ` (página ${q.section_page})` : ""}</p>}
        {checked && <label>Origem do quesito (confirme com os autos)<select value={origins[q.proposal_id] ?? q.source.origin} disabled={busy} onChange={(e) => setOrigins((prior) => ({ ...prior, [q.proposal_id]: e.target.value as QuestionOrigin }))}><option value="COURT">{questionOriginLabel("COURT")}</option><option value="CLAIMANT">{questionOriginLabel("CLAIMANT")}</option><option value="DEFENDANT">{questionOriginLabel("DEFENDANT")}</option></select></label>}
        <p style={{ whiteSpace: "pre-wrap" }}>{q.text}</p>
        {q.context_after && <p className="field-hint">Segue no documento: <span style={{ whiteSpace: "pre-wrap" }}>{q.context_after}</span></p>}
        <details><summary>Ver trecho original · página {q.source.page_start}{q.source.page_end !== q.source.page_start ? `–${q.source.page_end}` : ""}</summary><p>{String(envelope.snapshot.documents.find((d) => d.document_id === q.document_id)?.raw_type ?? "Documento")} · {q.source.method.includes("OCR") ? "Leitura local por OCR" : "Texto do PDF"}</p><p style={{ whiteSpace: "pre-wrap" }}>{q.source.excerpt}</p></details>
      </div>; })}
      {intake.questions.length > 0 && <button className="primary-action" type="button" disabled={busy || selected.length === 0 || stale} onClick={async () => { setBusy(true); setError(false); try { const updated = await acceptCaseQuestions(workspaceId, envelope.revision, selected.map((id) => ({ proposal_id: id, origin: origins[id] ?? intake.questions.find((q) => q.proposal_id === id)!.source.origin }))); setSelected([]); setOrigins({}); onSaved(updated); } catch { setError(true); } finally { setBusy(false); } }}>Adicionar quesitos selecionados à análise</button>}
      <h3>Documentos usuais</h3>{intake.inventory.map((proposal) => <InventoryRow key={`${proposal.category}:${envelope.revision}`} proposal={proposal} workspaceId={workspaceId} envelope={envelope} onSaved={onSaved}/>)}
    </>}
  </details>;
}
