# Inventário de egresso de rede

`EXTERNAL_DATA_EGRESS_REQUIRED` aplica-se a qualquer execução dos seguintes
componentes capazes de acessar rede:

- `scripts/conhecimento_privado/pesquisa_online.py` — somente consultas públicas;
- `.agents/skills/impeccable/scripts/generate-image.mjs` — API externa;
- `.agents/skills/impeccable/scripts/concept-seed.mjs` — serviço externo;
- `.agents/skills/impeccable/scripts/context.mjs` — verificação de atualização;
- recursos de navegador, captura e servidor da Skill Impeccable que resolvam URLs.

Esses componentes não integram automaticamente o pipeline pericial privado.
Dados, trechos, nomes, números ou artefatos de processos reais não podem ser
enviados. Pesquisa normativa admite apenas consulta pública abstrata, mediante
`AgentSearchProvider` explicitamente acionado pelo agente.
