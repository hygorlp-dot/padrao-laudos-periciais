# Arquitetura do sistema

## Regra aprovada

O repositório é a memória canônica do sistema. O fluxo de engenharia é
`Issue → branch → implementação → gates → revisões independentes → PR → CI → merge`.
Conversas e memória transitória de agentes não substituem contratos, ADRs,
schemas, testes ou evidências persistidas.

O Core Pericial mantém autoridade de domínio. A camada `scripts/agentic/`
governa desenvolvimento e revisão, mas não decide conteúdo técnico pericial.
