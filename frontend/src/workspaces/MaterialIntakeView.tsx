import { useEffect, useRef, useState } from "react";

import {
  importCaseDocument,
  listCaseDocuments,
  listMaterialProcessing,
  materialUrl,
  MaterialApiError,
  retryMaterialProcessing,
  type MaterialMetadata,
  type MaterialProcessingState,
} from "../data/materials";
import { navigate } from "../app/router";
import { workspacePath } from "../routes/routeCatalog";
import { PjeDocumentAvailability } from "./PjeDocumentAvailability";

type MaterialIntakeViewProps = { workspaceId: string };
type ViewState =
  | { kind: "loading" }
  | { kind: "ready"; items: MaterialMetadata[] }
  | { kind: "error"; message: string };

function message(error: unknown) {
  return error instanceof MaterialApiError
    ? error.message
    : "Não foi possível concluir a operação local";
}

// Enquanto algum documento esta em leitura, o estado e reconsultado neste ritmo.
const PROCESSING_POLL_MS = 1500;

// Texto orientado a acao; nunca detalhe interno (#266).
const PROCESSING_LABEL: Record<MaterialProcessingState, string | null> = {
  READY: null,
  PROCESSING: "Documento recebido. Processando conteúdo localmente…",
  FAILED: "Não foi possível concluir a leitura deste documento.",
  INTERRUPTED: "A leitura deste documento foi interrompida antes de terminar.",
};

function withoutDuplicate(items: MaterialMetadata[], imported: MaterialMetadata) {
  // Reimportar os mesmos bytes devolve a MESMA fonte: a lista nao pode dobra-la.
  return items.some((item) => item.content_id === imported.content_id) ? items : [...items, imported];
}

