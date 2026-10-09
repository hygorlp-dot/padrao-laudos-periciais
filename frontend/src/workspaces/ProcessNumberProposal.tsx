import type { ProcessNumberCandidate, ProcessNumberClassification, ProcessNumberOccurrence } from "../data/processNumber";

// #286: o número principal aparece separado dos processos citados. Nada é
// aplicado sozinho: "Usar" só preenche o campo, que o perito ainda confirma.

const CONTEXT_LABELS: Record<ProcessNumberOccurrence["context"], string> = {
  PJE_COVER: "Capa do PJe",
  JUDICIAL_HEADER: "Cabeçalho de peça judicial",
  CITATION: "Citação de julgado",
  DECLARED_RELATION: "Processo relacionado",
  UNQUALIFIED: "Menção no texto",
};

const CLASS_LABELS: Record<ProcessNumberCandidate["classification"], string> = {
  PRIMARY: "Número principal",
  CITED_CASE: "Precedente citado",
  RELATED_CASE: "Processo relacionado",
  UNKNOWN: "Sem classificação",
};

function counts(candidate: ProcessNumberCandidate) {
  const occurrences = `${candidate.occurrence_count} ocorrência${candidate.occurrence_count > 1 ? "s" : ""}`;
  const documents = `${candidate.document_count} documento${candidate.document_count > 1 ? "s" : ""}`;
  return `${occurrences} · ${documents}`;
}

function Source({ occurrence }: { occurrence: ProcessNumberOccurrence }) {
  return (
    <span className="process-number__source">
      {CONTEXT_LABELS[occurrence.context]} — {occurrence.filename}, p. {occurrence.page}
      {occurrence.extraction_mode === "OCR" ? " (OCR)" : ""}: <q>{occurrence.excerpt}</q>
    </span>
  );
}

function UseButton({ value, current, disabled, onUse, label }: { value: string; current: string; disabled: boolean; onUse: (value: string) => void; label: string }) {
  if (current === value) return <span className="process-number__in-use">Em uso no campo</span>;
  return (
    <button type="button" className="text-action" disabled={disabled} onClick={() => onUse(value)}>
      {label}
    </button>
  );
}

const UNRESOLVED_TEXT: Record<NonNullable<ProcessNumberClassification["unresolved_reason"]>, string> = {
  CONFLICTING_PRIMARY_SOURCES: "Os autos indicam mais de um número principal (capas ou cabeçalhos diferentes). Confira as fontes e escolha; nada foi preenchido.",
  NO_PRIMARY_SOURCE: "Nenhum número aparece na capa do PJe nem no cabeçalho de uma peça judicial. Os números encontrados estão abaixo; confira antes de usar.",
  READING_INCOMPLETE: "A leitura dos documentos ainda não terminou ou há páginas sem texto legível. O número principal pode estar nelas.",
  SOURCES_UNAVAILABLE: "Não foi possível reler os documentos agora. Tente novamente mais tarde; o campo continua editável.",
  LOW_CONFIDENCE_OCR: "O número da capa ou do cabeçalho foi lido por OCR com baixa confiança e não pode ser proposto como principal. Confira a página e digite o número.",
};

export function ProcessNumberProposal({ classification, current, disabled, onUse }: {
  classification: ProcessNumberClassification;
  current: string;
  disabled: boolean;
  onUse: (value: string) => void;
}) {
  const primary = classification.candidates.find((item) => item.classification === "PRIMARY");
  const contenders = classification.candidates.filter((item) => item.primary_evidence && item.classification !== "PRIMARY");
  const others = classification.candidates.filter((item) => item.classification !== "PRIMARY" && !item.primary_evidence);
  const incomplete = classification.pending_documents.length > 0 || classification.unread_pages.length > 0;
  return (
    <div className="process-number">
      {primary && classification.resolution === "RESOLVED" ? (
        <div className="process-number__primary" role="status">
          <span className="process-number__eyebrow">Número principal identificado</span>
          <strong className="process-number__value">{primary.value}</strong>
          <span>
            Confiança documental: {classification.confidence === "HIGH" ? "alta" : "média"} · {counts(primary)}
          </span>
          {primary.occurrences[0] ? <Source occurrence={primary.occurrences[0]} /> : null}
          {incomplete ? <span className="field-warning">Leitura incompleta: há documentos ou páginas ainda não lidos.</span> : null}
          <UseButton value={primary.value} current={current} disabled={disabled} onUse={onUse} label="Usar este número" />
        </div>
      ) : null}
      {classification.resolution === "NOT_FOUND" ? (
        <p className="field-hint" role="status">Nenhum número de processo válido foi encontrado nos documentos lidos.</p>
      ) : null}
      {classification.invalid_occurrences.length ? (
        <p className="field-warning" role="status">
          Número com dígito verificador inválido (truncado ou mal lido) em {classification.invalid_occurrences.map((item) => `${item.filename}, p. ${item.page}`).join("; ")}. Não foi proposto: confira a página.
        </p>
      ) : null}
      {classification.resolution === "UNRESOLVED" && classification.unresolved_reason ? (
        <p className="field-warning" role={classification.unresolved_reason === "CONFLICTING_PRIMARY_SOURCES" ? "alert" : "status"}>
          {UNRESOLVED_TEXT[classification.unresolved_reason]}
        </p>
      ) : null}
      {contenders.length ? (
        <ul className="process-number__list" aria-label="Números com indício de principal">
          {contenders.map((item) => (
            <li key={item.value}>
              <strong>{item.value}</strong> <span>{counts(item)}</span>
              {item.occurrences[0] ? <Source occurrence={item.occurrences[0]} /> : null}
              <UseButton value={item.value} current={current} disabled={disabled} onUse={onUse} label={`Usar ${item.value}`} />
            </li>
          ))}
        </ul>
      ) : null}
      {others.length ? (
        <details className="process-number__others">
          <summary>Outros processos citados nos autos ({others.length})</summary>
          <ul className="process-number__list">
            {others.map((item) => (
              <li key={item.value}>
                <strong>{item.value}</strong> <span className="process-number__class">{CLASS_LABELS[item.classification]}</span> <span>{counts(item)}</span>
                {item.occurrences[0] ? <Source occurrence={item.occurrences[0]} /> : null}
                {item.classification === "UNKNOWN" ? (
                  <UseButton value={item.value} current={current} disabled={disabled} onUse={onUse} label={`Usar ${item.value}`} />
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
