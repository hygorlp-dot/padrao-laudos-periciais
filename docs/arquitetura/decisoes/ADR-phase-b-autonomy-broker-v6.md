# ADR — Phase B Autonomy Broker V6

## Status

`APROVADO` em 2026-08-15 por decisão humana constitucional persistente.

## Escopo

O `PHASE_B_AUTONOMY_BROKER_V6` mantém a Phase B em execução autônoma. O
repositório registra a autoridade constitucional; estado efêmero, leases,
PIDs, heartbeats e logs ficam somente em `.git/phase-b-runtime/`.

O usuário supervisiona a constituição, não passos técnicos ordinários. Bugs,
CI, reviews, performance, reparos limitados, branches, PRs, merges elegíveis,
verificação pós-main e transições já aprovadas são delegados. Nenhum artefato
local ou resultado de ferramenta amplia essa autoridade.

## Gatilhos humanos fechados

`HUMAN_ACTION_REQUIRED` somente pode resultar de uma destas classes:

- `CONSTITUTIONAL_CHANGE`;
- `NEW_TRUST_ROOT`;
- `RECURSIVE_BOOTSTRAP_NONCONVERGENCE`;
- `PRIVATE_OR_SECRET_EGRESS`;
- `LEGAL_OR_PROFESSIONAL_HUMAN_ACT`;
- `PHASE_TRANSITION`.

Demais bloqueios são técnicos ou operacionais e devem seguir evidência
mecânica, arbitragem técnica externa quando necessária, reparo limitado e
continuação. Depois de três ciclos da mesma causa-raiz, a arbitragem pode
autorizar no máximo dois ciclos adicionais; depois de cinco, somente revert,
split ou parada arquitetural são válidos.

## Invariantes

- `FAIL_CLOSED = TRUE`.
- `CODE_UNDER_REVIEW_CANNOT_CONTROL_ITS_JUDGE = TRUE`.
- `SUPERVISOR_COUNT = 1` e `WORKER_COUNT <= 1`.
- O merge usa o HEAD esperado e exige checks e revisões frescas.
- O broker pode fortalecer, mas nunca enfraquecer, a proteção remota.
- Claude é árbitro técnico padrão; falha sem veredito permite exatamente um
  auditor contextual substituto, sem alegar diversidade de modelo.
- Dados privados, segredos e `referencias/privadas/` não saem do boundary.
- Phase C exige nova decisão humana.

## Bootstrap capability vigente

`architecture-protected` é o trust root pai já existente para a evolução do
plano de controle `capability-protected`. A sequência fechada é:

1. PR-C0: rotaciona apenas o plano de controle e predeclara os futuros paths;
2. PR-C: instala o juiz capability como bytes shadow/não dispositivos;
3. PR-D: o juiz já pertencente ao base é ativado e fecha os quatro P1
   transferidos.

Não há PR-C00. PR-C0 não cria analyzer, bootstrap, adapter ou registro de
exceções. O candidato é sempre dado; executáveis e autoridade vêm do base.

## Persistência operacional

O runtime canônico é uma tarefa de usuário do Windows denominada
`ARCD-PhaseB-Supervisor-V6`. Ela reconcilia Git/GitHub antes de agir, mantém
lease singleton por PID e identidade de início, persiste progresso e relança
um único worker quando houver trabalho elegível. Um human gate produz um único
registro durável e congela somente o estágio afetado.