function sizeLabel(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function MaterialIntakeView({ workspaceId }: MaterialIntakeViewProps) {
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [inventoryRefresh, setInventoryRefresh] = useState(0);
  const importButton = useRef<HTMLButtonElement | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const activeImport = useRef<AbortController | null>(null);
  const [processing, setProcessing] = useState<Record<string, MaterialProcessingState>>({});
  const [processingCheck, setProcessingCheck] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const previous = useRef<Record<string, MaterialProcessingState>>({});

  useEffect(() => {
    const controller = new AbortController();
    listCaseDocuments(workspaceId, controller.signal).then(
      (items) => { if (!controller.signal.aborted) setState({ kind: "ready", items }); },
      (error) => {
        if (!controller.signal.aborted) {
          setState({ kind: "error", message: message(error) });
        }
      },
    );
    return () => {
      controller.abort();
      activeImport.current?.abort();
      activeImport.current = null;
    };
  }, [workspaceId, attempt]);

  // O estado da leitura vem do produto, nao desta aba: recarregar a pagina ou
  // reabrir a pericia mostra o mesmo estado (#266).
  const ready = state.kind === "ready";
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    let retryTimer: number | undefined;
    listMaterialProcessing(workspaceId, controller.signal).then(
      (states) => {
        if (controller.signal.aborted) return;
        const finished = Object.entries(states).some(
          ([id, value]) => value === "READY" && previous.current[id] === "PROCESSING",
        );
        previous.current = states;
        setProcessing(states);
        if (finished) {
          setNotice("Processamento concluído.");
          setInventoryRefresh((value) => value + 1);
        }
      },
      () => {
        // Uma consulta que falhou nao pode congelar a tela em "processando":
        // nova tentativa no mesmo ritmo enquanto houver leitura em curso.
        if (!controller.signal.aborted && Object.values(previous.current).includes("PROCESSING")) {
          retryTimer = window.setTimeout(() => setProcessingCheck((value) => value + 1), PROCESSING_POLL_MS);
        }
      },
    );
    return () => {
      controller.abort();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [workspaceId, ready, processingCheck]);

  const anyProcessing = Object.values(processing).includes("PROCESSING");
  useEffect(() => {
    if (!anyProcessing) return;
    const timer = window.setTimeout(() => setProcessingCheck((value) => value + 1), PROCESSING_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [anyProcessing, processing]);

  async function refreshAfterUnconfirmedImport() {
    try {
      const items = await listCaseDocuments(workspaceId);
      setState({ kind: "ready", items });
    } catch {
      // A mensagem ja pede conferencia; uma lista indisponivel nao a contradiz.
    }
    setProcessingCheck((value) => value + 1);
  }

  async function retry(contentId: string) {
    if (retrying !== null) return;
    setRetrying(contentId);
    setNotice(null);
    try {
      const value = await retryMaterialProcessing(workspaceId, contentId);
      setProcessing((current) => ({ ...current, [contentId]: value }));
      previous.current = { ...previous.current, [contentId]: "PROCESSING" };
      setProcessingCheck((current) => current + 1);
    } catch (error) {
      setNotice(message(error));
    } finally {
      setRetrying(null);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === null || importing || state.kind !== "ready") return;
    const controller = new AbortController();
    activeImport.current = controller;
    setImporting(true);
    setImportError(null);
    try {
      const imported = await importCaseDocument(workspaceId, selected, controller.signal);
      if (!controller.signal.aborted) {
        setState((current) => current.kind === "ready"
          ? { kind: "ready", items: withoutDuplicate(current.items, imported) }
          : current);
        setSelected(null);
        setNotice(null);
        previous.current = { ...previous.current, [imported.content_id]: "PROCESSING" };
        setProcessingCheck((value) => value + 1);
        setInventoryRefresh((value) => value + 1);
        if (fileInput.current !== null) fileInput.current.value = "";
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setImportError(message(error));
        if (error instanceof MaterialApiError && error.kind === "unconfirmed") {
          void refreshAfterUnconfirmedImport();
        }
      }
    } finally {
      if (!controller.signal.aborted) {
        setImporting(false);
        requestAnimationFrame(() => importButton.current?.focus());
      }
      if (activeImport.current === controller) activeImport.current = null;
    }
  }

  if (state.kind === "loading") {
    return (
      <section className="status-state status-state--loading" role="status" aria-live="polite">
        <span className="state-rule" aria-hidden="true" />
        <div><h2>Carregando materiais</h2><p>Recuperando os documentos desta perícia.</p></div>
      </section>
    );
  }
  if (state.kind === "error") {
    return (
      <section className="status-state status-state--error" role="alert">
        <span className="state-mark" aria-hidden="true">!</span>
        <div>
          <h2>Não foi possível carregar os materiais</h2>
          <p>{state.message}</p>
          <button
            className="text-action"
            type="button"
            onClick={() => {
              setState({ kind: "loading" });
              setAttempt((value) => value + 1);
            }}
          >
            Tentar novamente
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="material-intake" aria-labelledby="material-intake-title">
      <div className="material-intake-heading">
        <div>
          <h2 id="material-intake-title">Documentos do processo</h2>
          <p>Importe PDFs recebidos para mantê-los vinculados somente a esta perícia.</p>
        </div>
        <form className="material-import-form" onSubmit={submit}>
          <label htmlFor="material-file">Selecionar PDF</label>
          <input
            id="material-file"
            ref={fileInput}
            type="file"
            accept=".pdf,application/pdf"
            disabled={importing}
            onChange={(event) => {
              setSelected(event.currentTarget.files?.[0] ?? null);
              setImportError(null);
            }}
          />
          <button
            ref={importButton}
            className="primary-action"
            type="submit"
            disabled={selected === null || importing}
          >
            {importing ? "Processando PDF…" : "Importar PDF"}
          </button>
        </form>
      </div>
      {importing ? (
        <p className="material-import-status" role="status" aria-live="polite">
          Leitura local em andamento. OCR será usado somente nas páginas sem texto útil.
        </p>
      ) : null}
      {importError ? <p className="material-message material-message--error" role="alert">{importError}</p> : null}
      {notice ? <p className="material-import-status" role="status" aria-live="polite">{notice}</p> : null}
      {state.items.length === 0 ? (
        <div className="material-empty">
          <span className="state-mark" aria-hidden="true">PDF</span>
          <div><h3>Nenhum documento importado</h3><p>Selecione o primeiro PDF dos autos para começar.</p></div>
        </div>
      ) : (
        <>
          <div className="material-review-action">
            <p>A identificação disponível foi extraída localmente e aguarda sua conferência.</p>
            <a
              className="text-action"
              href={workspacePath(workspaceId, "processo")}
              onClick={navigate}
            >
              Revisar dados extraídos
            </a>
          </div>
          <ul className="material-list">
            {state.items.map((item) => (
            <li key={item.content_id}>
              <div>
                <strong>{item.original_filename}</strong>
                <span>{sizeLabel(item.byte_size)} · PDF · importado em {new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(new Date(item.imported_at))}</span>
                {processing[item.content_id] && PROCESSING_LABEL[processing[item.content_id]] ? (
                  <span
                    className={`material-processing material-processing--${processing[item.content_id].toLowerCase()}`}
                    role={processing[item.content_id] === "PROCESSING" ? "status" : undefined}
                  >
                    {PROCESSING_LABEL[processing[item.content_id]]}
                  </span>
                ) : null}
                {processing[item.content_id] === "FAILED" || processing[item.content_id] === "INTERRUPTED" ? (
                  <button
                    className="text-action"
                    type="button"
                    disabled={retrying !== null}
                    onClick={() => void retry(item.content_id)}
                    aria-label={`Tentar novamente a leitura de ${item.original_filename}`}
                  >
                    {retrying === item.content_id ? "Iniciando…" : "Tentar novamente"}
                  </button>
                ) : null}
              </div>
              <a
                className="text-action"
                href={materialUrl(workspaceId, item.content_id)}
                target="_blank"
                rel="noreferrer"
                aria-label={`Abrir ${item.original_filename}`}
              >
                Abrir PDF
              </a>
            </li>
            ))}
          </ul>
          <PjeDocumentAvailability workspaceId={workspaceId} refreshKey={inventoryRefresh} />
        </>
      )}
    </section>
  );
}
