import { useEffect, useState } from "react";
import { getPjeIntake, setPjeDocumentAvailability, type PjeIntakeEnvelope } from "../data/pjeIntake";

export function PjeDocumentAvailability({ workspaceId, refreshKey }: { workspaceId: string; refreshKey: number }) {
  const [value, setValue] = useState<PjeIntakeEnvelope | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => { const controller = new AbortController(); getPjeIntake(workspaceId, controller.signal).then(setValue, () => undefined); return () => controller.abort(); }, [workspaceId, refreshKey]);
  if (value === null) return null;
  async function toggle(documentId: string, available: boolean) {
    if (value === null || busy !== null) return;
    setBusy(documentId); setError(false);
    try { setValue(await setPjeDocumentAvailability(workspaceId, value, documentId, available)); }
    catch { setError(true); }
    finally { setBusy(null); }
  }
  return <section className="pje-document-availability" aria-labelledby="pje-documents-title">
    <div><h3 id="pje-documents-title">Documentos identificados no PJe</h3><p>Desative um documento para mantê-lo fora da análise sem removê-lo do processo.</p></div>
    {error ? <p role="alert">Não foi possível salvar a disponibilidade. Tente novamente.</p> : null}
    <ul>{value.inventory.documents.map((item) => <li key={item.document_id}>
      <div><strong>{item.title}</strong><span>PJe {item.id_pje} · páginas {item.page_start}–{item.page_end}</span></div>
      <label><input type="checkbox" checked={item.available} disabled={busy !== null} onChange={(event) => void toggle(item.document_id, event.currentTarget.checked)} /> Disponível para análise</label>
    </li>)}</ul>
    {busy ? <p role="status">Salvando disponibilidade…</p> : null}
  </section>;
}
