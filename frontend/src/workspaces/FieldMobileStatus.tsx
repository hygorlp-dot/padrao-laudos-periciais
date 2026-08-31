export type FieldSyncConflict = { code: string; message: string };

export function FieldMobileStatus({
  online,
  pendingCaptures,
  conflicts,
  onCapture,
}: {
  online: boolean;
  pendingCaptures: number;
  conflicts: FieldSyncConflict[];
  onCapture?: (kind: "observation" | "measurement" | "photo") => void;
}) {
  const pendingLabel = `${pendingCaptures} ${pendingCaptures === 1 ? "registro aguarda" : "registros aguardam"} sincronização`;
  return <aside className="field-mobile" aria-label="Estado da vistoria móvel">
    <div className="field-mobile__status" role="status" aria-live="polite">
      <span className={`field-mobile__signal ${online ? "is-online" : "is-offline"}`} aria-hidden="true" />
      <div><strong>{online ? "Conectado" : "Modo offline"}</strong><span>{pendingLabel}</span></div>
    </div>
    <div className="field-mobile__quick-actions" aria-label="Captura rápida">
      <button type="button" onClick={() => onCapture?.("observation")}>Registrar observação</button>
      <button type="button" onClick={() => onCapture?.("measurement")}>Adicionar medição</button>
      <button type="button" onClick={() => onCapture?.("photo")}>Associar foto</button>
    </div>
    {conflicts.length > 0 && <section className="field-mobile__conflicts" role="alert">
      <strong>Sincronização requer revisão</strong>
      <ul>{conflicts.map((conflict) => <li key={`${conflict.code}:${conflict.message}`}><code>{conflict.code}</code> {conflict.message}</li>)}</ul>
      <p>Nenhum registro material será sobrescrito automaticamente.</p>
    </section>}
  </aside>;
}
