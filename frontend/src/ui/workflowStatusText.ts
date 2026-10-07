// Texto da situação do fluxo. Só traduz códigos da projeção do backend:
// nenhuma regra aqui conclui etapa, aprova ou infere progresso.
import { WORKFLOW_ROUTES, type ShellRoute } from "../routes/routeCatalog";
import type { WorkflowReason, WorkflowStageState, WorkflowStageStatus, WorkflowStatus } from "../data/workflowStatus";
import { plural, stateLabel } from "./labels";

export const STAGE_STATE_TEXT: Record<WorkflowStageState, string> = {
  NOT_STARTED: "Não iniciada",
  IN_PROGRESS: "Em andamento",
  PROCESSING: "Processando",
  AWAITING_REVIEW: "Aguardando conferência",
  REVIEW_REQUIRED: "Revisão necessária",
  ATTENTION: "Requer atenção",
  READY: "Pronta pelos critérios do sistema",
  APPROVED: "Aprovada",
  RECORDED: "Registros presentes",
  NOT_TRACKED: "Sem situação de etapa",
  UNAVAILABLE: "Não verificada",
};

// Símbolo visível ao lado do nome: a situação nunca depende só de cor.
// "Registros presentes" usa ponto, não visto: registro não é conclusão.
export const STAGE_STATE_SYMBOL: Record<WorkflowStageState, string> = {
  NOT_STARTED: "○",
  IN_PROGRESS: "◐",
  PROCESSING: "⋯",
  AWAITING_REVIEW: "◇",
  REVIEW_REQUIRED: "↺",
  ATTENTION: "!",
  READY: "✓",
  APPROVED: "✓",
  RECORDED: "•",
  NOT_TRACKED: "",
  UNAVAILABLE: "?",
};

const SUMMARY_PLURAL: Record<WorkflowStageState, [string, string]> = {
  NOT_STARTED: ["etapa não iniciada", "etapas não iniciadas"],
  IN_PROGRESS: ["etapa em andamento", "etapas em andamento"],
  PROCESSING: ["etapa processando", "etapas processando"],
  AWAITING_REVIEW: ["etapa aguardando conferência", "etapas aguardando conferência"],
  REVIEW_REQUIRED: ["etapa com revisão necessária", "etapas com revisão necessária"],
  ATTENTION: ["etapa que requer atenção", "etapas que requerem atenção"],
  READY: ["etapa pronta pelos critérios do sistema", "etapas prontas pelos critérios do sistema"],
  APPROVED: ["etapa aprovada", "etapas aprovadas"],
  RECORDED: ["etapa com registros presentes", "etapas com registros presentes"],
  NOT_TRACKED: ["ferramenta sem situação de etapa", "ferramentas sem situação de etapa"],
  UNAVAILABLE: ["etapa não verificada", "etapas não verificadas"],
};

export function stateSummaryText(state: WorkflowStageState, count: number) {
  const [one, many] = SUMMARY_PLURAL[state];
  return plural(count, one, many);
}

