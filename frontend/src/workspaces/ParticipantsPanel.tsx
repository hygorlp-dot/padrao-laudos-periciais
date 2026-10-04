import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  decideParticipants,
  getParticipants,
  ParticipantsApiError,
  PERSON_TYPE_OPTIONS,
  POLE_LABELS,
  ROLE_OPTIONS,
  roleLabel,
  type Participant,
  type ParticipantAction,
  type ParticipantDraft,
  type ParticipantPole,
  type ParticipantsView,
} from "../data/processParticipants";

const POLES: readonly ParticipantPole[] = ["ACTIVE", "PASSIVE", "OTHER"];
const DEFAULT_ROLE: Record<ParticipantPole, string> = { ACTIVE: "CLAIMANT", PASSIVE: "DEFENDANT", OTHER: "INTERESTED_THIRD_PARTY" };

function emptyDraft(pole: ParticipantPole = "ACTIVE"): ParticipantDraft {
  return { name: "", pole, procedural_role: DEFAULT_ROLE[pole], source_role_label: "", person_type: "UNKNOWN", representatives: [] };
}

function draftOf(participant: Participant): ParticipantDraft {
  return {
    name: participant.name,
    pole: participant.pole,
    procedural_role: participant.procedural_role,
    source_role_label: participant.source_role_label,
    person_type: participant.person_type,
    representatives: participant.representatives.map((item) => ({ name: item.name, role_label: item.role_label, registration: item.registration })),
  };
}

function failure(error: unknown) {
  if (error instanceof ParticipantsApiError) {
    if (error.kind === "conflict") return "Os participantes mudaram em outra tela. Os dados foram recarregados; repita a ação.";
    if (error.kind === "process_required") return "Confirme os dados do processo acima antes de registrar participantes.";
    if (error.kind === "invalid") return "Confira os campos. Uma proposta que mudou na fonte ou cuja peça foi excluída precisa ser revista de novo.";
  }
  // Sem resposta clara, não dá para afirmar que nada foi gravado: a lista é
  // recarregada para mostrar o estado real antes de uma nova tentativa.
  return "Não foi possível confirmar o resultado. A lista foi recarregada com o que está gravado; confira antes de repetir.";
}

function originText(participant: Participant) {
  if (participant.origin === "MANUAL") return "Informado pelo perito";
  if (participant.origin === "LEGACY_PROCESS_CASE") return "Registrado antes da lista de participantes";
  return participant.edited ? "Lido dos autos e corrigido pelo perito" : "Lido dos autos";
}

function SourceDetails({ participant }: { participant: Participant }) {
  if (!participant.provenance.length) return null;
  return (
    <details className="participant-source">
      <summary>Ver fonte</summary>
      {participant.provenance.map((source) => (
        <div key={`${source.content_id}-${source.page}-${source.source_start}`}>
          <p>
            {source.filename}, página {source.page}
            {source.extraction_mode === "OCR" ? " · leitura por OCR" : " · texto do documento"}
          </p>
          <blockquote>{source.excerpt}</blockquote>
        </div>
      ))}
    </details>
  );
}

function Representatives({ participant }: { participant: Participant }) {
  if (!participant.representatives.length) return <p className="participant-meta">Sem representante indicado</p>;
  return (
    <p className="participant-meta">
      Representação:{" "}
      {participant.representatives.map((item, index) => (
        <span key={`${item.name}-${index}`}>
          {index > 0 ? "; " : ""}
          {item.name} ({item.role_label.toLowerCase()}{item.registration ? `, ${item.registration}` : ""})
        </span>
      ))}
    </p>
  );
}

