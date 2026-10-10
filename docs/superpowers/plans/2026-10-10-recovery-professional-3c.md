# Recuperação profissional 3C — plano serial

Execução inline com writing-plans/executing-plans. Refs #291.

## Contrato e auditoria de entrada

Base: `bdd9a877f8fcb5ee9d2bd4420fee696a10e0a039`. Issue #291 aberta;
nenhuma PR aberta na entrada. Branch `improve/291-recovery-professional-3c`,
worktree reutilizado `C:/tmp/plp280-20261008`. Inventários preservados em
`C:/tmp/recovery3c-20261010-evidence`. Arquivo untracked de higiene de outra
execução preservado, sem staging. FILES_DELETED=0; HUMAN_RC_READY=FALSE.

Auditoria: global App/routeCatalog alcança WorkspaceRecoveryView sem workspace;
contextual WorkspaceView usa o mesmo componente. workspaceRecovery.ts faz parse
closed-set e traduz códigos reais. Local API transport/composition e Product
Bridge já expõem export, verify, staging, pending, promote, discard e abandon.
application/workspace_recovery.py orquestra infraestrutura/productization.py e
private_filesystem.py; não criar outro engine, manifest, tabela ou cache.
Schema workspace-backup-v1 e VerifyWorkspaceBackup validam identidade, sequência,
dependências, privado, papéis, Delivery/Word/PDF e settings capturados. V0 está
na janela existente de compatibilidade. Staging mantém quarentena e descriptor
durável; startup reconstrói sessões. Promoção copia para storage vivo somente
por comando confirmado, recusa identidade existente e possui journal retomável.
Reopen usa rota normal de WorkspaceView. Testes existentes de reachability,
transaction, platform, productization, PJe closure e oracle V7 cobrem essas bases.

Gaps de apresentação observados: IDs na camada principal, ação sem seleção,
review e confirmação misturados, ausência de abrir após promover, arquivo
substituível durante operações, erro de transporte sem reconciliação honesta.
Resumo existente fornece nome/data de criação/revisões/documentos privados,
mas não data do backup nem contagens por domínio. Mostrar somente esses fatos;
não usar data de criação como data de backup nem inferir conteúdo por frontend.

## Design aprovado pelo pedido

Calibrated Process Ledger; cores/tipos/tokens existentes de DESIGN.md.
Uma etapa em foco, divisores, resumo em dl, detalhes técnicos nativos em details.
Sem animação, dashboard, stepper ornamental ou modal wizard. Selecionar → verificar
→ preparar separado → abrir revisão → confirmação clara inline → promover → abrir.
Backup contextual sob disclosure para não disputar ação primária da recuperação.
Pending persistido permite retomar revisão sem reenvio após restart. Busy mantém
nome/foco da ação, aria-busy/status, guarda síncrona contra duplo clique.

## Sequência

- [x] RED: testes frontend de 17 estados, transições sem auto-promoção, seleção
  imutável durante operação, foco, retry/unavailable e navegação de reopen.
  `npm test -- src/workspaces/RecoveryProfessionalView.test.tsx`.
- [x] GREEN: mudança limitada a WorkspaceRecoveryView e CSS recovery-editorial;
  clientes existentes preservados. Atualizar testes legados pelos novos rótulos
  e pelo passo explícito de revisão, preservando assertions de autoridade.
- [x] Executar regressão backend existente e adversariais exigidos; acrescentar
  teste RED e correção mínima somente onde gap causal for reproduzido.
- [x] Build de produção e prova longitudinal sintética por UI real: backup,
  encerramento/start, global verify/stage, restart/review/promote, reopen/restart.
  Comparar revisões/settings e bytes/hash/roles/proveniência Word/PDF/anexos.
  QA 1366/1280/1024, conteúdo longo, disclosure aberto, teclado/foco.
- [x] Impeccable somente auditor de UX, IMPECCABLE_NO_UPDATE_CHECK=1, sem rede.
- [ ] Vitest integral, ESLint, TS, build, focused backend/oracle, privacy,
  schemas/hygiene/Ruff/architecture/change impact e uma execução final fresca
  `python -m scripts.quality.verify_core --full`.
- [ ] Commit/staging cirúrgico, scan de publicação árvore/história, uma PR
  `feat(ux): profissionalizar recuperação em etapas (#291, inc-3C)`.
- [ ] Reviewer e Systemic Auditor seriais, contextos novos/checkouts separados
  read-only/SHA exato; P0/P1 bloqueiam, P2 tracking sem loop.
- [ ] CI protegido e classificador real no HEAD final. Claude somente se exigido;
  indisponibilidade exige waiver nova da PR/SHA, nenhuma waiver anterior vale.
