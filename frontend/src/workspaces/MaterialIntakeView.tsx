import { useEffect, useRef, useState } from "react";

import {
  importCaseDocument,
  listCaseDocuments,
  materialUrl,
  MaterialApiError,
  type MaterialMetadata,
} from "../data/materials";
import { navigate } from "../app/router";
import { workspacePath } from "../routes/routeCatalog";

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
  const importButton = useRef<HTMLButtonElement | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const activeImport = useRef<AbortController | null>(null);

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
          ? { kind: "ready", items: [...current.items, imported] }
          : current);
        setSelected(null);
        if (fileInput.current !== null) fileInput.current.value = "";
      }
    } catch (error) {
      if (!controller.signal.aborted) setImportError(message(error));
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
        </>
      )}
    </section>
  );
}
