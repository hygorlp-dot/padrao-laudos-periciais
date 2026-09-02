import { useEffect, useState } from "react";
import { getPjeIntake, setPjeDocumentAvailability, type PjeIntakeEnvelope } from "../data/pjeIntake";

type LoadState =
  | { kind: "loading" }
  | { kind: "absent" }
  | { kind: "unreadable" }
  | { kind: "ready"; value: PjeIntakeEnvelope };

export function PjeDocumentAvailability({ workspaceId, refreshKey }: { workspaceId: string; refreshKey: number }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [loaded, setLoaded] = useState<{ key: string; state: LoadState } | null>(null);
  const loadKey = `${workspaceId}:${refreshKey}:${reloadKey}`;
  useEffect(() => {
    const controller = new AbortController();
    getPjeIntake(workspaceId, controller.signal).then(
      (value) => setLoaded({ key: loadKey, state: value === null ? { kind: "absent" } : { kind: "ready", value } }),
      // Um workspace sem PJe devolve null acima. Chegar aqui significa leitura
      // falha, que não pode ser exibida como "não há documentos".
      () => { if (!controller.signal.aborted) setLoaded({ key: loadKey, state: { kind: "unreadable" } }); },
    );
    return () => controller.abort();
  }, [workspaceId, loadKey]);

  // Derivar em vez de setar: enquanto a carga corrente não chega, o inventário
  // de um workspace anterior nunca aparece como se fosse deste.
  const state: LoadState = loaded !== null && loaded.key === loadKey ? loaded.state : { kind: "loading" };

  if (state.kind === "loading" || state.kind === "absent") return null;
  if (state.kind === "unreadable") {
    return <section className="pje-document-availability" aria-labelledby="pje-documents-title">
      <div><h3 id="pje-documents-title">Documentos identificados no PJe</h3></div>
      <p role="alert">Não foi possível ler os documentos identificados no processo.</p>
      <button type="button" onClick={() => setReloadKey((key) => key + 1)}>Tentar novamente</button>
    </section>;
  }

  const envelope = state.value;
  async function toggle(documentId: string, available: boolean) {
    if (busy !== null) return;
    setBusy(documentId); setError(false);
    try {
      setLoaded({ key: loadKey, state: { kind: "ready", value: await setPjeDocumentAvailability(workspaceId, envelope, documentId, available) } });
    } catch {
      // A revisão em mãos pode ter ficado velha (outra alteração venceu a
      // corrida). Recarregar evita que a tela fique presa em conflito.
      setError(true);
      setReloadKey((key) => key + 1);
    } finally { setBusy(null); }
  }

  return <section className="pje-document-availability" aria-labelledby="pje-documents-title">
    <div><h3 id="pje-documents-title">Documentos identificados no PJe</h3><p>Desative um documento para mantê-lo fora da análise sem removê-lo do processo.</p></div>
    {error ? <p role="alert">Não foi possível salvar a disponibilidade. A lista foi recarregada; tente novamente.</p> : null}
    <ul>{envelope.inventory.documents.map((item) => <li key={item.document_id}>
      <div><strong>{item.title}</strong><span>PJe {item.id_pje} · páginas {item.page_start}–{item.page_end}</span></div>
      <label><input type="checkbox" checked={item.available} disabled={busy !== null} onChange={(event) => void toggle(item.document_id, event.currentTarget.checked)} /> Disponível para análise</label>
    </li>)}</ul>
    {busy ? <p role="status">Salvando disponibilidade…</p> : null}
  </section>;
}