const FIXED: Record<string, string> = {
  NO_PROCESS_DATA: "Nenhum dado do processo registrado",
  PROCESS_DATA_RECORDED: "Dados do processo registrados",
  METADATA_REVIEW_UNAVAILABLE: "Conferência de dados extraídos indisponível nesta instalação",
  METADATA_CONFIRMED: "Dados extraídos dos autos conferidos e confirmados",
  METADATA_CONFIRMATION_OUTDATED: "A confirmação dos dados do processo não corresponde mais às fontes atuais",
  METADATA_CONFLICT: "Os autos trazem valores divergentes para dados do processo",
  METADATA_EXTRACTION_FAILED: "A leitura dos dados do processo falhou",
  METADATA_AWAITING_CONFIRMATION: "Dados extraídos dos autos aguardam sua conferência",
  METADATA_PARTIAL_AWAITING_CONFIRMATION: "Dados extraídos em parte aguardam sua conferência",
  NO_MATERIALS: "Nenhum material importado",
  COVERAGE_PARTIAL: "Cobertura parcial dos documentos",
  COVERAGE_UNAVAILABLE: "Cobertura dos documentos indisponível",
  UPSTREAM_CHANGED: "Uma etapa anterior mudou depois deste registro",
  PLANNING_READY: "Todas as decisões do planejamento foram registradas",
  PLANNING_PARTIAL: "Planejamento com pendências registradas",
  PLANNING_BLOCKED: "Planejamento bloqueado",
  NO_ITEMS: "Nenhum item de vistoria registrado",
  NO_EVIDENCE: "Nenhuma evidência registrada",
  NO_PROPOSALS: "Nenhuma proposta de constatação",
  REPORT_DRAFT: "Laudo em elaboração",
  REPORT_REVIEWED: "Laudo revisado, aguardando aprovação",
  REPORT_APPROVED: "Laudo aprovado",
  REPORT_SUPERSEDED: "Laudo substituído por nova versão",
  COVERAGE_INCOMPLETE: "Conteúdo obrigatório ainda incompleto",
  REPORT_NOT_STARTED: "Ainda não há laudo para revisar",
  REPORT_NOT_REVIEWED: "O laudo ainda não foi revisado",
  REPORT_AWAITING_APPROVAL: "Revisado, aguardando aprovação",
  NO_ARTIFACTS: "Nenhum arquivo de entrega gerado",
  WORD_PRESENT: "Documento Word disponível",
  WORD_ABSENT: "Documento Word ausente",
  PDF_PRESENT: "PDF disponível",
  PDF_ABSENT: "PDF ainda não gerado: entrega parcial",
  DELIVERY_DRAFT: "Entrega em elaboração",
  DELIVERY_READY_FOR_REVIEW: "Entrega pronta para revisão",
  DELIVERY_APPROVED: "Entrega aprovada",
  DELIVERY_FINALIZED: "Entrega finalizada",
  DELIVERY_DELIVERED: "Entrega registrada como entregue",
  DELIVERY_SUPERSEDED: "Entrega substituída",
  UPSTREAM_AUTHORITY_UNAVAILABLE: "Não foi possível verificar as etapas anteriores",
  OPTIONAL_STAGE: "Etapa de gestão, não obrigatória para o laudo",
  MANAGEMENT_TOOL: "Ferramenta de gestão, sem situação de etapa",
  QUERY_FAILED: "A consulta desta etapa falhou",
  NOT_REPORTED: "O sistema não informou a situação desta etapa",
  SERVICE_UNAVAILABLE: "Esta instalação não oferece a consulta desta etapa",
};

const COUNTED: Record<string, [string, string]> = {
  MATERIALS_PROCESSING: ["material em processamento", "materiais em processamento"],
  MATERIALS_READY: ["material pronto", "materiais prontos"],
  MATERIALS_FAILED: ["material com falha no processamento", "materiais com falha no processamento"],
  MATERIALS_INTERRUPTED: ["processamento interrompido", "processamentos interrompidos"],
  SOURCES_CHANGED: ["fonte alterada depois da análise", "fontes alteradas depois da análise"],
  SOURCES_NOT_INDEXED: ["fonte nova fora da análise", "fontes novas fora da análise"],
  CONFLICTS_AWAITING_REVIEW: ["conflito aguarda sua decisão", "conflitos aguardam sua decisão"],
  QUESTIONS_RECORDED: ["quesito registrado", "quesitos registrados"],
  ITEMS_AWAITING_REVIEW: ["item aguarda sua decisão", "itens aguardam sua decisão"],
  ITEMS_DEFERRED: ["item adiado", "itens adiados"],
  ITEMS_PENDING: ["item de vistoria pendente", "itens de vistoria pendentes"],
  ITEMS_COMPLETED: ["item concluído", "itens concluídos"],
  ITEMS_PARTIAL: ["item executado em parte", "itens executados em parte"],
  ITEMS_NOT_EXECUTED: ["item não executado", "itens não executados"],
  ITEMS_NOT_APPLICABLE: ["item registrado como não aplicável", "itens registrados como não aplicáveis"],
  ITEMS_BLOCKED: ["item com execução impedida", "itens com execução impedida"],
  EVIDENCE_AWAITING_REVIEW: ["evidência aguarda sua decisão", "evidências aguardam sua decisão"],
  EVIDENCE_APPROVED: ["evidência aprovada", "evidências aprovadas"],
  EVIDENCE_REJECTED: ["evidência rejeitada", "evidências rejeitadas"],
  PROPOSALS_AWAITING_DECISION: ["proposta de constatação aguarda sua decisão", "propostas de constatação aguardam sua decisão"],
  CONFLICTS_UNRESOLVED: ["conflito não resolvido", "conflitos não resolvidos"],
  FINDINGS_EFFECTIVE: ["constatação efetiva", "constatações efetivas"],
  PATHOLOGY_REVIEWS: ["decisão sobre patologia registrada", "decisões sobre patologias registradas"],
};

