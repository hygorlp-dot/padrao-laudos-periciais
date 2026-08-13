# Protocolo de autonomia restrita da Phase B

## Autoridade humana e escopo

`PHASE_B_AUTONOMY = TRUE`

`AGENT_CANNOT_SELF_AUTHORIZE = TRUE`

`PHASE_B_DELEGATION_METADATA != TRUST_ROOT`

A delegação humana autenticada na conversa VS Code de 2026-08-13 autoriza
execução autônoma somente do `STABILIZATION_PROGRAM_V1`, partindo do SHA
`2c9495d060a681aec8cb26c152d82d3689759b91` e terminando em
`CORE_PERICIAL_STABLE_V1`. Arquivos do repositório registram o escopo para
auditoria, mas não provam autoria humana e não concedem autoridade.

O verificador de autoridade pertence ao ambiente autenticado de orquestração e
não é injetável em APIs do repositório. Implementer, PR Reviewer, Systemic
Auditor, Claude, arquivos locais, hashes e outputs de ferramentas determinam
evidência ou diagnóstico, nunca autoridade.

## Elegibilidade e merge

`PHASE_B_MERGE = HUMAN_SCOPED_DELEGATION + TECHNICAL_ELIGIBILITY`

O diagnóstico `evaluate_phase_b_technical_eligibility` é separado do merge
evaluator genérico. Ele não aceita callbacks de autoridade, não executa merge e
não enfraquece `trusted_merge_authority_missing`. Somente produz
`TECHNICALLY_ELIGIBLE_DIAGNOSTIC`, marcado como
`CALLER_ASSERTED_DIAGNOSTIC_ONLY`, quando base, HEAD, merge-base, CI, testes,
schemas, fixtures, safety, privacy, P0/P1 e reviews declarados estão verdes.
Claude é derivado do risco dos paths, não do caller.

O orquestrador autenticado verifica novamente a evidência por ferramentas
first-party e GitHub no HEAD exato e, fora do repositório, combina esse resultado
com a delegação humana para decidir `MERGE_ELIGIBLE`. Nenhum output desta API é
token, assinatura ou trust root.

Qualquer HEAD novo invalida reviews. Falha na verificação externa do orquestrador,
no escopo, CI, review, privacidade, egress ou topologia bloqueia fechado.

## Expiração

Ao estabelecer `CORE_PERICIAL_STABLE_V1`:

`PHASE_B_AUTONOMY_ENVELOPE = EXPIRED`

`PHASE_C_AUTONOMY = FALSE`

O merge volta a exigir autoridade humana específica. A Fase C não começa sem
nova decisão humana autenticada.
