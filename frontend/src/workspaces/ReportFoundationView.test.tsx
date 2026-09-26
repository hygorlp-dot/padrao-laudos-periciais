import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ReportFoundationView } from "./ReportFoundationView";

const ID = "11111111-1111-4111-8111-111111111111";
const profile = { profile_id: "EXPERT-PROFILE-001", revision: 1, full_name: "Profissional Sintético", professional_title: "Perito Judicial", registration: "CREA-SYN-001", court_registration: "TRIB-SYN-001", contact_line: "contato sintético" };
const sections = [
  ["IDENTIFICATION", "Identificação", true], ["PROCEDURAL_CONTEXT", "Contexto Processual", true], ["PURPOSE_OBJECT", "Objeto da Perícia", true], ["SCOPE", "Escopo", false],
  ["DOCUMENTS_EVIDENCE", "Documentos e Evidências Examinados", true], ["METHODOLOGY", "Metodologia", false], ["INSPECTION", "Vistoria", true], ["TECHNICAL_ANALYSIS", "Análise Técnica", true],
  ["TECHNICAL_FINDINGS", "Achados Técnicos", true], ["ANSWERS_TO_QUESTIONS", "Respostas aos Quesitos", true], ["CONCLUSIONS", "Conclusões", false], ["LIMITATIONS_RESERVATIONS", "Limitações e Ressalvas", false],
  ["REFERENCES", "Referências", false], ["ATTACHMENTS", "Anexos", false],
].map(([kind, title, required], index) => ({ section_id: `SEC-${index + 1}`, kind, title, order: index + 1, required_by_cpc473: required }));
const context = ["PROCESS_NUMBER", "COURT", "PARTIES", "ADDRESSES", "CLAIM_AND_GROUNDS", "REQUESTS"].map((field, index) => (
  index === 0
    ? { context_id: `CTX-${index + 1}`, field, required: true, status: "PRESENT", source_id: "DOC-1", note: "Processo nº 0000001-00.2026." }
    : { context_id: `CTX-${index + 1}`, field, required: true, status: "MISSING", source_id: null, note: `[INFORMAÇÃO NECESSÁRIA: ${field.toLowerCase()}]` }
));
const baseSnapshot = {
  schema_version: "1.0.0", report_id: "REPORT-001", workspace_id: ID,
  source_snapshot: { workspace_id: ID, construction_defect_analysis_snapshot_id: null, construction_defect_analysis_revision: null, construction_defect_analysis_digest: null },
  expert_profile: profile, editorial_profile: { profile_id: "JUSTICA_PLURAL_CHAPTER_4", font_family: "Arial", body_font_pt: 11 },
  context_matrix: context, sections,
  claims: [{ claim_id: "CLAIM-1", section_id: "SEC-1", text: "Afirmação documentada.", authority: "DOCUMENTED", provenance: [{ provenance_id: "PROV-1", source_kind: "CASE_DOCUMENT", source_id: "DOC-1", source_revision: 1 }] }],
  answers: [], review_decisions: [], state: "DRAFT",
  coverage: { sections: 14, material_claims: 1, traceable_claims: 1, answers: 0, traceable_answers: 0, cpc473_required_sections: 8, cpc473_present_sections: 1, context_required_fields: 6, context_present_fields: 1, complete: false, reasons: ["Conteúdo incompleto."] },
  upstream_stale: false, upstream_stale_reasons: [],
};
const catalog = {
  sources: [
    { kind: "CASE_DOCUMENT", id: "DOC-1", label: "01 · Petição inicial · páginas 1-4" },
    { kind: "FIELD_OBSERVATION", id: "OBS-1", label: "Fissura inclinada na parede leste" },
    { kind: "TECHNICAL_FINDING", id: "FINDING-1", label: "Há fissura ativa na parede leste." },
  ],
  context_sources: { PROCESS_NUMBER: [{ id: "DOC-1", label: "01 · Petição inicial · páginas 1-4" }], COURT: [], PARTIES: [], ADDRESSES: [], CLAIM_AND_GROUNDS: [], REQUESTS: [] },
  questions: [{ question_id: "QUESTION-1", text: "Existe umidade na parede?", findings: [{ finding_id: "FINDING-1", label: "Há fissura ativa na parede leste." }] }],
};
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const envelope = (snapshot: object, revision = 3) => ({ revision, updated_at: "2026-08-31T12:00:00Z", snapshot });

