import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ExpertProfileSetup } from "./ExpertProfileSetup";

afterEach(() => vi.unstubAllGlobals());
test("reuse previews only professional identity and requires an explicit save in the new workspace", async () => {
  const source = "11111111-1111-4111-8111-111111111111";
  const target = "22222222-2222-4222-8222-222222222222";
  const profile = { profile_id: "EXPERT-PROFILE-001", revision: 4, full_name: "Perita Sintética", professional_title: "Engenheira", registration: "Registro sintético", court_registration: "Cadastro sintético", contact_line: "Contato sintético" };
  const saved = vi.fn();
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    requests.push({ url, init });
    const value = url.endsWith("/workspaces") ? { items: [{ workspace_id: source, name: "Perícia anterior", created_at: "2026-09-01T12:00:00Z" }] } : { revision: 4, profile };
    return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  render(<ExpertProfileSetup workspaceId={target} onSaved={saved} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Reutilizar perfil cadastrado" }));
  await user.selectOptions(await screen.findByLabelText("Perícia de origem do perfil"), source);
  await waitFor(() => expect(screen.getByLabelText("Nome completo")).toHaveValue("Perita Sintética"));
  expect(requests.some((request) => request.init?.method === "PUT")).toBe(false);
  await user.click(screen.getByRole("button", { name: "Salvar perfil do perito" }));
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  const request = requests.find((request) => request.init?.method === "PUT")!;
  expect(request.url).toContain(target);
  expect(JSON.parse(String(request.init?.body))).toEqual({ expected_revision: null, profile: { ...profile, revision: 1 } });
});
