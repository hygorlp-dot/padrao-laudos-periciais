import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { SiteLocationPanel } from "./SiteLocationPanel";

const ID = "11111111-1111-4111-8111-111111111111";
const response = (status: number, value: object) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const location = (state: "PROPOSED" | "CONFIRMED", input_format = "DECIMAL") => ({
  schema_version: "1.0.0", workspace_id: ID, latitude: -23.55052, longitude: -46.633308, datum: "WGS84", input_format,
  address_label: "Rua Sintética, 100", note: null, state, confirmed_by: state === "CONFIRMED" ? "EXPERT-PROFILE-001" : null, confirmed_at: state === "CONFIRMED" ? "2026-09-26T10:00:00-03:00" : null,
});

afterEach(() => vi.unstubAllGlobals());

describe("site location (Planejamento)", () => {
  test("a short link is explained instead of being resolved over the network", async () => {
    const requests: Array<{ url: string; body?: string }> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      requests.push({ url: String(input), body: init?.body ? String(init.body) : undefined });
      if (init?.method === "PUT") return Promise.resolve(response(422, { error: { code: "LOCATION_SHORT_LINK_REQUIRES_NETWORK", message: "localização não reconhecida" } }));
      return Promise.resolve(response(404, {}));
    }));
    render(<SiteLocationPanel workspaceId={ID} />);
    fireEvent.change(await screen.findByLabelText("Link do mapa ou coordenadas"), { target: { value: "https://maps.app.goo.gl/AbC" } });
    fireEvent.click(screen.getByRole("button", { name: "Ler localização" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Links curtos (maps.app.goo.gl)");
    expect(requests.every((item) => item.url.startsWith("/app-api/"))).toBe(true);
    expect(JSON.parse(requests[1].body!)).toEqual({ expected_revision: null, input: "https://maps.app.goo.gl/AbC", address_label: null, note: null });
  });

  test("a proposal shows its coordinates, warns about a map centre and is confirmed by the expert", async () => {
    const bodies: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.endsWith("/site-location/confirmation")) { bodies.push({ url, body: JSON.parse(String(init.body)) }); return Promise.resolve(response(200, { revision: 2, updated_at: "2026-09-26T13:00:00Z", location: location("CONFIRMED") })); }
      return Promise.resolve(response(200, { revision: 1, updated_at: "2026-09-26T12:00:00Z", location: location("PROPOSED", "GOOGLE_MAPS_VIEWPORT") }));
    }));
    render(<SiteLocationPanel workspaceId={ID} />);
    expect(await screen.findByText("23,550520° S, 46,633308° O")).toBeInTheDocument();
    expect(screen.getByText(/só o centro do mapa/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar localização" }));
    await waitFor(() => expect(bodies).toEqual([{ url: `/app-api/v1/workspaces/${ID}/site-location/confirmation`, body: { expected_revision: 1 } }]));
    expect(await screen.findByText("Confirmada pelo perito")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirmar localização" })).not.toBeInTheDocument();
  });
});
