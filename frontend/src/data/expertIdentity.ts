import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { getExpertProfile, type ExpertProfile } from "./reportSnapshot";

// A identidade do perito vem do perfil cadastrado na etapa Laudo e é lida uma
// vez por perícia, só quando alguma tela precisa dela. Formulários de decisão
// profissional usam esse perfil como valor inicial, para que a operação normal
// não dependa de digitar um identificador interno.
type ExpertIdentity = { profile: ExpertProfile | null; request: () => void; refresh: () => void };

const ExpertIdentityContext = createContext<ExpertIdentity>({ profile: null, request: () => undefined, refresh: () => undefined });

export function ExpertIdentityProvider({ workspaceId, children }: { workspaceId: string; children: ReactNode }) {
  const [profile, setProfile] = useState<ExpertProfile | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (version === 0) return;
    const controller = new AbortController();
    getExpertProfile(workspaceId, controller.signal).then(
      (value) => setProfile(value.profile),
      () => { if (!controller.signal.aborted) setProfile(null); },
    );
    return () => controller.abort();
  }, [workspaceId, version]);
  const request = useCallback(() => setVersion((value) => (value === 0 ? 1 : value)), []);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  return createElement(ExpertIdentityContext.Provider, { value: { profile, request, refresh } }, children);
}

export function useExpertIdentity(): ExpertProfile | null {
  const { profile, request } = useContext(ExpertIdentityContext);
  useEffect(() => { request(); }, [request]);
  return profile;
}

export function useRefreshExpertIdentity(): () => void {
  return useContext(ExpertIdentityContext).refresh;
}

// Valor inicial do campo: o perfil, somente enquanto o usuário não escreveu nada.
export function usePrefilledProfessional(profile: ExpertProfile | null, value: string, setValue: (value: string) => void) {
  useEffect(() => {
    if (profile && !value) setValue(profile.profile_id);
    // Só reage à chegada do perfil; depois disso o campo é do usuário.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);
}
