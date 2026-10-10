import type { DeliveryArtifact, DeliveryEnvelope } from "../data/deliverySnapshot";
import { artifactDownloadUrl } from "../data/deliverySnapshot";
import { plural } from "../ui/labels";
import { TechnicalDetails } from "../ui/TechnicalDetails";
import { DELIVERY_LABELS } from "./deliveryLabels";

const ROLE_LABELS: Record<string, string> = {
  MAIN_REPORT: "Laudo em Word", DERIVED_PDF: "PDF derivado do Word", ANNEX: "Anexo",
  PHOTO_APPENDIX: "Apêndice fotográfico", TECHNICAL_APPENDIX: "Apêndice técnico", SUPPORTING_FILE: "Arquivo de apoio",
};
const DECISION_LABELS: Record<string, string> = {
  MARK_READY_FOR_REVIEW: "Enviada para conferência", APPROVE: "Entrega aprovada", FINALIZE: "Arquivos finalizados",
  DELIVER: "Registrada como entregue", SUPERSEDE: "Substituída por nova revisão",
};

function formatBytes(value: number) {
  if (value < 1024) return `${value.toLocaleString("pt-BR")} bytes`;
  if (value < 1024 * 1024) return `${(value / 1024).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} KB`;
  return `${(value / (1024 * 1024)).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`;
}
function FriendlyTime({ value }: { value: string }) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? <span>Data não disponível</span> : <time dateTime={value}>{date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</time>;
}
function ArtifactRow({ artifact, workspaceId }: { artifact: DeliveryArtifact; workspaceId: string }) {
  return <div className="delivery-file-row"><div className="delivery-file-copy">
    <strong>{ROLE_LABELS[artifact.role] ?? "Arquivo do pacote"}</strong>
    <span className="delivery-filename">{artifact.filename}</span>
    <span>{artifact.format === "OTHER" ? artifact.media_type : artifact.format} · {formatBytes(artifact.byte_size)}</span>
    <TechnicalDetails><dl><dt>SHA-256</dt><dd><code>{artifact.checksum_sha256}</code></dd><dt>Identificador do conteúdo</dt><dd className="data">{artifact.content_id}</dd><dt>Identificador do arquivo</dt><dd className="data">{artifact.artifact_id}</dd><dt>Tipo de mídia</dt><dd>{artifact.media_type}</dd><dt>Tamanho em bytes</dt><dd>{artifact.byte_size}</dd></dl></TechnicalDetails>
  </div><a className="text-action" href={artifactDownloadUrl(workspaceId, artifact.content_id)} download={artifact.filename}>Baixar {artifact.role === "MAIN_REPORT" ? "Word" : artifact.role === "DERIVED_PDF" ? "PDF" : "arquivo"}</a></div>;
}

export function DeliveryFiles({ value, workspaceId, busy, onRender }: { value: DeliveryEnvelope; workspaceId: string; busy: boolean; onRender: () => void }) {
  const { snapshot } = value;
  const word = snapshot.artifacts.find((a) => a.role === "MAIN_REPORT");
  const pdf = snapshot.artifacts.find((a) => a.role === "DERIVED_PDF");
  const supporting = snapshot.artifacts.filter((a) => a.role !== "MAIN_REPORT" && a.role !== "DERIVED_PDF");
  const historical = snapshot.state === "STALE" || snapshot.state === "SUPERSEDED";
  return <section className="delivery-files" aria-labelledby="package-title">
    <h3 id="package-title">Pacote da entrega</h3>
    {historical && <p className="delivery-historical-note">Arquivos preservados desta entrega anterior. Não são apresentados como atuais.</p>}
    <section className="delivery-official" aria-labelledby="official-title">
      <h4 id="official-title">Documento oficial</h4>
      {word ? <><p className="delivery-readiness">Word pronto</p><ArtifactRow artifact={word} workspaceId={workspaceId} /></> : <p>Word ainda não gerado. Gerar os arquivos não aprova, finaliza ou registra a entrega.</p>}
    </section>
    <section className="delivery-pdf" aria-labelledby="pdf-title">
      <h4 id="pdf-title">PDF derivado do Word</h4>
      {pdf ? <><p className="delivery-readiness">Conferido</p><p>Gerado a partir deste Word e conferido pelo sistema. O Word continua sendo o documento oficial.</p><ArtifactRow artifact={pdf} workspaceId={workspaceId} /></>
        : word ? <><p className="delivery-readiness">PDF indisponível</p><p>O Word está pronto e pode ser baixado. A conversão local ou a conferência do PDF não foi concluída; nenhum PDF parcial é disponibilizado.</p>
          {snapshot.state === "DRAFT" && <button className="text-action" type="button" aria-disabled={busy} onClick={() => { if (!busy) onRender(); }}>Tentar gerar o PDF novamente</button>}
          <TechnicalDetails summary="Ver detalhes da conversão"><p>A geração usa o Microsoft Word desta máquina. Falta de disponibilidade, timeout ou recusa na conferência de fidelidade deixam o PDF indisponível. A tentativa gera novamente o Word e o PDF desta entrega em preparação.</p></TechnicalDetails></>
          : <p>O PDF poderá ser derivado depois de gerar o Word e conferir o resultado.</p>}
    </section>
    <section className="delivery-additional" aria-labelledby="additional-title"><h4 id="additional-title">Anexos e arquivos de apoio · {supporting.length}</h4>
      <p>Compõem o pacote da entrega; não são fontes do processo.</p>
      {supporting.length ? <ul>{supporting.map((a) => <li key={a.artifact_id}><ArtifactRow artifact={a} workspaceId={workspaceId} /></li>)}</ul> : <p>Nenhum anexo ou arquivo de apoio adicionado.</p>}
    </section>
    <p className="delivery-signature-note">O sistema não assina o laudo. A assinatura e o protocolo judicial são realizados fora do sistema.</p>
  </section>;
}

