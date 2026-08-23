import type { MouseEventHandler } from "react";

export type StatusStateProps = {
  kind: "loading" | "empty" | "error" | "ready";
  stage?: string;
  onNavigate?: MouseEventHandler<HTMLAnchorElement>;
};

export function StatusState({ kind, stage, onNavigate }: StatusStateProps) {
  if (kind === "loading") {
    return (
      <section className="status-state status-state--loading" role="status" aria-live="polite">
        <span className="state-rule" aria-hidden="true" />
        <div>
          <h2>Preparando esta etapa</h2>
          <p>A estrutura necessária está sendo organizada.</p>
        </div>
      </section>
    );
  }

  if (kind === "empty") {
    return (
      <section className="status-state status-state--empty">
        <span className="empty-sheet" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <div>
          <h2>Nenhuma perícia selecionada</h2>
          <p>
            O shell está pronto. Nesta fase, você pode conhecer a sequência do
            trabalho sem criar ou alterar um caso.
          </p>
          <a className="primary-action" href="/processo" onClick={onNavigate}>
            Conhecer o fluxo
          </a>
        </div>
      </section>
    );
  }

  if (kind === "error") {
    return (
      <section className="status-state status-state--error" role="alert">
        <span className="state-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M12 7.25v6.5M12 17.25h.01" />
          </svg>
        </span>
        <div>
          <h2>Não foi possível mostrar esta etapa</h2>
          <p>Volte ao início e tente novamente.</p>
          <a className="text-action" href="/" onClick={onNavigate}>
            Voltar ao início
          </a>
        </div>
      </section>
    );
  }

  return (
    <section className="status-state status-state--ready">
      <span className="state-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="m7 12.25 3.1 3.1L17.5 8" />
        </svg>
      </span>
      <div>
        <h2>Etapa preparada</h2>
        <p>{stage} está pronta para receber o fluxo futuro.</p>
      </div>
    </section>
  );
}
