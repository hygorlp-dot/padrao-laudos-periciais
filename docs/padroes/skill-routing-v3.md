# SKILL_ROUTING_V3

O roteamento seleciona o conjunto mínimo de Skills; não instala, executa,
carrega código, acessa rede, altera egress nem decide domínio ou merge.

Precedência: `AGENTS.md > FIRST_PARTY_SKILL > APPROVED_PRODUCT_PRINCIPLE >
PINNED_THIRD_PARTY_SKILL`. O manifesto `.agents/skill-router.json` é pequeno,
declarativo e validado por schema. Contexto material desconhecido falha com
`UNMAPPED_SKILL_CONTEXT`; nunca carrega todas as Skills por conveniência.
`repository_mutation` é distinto de claims periciais materiais e de reviews
read-only. Toda mutação de repositório é material para o roteador, exige profile
mapeado e herda o bundle obrigatório de engenharia.

As famílias F1–F6 permanecem as definidas no SKILL_ROUTING_V2. Skills de
review terminal só entram por condição explícita e `using-superpowers`,
`claim-audit` e `proposition-audit` permanecem referências subordinadas.

`NEW_SKILL_REQUIRED = 0`; não há novo MCP, plugin, provider ou trust plane.
