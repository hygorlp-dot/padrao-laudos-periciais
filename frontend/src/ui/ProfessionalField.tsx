import { useId } from "react";

import type { ExpertProfile } from "../data/reportSnapshot";

// Campo de identidade do profissional que decide. Com perfil cadastrado, mostra
// o nome do perito e usa o identificador do perfil; sem perfil, pede a
// identificação e indica onde cadastrá-la.
export function ProfessionalField({ label, value, onChange, profile, disabled, required = true, autoFocus }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  profile: ExpertProfile | null;
  disabled?: boolean;
  required?: boolean;
  autoFocus?: boolean;
}) {
  const hintId = useId();
  const usingProfile = profile !== null && value === profile.profile_id;
  return (
    <div className="professional-field">
      <label>
        {label}
        <input value={value} onChange={(event) => onChange(event.target.value)} required={required} disabled={disabled} autoFocus={autoFocus} aria-describedby={hintId} />
      </label>
      <small className="field-hint" id={hintId}>
        {usingProfile
          ? `${profile.full_name} · ${profile.registration} (seu perfil de perito)`
          : profile
            ? "Identificação diferente do seu perfil de perito."
            : "Cadastre seu perfil na etapa Laudo para preencher este campo automaticamente."}
      </small>
    </div>
  );
}
