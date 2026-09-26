import type { ReactNode } from "react";

// Auditoria sob demanda: identificadores, hashes e versões continuam acessíveis,
// mas não competem com o trabalho na primeira camada.
export function TechnicalDetails({ children, summary = "Detalhes técnicos" }: { children: ReactNode; summary?: string }) {
  return (
    <details className="technical-details">
      <summary>{summary}</summary>
      <div className="technical-details-body">{children}</div>
    </details>
  );
}
