import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { getCaseAnalysis, type CaseAnalysisEnvelope } from "../data/caseAnalysis";
import { getInspectionSession, type InspectionEnvelope } from "../data/inspectionSession";
import { getTechnicalSnapshot, type TechnicalEnvelope } from "../data/technicalSnapshot";
import type { ReportSnapshot } from "../data/reportSnapshot";
import { FindingBasis, QuestionSource, SourceReading } from "./ReportProvenance";
import { useReportContext, type ReportContext } from "./reportContext";
import caseFixture from "../../../tests/fixtures/case-analysis-snapshot-v1.json";
import inspectionFixture from "../../../tests/fixtures/inspection-session-v1.json";
import technicalFixture from "../../../tests/fixtures/technical-snapshot-v1.json";
import reportFixture from "../../../tests/fixtures/report-snapshot-v1.json";

vi.mock("../data/caseAnalysis", () => ({ getCaseAnalysis: vi.fn() }));
vi.mock("../data/inspectionSession", () => ({ getInspectionSession: vi.fn() }));
vi.mock("../data/technicalSnapshot", () => ({ getTechnicalSnapshot: vi.fn() }));
const report = { ...reportFixture, source_snapshot: { ...reportFixture.source_snapshot, case_analysis_snapshot_id: caseFixture.snapshot_id, inspection_session_id: inspectionFixture.session_id, technical_snapshot_id: technicalFixture.snapshot_id } } as unknown as ReportSnapshot;
const caseEnvelope = { revision: report.source_snapshot.case_analysis_revision, snapshot: { ...caseFixture, source_inventory_stale: false, stale_document_ids: [] }, updated_at: "2026-10-09T00:00:00Z" } as unknown as CaseAnalysisEnvelope;
const inspection = { revision: report.source_snapshot.inspection_session_revision, snapshot: inspectionFixture } as unknown as InspectionEnvelope;
const technical = { revision: report.source_snapshot.technical_snapshot_revision, snapshot: technicalFixture } as unknown as TechnicalEnvelope;
const context: ReportContext = { case: { kind: "ready", value: caseEnvelope.snapshot }, inspection: { kind: "ready", value: inspection.snapshot }, technical: { kind: "ready", value: technical.snapshot } };

beforeEach(() => {
  vi.mocked(getCaseAnalysis).mockResolvedValue(caseEnvelope);
  vi.mocked(getInspectionSession).mockResolvedValue(inspection);
  vi.mocked(getTechnicalSnapshot).mockResolvedValue(technical);
});

test("reads only the bound identities and revisions and refuses a newer source", async () => {
  vi.mocked(getTechnicalSnapshot).mockResolvedValue({ ...technical, revision: technical.revision + 1 });
  const { result } = renderHook(() => useReportContext(report, 1));
  await waitFor(() => expect(result.current.technical.kind).toBe("different"));
  expect(result.current.case.kind).toBe("ready");
  expect(result.current.inspection.kind).toBe("ready");
});

test("a matching revision with a different identity is not the bound source", async () => {
  vi.mocked(getCaseAnalysis).mockResolvedValue({ ...caseEnvelope, snapshot: { ...caseEnvelope.snapshot, snapshot_id: "ANOTHER-SNAPSHOT" } });
  const { result } = renderHook(() => useReportContext(report, 1));
  await waitFor(() => expect(result.current.case.kind).toBe("different"));
});

test("upstream staleness is not fresh authority despite a matching revision", async () => {
  vi.mocked(getTechnicalSnapshot).mockResolvedValue({ ...technical, snapshot: { ...technical.snapshot, upstream_stale: true } });
  const { result } = renderHook(() => useReportContext(report, 1));
  await waitFor(() => expect(result.current.technical.kind).toBe("different"));
});

test("does not carry consultation data between workspaces or accept late responses", async () => {
  let late!: (value: TechnicalEnvelope) => void;
  vi.mocked(getTechnicalSnapshot).mockImplementationOnce(() => new Promise((resolve) => { late = resolve; })).mockRejectedValueOnce(new Error("Unavailable"));
  const { result, rerender } = renderHook(({ value }) => useReportContext(value, 1), { initialProps: { value: report } });
  rerender({ value: { ...report, workspace_id: "22222222-2222-4222-8222-222222222222" } });
  await waitFor(() => expect(result.current.technical.kind).toBe("unavailable"));
  late(technical);
  await waitFor(() => expect(result.current.technical.kind).toBe("unavailable"));
});

test("source consultation failure remains distinct from an empty evidence chain", () => {
  render(<FindingBasis findingId="FINDING-001" context={{ ...context, technical: { kind: "unavailable" } }} />);
  expect(screen.getByText(/Consulta da fonte indisponível/)).toBeVisible();
});

test("shows the persisted finding, supporting/contrary evidence, method and human decision", () => {
  const finding = technical.snapshot.findings[0];
  render(<FindingBasis findingId={finding.finding_id} context={context} />);
  expect(screen.getAllByText(finding.technical_proposition, { exact: false })[0]).toBeVisible();
  expect(screen.getAllByText("Evidência de suporte:").length).toBeGreaterThan(0);
  expect(screen.getByText("Decisão profissional registrada:")).toBeVisible();
  expect(screen.getAllByText("Análise / método:").length).toBeGreaterThan(0);
  expect(screen.getByText(/A redação da resposta e a aprovação do laudo são atos distintos/)).toBeVisible();
  expect(screen.getByText(/"decision_id"/).closest("details")).not.toBeNull();
});

test("displays literal question origin and exact source page without promoting it to a decision", () => {
  const question = caseEnvelope.snapshot.questions[0];
  const value = { ...caseEnvelope.snapshot, questions: [{ ...question, source_question: { origin: "CLAIMANT" as const, original_number: "7.b", page_start: 4, page_end: 4, excerpt: question.text, method: "SYNTHETIC" } }] };
  render(<QuestionSource questionId={question.item_id} context={{ ...context, case: { kind: "ready", value } }} />);
  expect(screen.getByText(/Parte requerente · quesito 7.b/)).toBeVisible();
  expect(screen.getAllByText(question.provenance[0].page_or_span, { exact: false })[0]).toBeVisible();
  expect(screen.queryByText("Conclusão profissional")).not.toBeInTheDocument();
});

test("measurement keeps raw value/unit and displays actual method and equipment names", () => {
  const item = inspection.snapshot.measurements[0];
  render(<SourceReading kind="MEASUREMENT" id={item.measurement_id} context={context} />);
  expect(screen.getByText(`${item.quantity}: ${item.raw_value} ${item.raw_unit}`, { exact: false })).toBeVisible();
  expect(screen.getByText(/Método:.*Equipamento:/)).toBeVisible();
  expect(screen.queryByText("Conclusão profissional")).not.toBeInTheDocument();
});

test("a source from another revision does not display the newer measurement", () => {
  const item = inspection.snapshot.measurements[0];
  render(<SourceReading kind="MEASUREMENT" id={item.measurement_id} context={context} sourceRevision={1} boundRevision={2} />);
  expect(screen.getByText(/A revisão desta fonte não corresponde/)).toBeVisible();
  expect(screen.queryByText(`${item.quantity}: ${item.raw_value} ${item.raw_unit}`, { exact: false })).not.toBeInTheDocument();
});

test("an absent explicit finding identity is not replaced by a similar finding", () => {
  render(<FindingBasis findingId="NOT-LINKED" context={context} />);
  expect(screen.getByText(/Nenhuma conclusão foi deduzida/)).toBeVisible();
  expect(screen.queryByText("Decisão profissional registrada:")).not.toBeInTheDocument();
});
