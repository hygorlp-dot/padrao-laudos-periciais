import { useState, type FormEvent } from "react";
import type { ProfessionalReportCapture, ReportSnapshot } from "../data/reportSnapshot";

const detailFields = [
  ["action_type", "Tipo de ação"], ["protocol_opening", "Apresentação protocolar"],
  ["qualification", "Qualificação"], ["preamble", "Preâmbulo"], ["objective", "Objetivo"],
  ["definitions", "Definições"], ["classification_framework", "Classificações adotadas"],
  ["conditions", "Condições da vistoria"], ["city", "Local do encerramento"],
  ["report_date", "Data do laudo"], ["closing", "Encerramento"],
] as const;
const repairFields = [
  ["group", "Grupo"], ["item", "Item"], ["source", "Fonte de preços"], ["code", "Código"],
  ["description", "Serviço"], ["unit", "Unidade"], ["quantity", "Quantidade"],
  ["memory", "Memória de cálculo"], ["unit_cost", "Custo unitário"], ["bdi_percent", "BDI (%)"],
  ["unit_price", "Preço unitário"], ["total", "Total do item"],
] as const;
type Values = Omit<ProfessionalReportCapture, "sources">;

export function ReportProfessionalPresentation({ capture, figures, pathologies, editable, busy, save }: {
  capture: ProfessionalReportCapture; figures: NonNullable<ReportSnapshot["figures"]>;
  pathologies: Array<{ id: string; label: string }>; editable: boolean; busy: boolean;
  save: (values: Values) => void;
}) {
  const [details, setDetails] = useState(capture.details);
  const [sheets, setSheets] = useState(capture.sheet_figures);
  const [budget, setBudget] = useState(capture.repair_budget);
  function submit(event: FormEvent) {
    event.preventDefault();
    save({ details: Object.fromEntries(detailFields.map(([key]) => [key, details[key]?.trim() || null])), repair_budget: budget, sheet_figures: sheets });
  }
  return <details className="analysis-section report-professional-presentation"><summary>Apresentação profissional do documento</summary>
    <p>Estes dados compõem o Word desta revisão. Preencha apenas o que foi fornecido e conferido. A identidade gráfica usa os assets configurados pelo usuário.</p>
    <form className="analysis-form" onSubmit={submit}>
      <fieldset disabled={!editable || busy}><legend>Texto do documento</legend>
        {detailFields.map(([key, label]) => <label key={key}>{label}{key === "report_date" ? <input type="date" value={details[key] ?? ""} onChange={(e) => setDetails({ ...details, [key]: e.target.value })} /> : <textarea rows={key === "city" || key === "action_type" ? 1 : 3} value={details[key] ?? ""} onChange={(e) => setDetails({ ...details, [key]: e.target.value })} />}</label>)}
      </fieldset>
      <fieldset disabled={!editable || busy}><legend>Fotografia e mini-planta de cada ficha</legend>
        <p>A seleção é explícita. A fotografia deve estar vinculada à manifestação na vistoria; o backend confere essa origem.</p>
        {pathologies.map((pat) => {
          const selected = sheets.find((row) => row.pat_id === pat.id);
          function change(role: "photo_figure_id" | "plan_figure_id", value: string) {
            const updated = { pat_id: pat.id, photo_figure_id: selected?.photo_figure_id ?? null, plan_figure_id: selected?.plan_figure_id ?? null, [role]: value || null };
            setSheets([...sheets.filter((row) => row.pat_id !== pat.id), updated].filter((row) => row.photo_figure_id || row.plan_figure_id));
          }
          return <div key={pat.id}><strong>{pat.label}</strong>{(["photo_figure_id", "plan_figure_id"] as const).map((role) => <label key={role}>{role === "photo_figure_id" ? "Fotografia" : "Mini-planta"}<select value={selected?.[role] ?? ""} onChange={(e) => change(role, e.target.value)}><option value="">Não fornecida</option>{figures.map((f) => <option key={f.figure_id} value={f.figure_id}>{f.caption}</option>)}</select></label>)}</div>;
        })}
        {pathologies.length === 0 && <p>Nenhuma manifestação aprovada disponível para compor fichas.</p>}
      </fieldset>
      <details><summary>Orçamento analítico de reparos</summary>
        <p>Valores e memória são fornecidos pelo perito. O backend confere os totais e a elegibilidade de cada manifestação. Honorários e despesas não entram nesta tabela.</p>
        <fieldset disabled={!editable || busy}><legend>Dados de reparos</legend>
          <label className="report-repair-toggle"><input type="checkbox" checked={budget !== null} onChange={(e) => setBudget(e.target.checked ? { competence: "", regime: "", observations: "", bdi_memory: "", lines: [] } : null)} />Incluir orçamento de reparos nesta revisão</label>
          {budget && <>
            {([["competence", "Competência da fonte"], ["regime", "Regime de preços"], ["observations", "Observações"], ["bdi_memory", "Memória do BDI"]] as const).map(([key, label]) => <label key={key}>{label}<textarea value={budget[key]} onChange={(e) => setBudget({ ...budget, [key]: e.target.value })} /></label>)}
            {budget.lines.map((line, index) => <fieldset key={index}><legend>Serviço {index + 1}</legend>
              <label>Manifestação vinculada<select value={line.pat_id} onChange={(e) => setBudget({ ...budget, lines: budget.lines.map((v, i) => i === index ? { ...v, pat_id: e.target.value } : v) })}><option value="">Selecione</option>{pathologies.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
              {repairFields.map(([key, label]) => <label key={key}>{label}<input value={line[key]} onChange={(e) => setBudget({ ...budget, lines: budget.lines.map((v, i) => i === index ? { ...v, [key]: e.target.value } : v) })} /></label>)}
              <button type="button" className="text-action" onClick={() => setBudget({ ...budget, lines: budget.lines.filter((_, i) => i !== index) })}>Retirar serviço {index + 1}</button>
            </fieldset>)}
            <button type="button" className="text-action" onClick={() => setBudget({ ...budget, lines: [...budget.lines, { pat_id: "", group: "", item: "", source: "", code: "", description: "", unit: "", quantity: "", memory: "", unit_cost: "", bdi_percent: "", unit_price: "", total: "" }] })}>Adicionar serviço</button>
          </>}
        </fieldset>
      </details>
      {editable && <button className="primary-action" type="submit" disabled={busy}>Salvar apresentação</button>}
    </form>
  </details>;
}