function routed(snapshot: object, amendments: (body: Record<string, unknown>) => Response | Promise<Response> = () => response(200, envelope(snapshot, 4))) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/expert-profile")) return Promise.resolve(response(200, { revision: 1, updated_at: "2026-08-31T12:00:00Z", profile }));
    if (url.endsWith("/report-snapshot/sources")) return Promise.resolve(response(200, catalog));
    if (url.endsWith("/report-snapshot/draft-amendments")) return Promise.resolve(amendments(JSON.parse(String(init?.body))));
    if (url.endsWith("/report-snapshot")) return Promise.resolve(response(200, envelope(snapshot)));
    return Promise.resolve(response(404, {}));
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("professional report authoring (Laudo)", () => {
  test("presents sections, readable sources and the process context without internal identities on the first layer", async () => {
    vi.stubGlobal("fetch", routed(baseSnapshot));
    render(<ReportFoundationView workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: "Laudo técnico" })).toBeInTheDocument();
    expect(screen.getByText("Em elaboração")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1. Identificação" })).toBeInTheDocument();
    expect(await screen.findByText(/Fonte: Documento do processo — 01 · Petição inicial · páginas 1-4/)).toBeInTheDocument();
    expect(screen.getByText("Documentado nos autos")).toBeInTheDocument();
    expect(screen.getByText(/CLAIM-1 · CASE_DOCUMENT · DOC-1/).closest("details")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Contexto processual (art. 319)" })).toBeInTheDocument();
    expect(screen.getByText("Número do processo")).toBeInTheDocument();
    expect(screen.getByText(/1 de 8 seções obrigatórias/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Conferir em Revisão" })).toHaveAttribute("href", `/pericias/${ID}/revisao`);
    expect(screen.getByRole("button", { name: "Baixar trilha de auditoria" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /entregar|protocolar|aprovar laudo/i })).not.toBeInTheDocument();
  });

  test("adds a paragraph by choosing its source by content, never by typing an identity", async () => {
    let sent: Record<string, unknown> | undefined;
    vi.stubGlobal("fetch", routed(baseSnapshot, (body) => { sent = body; return response(200, envelope(baseSnapshot, 4)); }));
    render(<ReportFoundationView workspaceId={ID} />);
    const section = within(await screen.findByRole("article", { name: "7. Vistoria" }));
    fireEvent.click(section.getByRole("button", { name: "Adicionar texto a esta seção" }));
    expect(section.getByLabelText("Tipo de fonte")).toHaveValue("FIELD_OBSERVATION");
    fireEvent.change(section.getByLabelText("Fonte"), { target: { value: "OBS-1" } });
    expect(section.getByLabelText("Texto do laudo")).toHaveValue("Fissura inclinada na parede leste");
    fireEvent.change(section.getByLabelText("Texto do laudo"), { target: { value: "Durante a vistoria verificou-se fissura inclinada." } });
    fireEvent.click(section.getByRole("button", { name: "Adicionar ao laudo" }));
    await waitFor(() => expect(sent).toBeDefined());
    expect(sent).toEqual({ expected_revision: 3, action: "ADD_CLAIM", values: { section_id: "SEC-7", text: "Durante a vistoria verificou-se fissura inclinada.", source_kind: "FIELD_OBSERVATION", source_id: "OBS-1" } });
  });

  test("an uncited finding is included first; then the answer is derived from question and finding only", async () => {
    const bodies: Record<string, unknown>[] = [];
    const cited = { ...baseSnapshot, claims: [...baseSnapshot.claims, { claim_id: "CLAIM-2", section_id: "SEC-9", text: "Há fissura ativa na parede leste.", authority: "TECHNICALLY_FOUND", provenance: [{ provenance_id: "PROV-2", source_kind: "TECHNICAL_FINDING", source_id: "FINDING-1", source_revision: 4 }] }] };
    vi.stubGlobal("fetch", routed(baseSnapshot, (body) => { bodies.push(body); return response(200, envelope(cited, 4)); }));
    render(<ReportFoundationView workspaceId={ID} />);
    const answers = within(await screen.findByRole("article", { name: "10. Respostas aos Quesitos" }));
    expect(await answers.findByText("Existe umidade na parede?")).toBeInTheDocument();
    fireEvent.click(answers.getByRole("button", { name: "Incluir o achado em “Achados Técnicos”" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "ADD_CLAIM", values: { section_id: "SEC-9", source_kind: "TECHNICAL_FINDING", source_id: "FINDING-1" } });
    fireEvent.change(await answers.findByLabelText("Resposta"), { target: { value: "Sim, há umidade junto ao piso." } });
    fireEvent.click(answers.getByRole("button", { name: "Registrar resposta" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual({ expected_revision: 4, action: "ANSWER_QUESTION", values: { question_id: "QUESTION-1", finding_id: "FINDING-1", text: "Sim, há umidade junto ao piso." } });
  });

  test("an approved report is read-only and points to a new version through Revisão", async () => {
    const approved = { ...baseSnapshot, state: "APPROVED", review_decisions: [{ review_id: "R-1", action: "MARK_REVIEWED", professional_id: "EXPERT-PROFILE-001", reason: "ok", timestamp: "2026-08-31T10:00:00Z", supersedes_review_id: null }, { review_id: "R-2", action: "APPROVE", professional_id: "EXPERT-PROFILE-001", reason: "ok", timestamp: "2026-08-31T11:00:00Z", supersedes_review_id: "R-1" }] };
    vi.stubGlobal("fetch", routed(approved));
    render(<ReportFoundationView workspaceId={ID} />);
    expect(await screen.findByText("Aprovado")).toBeInTheDocument();
    expect(screen.getByText(/o texto fica bloqueado para edição/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar texto a esta seção" })).not.toBeInTheDocument();
  });

  test("a refused amendment keeps the report on screen with an inline error", async () => {
    vi.stubGlobal("fetch", routed(baseSnapshot, () => response(409, {})));
    render(<ReportFoundationView workspaceId={ID} />);
    const first = within(await screen.findByRole("article", { name: "1. Identificação" }));
    fireEvent.change(first.getByLabelText("Texto"), { target: { value: "Texto alterado." } });
    fireEvent.click(first.getByRole("button", { name: "Salvar texto" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível salvar o texto.");
    expect(screen.getByRole("heading", { name: "Laudo técnico" })).toBeInTheDocument();
  });

  test("the editorial profile is configured within the domain ranges and can be restored to the product preset", async () => {
    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", routed(baseSnapshot, (body) => { bodies.push(body); return response(200, envelope(baseSnapshot, 4)); }));
    render(<ReportFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByText("Padrão editorial"));
    fireEvent.change(screen.getByLabelText("Fonte"), { target: { value: "Calibri" } });
    fireEvent.change(screen.getByLabelText("Tamanho (pt)"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar padrão editorial" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "SET_EDITORIAL_PROFILE", values: { editorial_profile: { profile_id: "CUSTOM", font_family: "Calibri", body_font_pt: 12, first_line_indent_cm: 1.25, typography: { heading1_pt: 14 } } } });
  });

  test("references are added as works apart from case documents and cited in the text author-date", async () => {
    const bodies: Record<string, unknown>[] = [];
    const nbr = { reference_id: "REFERENCE-1", kind: "TECHNICAL_STANDARD", author: "Associação Brasileira de Normas Técnicas", title: "Desempenho", year: 2021, identifier: "ABNT NBR 15575-1", details: null };
    const withReference = { ...baseSnapshot, references: [nbr] };
    vi.stubGlobal("fetch", routed(withReference, (body) => { bodies.push(body); return response(200, envelope(withReference, 4)); }));
    render(<ReportFoundationView workspaceId={ID} />);
    const form = await screen.findByRole("form", { name: "Adicionar referência" });
    expect(screen.getAllByText("(ABNT NBR 15575-1, 2021)").length).toBeGreaterThan(0);
    fireEvent.change(within(form).getByLabelText("Tipo"), { target: { value: "TECHNICAL_LITERATURE" } });
    fireEvent.change(within(form).getByLabelText("Autor ou entidade"), { target: { value: "Thomaz, Ercio" } });
    fireEvent.change(within(form).getByLabelText("Título"), { target: { value: "Trincas em edifícios" } });
    fireEvent.change(within(form).getByLabelText("Ano (opcional)"), { target: { value: "20" } });
    expect(within(form).getByRole("button", { name: "Adicionar referência" })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Ano (opcional)"), { target: { value: "2020" } });
    fireEvent.click(within(form).getByRole("button", { name: "Adicionar referência" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ expected_revision: 3, action: "ADD_REFERENCE", values: { kind: "TECHNICAL_LITERATURE", author: "Thomaz, Ercio", title: "Trincas em edifícios", year: 2020, identifier: null, details: null } });
    fireEvent.change(screen.getByLabelText("Inserir citação"), { target: { value: "REFERENCE-1" } });
    expect(screen.getByDisplayValue("Afirmação documentada. (ABNT NBR 15575-1, 2021)")).toBeInTheDocument();
  });

  test("the findings summary is captured from the bound pathology analysis and shown as a table", async () => {
    const bodies: Record<string, unknown>[] = [];
    const bound = { ...baseSnapshot, source_snapshot: { ...baseSnapshot.source_snapshot, construction_defect_analysis_snapshot_id: "CDA-1", construction_defect_analysis_revision: 2, construction_defect_analysis_digest: "a".repeat(64) } };
    const tabled = { ...bound, findings_table: [{ manifestation: "Umidade na interface.", environment: null, finding: "Manchas até 40 cm.", situation: "ANOMALIA", provenance: { provenance_id: "P-1", source_kind: "PATHOLOGY", source_id: "PAT-001", source_revision: 2 } }] };
    vi.stubGlobal("fetch", routed(bound, (body) => { bodies.push(body); return response(200, envelope(tabled, 4)); }));
    render(<ReportFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Inserir tabela-resumo dos achados" }));
    await waitFor(() => expect(bodies).toEqual([{ expected_revision: 3, action: "SET_FINDINGS_TABLE", values: {} }]));
    const table = await screen.findByRole("table", { name: "Tabela 1 – Resumo dos achados técnicos" });
    expect(within(table).getByText("Não informado")).toBeInTheDocument();
    expect(within(table).getByText("Anomalia")).toBeInTheDocument();
    expect(within(table).queryByText("PAT-001")).not.toBeInTheDocument();
  });

  test("a superseded report opens its next version and says what did not carry over", async () => {
    const superseded = { ...baseSnapshot, state: "SUPERSEDED", review_decisions: [{ review_id: "R-1", action: "SUPERSEDE", professional_id: profile.profile_id, reason: "Correção.", timestamp: "2026-09-01T10:00:00Z", supersedes_review_id: null }] };
    const calls: Array<{ url: string; body?: string }> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, body: init?.body ? String(init.body) : undefined });
      if (url.endsWith("/report-snapshot/versions")) return Promise.resolve(response(201, { ...envelope(baseSnapshot, 4), dropped: { claims: 2, answers: 0, context_fields: ["COURT"], findings_table: false, site_location: true } }));
      return routed(superseded)(input, init);
    }));
    render(<ReportFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Iniciar nova versão do laudo" }));
    expect(await screen.findByText(/Saíram desta versão: 2 textos sem fonte atual; contexto processual a confirmar: .+; localização do imóvel\./)).toBeInTheDocument();
    expect(JSON.parse(calls.find((call) => call.url.endsWith("/versions"))!.body!)).toEqual({ expected_revision: 3 });
    expect(screen.queryByRole("button", { name: "Iniciar nova versão do laudo" })).not.toBeInTheDocument();
  });

  test("the confirmed site location is inserted in the inspection section", async () => {
    const bodies: Record<string, unknown>[] = [];
    const located = { ...baseSnapshot, site_location: { latitude: -23.55052, longitude: -46.633308, address_label: "Rua Sintética, 100", source_revision: 2, source_checksum: "a".repeat(64) } };
    vi.stubGlobal("fetch", routed(baseSnapshot, (body) => { bodies.push(body); return response(200, envelope(located, 4)); }));
    render(<ReportFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Inserir localização" }));
    await waitFor(() => expect(bodies).toEqual([{ expected_revision: 3, action: "SET_SITE_LOCATION", values: {} }]));
    expect(await screen.findByText("23,550520° S, 46,633308° O")).toBeInTheDocument();
  });

  test("figures come from the library and are cited in the text by a marker the document numbers", async () => {
    const bodies: Record<string, unknown>[] = [];
    const figure = (id: string, section: string, caption: string) => ({ figure_id: id, content_id: "00000001-0000-4000-8000-000000000000", original_sha256: "a".repeat(64), caption, section_kind: section, width: 1200, height: 900 });
    const figured = { ...baseSnapshot, figures: [figure("PHOTO-B", "ATTACHMENTS", "Anexo fotográfico"), figure("PHOTO-A", "INSPECTION", "Fissura na parede leste")] };
    vi.stubGlobal("fetch", routed(baseSnapshot, (body) => { bodies.push(body); return response(200, envelope(figured, 4)); }));
    render(<ReportFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Trazer figuras da biblioteca" }));
    await waitFor(() => expect(bodies).toEqual([{ expected_revision: 3, action: "SET_FIGURES", values: {} }]));
    expect(await screen.findByText("Figura 1")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Figura 1 – Fissura na parede leste" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Inserir referência a figura ou tabela"), { target: { value: "[[FIGURA:PHOTO-B]]" } });
    expect(screen.getByDisplayValue("Afirmação documentada. [[FIGURA:PHOTO-B]]")).toBeInTheDocument();
    expect(screen.getByText(/conforme a ordem final: Figura 2/)).toBeInTheDocument();
  });

  test("the writing assistant says it is unavailable and why, and never decides", async () => {
    vi.stubGlobal("fetch", routed(baseSnapshot));
    render(<ReportFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByText("Assistente de redação"));
    expect(screen.getByText("Indisponível nesta instalação")).toBeInTheDocument();
    expect(screen.getByText(/Por padrão, nada do caso sai desta máquina/)).toBeInTheDocument();
    expect(screen.getByText(/Nada entra no laudo sem a sua decisão/)).toBeInTheDocument();
  });

  test("a report that cannot start yet says which stages it needs instead of blaming integrity", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/expert-profile")) return Promise.resolve(response(200, { revision: 1, updated_at: "2026-08-31T12:00:00Z", profile }));
      if (url.endsWith("/report-snapshot") && init?.method === "POST") return Promise.resolve(response(400, { error: { code: "INVALID_REQUEST" } }));
      if (url.endsWith("/report-snapshot")) return Promise.resolve(response(404, {}));
      return Promise.resolve(response(404, {}));
    }));
    render(<ReportFoundationView workspaceId={ID} />);
    fireEvent.click(await screen.findByRole("button", { name: "Iniciar laudo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("O laudo ainda não pode começar");
    expect(screen.queryByText(/conferência de integridade/)).not.toBeInTheDocument();
  });

  test("stale reasons are said in plain Portuguese, once each", async () => {
    vi.stubGlobal("fetch", routed({ ...baseSnapshot, upstream_stale: true, upstream_stale_reasons: ["technical snapshot revision changed", "technical snapshot content changed", "site location changed"] }));
    render(<ReportFoundationView workspaceId={ID} />);
    expect(await screen.findByText("As evidências e os achados técnicos mudaram depois deste laudo.")).toBeInTheDocument();
    expect(screen.getByText("A localização do imóvel mudou depois de inserida no laudo.")).toBeInTheDocument();
    expect(screen.queryByText(/technical snapshot/)).not.toBeInTheDocument();
  });

  test("requires the master expert profile before starting a report", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/report-snapshot/sources")) return Promise.resolve(response(200, catalog));
      if (url.endsWith("/expert-profile")) return Promise.resolve(init?.method === "PUT" ? response(200, { revision: 1, updated_at: "2026-08-31T12:00:00Z", profile }) : response(404, {}));
      if (url.endsWith("/report-snapshot") && init?.method === "POST") return Promise.resolve(response(201, envelope(baseSnapshot, 1)));
      return Promise.resolve(response(404, {}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup(); render(<ReportFoundationView workspaceId={ID} />);
    await user.type(await screen.findByLabelText("Nome completo"), "Profissional Sintético");
    await user.type(screen.getByLabelText("Título profissional"), "Perito Judicial");
    await user.type(screen.getByLabelText("Registro profissional"), "CREA-SYN-001");
    await user.type(screen.getByLabelText("Cadastro no tribunal"), "TRIB-SYN-001");
    await user.type(screen.getByLabelText("Contato profissional"), "contato sintético");
    await user.click(screen.getByRole("button", { name: "Salvar perfil e iniciar laudo" }));
    expect(await screen.findByRole("heading", { name: "Laudo técnico" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "PUT")).toHaveLength(1);
  });
});
