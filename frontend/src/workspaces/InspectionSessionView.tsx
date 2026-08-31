import { FormEvent, useEffect, useState } from "react";

import { getInspectionSession, InspectionSessionApiError, saveInspectionSession, startInspectionSession, uploadInspectionPhoto, type ExecutionState, type InspectionEnvelope, type InspectionSnapshot } from "../data/inspectionSession";
import { FieldMobileStatus } from "./FieldMobileStatus";

type State = { kind: "loading" } | { kind: "ready"; value: InspectionEnvelope } | { kind: "empty" } | { kind: "error" };
const stateLabel = { PENDING: "Pendente", COMPLETED: "Concluído", PARTIAL: "Execução parcial", NOT_EXECUTED: "Não executado", NOT_APPLICABLE: "Não aplicável", BLOCKED: "Bloqueado" } as const;

const recordId = (prefix: string) => `${prefix}-${crypto.randomUUID().replaceAll("-", "").toUpperCase()}`;
function withCoverage(snapshot: InspectionSnapshot): InspectionSnapshot {
  const count = (state: ExecutionState) => snapshot.items.filter((item) => item.state === state).length;
  const limitationIds = snapshot.limitations.map((item) => item.limitation_id);
  const incomplete = count("PENDING") + count("PARTIAL") + count("NOT_EXECUTED") + count("BLOCKED");
  return { ...snapshot, coverage: { total_items: snapshot.items.length, pending_items: count("PENDING"), completed_items: count("COMPLETED"), partial_items: count("PARTIAL"), not_executed_items: count("NOT_EXECUTED"), not_applicable_items: count("NOT_APPLICABLE"), blocked_items: count("BLOCKED"), complete: incomplete === 0 && limitationIds.length === 0, limitation_ids: limitationIds, reasons: incomplete || limitationIds.length ? ["Execução de campo ainda possui itens pendentes, parciais, bloqueados ou limitados."] : [] } };
}

