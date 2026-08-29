import { useEffect, useRef, useState } from "react";

import {
  getProcessCase,
  ProcessCaseApiError,
  type ProcessCaseData,
  type ProcessCaseSnapshot,
  saveProcessCase,
} from "../data/processCase";
import {
  confirmProcessMetadataSourceSpan,
  getProcessMetadataReview,
  ProcessMetadataApiError,
  type ProcessMetadataEvidence,
  type ProcessMetadataReview,
} from "../data/processMetadata";
import { navigate } from "../app/router";
import { workspacePath } from "../routes/routeCatalog";

type ProcessCaseViewProps = {
  workspaceId: string;
};

const FIELDS: readonly {
  key: keyof ProcessCaseData;
  label: string;
  autoComplete?: string;
}[] = [
  { key: "numero_processo", label: "Número do processo" },
  { key: "ramo_justica", label: "Ramo da Justiça" },
  { key: "tribunal", label: "Tribunal" },
  { key: "vara", label: "Vara" },
  { key: "municipio_sede", label: "Município-sede" },
  { key: "subsecao_judiciaria", label: "Subseção judiciária" },
  { key: "comarca_municipio", label: "Comarca ou município" },
  { key: "uf", label: "UF" },
  { key: "parte_requerente", label: "Parte requerente" },
  { key: "parte_requerida", label: "Parte requerida" },
];

function distinctReviewCandidates(evidence: readonly ProcessMetadataEvidence[]) {
  const candidates = new Map<string, ProcessMetadataEvidence>();
  for (const candidate of evidence) {
    if (
      !candidate.requires_source_selection
      && candidate.extracted_value
      && !candidates.has(candidate.extracted_value)
    ) {
      candidates.set(candidate.extracted_value, candidate);
    }
  }
  return Array.from(candidates.values());
}

type SourceSelectionState = {
  field: "parte_requerente" | "parte_requerida";
  label: string;
  evidence: ProcessMetadataEvidence;
  start: number;
  end: number;
  kind: "selecting" | "saving" | "error";
  message?: string;
};

function utf16OffsetToCodePoint(text: string, offset: number) {
  return Array.from(text.slice(0, offset)).length;
}

function selectedSourceText(selection: SourceSelectionState) {
  return Array.from(selection.evidence.source_text)
    .slice(selection.start, selection.end)
    .join("");
}

type ViewState =
  | { kind: "loading" }
  | {
      kind: "ready";
      workspaceId: string;
      snapshot: ProcessCaseSnapshot;
      review: ProcessMetadataReview;
      draft: ProcessCaseData;
    }
  | { kind: "load-error"; workspaceId: string; message: string };

type SaveState =
  | { kind: "idle" }
  | { kind: "saving"; workspaceId: string }
  | { kind: "saved"; workspaceId: string }
  | { kind: "error"; workspaceId: string; message: string };

function errorMessage(error: unknown) {
  return error instanceof ProcessCaseApiError || error instanceof ProcessMetadataApiError
    ? error.message
    : "Não foi possível concluir a operação local";
}

function initialDraft(snapshot: ProcessCaseSnapshot, review: ProcessMetadataReview) {
  return Object.fromEntries(FIELDS.map(({ key }) => {
    const manual = snapshot.data[key];
    const extracted = review.fields[key];
    return [
      key,
      snapshot.revision !== null
        ? manual
        : manual || (extracted.state === "CONFIDENT" ? extracted.value : ""),
    ];
  })) as ProcessCaseData;
}

const REVIEW_LABELS: Record<ProcessMetadataReview["state"], string> = {
  WAITING_FOR_DOCUMENTS: "Aguardando documentos do processo",
  EXTRACTING: "Extraindo identificação local",
  EXTRACTED: "Dados extraídos para revisão",
  PARTIAL: "Extração parcial para revisão",
  CONFLICT: "Conflitos documentais exigem revisão",
  CONFIRMED: "Dados processuais confirmados",
  ERROR: "Não foi possível extrair a camada de texto",
};