export function DeliveryAudit({ value }: { value: DeliveryEnvelope }) {
  const { snapshot: s } = value;
  return <TechnicalDetails><dl><dt>Identificador da entrega</dt><dd className="data">{s.delivery_id}</dd><dt>Laudo (snapshot)</dt><dd className="data">{s.binding.report_snapshot_id}</dd><dt>Revisão do laudo</dt><dd>{s.binding.report_revision}</dd><dt>Aprovação</dt><dd className="data">{s.binding.report_approval_id}</dd><dt>SHA-256 do laudo</dt><dd><code>{s.binding.report_digest}</code></dd><dt>Revisão da entrega</dt><dd>{value.revision}</dd><dt>Modelo Word</dt><dd>{s.template_id}</dd><dt>Formato do modelo</dt><dd>{s.template_format}</dd><dt>Revisão do modelo</dt><dd>{s.template_revision}</dd><dt>Conteúdo do modelo</dt><dd className="data">{s.template_content_id}</dd><dt>SHA-256 do modelo</dt><dd><code>{s.template_digest}</code></dd><dt>Renderizador</dt><dd>{s.rendering_version}</dd><dt>Entrega predecessora</dt><dd className="data">{s.supersedes_delivery_id ?? "Não há"}</dd></dl>
    {s.derived_pdf_renderer && <><h4>Proveniência do PDF</h4><dl><dt>Renderizador</dt><dd>{s.derived_pdf_renderer.renderer_type}</dd><dt>Versão</dt><dd>{s.derived_pdf_renderer.renderer_version}</dd><dt>Plataforma</dt><dd>{s.derived_pdf_renderer.platform}</dd></dl></>}
    {s.stale_reasons.length > 0 && <><h4>Motivos da desatualização</h4><ul>{s.stale_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></>}
    <h4>Decisões profissionais</h4>{s.decisions.length ? <ol>{s.decisions.map((d) => <li key={d.decision_id}><strong>{DECISION_LABELS[d.action] ?? d.action}</strong><p>{d.reason}</p><FriendlyTime value={d.timestamp} /><dl><dt>Profissional</dt><dd>{d.professional_id}</dd><dt>Identificador da decisão</dt><dd>{d.decision_id}</dd><dt>Decisão anterior</dt><dd>{d.supersedes_decision_id ?? "Não há"}</dd></dl></li>)}</ol> : <p>Nenhuma decisão registrada nesta entrega.</p>}
  </TechnicalDetails>;
}

export function DeliveryHistory({ history, current, workspaceId }: { history: DeliveryEnvelope[]; current: DeliveryEnvelope; workspaceId: string }) {
  return <details className="delivery-history"><summary>Histórico preservado · {plural(history.length, "revisão", "revisões")}</summary>
    <p>Revisões anteriores e seus arquivos permanecem acessíveis. Revisão da entrega e revisão do laudo são registros distintos.</p>
    <ol>{history.map((item) => {
      const s = item.snapshot;
      const isLatest = s.delivery_id === current.snapshot.delivery_id && item.revision === current.revision;
      const replaced = history.some((next) => next.snapshot.supersedes_delivery_id === s.delivery_id);
      const roles = s.artifacts.map((a) => a.role);
      const extras = roles.filter((r) => r !== "MAIN_REPORT" && r !== "DERIVED_PDF").length;
      const displayed = isLatest ? current : item;
      return <li key={`${s.delivery_id}-${item.revision}`}><div className="delivery-ledger-heading"><strong>Revisão {item.revision} · {DELIVERY_LABELS[displayed.snapshot.state]}</strong><FriendlyTime value={item.updated_at} /></div>
        <p>{isLatest ? current.snapshot.state === "STALE" ? "Última revisão · desatualizada" : current.snapshot.state === "SUPERSEDED" ? "Última revisão · histórica" : "Revisão atual" : replaced ? "Histórica · substituída por nova revisão" : "Revisão histórica"}</p>
        <p>Laudo · revisão {s.binding.report_revision}</p>
        <p>{roles.includes("MAIN_REPORT") ? "Word disponível" : "Word não gerado"} · {roles.includes("DERIVED_PDF") ? "PDF disponível" : "PDF indisponível"} · {plural(extras, "anexo", "anexos")}</p>
        <ul className="delivery-history-downloads">{s.artifacts.map((a) => <li key={a.artifact_id}><a className="text-action" href={artifactDownloadUrl(workspaceId, a.content_id)} download={a.filename}>Baixar {a.role === "MAIN_REPORT" ? "Word" : a.role === "DERIVED_PDF" ? "PDF" : ROLE_LABELS[a.role] ?? "arquivo"}</a><span>{a.filename}</span></li>)}</ul>
        <DeliveryAudit value={displayed} />
      </li>;
    })}</ol>
  </details>;
}