const FINANCIAL: Record<string, string> = {
  DRAFT: "em elaboração",
  PROPOSED: "proposta apresentada",
  COURT_APPROVED: "valor aprovado pelo Juízo",
  PARTIALLY_RECEIVED: "recebido em parte",
  RECEIVED: "recebido",
  CLOSED: "encerrado",
};

export function reasonText({ code, count }: WorkflowReason): string {
  if (code in COUNTED && count !== undefined) {
    const [one, many] = COUNTED[code];
    return plural(count, one, many);
  }
  if (code in FIXED) return FIXED[code];
  if (code.startsWith("GATE_")) return `Situação para redação: ${stateLabel(code.slice(5)).toLowerCase()}`;
  if (code.startsWith("FINANCIAL_") && code.slice(10) in FINANCIAL) return `Orçamento ${FINANCIAL[code.slice(10)]}`;
  // Código novo do backend: o texto é genérico e o código fica nos detalhes técnicos.
  return "Outro detalhe registrado";
}

// Com a base desatualizada, o estado registrado do laudo/entrega é HISTÓRICO:
// o texto diz isso, para "Laudo aprovado" nunca ser lido como vigente.
const HISTORICAL = /^(REPORT|DELIVERY)_/;

export function stageReasonsText(status: WorkflowStageStatus): string[] {
  return status.reasons.map((reason) => {
    const text = reasonText(reason);
    if (status.currency === "STALE" && HISTORICAL.test(reason.code)) {
      return `Antes da mudança: ${text.charAt(0).toLowerCase()}${text.slice(1)}`;
    }
    return text;
  });
}

export function stageDescription(status: WorkflowStageStatus) {
  return [STAGE_STATE_TEXT[status.state], ...stageReasonsText(status)].join(". ");
}

// "Processando" não pede decisão do perito: aparece na situação e na
// navegação, mas não entra em "Precisa de atenção".
const ATTENTION_ORDER: WorkflowStageState[] = ["UNAVAILABLE", "ATTENTION", "REVIEW_REQUIRED", "AWAITING_REVIEW"];
// Estados em que não há ação pendente apontada pelas regras do sistema.
const SETTLED: ReadonlySet<WorkflowStageState> = new Set(["RECORDED", "READY", "APPROVED", "NOT_TRACKED"]);

export type StageWithRoute = { route: ShellRoute; status: WorkflowStageStatus };

export function attentionItems(stages: StageWithRoute[]): StageWithRoute[] {
  return stages
    .filter((item) => ATTENTION_ORDER.includes(item.status.state))
    .sort((a, b) => ATTENTION_ORDER.indexOf(a.status.state) - ATTENTION_ORDER.indexOf(b.status.state));
}

// Primeira etapa técnica, na ordem do catálogo, que ainda tem algo a fazer.
// Gestão (orçamento, recuperação) nunca é imposta como próximo passo do laudo.
export function nextAction(stages: StageWithRoute[]): StageWithRoute | undefined {
  return stages.find((item) => item.route.group !== "Gestão" && !SETTLED.has(item.status.state));
}

// Etapa do catálogo sem resposta da projeção: nunca vira "concluída".
function unreported(stage: string): WorkflowStageStatus {
  return {
    stage, state: "UNAVAILABLE", availability: "UNAVAILABLE", currency: "NOT_EVALUATED", decision: "NOT_TRACKED",
    reasons: [{ code: "NOT_REPORTED" }], revision: null, updated_at: null,
  };
}

export function stagesFromCatalog(value: WorkflowStatus): StageWithRoute[] {
  const byStage = new Map(value.stages.map((item) => [item.stage, item]));
  return WORKFLOW_ROUTES.filter((route) => route.kind === "stage").map((route) => {
    const stage = route.path.slice(1);
    return { route, status: byStage.get(stage) ?? unreported(stage) };
  });
}