export function ProcessCaseView({ workspaceId }: ProcessCaseViewProps) {
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [sourceSelection, setSourceSelection] = useState<SourceSelectionState | null>(null);
  const [sourceConfirmation, setSourceConfirmation] = useState<string | null>(null);
  const activeSave = useRef<AbortController | null>(null);
  const activeSourceSave = useRef<AbortController | null>(null);
  const saveButton = useRef<HTMLButtonElement | null>(null);
  const sourceText = useRef<HTMLTextAreaElement | null>(null);
  const sourceReturnFocus = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const snapshot = await getProcessCase(workspaceId, controller.signal);
        const review = await getProcessMetadataReview(workspaceId, controller.signal);
        if (!controller.signal.aborted) {
          setState({
            kind: "ready",
            workspaceId,
            snapshot,
            review,
            draft: initialDraft(snapshot, review),
          });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setState({
            kind: "load-error",
            workspaceId,
            message: errorMessage(error),
          });
        }
      }
    })();
    return () => {
      controller.abort();
      const pendingSave = activeSave.current;
      if (pendingSave !== null) {
        pendingSave.abort();
        activeSave.current = null;
        setSaveState((current) =>
          current.kind === "saving" && current.workspaceId === workspaceId
            ? { kind: "idle" }
            : current,
        );
      }
      const pendingSourceSave = activeSourceSave.current;
      if (pendingSourceSave !== null) {
        pendingSourceSave.abort();
        activeSourceSave.current = null;
      }
      setSourceSelection(null);
      setSourceConfirmation(null);
    };
  }, [workspaceId, loadAttempt]);

  useEffect(() => {
    if (sourceSelection?.kind === "selecting") {
      sourceText.current?.focus();
    }
  }, [
    sourceSelection?.field,
    sourceSelection?.evidence.evidence_id,
    sourceSelection?.kind,
  ]);

  useEffect(() => {
    if (
      (saveState.kind === "saved" || saveState.kind === "error") &&
      saveState.workspaceId === workspaceId
    ) {
      saveButton.current?.focus();
    }
  }, [saveState, workspaceId]);

  function update(field: keyof ProcessCaseData, value: string) {
    setState((current) =>
      current.kind === "ready" && current.workspaceId === workspaceId
        ? { ...current, draft: { ...current.draft, [field]: value } }
        : current,
    );
    setSaveState({ kind: "idle" });
    setSourceConfirmation(null);
  }

  function cancelSourceSelection() {
    const field = sourceSelection?.field;
    sourceReturnFocus.current = field ?? null;
    setSourceSelection(null);
  }

  async function confirmSourceSelection() {
    if (
      state.kind !== "ready"
      || state.workspaceId !== workspaceId
      || sourceSelection === null
      || sourceSelection.kind === "saving"
    ) return;
    const selected = selectedSourceText(sourceSelection);
    if (!selected.trim()) return;
    const controller = new AbortController();
    activeSourceSave.current = controller;
    setSourceSelection({ ...sourceSelection, kind: "saving", message: undefined });
    try {
      const snapshot = await confirmProcessMetadataSourceSpan(
        workspaceId,
        {
          field_name: sourceSelection.field,
          evidence_id: sourceSelection.evidence.evidence_id,
          source_start: sourceSelection.start,
          source_end: sourceSelection.end,
          expected_source_revision: state.review.extraction_fingerprint,
          expected_revision: state.snapshot.revision,
        },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        const field = sourceSelection.field;
        setState((current) =>
          current.kind === "ready" && current.workspaceId === workspaceId
            ? {
              ...current,
              snapshot,
              draft: {
                ...current.draft,
                [field]: snapshot.data[field],
              },
            }
            : current,
        );
        setSourceSelection(null);
        setSourceConfirmation(field);
        setSaveState({ kind: "idle" });
        requestAnimationFrame(() => {
          document.getElementById(`process-case-${field}`)?.focus();
        });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setSourceSelection({
          ...sourceSelection,
          kind: "error",
          message: errorMessage(error),
        });
      }
    } finally {
      if (activeSourceSave.current === controller) activeSourceSave.current = null;
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const saving = saveState.kind === "saving" && saveState.workspaceId === workspaceId;
    if (state.kind !== "ready" || state.workspaceId !== workspaceId || saving) return;
    const controller = new AbortController();
    activeSave.current = controller;
    setSaveState({ kind: "saving", workspaceId });
    try {
      const snapshot = await saveProcessCase(
        workspaceId,
        state.draft,
        state.snapshot.revision,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setState({
          kind: "ready",
          workspaceId,
          snapshot,
          review: {
            ...state.review,
            state: "CONFIRMED",
            confirmed_revision: snapshot.revision,
          },
          draft: { ...snapshot.data },
        });
        setSaveState({ kind: "saved", workspaceId });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setSaveState({ kind: "error", workspaceId, message: errorMessage(error) });
      }
    } finally {
      if (activeSave.current === controller) activeSave.current = null;
    }
  }

  const visibleState =
    state.kind !== "loading" && state.workspaceId !== workspaceId
      ? ({ kind: "loading" } as const)
      : state;
  const saving = saveState.kind === "saving" && saveState.workspaceId === workspaceId;
  const saveError =
    saveState.kind === "error" && saveState.workspaceId === workspaceId
      ? saveState.message
      : undefined;
  const saved = saveState.kind === "saved" && saveState.workspaceId === workspaceId;
  const review = visibleState.kind === "ready" ? visibleState.review : undefined;

  if (visibleState.kind === "loading") {
    return (
      <section className="status-state status-state--loading" role="status" aria-live="polite">
        <span className="state-rule" aria-hidden="true" />
        <div>
          <h2>Carregando dados do processo</h2>
          <p>Recuperando a identificação processual deste workspace.</p>
        </div>
      </section>
    );
  }

  if (visibleState.kind === "load-error") {
    return (
      <section className="status-state status-state--error" role="alert">
        <span className="state-mark" aria-hidden="true">!</span>
        <div>
          <h2>Não foi possível carregar os dados do processo</h2>
          <p>{visibleState.message}</p>
          <button
            className="text-action"
            type="button"
            onClick={() => {
              setState({ kind: "loading" });
              setLoadAttempt((attempt) => attempt + 1);
            }}
          >
            Tentar novamente
          </button>
        </div>
      </section>
    );
  }

  return (
    <form className="process-case-form" onSubmit={submit}>
      <div className="process-case-intro">
        <h2>Identificação do processo</h2>
        <p>Revise os dados extraídos dos autos. Corrija apenas o que o documento não informou corretamente.</p>
      </div>
      {review ? (
        <section
          className={`metadata-review-state metadata-review-state--${review.state.toLowerCase()}`}
          role={review.state === "CONFLICT" || review.state === "ERROR" ? "alert" : "status"}
        >
          <div>
            <strong>{REVIEW_LABELS[review.state]}</strong>
            {review.state === "WAITING_FOR_DOCUMENTS" ? (
              <p>Importe os PDFs dos autos para preencher a identificação automaticamente.</p>
            ) : (
              <p>Confira os valores e suas fontes antes de confirmar.</p>
            )}
          </div>
          {review.state === "WAITING_FOR_DOCUMENTS" ? (
            <a
              className="text-action"
              href={workspacePath(workspaceId, "materiais")}
              onClick={navigate}
            >
              Importar documentos
            </a>
          ) : null}
        </section>
      ) : null}
      {review?.documents
        .filter((document) => document.text_state !== "AVAILABLE")
        .map((document) => (
          <section
            className="metadata-document-notice"
            key={document.document_id}
            role={document.text_state === "ERROR" ? "alert" : "status"}
          >
            <strong>{document.source_filename}</strong>
            <span>
              {document.text_state === "TEXT_EXTRACTION_UNAVAILABLE"
                ? "O OCR local não conseguiu obter texto utilizável. Revise o arquivo ou importe uma cópia legível."
                : "A extração local deste PDF não pôde ser concluída."}
            </span>
          </section>
        ))}
      <div className="process-case-fields">
        {FIELDS.map((field) => {
          const extracted = review?.fields[field.key];
          const reviewCandidates = extracted?.state === "AMBIGUOUS"
            || extracted?.state === "CONFLICTING"
            ? distinctReviewCandidates(extracted.evidence)
            : [];
          const sourceEvidence = extracted?.evidence.filter(
            (evidence) => evidence.requires_source_selection,
          ) ?? [];
          const manualValue = visibleState.snapshot.data[field.key];
          const manualConflict = Boolean(
            manualValue
            && extracted?.state === "CONFIDENT"
            && extracted.value
            && manualValue !== extracted.value,
          );
          return (
          <div className={`field-group${manualConflict ? " field-group--conflict" : ""}`} key={field.key}>
            <label htmlFor={`process-case-${field.key}`}>{field.label}</label>
            <input
              id={`process-case-${field.key}`}
              name={field.key}
              type="text"
              value={visibleState.draft[field.key]}
              disabled={saving}
              onChange={(event) => update(field.key, event.currentTarget.value)}
            />
            {extracted?.evidence[0] && reviewCandidates.length === 0 ? (
              <p className="field-provenance">
                {extracted.evidence[0].extraction_mode === "OCR" ? "Extraído por OCR local de " : "Extraído de "}
                {extracted.evidence[0].source_filename}, página {extracted.evidence[0].source_page}
              </p>
            ) : null}
            {manualConflict && extracted ? (
              <div className="field-conflict" role="status">
                <span>Valor informado difere do documento.</span>
                <button
                  className="text-action"
                  type="button"
                  disabled={saving}
                  onClick={() => update(field.key, extracted.value)}
                >
                  Usar valor extraído para {field.label}
                </button>
              </div>
            ) : null}
            {reviewCandidates.length > 0 ? (
              <div
                className="field-conflict"
                role={extracted?.state === "CONFLICTING" ? "alert" : "status"}
              >
                <span>
                  {extracted?.state === "CONFLICTING"
                    ? "Os documentos apresentam valores diferentes."
                    : "Candidato extraído — confira a fonte antes de usar."}
                </span>
                {reviewCandidates.map((candidate) => (
                  <button
                    className="text-action"
                    type="button"
                    key={candidate.extracted_value}
                    disabled={saving}
                    onClick={() => update(field.key, candidate.extracted_value)}
                  >
                    Usar {candidate.extracted_value} — {candidate.source_filename}, página {candidate.source_page}
                  </button>
                ))}
              </div>
            ) : null}
            {sourceEvidence.map((evidence) => {
              const active = sourceSelection?.evidence.evidence_id === evidence.evidence_id;
              const selected = active && sourceSelection ? selectedSourceText(sourceSelection) : "";
              return (
                <div className="source-evidence" key={evidence.evidence_id}>
                  <div className="source-evidence__summary">
                    <strong>Fonte ambígua</strong>
                    <span>
                      {evidence.source_filename}, página {evidence.source_page}. A fonte não permite
                      separar automaticamente a parte.
                    </span>
                  </div>
                  {!active ? (
                    <button
                      ref={(node) => {
                        if (node && sourceReturnFocus.current === field.key) {
                          sourceReturnFocus.current = null;
                          node.focus();
                        }
                      }}
                      id={`source-span-trigger-${field.key}`}
                      className="text-action"
                      type="button"
                      disabled={saving}
                      onClick={() => {
                        if (field.key !== "parte_requerente" && field.key !== "parte_requerida") return;
                        setSourceConfirmation(null);
                        setSourceSelection({
                          field: field.key,
                          label: field.label,
                          evidence,
                          start: 0,
                          end: 0,
                          kind: "selecting",
                        });
                      }}
                    >
                      Selecionar trecho da fonte para {field.label}
                    </button>
                  ) : sourceSelection ? (
                    <div className="source-span-review">
                      <label htmlFor={`source-span-${evidence.evidence_id}`}>
                        Selecione na fonte o trecho correspondente à parte.
                      </label>
                      <textarea
                        ref={sourceText}
                        id={`source-span-${evidence.evidence_id}`}
                        aria-label={`Fonte para ${field.label}`}
                        aria-readonly="true"
                        value={evidence.source_text}
                        disabled={sourceSelection.kind === "saving"}
                        onBeforeInput={(event) => event.preventDefault()}
                        onChange={() => undefined}
                        onCut={(event) => event.preventDefault()}
                        onDrop={(event) => event.preventDefault()}
                        onPaste={(event) => event.preventDefault()}
                        onSelect={(event) => {
                          const control = event.currentTarget;
                          const start = utf16OffsetToCodePoint(
                            evidence.source_text,
                            control.selectionStart,
                          );
                          const end = utf16OffsetToCodePoint(
                            evidence.source_text,
                            control.selectionEnd,
                          );
                          setSourceSelection((current) => current === null ? current : {
                            ...current,
                            start,
                            end,
                            kind: "selecting",
                            message: undefined,
                          });
                        }}
                      />
                      <p className="source-span-review__selection" role="status" aria-live="polite">
                        {selected
                          ? `Trecho selecionado: ${selected}`
                          : "Nenhum trecho selecionado."}
                      </p>
                      {sourceSelection.message ? (
                        <p className="field-error" role="alert">{sourceSelection.message}</p>
                      ) : null}
                      <div className="source-span-review__actions">
                        <button
                          className="primary-action"
                          type="button"
                          disabled={sourceSelection.kind === "saving" || !selected.trim()}
                          onClick={() => void confirmSourceSelection()}
                        >
                          {sourceSelection.kind === "saving"
                            ? "Confirmando trecho…"
                            : `Confirmar trecho para ${field.label}`}
                        </button>
                        <button
                          className="text-action"
                          type="button"
                          disabled={sourceSelection.kind === "saving"}
                          onClick={cancelSourceSelection}
                        >
                          Cancelar seleção para {field.label}
                        </button>
                      </div>
                    </div>
                  ) : null}
                  {sourceConfirmation === field.key ? (
                    <p className="source-evidence__confirmed" role="status">
                      Trecho da fonte confirmado
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
          );
        })}
      </div>
      {saveError ? <p className="process-case-message process-case-message--error" role="alert">{saveError}</p> : null}
      {saved ? (
        <p className="process-case-message" role="status">
          <strong>Dados do processo confirmados</strong>
          {visibleState.snapshot.revision === null ? null : (
            <span>Revisão {visibleState.snapshot.revision}</span>
          )}
        </p>
      ) : null}
      <div className="form-actions">
        <button ref={saveButton} className="primary-action" type="submit" disabled={saving}>
          {saving ? "Confirmando…" : "Confirmar dados do processo"}
        </button>
        {!saved && visibleState.snapshot.revision !== null ? (
          <span className="revision-note">Revisão atual {visibleState.snapshot.revision}</span>
        ) : null}
      </div>
    </form>
  );
}
