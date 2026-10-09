import { useEffect, useState } from "react";
import { getCaseAnalysis, type CaseAnalysisSnapshot } from "../data/caseAnalysis";
import { getInspectionSession, type InspectionSnapshot } from "../data/inspectionSession";
import { getTechnicalSnapshot, type TechnicalSnapshot } from "../data/technicalSnapshot";
import type { ReportSnapshot } from "../data/reportSnapshot";

export type Read<T> = { kind: "loading" | "unavailable" | "different" } | { kind: "ready"; value: T };
export type ReportContext = { case: Read<CaseAnalysisSnapshot>; inspection: Read<InspectionSnapshot>; technical: Read<TechnicalSnapshot> };
const loading: ReportContext = { case: { kind: "loading" }, inspection: { kind: "loading" }, technical: { kind: "loading" } };

// These are identity joins on existing read models, never reconstructed domain edges.
// A newer upstream revision is not the historical source of an older report.
export function useReportContext(report: ReportSnapshot | null, revision: number) {
  const [state, setState] = useState<{ key: string; value: ReportContext } | null>(null);
  const key = report ? `${report.workspace_id}:${report.report_id}:${revision}` : "";
  useEffect(() => {
    if (!report) return;
    const controller = new AbortController();
    const binding = report.source_snapshot;
    const put = <K extends keyof ReportContext>(name: K, value: ReportContext[K]) => {
      if (!controller.signal.aborted) setState((previous) => ({ key, value: { ...(previous?.key === key ? previous.value : loading), [name]: value } }));
    };
    getCaseAnalysis(report.workspace_id, controller.signal).then((item) => put("case", item.revision === binding.case_analysis_revision && item.snapshot.snapshot_id === binding.case_analysis_snapshot_id && !item.snapshot.source_inventory_stale && !item.snapshot.stale_document_ids.length ? { kind: "ready", value: item.snapshot } : { kind: "different" }), () => put("case", { kind: "unavailable" }));
    getInspectionSession(report.workspace_id, controller.signal).then((item) => put("inspection", item.revision === binding.inspection_session_revision && item.snapshot.session_id === binding.inspection_session_id && !item.snapshot.upstream_stale ? { kind: "ready", value: item.snapshot } : { kind: "different" }), () => put("inspection", { kind: "unavailable" }));
    getTechnicalSnapshot(report.workspace_id, controller.signal).then((item) => put("technical", item.revision === binding.technical_snapshot_revision && item.snapshot.snapshot_id === binding.technical_snapshot_id && !item.snapshot.upstream_stale ? { kind: "ready", value: item.snapshot } : { kind: "different" }), () => put("technical", { kind: "unavailable" }));
    return () => controller.abort();
  }, [key, report]);
  return state?.key === key ? state.value : loading;
}

export function editorialNature(authority: string) {
  const labels: Record<string, string> = { ALLEGED: "Alegação nos autos", DOCUMENTED: "Documento / fonte", DECIDED_BY_COURT: "Decisão judicial", OBSERVED: "Observado em vistoria", MEASURED: "Medição", TECHNICALLY_FOUND: "Constatação", PROFESSIONALLY_CONCLUDED: "Conclusão profissional", PROFESSIONAL_DECISION: "Conclusão profissional", AI_PROPOSAL: "Proposta aguardando decisão" };
  return labels[authority] ?? "Natureza não informada";
}
