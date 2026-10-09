import { useEffect, useState } from "react";

import { getReportPreflight, type PreflightFinding, type ReportPreflight, type ReportSnapshot } from "../data/reportSnapshot";

// Pré-verificação jurídico-editorial (#272). Avisos não reescrevem o texto;
// pendência aberta impede a emissão do Word final.

const CODE_LABELS: Record<string, string> = {
  PENDING_MARKER: "Pendências abertas",
  ACRONYM_NOT_DEFINED: "Siglas sem o nome por extenso",
  LATINISM: "Expressões latinas",
  FOREIGN_TERM: "Termos estrangeiros",
  JARGON: "Expressões rebuscadas",
  LONG_SENTENCE: "Frases longas",
  LONG_PARAGRAPH: "Parágrafos longos",
};
const NATURE: Record<ReportPreflight["sources"][number]["nature"], string> = {
  RECOMMENDATORY: "recomendatória",
  MANDATORY: "obrigatória para a administração pública",
  INSTITUTIONAL: "institucional",
};

function groups(findings: PreflightFinding[]) {
  const order = Object.keys(CODE_LABELS);
  const byCode = new Map<string, PreflightFinding[]>();
  for (const item of findings) byCode.set(item.code, [...(byCode.get(item.code) ?? []), item]);
  return [...byCode.entries()].sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));
}

type Props = { workspaceId: string; reportRevision?: number | null; snapshot?: ReportSnapshot };
export function ReportPreflightPanel(props: Props) {
  return <PreflightContent key={`${props.workspaceId}:${props.reportRevision ?? "unknown"}`} {...props} />;
}

function PreflightContent({ workspaceId, reportRevision, snapshot }: Props) {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "ready"; value: ReportPreflight } | { kind: "error" }>({ kind: "loading" });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getReportPreflight(workspaceId, controller.signal).then(
      (value) => { if (!controller.signal.aborted) setState(reportRevision != null && value.report_revision !== reportRevision ? { kind: "error" } : { kind: "ready", value }); },
      () => { if (!controller.signal.aborted) setState({ kind: "error" }); },
    );
    return () => controller.abort();
  }, [workspaceId, reportRevision, version]);

  if (state.kind === "loading") {
    return <section className="analysis-section preflight-panel" aria-busy="true" aria-labelledby="preflight-title"><h3 id="preflight-title">Linguagem e pendências</h3><p role="status">Conferindo o texto do laudo…</p></section>;
  }
  if (state.kind === "error") {
    return (
      <section className="analysis-section preflight-panel" aria-labelledby="preflight-title">
        <h3 id="preflight-title">Linguagem e pendências</h3>
        <p role="alert">Não foi possível conferir o texto agora. A emissão continua bloqueada se houver pendência aberta.</p>
        <button type="button" className="text-action" onClick={() => { setState({ kind: "loading" }); setVersion((value) => value + 1); }}>Tentar novamente</button>
      </section>
    );
  }
  const { value } = state;
  const warnings = value.findings.filter((item) => item.severity === "WARNING").length;
  const target = (finding: PreflightFinding) => {
    if (!snapshot) return null;
    const section = snapshot.sections.find((item) => item.section_id === finding.section_id);
    const claim = snapshot.claims.find((item) => item.claim_id === finding.location_id && item.section_id === finding.section_id);
    const answerNumber = /^ANSWER-([1-9]\d*)$/.exec(finding.location_id)?.[1];
    const answer = answerNumber ? snapshot.answers[Number(answerNumber) - 1] : undefined;
    const id = claim ? `report-claim-${claim.claim_id}` : answer?.section_id === finding.section_id ? `report-answer-${answerNumber}` : section ? `section-${section.section_id}` : "report-preparation";
    return { id, label: section?.title ?? "Preparação do documento" };
  };
  return (
    <section className="analysis-section preflight-panel" aria-labelledby="preflight-title">
      <h3 id="preflight-title">Linguagem e pendências</h3>
      <p className="field-hint">Perfil editorial de referência: {value.profile_label}. Os avisos sugerem; o texto só muda quando você o edita no Laudo.</p>
      {value.blocking ? (
        <p className="preflight-blocking" role="alert">O laudo tem pendência aberta. O Word final não é emitido até ela ser resolvida onde a lista abaixo indica.</p>
      ) : (
        <p className="settings-confirmation" role="status">Nenhuma pendência editorial aberta. {warnings ? `${warnings} ${warnings === 1 ? "aviso de linguagem" : "avisos de linguagem"} para conferir.` : "Nenhum aviso de linguagem."} Esta consulta não aprova o laudo nem substitui a revisão profissional.</p>
      )}
      {groups(value.findings).map(([code, items]) => (
        <details className="preflight-group" key={code} open={code === "PENDING_MARKER"}>
          <summary><strong>{CODE_LABELS[code] ?? code}</strong> <span className="field-hint">{items.length}</span></summary>
          <ul className="preflight-list">
            {items.map((item, index) => (
              <li key={`${item.location_id}-${index}`}>
                <blockquote>{item.excerpt}</blockquote>
                <p>{item.message} <span className="field-hint">{item.suggestion}</span></p>
                {target(item) && <a className="text-action" href={`#${target(item)!.id}`} onClick={() => { const element = document.getElementById(target(item)!.id); if (element instanceof HTMLDetailsElement) element.open = true; element?.focus(); }}>Ir ao trecho: {target(item)!.label}</a>}
              </li>
            ))}
          </ul>
        </details>
      ))}
      <details className="preflight-sources">
        <summary>Fontes do perfil de referência</summary>
        <ul>{value.sources.map((source) => <li key={source.name}>{source.name} · natureza {NATURE[source.nature]}</li>)}</ul>
      </details>
    </section>
  );
}
