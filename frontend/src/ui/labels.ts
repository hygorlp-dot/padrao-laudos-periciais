// Tradução de códigos internos para a primeira camada da interface.
// Os códigos continuam disponíveis em "Detalhes técnicos"; aqui o perito lê a
// situação na própria língua do trabalho. Código desconhecido nunca aparece em
// caixa alta crua: é humanizado, e o código exato fica na auditoria.

const STATE_LABELS: Record<string, string> = {
  DRAFT: "Em elaboração",
  READY_FOR_REVIEW: "Pronto para revisão",
  REVIEWED: "Revisado",
  APPROVED: "Aprovado",
  FINALIZED: "Finalizado",
  DELIVERED: "Entregue",
  STALE: "Desatualizado",
  SUPERSEDED: "Substituído",
  REJECTED: "Rejeitado",
  MODIFIED: "Modificado",
  DEFERRED: "Adiado",
  PENDING: "Aguardando revisão",
  RECEIVED: "Recebido",
  OPEN: "Em aberto",
  CLOSED: "Encerrado",
  COMPLETE: "Completo",
  PARTIAL: "Parcial",
  ACTIVE: "Ativo",
  EFFECTIVE: "Efetivo",
  PROPOSED: "Proposto",
  APTO_PARA_REDACAO: "Apto para redação",
  APTO_PARA_REDACAO_COM_RESSALVAS: "Apto para redação com ressalvas",
  NAO_APTO_PARA_REDACAO: "Não apto para redação",
  BLOQUEADO_PARA_REDACAO: "Bloqueado para redação",
  BLOQUEADO: "Bloqueado",
};

const ACTION_LABELS: Record<string, string> = {
  APPROVE: "Aprovado",
  REJECT: "Rejeitado",
  MODIFY: "Modificado",
  MODIFY_AND_APPROVE: "Modificado e aprovado",
  DEFER: "Adiado",
  CONFIRM: "Confirmado",
  CORRECT: "Corrigido",
  MARK_REVIEWED: "Marcado como revisado",
  MARK_READY_FOR_REVIEW: "Enviado para revisão",
  SUPERSEDE: "Substituído",
  FINALIZE: "Finalizado",
  DELIVER: "Entregue",
};

const AUTHORITY_LABELS: Record<string, string> = {
  DOCUMENTED: "Documentado nos autos",
  ALLEGED: "Alegado",
  OBSERVED: "Observado em vistoria",
  MEASURED: "Medido",
  TECHNICALLY_FOUND: "Constatado tecnicamente",
  PROFESSIONAL_DECISION: "Decisão profissional",
  AI_PROPOSAL: "Proposta automática",
  SOURCE_VALUE: "Valor da fonte",
  ENGINE_DECISION: "Decisão do motor",
  PROFESSIONAL_OVERRIDE: "Ajuste profissional",
};

const SOURCE_KIND_LABELS: Record<string, string> = {
  ALLEGATION: "Alegação",
  COURT_DECISION: "Decisão judicial",
  CASE_DOCUMENT: "Documento do processo",
  FIELD_OBSERVATION: "Observação de campo",
  MEASUREMENT: "Medição",
  PHOTO: "Fotografia",
  PHOTOGRAPH: "Fotografia",
  TECHNICAL_FINDING: "Achado técnico",
  PATHOLOGY: "Análise de manifestação (PAT)",
  PROFESSIONAL_DECISION: "Decisão profissional",
  DOCUMENTED_ALLEGATION: "Alegação documentada",
  DIRECT_OBSERVATION: "Observação direta",
  STATEMENT: "Declaração",
  NOTE: "Nota",
};

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  PETICAO: "Petição",
  PETICAO_INICIAL: "Petição inicial",
  DECISAO: "Decisão",
  DESPACHO: "Despacho",
  SENTENCA: "Sentença",
  CONTESTACAO: "Contestação",
  LAUDO: "Laudo",
  QUESITOS: "Quesitos",
  CERTIDAO: "Certidão",
  ATA: "Ata",
  DOCUMENTO: "Documento",
  OUTROS: "Outros",
};

const ROLE_LABELS: Record<string, string> = {
  AUTORA: "Autora",
  AUTOR: "Autor",
  REU: "Réu",
  RE: "Ré",
  REQUERENTE: "Requerente",
  REQUERIDO: "Requerido",
  REQUERIDA: "Requerida",
  ADVOGADO: "Advogado",
  ADVOGADA: "Advogada",
  PROCURADOR: "Procurador",
  PROCURADORA: "Procuradora",
  TERCEIRO: "Terceiro",
  ACTIVE: "Polo ativo",
  PASSIVE: "Polo passivo",
  OTHER: "Outro polo",
  UNKNOWN: "Polo não identificado",
};

function humanize(code: string): string {
  const words = code.trim().replace(/[_\s]+/g, " ").toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : code;
}

function lookup(table: Record<string, string>, code: string | null | undefined): string {
  if (code === null || code === undefined || code === "") return "Não informado";
  return table[code] ?? table[code.toUpperCase()] ?? humanize(code);
}

export const stateLabel = (code: string | null | undefined) => lookup(STATE_LABELS, code);
export const actionLabel = (code: string | null | undefined) => lookup(ACTION_LABELS, code);
export const authorityLabel = (code: string | null | undefined) => lookup(AUTHORITY_LABELS, code);
export const sourceKindLabel = (code: string | null | undefined) => lookup(SOURCE_KIND_LABELS, code);
export const documentTypeLabel = (code: string | null | undefined) => lookup(DOCUMENT_TYPE_LABELS, code);
export const roleLabel = (code: string | null | undefined) => lookup(ROLE_LABELS, code);

export function plural(count: number, singular: string, pluralForm: string) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "Não informado";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