function ParticipantForm({
  initial,
  submitLabel,
  busy,
  onSubmit,
  onCancel,
  legacyPole,
}: {
  initial: ParticipantDraft;
  submitLabel: string;
  busy: boolean;
  onSubmit: (draft: ParticipantDraft) => void;
  onCancel: () => void;
  legacyPole?: boolean;
}) {
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState("");
  const first = useRef<HTMLInputElement | null>(null);
  useEffect(() => { first.current?.focus(); }, []);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft.name.trim() || !draft.source_role_label.trim()) {
      setError("Informe o nome e o papel como aparece nos autos.");
      return;
    }
    if (draft.representatives.some((item) => !item.name.trim() || !item.role_label.trim())) {
      setError("Complete ou remova o representante sem nome ou sem qualificação.");
      return;
    }
    setError("");
    onSubmit({
      ...draft,
      name: draft.name.trim(),
      source_role_label: draft.source_role_label.trim(),
      representatives: draft.representatives.map((item) => ({
        name: item.name.trim(),
        role_label: item.role_label.trim(),
        registration: item.registration?.trim() ? item.registration.trim() : null,
      })),
    });
  }
  return (
    <form className="participant-form" onSubmit={submit} noValidate>
      <label>
        Nome
        <input ref={first} value={draft.name} disabled={busy} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
      </label>
      <label>
        Polo
        <select
          value={draft.pole}
          disabled={busy || legacyPole}
          onChange={(event) => {
            const pole = event.target.value as ParticipantPole;
            setDraft({ ...draft, pole, procedural_role: DEFAULT_ROLE[pole] });
          }}
        >
          {POLES.map((pole) => <option key={pole} value={pole}>{POLE_LABELS[pole]}</option>)}
        </select>
      </label>
      <label>
        Papel processual
        <select value={draft.procedural_role} disabled={busy} onChange={(event) => setDraft({ ...draft, procedural_role: event.target.value })}>
          {ROLE_OPTIONS.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
        </select>
      </label>
      <label>
        Papel como aparece nos autos
        <input value={draft.source_role_label} placeholder="Ex.: Autora, Réu, Terceiro interessado" disabled={busy} onChange={(event) => setDraft({ ...draft, source_role_label: event.target.value })} />
      </label>
      <label>
        Tipo
        <select value={draft.person_type} disabled={busy} onChange={(event) => setDraft({ ...draft, person_type: event.target.value as ParticipantDraft["person_type"] })}>
          {PERSON_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <fieldset className="participant-form__representatives">
        <legend>Representantes</legend>
        {draft.representatives.length === 0 ? <p className="field-hint">Nenhum representante. Adicione se os autos indicarem advogado, procurador ou defensor.</p> : null}
        {draft.representatives.map((item, index) => (
          <div className="participant-form__representative" key={index}>
            <label>
              Nome do representante
              <input value={item.name} disabled={busy} onChange={(event) => setDraft({ ...draft, representatives: draft.representatives.map((value, position) => position === index ? { ...value, name: event.target.value } : value) })} />
            </label>
            <label>
              Qualificação
              <input value={item.role_label} placeholder="Ex.: Advogada" disabled={busy} onChange={(event) => setDraft({ ...draft, representatives: draft.representatives.map((value, position) => position === index ? { ...value, role_label: event.target.value } : value) })} />
            </label>
            <label>
              Registro (opcional)
              <input value={item.registration ?? ""} placeholder="Ex.: OAB/PE 00000" disabled={busy} onChange={(event) => setDraft({ ...draft, representatives: draft.representatives.map((value, position) => position === index ? { ...value, registration: event.target.value } : value) })} />
            </label>
            <button type="button" className="text-action" disabled={busy} onClick={() => setDraft({ ...draft, representatives: draft.representatives.filter((_, position) => position !== index) })}>
              Remover representante {index + 1}
            </button>
          </div>
        ))}
        <button type="button" className="text-action" disabled={busy} onClick={() => setDraft({ ...draft, representatives: [...draft.representatives, { name: "", role_label: "Advogado", registration: null }] })}>
          Adicionar representante
        </button>
      </fieldset>
      {error ? <p className="field-error" role="alert">{error}</p> : null}
      <div className="participant-form__actions">
        <button type="submit" className="primary-action" disabled={busy}>{busy ? "Salvando…" : submitLabel}</button>
        <button type="button" className="text-action" disabled={busy} onClick={onCancel}>Cancelar</button>
      </div>
    </form>
  );
}

const UNREAD_PAGES_LISTED = 8;

// Um processo digitalizado grande pode ter centenas de páginas sem texto: o
// aviso agrupa por arquivo e diz quantas faltam, em vez de ler todas em voz alta.
function unreadSummary(pages: readonly { filename: string; page: number }[]) {
  const byFile = new Map<string, number[]>();
  for (const item of pages) byFile.set(item.filename, [...(byFile.get(item.filename) ?? []), item.page]);
  return Array.from(byFile, ([filename, numbers]) => {
    const listed = numbers.slice(0, UNREAD_PAGES_LISTED).join(", ");
    const rest = numbers.length - UNREAD_PAGES_LISTED;
    return `${filename}, p. ${listed}${rest > 0 ? ` e mais ${rest} página${rest > 1 ? "s" : ""}` : ""}`;
  }).join("; ");
}

export function ParticipantsPanel({ workspaceId, processSaved = true }: { workspaceId: string; processSaved?: boolean }) {
  // Gravar o processo pela primeira vez libera as decisões: a lista é relida.
  return <ParticipantsContent key={`${workspaceId}:${processSaved}`} workspaceId={workspaceId} />;
}

function ParticipantsContent({ workspaceId }: { workspaceId: string }) {
  const [view, setView] = useState<ParticipantsView | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "status" | "alert"; text: string } | null>(null);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const focusAfterRender = useRef<string | null>(null);

  // Depois de salvar, editar ou remover, a linha some ou muda: o foco vai para
  // o título do polo (ou da seção) em vez de cair no início da página.
  useEffect(() => {
    if (!focusAfterRender.current) return;
    document.getElementById(focusAfterRender.current)?.focus();
    focusAfterRender.current = null;
  }, [view]);

  useEffect(() => {
    const controller = new AbortController();
    getParticipants(workspaceId, controller.signal).then(
      (value) => { if (!controller.signal.aborted) { setView(value); setLoadError(false); } },
      () => { if (!controller.signal.aborted) setLoadError(true); },
    );
    return () => controller.abort();
  }, [workspaceId, version]);

  async function decide(decision: ParticipantAction, done: string, focusAfter = "participants-title") {
    if (!view) return;
    setBusy(true);
    setMessage(null);
    try {
      const next = await decideParticipants(workspaceId, view.revision, decision);
      setView(next);
      setEditing(null);
      setMessage({ kind: "status", text: done });
      focusAfterRender.current = focusAfter;
    } catch (error) {
      setMessage({ kind: "alert", text: failure(error) });
      if (!(error instanceof ParticipantsApiError) || error.kind === "conflict" || error.kind === "unavailable") setVersion((value) => value + 1);
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <section className="participants-panel" aria-labelledby="participants-title">
        <h2 id="participants-title">Participantes do processo</h2>
        <div role="alert">
          <p>Não foi possível carregar os participantes. Os dados salvos continuam preservados.</p>
          <button type="button" className="text-action" onClick={() => setVersion((value) => value + 1)}>Tentar novamente</button>
        </div>
      </section>
    );
  }
  if (!view) {
    return (
      <section className="participants-panel" aria-labelledby="participants-title" aria-busy="true">
        <h2 id="participants-title">Participantes do processo</h2>
        <p role="status">Carregando participantes…</p>
      </section>
    );
  }

  const active = view.participants.filter((item) => item.review_state === "CONFIRMED");
  const removed = view.participants.filter((item) => item.review_state === "REJECTED");
  const stale = new Set(view.stale_participant_ids);
  const order = view.participants.map((item) => item.participant_id);
  const locked = busy || !view.process_record_saved;
  const duplicates = new Map(view.duplicates.map((item) => [item.proposal_id, item.matches_name]));
  const poleHeading = (pole: ParticipantPole) => `participants-pole-${pole}`;

  function move(participant: Participant, offset: -1 | 1) {
    const samePole = active.filter((item) => item.pole === participant.pole);
    const position = samePole.findIndex((item) => item.participant_id === participant.participant_id);
    const target = samePole[position + offset];
    if (!target) return;
    const next = [...order];
    const from = next.indexOf(participant.participant_id);
    const to = next.indexOf(target.participant_id);
    [next[from], next[to]] = [next[to], next[from]];
    void decide({ action: "REORDER", payload: { participant_ids: next } }, "Ordem atualizada.", poleHeading(participant.pole));
  }

  return (
    <section className="participants-panel" aria-labelledby="participants-title">
      <header className="participants-panel__header">
        <div>
          <h2 id="participants-title" tabIndex={-1}>Participantes do processo</h2>
          <p>Partes de cada polo, outros participantes e seus representantes. Só entra no laudo o que você confirmar.</p>
        </div>
        {editing === null ? (
          <button type="button" className="text-action" disabled={locked} onClick={() => setEditing("new")}>Adicionar participante</button>
        ) : null}
      </header>

      {!view.process_record_saved ? (
        <p className="participants-notice participants-notice--warning" role="status">
          Confirme os dados do processo acima para confirmar, adicionar ou alterar participantes. As propostas continuam visíveis para conferência.
        </p>
      ) : null}
      {view.legacy_blocked_poles.length ? (
        <p className="participants-notice participants-notice--warning" role="status">
          O texto antigo de {view.legacy_blocked_poles.map((pole) => POLE_LABELS[pole].toLowerCase()).join(" e ")} é longo demais ou tem caracteres que o Word não aceita, por isso não foi trazido para a lista. Nada foi cortado: registre as partes uma a uma.
        </p>
      ) : null}
      {view.proposals_unavailable ? (
        <p className="participants-notice participants-notice--warning" role="status">
          Os documentos não puderam ser relidos agora, então não há propostas nesta visita. Os participantes já registrados continuam válidos.
        </p>
      ) : null}
      {view.legacy_projection ? (
        <p className="participants-notice" role="status">
          Estes nomes vieram dos campos “Parte requerente” e “Parte requerida” preenchidos antes. Revise-os; a primeira alteração passa a lista a valer como registro.
        </p>
      ) : null}
      {view.pending_documents.length ? (
        <p className="participants-notice" role="status">
          Leitura em andamento: {view.pending_documents.join(", ")}. Novas propostas podem aparecer quando terminar.
        </p>
      ) : null}
      {view.interrupted_pages.length ? (
        <p className="participants-notice participants-notice--warning" role="status">
          A tabela de partes não pôde ser lida até o fim em {view.interrupted_pages.map((item) => `${item.filename}, p. ${item.page}`).join("; ")}. Confira os autos: pode haver participantes não propostos.
        </p>
      ) : null}

      {view.unread_pages.length ? (
        <p className="participants-notice participants-notice--warning" role="status">
          Sem texto legível em {unreadSummary(view.unread_pages)}. Participantes nessas páginas não podem ser propostos: confira os autos.
        </p>
      ) : null}
      {!view.proposals.length && !view.participants.length && !view.proposals_unavailable && !view.pending_documents.length && !view.interrupted_pages.length && !view.unread_pages.length && !view.legacy_blocked_poles.length ? (
        <p className="participants-notice" role="status">
          Nenhuma proposta encontrada nos documentos lidos. Se a capa do processo ainda não foi importada, importe-a em Materiais; se já foi, confira os autos e adicione os participantes manualmente.
        </p>
      ) : null}

      {view.proposals.length ? (
        <section className="participants-proposals" aria-labelledby="participants-proposals-title">
          <h3 id="participants-proposals-title">Encontrados nos documentos ({view.proposals.length})</h3>
          <p className="field-hint">Confira cada nome com a fonte antes de confirmar. Nomes repetidos nos autos aparecem separados.</p>
          <ul className="participant-list">
            {view.proposals.map((proposal) => (
              <li className="participant-row participant-row--proposal" key={proposal.participant_id}>
                <div className="participant-row__main">
                  <strong className="participant-name">{proposal.name}</strong>
                  <span className="participant-role">{POLE_LABELS[proposal.pole]} · {roleLabel(proposal)}</span>
                  {duplicates.has(proposal.participant_id) ? (
                    <p className="field-warning">Possível repetição de “{duplicates.get(proposal.participant_id)}”, já na lista. Se for a mesma parte, descarte esta proposta.</p>
                  ) : null}
                  <Representatives participant={proposal} />
                  <SourceDetails participant={proposal} />
                </div>
                <div className="participant-row__actions">
                  <button type="button" className="primary-action primary-action--compact" disabled={locked} onClick={() => void decide({ action: "CONFIRM", payload: { proposal_id: proposal.participant_id } }, `${proposal.name} confirmado.`, poleHeading(proposal.pole))} aria-label={`Confirmar ${proposal.name}`}>
                    Confirmar
                  </button>
                  <button type="button" className="text-action" disabled={locked} onClick={() => void decide({ action: "REJECT", payload: { proposal_id: proposal.participant_id } }, `${proposal.name} descartado.`)} aria-label={`Descartar ${proposal.name}`}>
                    Descartar
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {editing === "new" ? (
        <ParticipantForm initial={emptyDraft()} submitLabel="Adicionar participante" busy={busy} onCancel={() => setEditing(null)} onSubmit={(draft) => void decide({ action: "ADD_MANUAL", payload: { participant: draft } }, `${draft.name} adicionado.`, poleHeading(draft.pole))} />
      ) : null}

      {POLES.map((pole) => {
        const members = active.filter((item) => item.pole === pole);
        return (
          <section className="participants-pole" key={pole} aria-labelledby={`participants-pole-${pole}`}>
            <h3 id={poleHeading(pole)} tabIndex={-1}>
              {POLE_LABELS[pole]} <span className="participants-count">{members.length}</span>
            </h3>
            {members.length === 0 ? (
              <p className="participants-empty">Nenhum participante confirmado neste polo.</p>
            ) : (
              <ul className="participant-list">
                {members.map((participant, index) => (
                  <li className="participant-row" key={participant.participant_id}>
                    {editing === participant.participant_id ? (
                      <ParticipantForm
                        initial={draftOf(participant)}
                        submitLabel="Salvar alterações"
                        busy={busy}
                        legacyPole={participant.origin === "LEGACY_PROCESS_CASE"}
                        onCancel={() => setEditing(null)}
                        onSubmit={(draft) => void decide({ action: "EDIT", payload: { participant_id: participant.participant_id, participant: draft } }, "Participante atualizado.", poleHeading(draft.pole))}
                      />
                    ) : (
                      <>
                        <div className="participant-row__main">
                          <strong className="participant-name">{participant.name}</strong>
                          <span className="participant-role">{roleLabel(participant)} · {originText(participant)}</span>
                          <Representatives participant={participant} />
                          {stale.has(participant.participant_id) ? (
                            <p className="field-warning" role="status">A peça que sustentava este participante foi excluída da análise. Confirme por outra fonte ou remova.</p>
                          ) : null}
                          <SourceDetails participant={participant} />
                        </div>
                        <div className="participant-row__actions">
                          <button type="button" className="text-action" disabled={locked} onClick={() => setEditing(participant.participant_id)} aria-label={`Editar ${participant.name}`}>
                            Editar
                          </button>
                          <button type="button" className="text-action" disabled={locked} onClick={() => void decide({ action: "REMOVE", payload: { participant_id: participant.participant_id } }, `${participant.name} removido. Ele continua no histórico.`, poleHeading(pole))} aria-label={`Remover ${participant.name}`}>
                            Remover
                          </button>
                          {members.length > 1 ? (
                            <span className="participant-order">
                              <button type="button" className="icon-action" disabled={locked || index === 0} aria-label={`Mover ${participant.name} para cima`} onClick={() => move(participant, -1)}>↑</button>
                              <button type="button" className="icon-action" disabled={locked || index === members.length - 1} aria-label={`Mover ${participant.name} para baixo`} onClick={() => move(participant, 1)}>↓</button>
                            </span>
                          ) : null}
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}

      {removed.length ? (
        <details className="participants-removed">
          <summary>Descartados e removidos ({removed.length})</summary>
          <ul className="participant-list">
            {removed.map((participant) => (
              <li className="participant-row participant-row--removed" key={participant.participant_id}>
                <div className="participant-row__main">
                  <strong className="participant-name">{participant.name}</strong>
                  <span className="participant-role">{POLE_LABELS[participant.pole]} · {roleLabel(participant)}</span>
                </div>
                <div className="participant-row__actions">
                  <button type="button" className="text-action" disabled={locked} onClick={() => void decide({ action: "RESTORE", payload: { participant_id: participant.participant_id } }, `${participant.name} restaurado.`, poleHeading(participant.pole))} aria-label={`Restaurar ${participant.name}`}>
                    Restaurar
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {message ? <p className={message.kind === "alert" ? "field-error" : "participants-saved"} role={message.kind}>{message.text}</p> : null}
      {view.revision !== null ? <p className="revision-note">Revisão {view.revision} da lista de participantes</p> : null}
    </section>
  );
}