export function InspectionSessionView({ workspaceId }: { workspaceId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [version, setVersion] = useState(0);
  const [responsible, setResponsible] = useState("");
  const [location, setLocation] = useState("");
  const [participants, setParticipants] = useState("");
  const [selectedItem, setSelectedItem] = useState<string | null>(null);
  const [itemState, setItemState] = useState<ExecutionState>("PENDING");
  const [note, setNote] = useState("");
  const [observation, setObservation] = useState("");
  const [observationType, setObservationType] = useState("DIRECT_OBSERVATION");
  const [statementSpeaker, setStatementSpeaker] = useState("");
  const [statementRole, setStatementRole] = useState("");
  const [statementText, setStatementText] = useState("");
  const [measurementQuantity, setMeasurementQuantity] = useState("");
  const [measurementValue, setMeasurementValue] = useState("");
  const [measurementUnit, setMeasurementUnit] = useState("");
  const [instrumentIdentity, setInstrumentIdentity] = useState("");
  const [instrumentModel, setInstrumentModel] = useState("");
  const [instrumentSerial, setInstrumentSerial] = useState("");
  const [instrumentCapability, setInstrumentCapability] = useState("");
  const [methodName, setMethodName] = useState("");
  const [methodProcedure, setMethodProcedure] = useState("");
  const [measurementRawObservation, setMeasurementRawObservation] = useState("");
  const [photoContentId, setPhotoContentId] = useState("");
  const [photoSha, setPhotoSha] = useState("");
  const [photoCaption, setPhotoCaption] = useState("");
  const [photoUploading, setPhotoUploading] = useState(false);
  const [limitation, setLimitation] = useState("");
  const [limitationKind, setLimitationKind] = useState("SCOPE_LIMITATION");
  const [accessOutcome, setAccessOutcome] = useState<"FULL_ACCESS" | "PARTIAL_ACCESS" | "DENIED" | "UNSAFE">("FULL_ACCESS");
  const [accessDescription, setAccessDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    getInspectionSession(workspaceId, controller.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error) => { if (!controller.signal.aborted) setState({ kind: error instanceof InspectionSessionApiError && error.kind === "not-found" ? "empty" : "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, version]);
  if (state.kind === "loading") return <section className="status-state status-state--loading" role="status"><span className="state-rule" aria-hidden="true"/><div><h2>Carregando vistoria</h2><p>Reabrindo registros de campo e suas proveniências.</p></div></section>;
  if (state.kind === "empty") {
    const start = async (event: FormEvent) => { event.preventDefault(); setSaving(true); setSaveError(false); try { const value = await startInspectionSession(workspaceId, { responsible_professional: responsible, location_context: location, participant_references: participants.split(",").map((item) => item.trim()).filter(Boolean) }); setState({ kind: "ready", value }); } catch { setSaveError(true); } finally { setSaving(false); } };
    return <section className="inspection-start"><h2>Vistoria ainda não registrada</h2><p>Inicie uma sessão somente quando o planejamento aprovado corresponder à diligência atual.</p><form onSubmit={start}><label>Profissional responsável<input value={responsible} onChange={(event) => setResponsible(event.target.value)} required/></label><label>Local e contexto<input value={location} onChange={(event) => setLocation(event.target.value)} required/></label><label>Participantes presentes (IDs separados por vírgula)<input value={participants} onChange={(event) => setParticipants(event.target.value)}/></label>{saveError && <p role="alert">Não foi possível iniciar. Confirme que há um planejamento aprovado e atual.</p>}<button className="primary-action" type="submit" disabled={saving}>{saving ? "Iniciando…" : "Iniciar sessão de vistoria"}</button></form></section>;
  }
  if (state.kind === "error") return <section className="status-state status-state--error" role="alert"><span className="state-mark" aria-hidden="true">!</span><div><h2>Não foi possível carregar a vistoria</h2><p>Verifique o serviço local e tente novamente.</p><button className="text-action" type="button" onClick={() => { setState({ kind: "loading" }); setVersion((value) => value + 1); }}>Tentar novamente</button></div></section>;
  const { snapshot } = state.value;
  const edit = snapshot.items.find((item) => item.item_id === selectedItem);
  const submitItem = async (event: FormEvent) => {
    event.preventDefault(); if (!edit) return; setSaving(true); setSaveError(false);
    const next = structuredClone(snapshot); const item = next.items.find((candidate) => candidate.item_id === edit.item_id)!;
    item.state = itemState; item.note = note.trim() || null;
    const locationId = (next.locations[0] as { location_id: string }).location_id; const now = new Date().toISOString();
    if (observation.trim()) { const id = recordId("OBS"); next.observations.push({ observation_id: id, inspection_item_id: item.item_id, observation_type: observationType, raw_observation: observation.trim(), location_id: locationId, timestamp: now, operator: next.responsible_professional, provenance: `Registro direto da sessão ${next.session_id}.` }); item.observation_ids.push(id); }
    const hasStatement = [statementSpeaker, statementRole, statementText].some((value) => value.trim());
    if (hasStatement && [statementSpeaker, statementRole, statementText].every((value) => value.trim())) (next.statements as object[]).push({ statement_id: recordId("STATEMENT"), inspection_item_id: item.item_id, observation_type: "PARTY_STATEMENT_ON_SITE", speaker: statementSpeaker.trim(), declared_role: statementRole.trim(), verbatim_or_summary: statementText.trim(), capture_kind: "SUMMARY", timestamp: now, provenance: `Declaração registrada na sessão ${next.session_id}; não confirmada como fato.` });
    else if (hasStatement) { setSaveError(true); setSaving(false); return; }
    const measurementFields = [measurementQuantity, measurementValue, measurementUnit, instrumentIdentity, instrumentModel, instrumentSerial, instrumentCapability, methodName, methodProcedure, measurementRawObservation];
    const hasMeasurement = measurementFields.some((value) => value.trim());
    if (hasMeasurement && measurementFields.every((value) => value.trim())) { const id = recordId("MEASUREMENT"); const instrumentId = recordId("INSTRUMENT"); const methodId = recordId("METHOD"); (next.instruments as object[]).push({ instrument_id: instrumentId, identity: instrumentIdentity.trim(), model: instrumentModel.trim(), serial_number: instrumentSerial.trim(), capability: instrumentCapability.trim(), calibration_claimed: false, certificate_reference: null }); (next.instrument_statuses as object[]).push({ status_id: recordId("INSTRUMENT-STATUS"), instrument_id: instrumentId, status: "NOT_CLAIMED", checked_at: now, evidence_reference: "Nenhuma alegação de calibração foi registrada." }); (next.methods as object[]).push({ method_id: methodId, name: methodName.trim(), procedure: methodProcedure.trim(), provenance: `Método informado pelo profissional na sessão ${next.session_id}.` }); next.measurements.push({ measurement_id: id, inspection_item_id: item.item_id, quantity: measurementQuantity.trim(), raw_value: measurementValue.trim(), raw_unit: measurementUnit.trim(), normalized_value: null, normalized_unit: null, instrument_id: instrumentId, method_id: methodId, location_id: locationId, timestamp: now, operator: next.responsible_professional, uncertainty: null, raw_observation: measurementRawObservation.trim(), provenance: `Registro bruto da sessão ${next.session_id}.` }); item.measurement_ids.push(id); }
    else if (hasMeasurement) { setSaveError(true); setSaving(false); return; }
    if (photoContentId.trim() && photoSha.trim() && photoCaption.trim()) { const id = recordId("PHOTO"); next.photos.push({ photo_id: id, inspection_item_id: item.item_id, private_content_id: photoContentId.trim(), original_sha256: photoSha.trim(), reliable_capture_timestamp: null, capture_timestamp_reliability: "UNVERIFIED", location_id: locationId, caption: photoCaption.trim(), device: "NÃO INFORMADO", provenance: "Original privado indicado pelo profissional." }); item.photo_ids.push(id); }
    if (limitation.trim()) { const id = recordId("LIMIT"); next.limitations.push({ limitation_id: id, inspection_item_id: item.item_id, kind: limitationKind, description: limitation.trim(), consequence_for_coverage: "A limitação exige consideração na cobertura da vistoria.", provenance: `Registro da sessão ${next.session_id}.` }); item.limitation_ids.push(id); }
    if (accessDescription.trim()) next.access_occurrences.push({ occurrence_id: recordId("ACCESS"), inspection_item_id: item.item_id, outcome: accessOutcome, description: accessDescription.trim(), timestamp: now });
    if (itemState !== "PENDING" && !note.trim()) { setSaveError(true); setSaving(false); return; }
    if (["PARTIAL", "NOT_EXECUTED", "BLOCKED"].includes(itemState) && item.limitation_ids.length === 0) { setSaveError(true); setSaving(false); return; }
    try { const value = await saveInspectionSession(workspaceId, state.value.revision, withCoverage(next)); setState({ kind: "ready", value }); setSelectedItem(null); setObservation(""); setStatementSpeaker(""); setStatementRole(""); setStatementText(""); setMeasurementQuantity(""); setMeasurementValue(""); setMeasurementUnit(""); setInstrumentIdentity(""); setInstrumentModel(""); setInstrumentSerial(""); setInstrumentCapability(""); setMethodName(""); setMethodProcedure(""); setMeasurementRawObservation(""); setPhotoContentId(""); setPhotoSha(""); setPhotoCaption(""); setLimitation(""); } catch { setSaveError(true); } finally { setSaving(false); }
  };
  return <section className="inspection-workspace" aria-labelledby="inspection-title">
    <FieldMobileStatus
      online={typeof navigator === "undefined" ? true : navigator.onLine}
      pendingCaptures={0}
      conflicts={snapshot.upstream_stale_reasons.map((message) => ({ code: "STALE_PLAN", message }))}
      onCapture={() => { const firstPending = snapshot.items.find((item) => item.state === "PENDING") ?? snapshot.items[0]; if (firstPending) { setSelectedItem(firstPending.item_id); setItemState(firstPending.state); setNote(firstPending.note ?? ""); } }}
    />
    {edit && <section className="inspection-editor inspection-editor--access" aria-label="Resultado de acesso"><h3>Resultado de acesso</h3><p>Somente acesso integral sustenta a conclusÃ£o de um requisito de acesso.</p><label>Resultado<select value={accessOutcome} onChange={(event) => setAccessOutcome(event.target.value as typeof accessOutcome)}><option value="FULL_ACCESS">Acesso integral</option><option value="PARTIAL_ACCESS">Acesso parcial</option><option value="DENIED">Acesso negado</option><option value="UNSAFE">Acesso inseguro</option></select></label><label>DescriÃ§Ã£o objetiva<textarea value={accessDescription} onChange={(event) => setAccessDescription(event.target.value)}/></label></section>}
    <header className="planning-overview"><div><h2 id="inspection-title">Vistoria de campo</h2><p>Registros brutos executados contra a revisão {snapshot.plan_snapshot.planning_revision} do plano. Evidências candidatas não são constatações técnicas.</p></div><div className="planning-readiness"><strong>{snapshot.coverage.complete ? "Execução coberta" : "Execução parcial"}</strong><span>{snapshot.coverage.completed_items} de {snapshot.coverage.total_items} itens concluídos</span></div></header>
    {snapshot.upstream_stale && <section className="analysis-inventory-warning" role="alert"><strong>Planejamento alterado — não continue esta sessão</strong><ul>{snapshot.upstream_stale_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></section>}
    {snapshot.coverage.reasons.length > 0 && <ul className="planning-reasons">{snapshot.coverage.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
    <section className="planning-section"><h3>Itens executados</h3><ol className="inspection-items">{snapshot.items.map((item) => {
      const observations = snapshot.observations.filter((record) => record.inspection_item_id === item.item_id);
      const statements = snapshot.statements.filter((record) => record.inspection_item_id === item.item_id);
      const measurements = snapshot.measurements.filter((record) => record.inspection_item_id === item.item_id);
      const photos = snapshot.photos.filter((record) => record.inspection_item_id === item.item_id);
      const limitations = snapshot.limitations.filter((record) => record.inspection_item_id === item.item_id);
      const candidates = snapshot.evidence_candidates.filter((record) => record.inspection_item_id === item.item_id);
      return <li className="inspection-item" key={item.item_id}><header><div><strong>{item.title}</strong><span>{stateLabel[item.state]}</span></div><div><code>{item.planning_item_id}</code><button className="text-action" type="button" onClick={() => { setSelectedItem(item.item_id); setItemState(item.state); setNote(item.note ?? ""); setSaveError(false); }}>Registrar campo</button></div></header>{item.note && <p>{item.note}</p>}
        {observations.length > 0 && <div><h4>Observações brutas</h4><ul>{observations.map((record) => <li key={record.observation_id}><strong>{record.observation_type}</strong> · {record.raw_observation}<small>{record.location_id} · {record.timestamp} · {record.provenance}</small></li>)}</ul></div>}
        {statements.length > 0 && <div><h4>Declarações em campo</h4><ul>{statements.map((record) => <li key={record.statement_id}><strong>Declaração da parte — não é observação pericial</strong><p>{record.verbatim_or_summary}</p><small>{record.speaker} · {record.declared_role} · {record.provenance}</small></li>)}</ul></div>}
        {measurements.length > 0 && <div><h4>Medições</h4><ul>{measurements.map((record) => <li key={record.measurement_id}><strong>{record.raw_value} {record.raw_unit}</strong>{record.normalized_value && <span> · normalizado: {record.normalized_value} {record.normalized_unit}</span>}<small>{record.quantity} · {record.instrument_id} · {record.method_id} · {record.uncertainty ?? "incerteza não informada"} · {record.provenance}</small></li>)}</ul></div>}
        {photos.length > 0 && <div><h4>Fotografias</h4><ul>{photos.map((record) => <li key={record.photo_id}><strong>{record.caption}</strong><small>Original privado · SHA-256 {record.original_sha256} · {record.private_content_id} · {record.device}</small></li>)}</ul></div>}
        {limitations.length > 0 && <div className="inspection-limitations"><h4>Limitações</h4><ul>{limitations.map((record) => <li key={record.limitation_id}><strong>{record.kind}</strong><p>{record.description}</p><small>{record.consequence_for_coverage}</small></li>)}</ul></div>}
        {candidates.length > 0 && <div><h4>Evidências candidatas</h4><ul>{candidates.map((record) => <li key={record.candidate_id}><strong>Candidato a análise técnica futura — não é achado</strong><p>{record.description}</p><small>{record.source_record_ids.join(" · ")} · {record.provenance}</small></li>)}</ul></div>}
      </li>;
    })}</ol></section>
    {edit && <section className="inspection-editor inspection-editor--measurement" aria-label="Proveniência completa da medição"><h3>Dados materiais da medição</h3><p>Obrigatórios quando qualquer campo de medição for iniciado; não são inferidos pelo sistema.</p><label>Capacidade ou faixa do instrumento<input value={instrumentCapability} onChange={(event) => setInstrumentCapability(event.target.value)}/></label><label>Procedimento efetivamente aplicado<textarea value={methodProcedure} onChange={(event) => setMethodProcedure(event.target.value)}/></label><label>Observação bruta da leitura<textarea value={measurementRawObservation} onChange={(event) => setMeasurementRawObservation(event.target.value)}/></label></section>}
    {edit && <section className="inspection-editor inspection-editor--semantic" aria-label="Classificação semântica dos registros"><label>Tipo explícito da observação<select value={observationType} onChange={(event) => setObservationType(event.target.value)}><option value="DIRECT_OBSERVATION">Observação direta</option><option value="MEASURED_VALUE">Valor medido</option><option value="DOCUMENT_PRESENTED_ON_SITE">Documento apresentado no local</option><option value="ENVIRONMENTAL_CONDITION">Condição ambiental</option><option value="ACCESS_LIMITATION">Limitação de acesso</option><option value="PROFESSIONAL_NOTE">Nota profissional</option></select></label><fieldset><legend>Declaração de parte no local</legend><label>Declarante<input value={statementSpeaker} onChange={(event) => setStatementSpeaker(event.target.value)}/></label><label>Papel declarado<input value={statementRole} onChange={(event) => setStatementRole(event.target.value)}/></label><label>Resumo fiel da declaração<textarea value={statementText} onChange={(event) => setStatementText(event.target.value)}/></label></fieldset><label>Tipo de limitação<select value={limitationKind} onChange={(event) => setLimitationKind(event.target.value)}><option value="INACCESSIBLE_AREA">Área inacessível</option><option value="IMPOSSIBLE_MEASUREMENT">Medição impossível</option><option value="EQUIPMENT_UNAVAILABLE">Equipamento indisponível</option><option value="ENVIRONMENTAL_CONDITION">Condição ambiental</option><option value="PARTY_ABSENCE">Ausência de parte</option><option value="DOCUMENT_UNAVAILABLE">Documento indisponível</option><option value="UNSAFE_CONDITION">Condição insegura</option><option value="SCOPE_LIMITATION">Limitação de escopo</option><option value="ACCESS_LIMITATION">Limitação de acesso</option></select></label></section>}
    {edit && <section className="inspection-editor" aria-labelledby="inspection-editor-title"><h3 id="inspection-editor-title">Registrar campo — {edit.title}</h3><p>Preencha somente o que foi efetivamente observado ou produzido. Campos vazios não geram registros.</p><form onSubmit={submitItem}><label>Estado de execução<select value={itemState} onChange={(event) => setItemState(event.target.value as ExecutionState)}><option value="PENDING">Pendente</option><option value="COMPLETED">Concluído</option><option value="PARTIAL">Parcial</option><option value="NOT_EXECUTED">Não executado</option><option value="NOT_APPLICABLE">Não aplicável</option><option value="BLOCKED">Bloqueado</option></select></label><label>Nota profissional<textarea value={note} onChange={(event) => setNote(event.target.value)}/></label><fieldset><legend>Observação direta</legend><label>Descrição bruta<textarea value={observation} onChange={(event) => setObservation(event.target.value)}/></label></fieldset><fieldset><legend>Medição bruta</legend><label>Grandeza<input value={measurementQuantity} onChange={(event) => setMeasurementQuantity(event.target.value)}/></label><label>Valor bruto<input value={measurementValue} onChange={(event) => setMeasurementValue(event.target.value)}/></label><label>Unidade bruta<input value={measurementUnit} onChange={(event) => setMeasurementUnit(event.target.value)}/></label><label>Identidade do instrumento<input value={instrumentIdentity} onChange={(event) => setInstrumentIdentity(event.target.value)}/></label><label>Modelo do instrumento<input value={instrumentModel} onChange={(event) => setInstrumentModel(event.target.value)}/></label><label>Número de série<input value={instrumentSerial} onChange={(event) => setInstrumentSerial(event.target.value)}/></label><label>Método aplicado<input value={methodName} onChange={(event) => setMethodName(event.target.value)}/></label></fieldset><fieldset><legend>Fotografia original privada</legend><label>Arquivo JPEG ou PNG<input type="file" accept="image/jpeg,image/png" disabled={photoUploading} onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; setPhotoUploading(true); setSaveError(false); try { const stored = await uploadInspectionPhoto(workspaceId, file); setPhotoContentId(stored.contentId); setPhotoSha(stored.sha256); } catch { setSaveError(true); } finally { setPhotoUploading(false); } }}/></label>{photoContentId && <p>Original preservado: {photoContentId} · SHA-256 {photoSha}</p>}<label>Legenda objetiva<input value={photoCaption} onChange={(event) => setPhotoCaption(event.target.value)}/></label></fieldset><fieldset><legend>Limitação de campo</legend><label>Descrição e alcance<textarea value={limitation} onChange={(event) => setLimitation(event.target.value)}/></label></fieldset>{saveError && <p role="alert">Não foi possível salvar. Complete todos os campos de uma medição iniciada e confira os vínculos e o original privado.</p>}<div className="planning-review__actions"><button className="primary-action" type="submit" disabled={saving || photoUploading}>{saving ? "Salvando…" : "Salvar registros de campo"}</button><button className="text-action" type="button" onClick={() => setSelectedItem(null)} disabled={saving || photoUploading}>Cancelar</button></div></form></section>}
  </section>;
}
