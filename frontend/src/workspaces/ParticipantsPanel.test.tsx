import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { Participant, ParticipantsView } from "../data/processParticipants";
import { ParticipantsPanel } from "./ParticipantsPanel";

const ID = "11111111-1111-4111-8111-111111111111";

function participant(overrides: Partial<Participant>): Participant {
  return {
    participant_id: "PARTICIPANT-MAN-" + "A".repeat(32),
    name: "ALFA SINTÉTICA",
    pole: "ACTIVE",
    procedural_role: "CLAIMANT",
    source_role_label: "Autora",
    person_type: "UNKNOWN",
    representatives: [],
    provenance: [],
    origin: "MANUAL",
    review_state: "CONFIRMED",
    decided_at: "2026-10-02T12:00:00+00:00",
    edited: false,
    ...overrides,
  };
}

const SOURCE = {
  content_id: "33333333-3333-4333-8333-333333333333",
  source_sha256: "a".repeat(64),
  filename: "capa.pdf",
  page: 1,
  source_start: 0,
  source_end: 4,
  excerpt: "BETA (REU) PROC (PROCURADOR)",
  extraction_mode: "NATIVE_TEXT" as const,
  logical_document_id: null,
};

function view(overrides: Partial<ParticipantsView> = {}): ParticipantsView {
  return {
    revision: null,
    updated_at: null,
    legacy_projection: false,
    participants: [],
    proposals: [],
    pending_documents: [],
    interrupted_pages: [],
    unread_pages: [],
    stale_participant_ids: [],
    legacy_blocked_poles: [],
    duplicates: [],
    proposals_unavailable: false,
    process_record_saved: true,
    ...overrides,
  };
}