- [ ] Merge normal condicionado a todos os gates. Uma prova pós-main, #291
  aberta, HUMAN_RC_READY=FALSE. Parar sem 3D/RC/release/casos reais.

## Evidência funcional e QA concluídas

Os receipts locais ficam fora do Git em `C:/tmp/recovery3c-20261010-evidence`;
backup, storage, imagens e arquivos sintéticos não entram na publicação.

Frontend: RED inicial 17 falhas; GREEN inicial 17 PASS, ampliado para 19 casos
de recuperação profissional. Regressão focal com testes legados: 41 PASS.
Vitest integral: 400 PASS / 47 arquivos com `--maxWorkers=1`; a execução
com concorrência padrão teve um timeout de 5 s no teste de Planejamento
inalterado. Sem alteração de testes ou limites, o integral serial passou.
ESLint sem avisos, TypeScript e build de produção PASS. O aviso preexistente
de chunk acima de 500 KB permanece; não introduzir refactor de bundle no 3C.

Backend: 216 PASS / 8 skips condicionados à plataforma nos testes de recovery,
transaction, productization e closure. Private filesystem e oracle de integração:
168 PASS / 1 skip condicionado à plataforma, incluindo Word Desktop nativo.
Dez ataques ao backup foram enviados aos endpoints reais de verify e staging:
byte alterado, truncamento, hash do manifest, versão incompatível, privado ausente,
SHA de revisão, dependência ausente, identidade de workspace divergente,
privado de outro workspace e revisão duplicada. Todos recusados antes de
workspace vivo ou pending. Colisão e retomada interrompida cobertas pela
regressão existente. O novo RED demonstrou promoção de nome adulterado no
staging, mantendo contagens iguais; correção mínima compara o plano ao descriptor
existente sob custódia antes do journal ou primeira mutação viva. GREEN cobre
adulteração do nome e dos bytes privados, com lista viva vazia.

Prova longitudinal pelo frontend de produção e Product Bridge reais, somente
material sintético: backup contextual, verify/stage global, morte do processo
entre staging e review, redescoberta sem reenvio, confirmação por teclado sem
auto-promoção, comando explícito, reopen pela rota normal e segundo restart.
64 revisões e 8 conteúdos privados idênticos entre origem e recuperado, incluindo
configurações capturadas, decisões, papéis e proveniência. Word oficial, PDF
derivado e anexo baixados pela UI com bytes e SHA-256 exatamente preservados.
Nenhum renderer foi executado para substituir artefatos históricos recuperados.

QA de apresentação separada da prova real: 18 estados em 1366/1280/1024,
nomes extensos, erros, busy, resume e disclosures abertos; nenhum overflow
horizontal, no máximo uma ação primária. Uma rodada de confirmação após a
correção do espaçamento das ações, sem nova rodada de polish. Teclado, foco e
nome estável dos comandos comprovados pelo browser e testes.

UX_AUDITOR / Impeccable: detector local sem findings nos arquivos da recuperação.
Implementation integrity PASS: ledger, tokens existentes, resumo autoritativo e
disclosure nativo. Acessibilidade 3/4 (teclado/foco/labels/status testados; nenhuma
alegação de certificação WCAG completa); performance 3/4 (sem dependência ou
motion, aviso de bundle preexistente); theming 3/4 (tokens existentes, sem nova
promessa de dark mode); responsive 4/4 nas classes desktop exigidas; integrity
4/4. Total 17/20 no escopo auditado, P0=0/P1=0. Sem agenda de redesign adicional.
FILES_DELETED=0; HUMAN_RC_READY=FALSE; #291 continua aberta.

## Reparo causal de leitura transitória

A conferência do descriptor deve distinguir leitura temporariamente bloqueada
de divergência comprovada. O bloqueio exclusivo real de `RECOVERY_SESSION_V1`
no Windows reproduziu conversão indevida de promoção parcial em irretomável.
O teste RED falhou em duas variantes; a correção limitada mantém a recusa da
operação enquanto a leitura estiver indisponível, preservando o journal e a
possibilidade de retomar. GREEN: quatro testes PASS, incluindo o mesmo recovery
após liberar o lock e após restart, sem duplicar conteúdos ou alterar seus hashes.

O candidato `8f67987d6324da4935bdcbad3489c3bd6cc8650f` teve gate integral PASS
(16 etapas, 1936.151 s, timing ATTRIBUTION_REQUIRED), arquitetura sem findings,
170 testes de confiança PASS e publicação privada limpa. Esse candidato foi
bloqueado pela revisão independente: sua evidência permanece registrada, mas
não transfere aprovação ao HEAD reparado. A revisão é invalidada pela correção;
novo gate proporcional, CI e revisões finais devem ficar vinculados ao SHA novo.
Frontend e QA continuam aplicáveis por identidade dos arquivos, sem reabrir UX.
