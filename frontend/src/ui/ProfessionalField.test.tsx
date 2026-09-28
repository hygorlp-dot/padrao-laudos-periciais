import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ProfessionalField } from "./ProfessionalField";

const profile = { profile_id: "EXPERT-PROFILE-001", revision: 1, full_name: "Perita Sintética", professional_title: "Engenheira civil", registration: "CREA-XX 1", court_registration: "", contact_line: "Contato sintético" };

test("a known profile displays the name while submitting its identity; another professional is explicit", () => {
  const submit = vi.fn();
  function Form() {
    const [value, setValue] = useState(profile.profile_id);
    return <form onSubmit={(e) => { e.preventDefault(); submit(value); }}><ProfessionalField label="Responsável" value={value} onChange={setValue} profile={profile} /><button>Salvar</button></form>;
  }
  render(<Form />);
  expect(screen.getByLabelText("Responsável")).toHaveValue(profile.full_name);
  fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
  expect(submit).toHaveBeenLastCalledWith(profile.profile_id);
  fireEvent.click(screen.getByRole("button", { name: "Usar outra identificação" }));
  fireEvent.change(screen.getByLabelText("Responsável"), { target: { value: "Profissional alternativo" } });
  fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
  expect(submit).toHaveBeenLastCalledWith("Profissional alternativo");
  fireEvent.click(screen.getByRole("button", { name: "Usar meu perfil" }));
  expect(screen.getByLabelText("Responsável")).toHaveValue(profile.full_name);
});

test("profile arrival does not replace an alternative identity or invent a name", () => {
  const onChange = vi.fn();
  const { rerender } = render(<ProfessionalField label="Responsável" value="Outro profissional" onChange={onChange} profile={null} />);
  expect(screen.getByLabelText("Responsável")).toHaveValue("Outro profissional");
  rerender(<ProfessionalField label="Responsável" value="Outro profissional" onChange={onChange} profile={profile} />);
  expect(screen.getByLabelText("Responsável")).toHaveValue("Outro profissional");
  expect(onChange).not.toHaveBeenCalled();
});