function json(status: number, value: object) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("participants panel (#268)", () => {
  test("shows an empty state per pole instead of two lonely text fields", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, view())));
    render(<ParticipantsPanel workspaceId={ID} />);
    expect(await screen.findByRole("heading", { name: /Polo ativo/ })).toBeInTheDocument();
    expect(screen.getAllByText("Nenhum participante confirmado neste polo.")).toHaveLength(3);
    expect(screen.queryByRole("textbox", { name: "Parte requerente" })).not.toBeInTheDocument();
  });

  test("says when the documents read produced no proposal, and never while reading failed or is pending (#285)", async () => {
    const none = "Nenhuma proposta encontrada nos documentos lidos.";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, view())));
    const { unmount } = render(<ParticipantsPanel workspaceId={ID} />);
    expect(await screen.findByText(new RegExp(none))).toBeInTheDocument();
    unmount();
    for (const overrides of [
      { interrupted_pages: [{ filename: "capa.pdf", page: 1 }] },
      { unread_pages: [{ filename: "capa.pdf", page: 1 }] },
      { legacy_blocked_poles: ["ACTIVE" as const] },
      { pending_documents: ["capa.pdf"] },
      { proposals_unavailable: true },
      { participants: [participant({})] },
    ]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, view(overrides))));
      const rendered = render(<ParticipantsPanel workspaceId={ID} />);
      expect(await screen.findByRole("heading", { name: /Polo ativo/ })).toBeInTheDocument();
      expect(screen.queryByText(new RegExp(none))).not.toBeInTheDocument();
      if ("unread_pages" in overrides) expect(screen.getByText(/Sem texto legível em capa.pdf, p. 1/)).toBeInTheDocument();
      rendered.unmount();
    }
  });

  test("a proposal stays a proposal until the expert confirms it, with the source on demand", async () => {
    const proposal = participant({
      participant_id: "PARTICIPANT-SRC-" + "B".repeat(24), name: "BETA SINTÉTICA", pole: "PASSIVE", procedural_role: "DEFENDANT",
      source_role_label: "REU", origin: "SOURCE", review_state: "PROPOSED", decided_at: null, provenance: [SOURCE],
      representatives: [{ name: "PROC", role_label: "Procurador", registration: null, provenance: [SOURCE] }],
    });
    const confirmed = { ...proposal, review_state: "CONFIRMED" as const, decided_at: "2026-10-02T12:00:00+00:00" };
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, view({ proposals: [proposal] })))
      .mockResolvedValueOnce(json(200, view({ revision: 1, participants: [confirmed] })));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ParticipantsPanel workspaceId={ID} />);

    const proposals = await screen.findByRole("region", { name: /Encontrados nos documentos/ });
    expect(within(proposals).getByText("BETA SINTÉTICA")).toBeInTheDocument();
    expect(within(proposals).getByText(/Polo passivo · Parte ré/)).toBeInTheDocument();
    expect(within(proposals).getByText(/PROC \(procurador\)/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /Polo passivo/ })).getByText("Nenhum participante confirmado neste polo.")).toBeInTheDocument();
    await user.click(within(proposals).getByText("Ver fonte"));
    expect(within(proposals).getByText("BETA (REU) PROC (PROCURADOR)")).toBeVisible();

    await user.click(within(proposals).getByRole("button", { name: "Confirmar BETA SINTÉTICA" }));
    expect(await screen.findByText("BETA SINTÉTICA confirmado.")).toBeInTheDocument();
    expect(JSON.parse(fetchSpy.mock.calls[1][1].body)).toEqual({ action: "CONFIRM", expected_revision: null, payload: { proposal_id: proposal.participant_id } });
    expect(within(screen.getByRole("region", { name: /Polo passivo/ })).getByText("BETA SINTÉTICA")).toBeInTheDocument();
  });

  test("adds a manual participant with a linked representative", async () => {
    const added = participant({ name: "GAMA MANUAL", pole: "OTHER", procedural_role: "INTERESTED_THIRD_PARTY", source_role_label: "Terceira interessada", representatives: [{ name: "DEFENSORA", role_label: "Defensora pública", registration: null, provenance: [] }] });
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, view()))
      .mockResolvedValueOnce(json(200, view({ revision: 1, participants: [added] })));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ParticipantsPanel workspaceId={ID} />);

    await user.click(await screen.findByRole("button", { name: "Adicionar participante" }));
    await user.type(screen.getByRole("textbox", { name: "Nome" }), "GAMA MANUAL");
    await user.selectOptions(screen.getByRole("combobox", { name: "Polo" }), "OTHER");
    await user.type(screen.getByRole("textbox", { name: "Papel como aparece nos autos" }), "Terceira interessada");
    await user.click(screen.getByRole("button", { name: "Adicionar representante" }));
    await user.type(screen.getByRole("textbox", { name: "Nome do representante" }), "DEFENSORA");
    await user.clear(screen.getByRole("textbox", { name: "Qualificação" }));
    await user.type(screen.getByRole("textbox", { name: "Qualificação" }), "Defensora pública");
    const form = screen.getByRole("button", { name: "Cancelar" }).closest("form") as HTMLFormElement;
    await user.click(within(form).getByRole("button", { name: "Adicionar participante" }));

    expect(await screen.findByText("GAMA MANUAL adicionado.")).toBeInTheDocument();
    const body = JSON.parse(fetchSpy.mock.calls[1][1].body);
    expect(body.action).toBe("ADD_MANUAL");
    expect(body.payload.participant).toEqual({
      name: "GAMA MANUAL", pole: "OTHER", procedural_role: "INTERESTED_THIRD_PARTY", source_role_label: "Terceira interessada",
      person_type: "UNKNOWN", representatives: [{ name: "DEFENSORA", role_label: "Defensora pública", registration: null }],
    });
  });

  test("validates the form without calling the product", async () => {
    const fetchSpy = vi.fn().mockResolvedValueOnce(json(200, view()));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ParticipantsPanel workspaceId={ID} />);
    await user.click(await screen.findByRole("button", { name: "Adicionar participante" }));
    const form = screen.getByRole("button", { name: "Cancelar" }).closest("form") as HTMLFormElement;
    await user.click(within(form).getByRole("button", { name: "Adicionar participante" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Informe o nome e o papel");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  test("a conflict reloads the saved list and says so", async () => {
    const saved = participant({});
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, view({ revision: 1, participants: [saved] })))
      .mockResolvedValueOnce(json(409, { error: { code: "CONFLICT" } }))
      .mockResolvedValueOnce(json(200, view({ revision: 2, participants: [saved] })));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ParticipantsPanel workspaceId={ID} />);
    await user.click(await screen.findByRole("button", { name: "Remover ALFA SINTÉTICA" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("mudaram em outra tela");
    expect(await screen.findByText("Revisão 2 da lista de participantes")).toBeInTheDocument();
  });

  test("twenty participants stay listed and reorder within their pole", async () => {
    const many = Array.from({ length: 20 }, (_, index) => participant({ participant_id: `PARTICIPANT-MAN-${index.toString(16).toUpperCase().padStart(32, "0")}`, name: `AUTORA ${index}` }));
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, view({ revision: 3, participants: many })))
      .mockResolvedValueOnce(json(200, view({ revision: 4, participants: many })));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ParticipantsPanel workspaceId={ID} />);
    const active = await screen.findByRole("region", { name: /Polo ativo/ });
    expect(within(active).getAllByRole("listitem")).toHaveLength(20);
    expect(within(active).getByText("20")).toBeInTheDocument();
    expect(within(active).getByRole("button", { name: "Mover AUTORA 0 para cima" })).toBeDisabled();
    await user.click(within(active).getByRole("button", { name: "Mover AUTORA 0 para baixo" }));
    const order = JSON.parse(fetchSpy.mock.calls[1][1].body).payload.participant_ids;
    expect(order.slice(0, 2)).toEqual([many[1].participant_id, many[0].participant_id]);
    expect(order).toHaveLength(20);
  });

  test("warns about legacy text and excluded sources instead of hiding them", async () => {
    const legacy = participant({ participant_id: "PARTICIPANT-LEGACY-ACTIVE", origin: "LEGACY_PROCESS_CASE", name: "ALFA E BETA", source_role_label: "Parte requerente" });
    const sourced = participant({ participant_id: "PARTICIPANT-SRC-" + "C".repeat(24), origin: "SOURCE", provenance: [SOURCE], name: "DELTA", pole: "PASSIVE", procedural_role: "DEFENDANT", source_role_label: "REU" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, view({ legacy_projection: true, participants: [legacy, sourced], stale_participant_ids: [sourced.participant_id], pending_documents: ["anexo.pdf"] }))));
    render(<ParticipantsPanel workspaceId={ID} />);
    expect(await screen.findByText(/vieram dos campos “Parte requerente” e “Parte requerida”/)).toBeInTheDocument();
    expect(screen.getByText(/Leitura em andamento: anexo.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/foi excluída da análise/)).toBeInTheDocument();
    expect(screen.getByText(/Registrado antes da lista de participantes/)).toBeInTheDocument();
  });

  test("load failure is recoverable and never shows an empty list as fact", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(503, {}))
      .mockResolvedValueOnce(json(200, view()));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ParticipantsPanel workspaceId={ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar os participantes");
    expect(screen.queryByText("Nenhum participante confirmado neste polo.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(await screen.findAllByText("Nenhum participante confirmado neste polo.")).toHaveLength(3);
  });

  test("without a saved process record the panel explains and locks decisions", async () => {
    const proposal = participant({ participant_id: "PARTICIPANT-SRC-" + "A".repeat(24), origin: "SOURCE", provenance: [SOURCE], name: "BETA", review_state: "PROPOSED", decided_at: null, pole: "PASSIVE", source_role_label: "REU", role_text: "parte ré" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(200, view({ process_record_saved: false, proposals: [proposal], legacy_blocked_poles: ["ACTIVE"], proposals_unavailable: true }))));
    render(<ParticipantsPanel workspaceId={ID} />);
    expect(await screen.findByText(/Confirme os dados do processo acima/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirmar BETA" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Adicionar participante" })).toBeDisabled();
    expect(screen.getByText(/Nada foi cortado: registre as partes uma a uma/)).toBeInTheDocument();
    expect(screen.getByText(/não puderam ser relidos agora/)).toBeInTheDocument();
    expect(screen.getByText(/Polo passivo · parte ré/)).toBeInTheDocument();
  });

  test("flags a possible duplicate and never claims nothing changed on an unclear failure", async () => {
    const legacy = participant({ participant_id: "PARTICIPANT-LEGACY-PASSIVE", origin: "LEGACY_PROCESS_CASE", name: "CAIXA", pole: "PASSIVE", source_role_label: "Parte requerida" });
    const proposal = participant({ participant_id: "PARTICIPANT-SRC-" + "B".repeat(24), origin: "SOURCE", provenance: [SOURCE], name: "CAIXA", review_state: "PROPOSED", decided_at: null, pole: "PASSIVE", source_role_label: "REU" });
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, view({ participants: [legacy], proposals: [proposal], duplicates: [{ proposal_id: proposal.participant_id, matches_id: legacy.participant_id, matches_name: "CAIXA" }] })))
      .mockResolvedValueOnce(json(500, {}))
      .mockResolvedValueOnce(json(200, view({ revision: 1, participants: [legacy] })));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ParticipantsPanel workspaceId={ID} />);
    expect(await screen.findByText(/Possível repetição de “CAIXA”/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmar CAIXA" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A lista foi recarregada com o que está gravado");
    expect(alert).not.toHaveTextContent("Nada foi alterado");
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  test("after removing, focus moves to the pole heading instead of the page start", async () => {
    const alfa = participant({ name: "ALFA" });
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(json(200, view({ revision: 1, participants: [alfa] })))
      .mockResolvedValueOnce(json(200, view({ revision: 2, participants: [{ ...alfa, review_state: "REJECTED" }] })));
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    render(<ParticipantsPanel workspaceId={ID} />);
    await user.click(await screen.findByRole("button", { name: "Remover ALFA" }));
    await screen.findByText(/ALFA removido/);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: /Polo ativo/ }));
  });
});
