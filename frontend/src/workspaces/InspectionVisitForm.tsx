import { useState, type FormEvent } from "react";
import { confirmInspectionVisit, type InspectionEnvelope, type VisitValues } from "../data/inspectionSession";
import { getProcessCase } from "../data/processCase";
import { getPropertyRecord } from "../data/propertyRecord";

const empty: VisitValues = { date: "", start_time: "", end_time: null, weather: null, temperature_c: null, relative_humidity_percent: null, attendants: [] };

export function PropertyAddressReuse({ workspaceId, onSelect }: { workspaceId: string; onSelect: (address: string) => void }) {
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  return <><button className="text-action" type="button" disabled={busy} onClick={async () => {
    setBusy(true); setError(false);
    try {
      const property = await getPropertyRecord(workspaceId);
      const address = ["street", "number", "complement", "unit", "block", "quadra", "neighborhood", "city", "state", "postal_code"].map((field) => property.record.values.find((v) => v.field === field)?.value).filter(Boolean).join(", ");
      if (!address) throw new Error("missing address");
      onSelect(address);
    } catch { setError(true); } finally { setBusy(false); }
  }}>{busy ? "Consultando imóvel…" : "Usar endereço confirmado do imóvel"}</button>{error && <p role="alert">O endereço confirmado não está disponível. Complete o cadastro do imóvel ou informe o local observado.</p>}</>;
}

export function InspectionVisitForm({ workspaceId, envelope, disabled, onSaved }: { workspaceId: string; envelope: InspectionEnvelope; disabled: boolean; onSaved: (value: InspectionEnvelope) => void }) {
  const captured = envelope.snapshot.visit_context;
  const [values, setValues] = useState<VisitValues>(() => captured ? { date: captured.date, start_time: captured.start_time, end_time: captured.end_time, weather: captured.weather, temperature_c: captured.temperature_c, relative_humidity_percent: captured.relative_humidity_percent, attendants: captured.attendants } : empty);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [candidates, setCandidates] = useState<{ name: string; role: string }[]>([]);
  const [candidateError, setCandidateError] = useState(false);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const set = (name: keyof Omit<VisitValues, "attendants">, value: string) => setValues((prior) => ({ ...prior, [name]: value || null }));
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(false);
    try { onSaved(await confirmInspectionVisit(workspaceId, envelope.revision, values)); }
    catch { setError(true); } finally { setBusy(false); }
  };
  const add = (person: { name: string; role: string }) => setValues((prior) => ({ ...prior, attendants: [...prior.attendants, { ...person, presence_confirmed: false }] }));
  return <details className="analysis-section"><summary>Dados da diligência{captured ? ` · ${captured.date.split("-").reverse().join("/")} às ${captured.start_time}` : " · ainda não informados"}</summary>
    <p>Registre quando a vistoria ocorreu e quem esteve presente. Estes dados serão reutilizados no laudo.</p>
    {disabled ? <p>Retome a sessão atual no serviço local para confirmar os dados da diligência.</p> : <form className="analysis-form visit-context-form" onSubmit={submit}>
      <label>Data da vistoria<input type="date" required value={values.date ?? ""} onChange={(e) => set("date", e.target.value)} disabled={busy}/></label>
      <label>Hora de início<input type="time" required value={values.start_time ?? ""} onChange={(e) => set("start_time", e.target.value)} disabled={busy}/></label>
      <label>Hora de término (mesmo dia)<input type="time" value={values.end_time ?? ""} onChange={(e) => set("end_time", e.target.value)} disabled={busy}/></label>
      <label>Clima observado<input value={values.weather ?? ""} onChange={(e) => set("weather", e.target.value)} disabled={busy}/></label>
      <label>Temperatura medida (°C)<input inputMode="decimal" value={values.temperature_c ?? ""} onChange={(e) => set("temperature_c", e.target.value)} disabled={busy}/></label>
      <label>Umidade relativa medida (%)<input inputMode="decimal" value={values.relative_humidity_percent ?? ""} onChange={(e) => set("relative_humidity_percent", e.target.value)} disabled={busy}/></label>
      <fieldset><legend>Pessoas presentes</legend><button type="button" className="text-action" disabled={busy || loadingCandidates} onClick={async () => {
        setLoadingCandidates(true); setCandidateError(false);
        const sources = await Promise.allSettled([getProcessCase(workspaceId), getPropertyRecord(workspaceId)]);
        const people: { name: string; role: string }[] = [];
        if (sources[0].status === "fulfilled") for (const [field, role] of [["parte_requerente", "Parte autora"], ["parte_requerida", "Parte ré"]] as const) { const name = sources[0].value.data[field]; if (name.trim()) people.push({ name, role }); }
        if (sources[1].status === "fulfilled") { const name = sources[1].value.record.values.find((v) => v.field === "owner")?.value; if (name) people.push({ name, role: "Proprietário" }); }
        setCandidates(people); setCandidateError(sources.some((r) => r.status === "rejected")); setLoadingCandidates(false);
      }}>{loadingCandidates ? "Consultando…" : "Consultar nomes do processo e do imóvel"}</button>
      {candidateError && <p role="alert">Algumas fontes não puderam ser consultadas. Os nomes disponíveis abaixo não confirmam presença.</p>}
      {candidates.map((person) => <button type="button" className="text-action" key={`${person.role}:${person.name}`} disabled={busy || values.attendants.some((v) => v.name === person.name && v.role === person.role)} onClick={() => add(person)}>Adicionar {person.name} · {person.role}</button>)}
      {values.attendants.map((person, index) => <div className="visit-attendant" key={index}>
        <label>Nome da pessoa<input required value={person.name} disabled={busy} onChange={(e) => setValues((prior) => ({ ...prior, attendants: prior.attendants.map((p, i) => i === index ? { ...p, name: e.target.value, presence_confirmed: false } : p) }))}/></label>
        <label>Papel na diligência<input required value={person.role} disabled={busy} onChange={(e) => setValues((prior) => ({ ...prior, attendants: prior.attendants.map((p, i) => i === index ? { ...p, role: e.target.value, presence_confirmed: false } : p) }))}/></label>
        <label className="checkbox-label"><input type="checkbox" required checked={person.presence_confirmed} disabled={busy} onChange={(e) => setValues((prior) => ({ ...prior, attendants: prior.attendants.map((p, i) => i === index ? { ...p, presence_confirmed: e.target.checked } : p) }))}/>Confirmo que esteve presente</label>
        <button type="button" className="text-action" disabled={busy} onClick={() => setValues((prior) => ({ ...prior, attendants: prior.attendants.filter((_p, i) => i !== index) }))}>Remover pessoa</button>
      </div>)}
      <button type="button" className="text-action" disabled={busy} onClick={() => add({ name: "", role: "" })}>Adicionar outra pessoa</button></fieldset>
      {error && <p role="alert">Não foi possível confirmar. Confira data, horários, medições e presença; se a versão mudou, reabra a vistoria.</p>}
      <button type="submit" className="authority-action" disabled={busy}>{busy ? "Confirmando…" : "Confirmar dados da diligência"}</button>
      {captured && <p>Confirmado pelo perito. Alterações exigem nova revisão do conteúdo dependente.</p>}
    </form>}
  </details>;
}
