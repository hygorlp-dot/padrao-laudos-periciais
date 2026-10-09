# Exportar profissional — Incremento 3B

> Execução estritamente serial pela skill executing-plans; revisão independente somente no HEAD final.

**Objetivo:** preparar, conferir e registrar a entrega do laudo sem exigir IDs internos, preservando Word oficial, PDF derivado e histórico.

**Base:** eb75cc97ffc8c4518f04a3d1260b09c0669e241a. Refs #291. Uma branch e uma PR; 3A terminal.

**Arquitetura:** reutilizar Local API, Product Bridge, Delivery lifecycle e template padrão. UI apresenta estados existentes; não decide autoridade nem cria lifecycle, endpoint, cache ou tabela. React/TypeScript/CSS locais, sem novas dependências.

## Auditoria antes de editar

DeliveryFoundationView mistura artefatos, destaca template_id, conserva fundamentação sem decisão aplicável e dá primárias concorrentes no draft com Word. O CSS contém sombras e borda lateral contrárias ao DESIGN.md. Promise.all confunde 404 do histórico com entrega ausente. História tem revisão/download, mas faltam data, papéis, relação com predecessor e indicação histórica. Backend valida exatamente Word/PDF, provenance, manifesto, hashes e decisões; só DRAFT aceita render/anexo. Reissue aceita SUPERSEDED ou STALE originado em DELIVERED. Workflow-status já projeta Exportar; não duplicar.

## Composição aprovada

Paleta e tipografia do DESIGN.md: grafite #18201d, mineral #f2f4f1, papel #fcfdfb, slate #5c655f, regra #d6dcd7, foco #185f72. Aptos Display para títulos, Aptos para leitura; mono somente auditoria. Ledger plano com divisores, sem novas animações.

Situação/revisão da entrega + revisão do laudo → Word oficial → PDF derivado → anexos → próxima decisão → histórico. Detalhes técnicos preservam binding/template/renderer/artefatos/decisões. Uma primária; geração repetida e substituição são secundárias. Fundamento contextual mantém reason persistido.

## Execução e provas

- [x] Testes RED: hierarquia/autoridade, ação por estado, fundamento contextual, stale/reissue, histórico, unavailable versus empty, erro parcial, acessibilidade e nome estável durante geração.
- [x] Implementação mínima em DeliveryFoundationView, componentes de apresentação de Delivery e CSS dedicado; tipos de provenance já existente em deliverySnapshot. Atualizar testes incumbentes para linguagem profissional.
- [x] Vitest focado e frontend completo (381 testes), lint, TypeScript, build; testes backend focais (742), incluindo Word nativo. Impeccable detector local sem update check.
- [x] Build produção, 1366/1280/1024: estados reais e matriz sintética de UI, teclado/foco/disclosure, nomes longos, zero overflow. Uma inspeção batelada; 48 verificações e capturas, sem outra iteração de polish.
- [x] Backend real sintético: approved Report → delivery/default → render Word/PDF Word16 → ready/approve/finalize/deliver → upstream válido alterado → stale com bytes preservados → reissue draft e predecessor auditável. Sem PDFs reais.
- [ ] Privacy/schema/hygiene/impact e gate integral fresco somente após funcional; sem retry-until-green.
- [ ] Commit/push/uma PR Refs #291, CI protegido e PR_REVIEWER independente HEAD final; SYSTEMIC_AUDITOR conforme materialidade. P0/P1 bloqueiam, P2 tracking proporcional.
- [ ] Classificador first-party HEAD final; dispensa #311 não se transfere. Claude uma vez se exigido; indisponibilidade exige autorização nova PR + SHA.
- [ ] Merge normal se gates satisfeitos; uma prova pós-main, 3B terminal e parar.

## Defeitos causais reproduzidos no fluxo de Delivery

O cliente reconstruía o manifesto anterior do template padrão e rejeitava os bindings profissionais já publicados pelo backend. Regressões RED provaram a incompatibilidade; o cliente agora aceita somente os dois manifestos canônicos conhecidos e consulta o Report vinculado pelo endpoint existente ao renderizar uma entrega reaberta. Divergência de identidade/revisão bloqueia a geração.

A geração nativa reproduziu rejeição de fidelidade visual quando capítulos profissionais vazios produziam tabelas de título adjacentes: o Word unia suas bordas. Duas regressões RED (estrutura DOCX e PDF nativo) precederam a separação canônica por parágrafo vazio apenas entre títulos consecutivos. A verificação de fidelidade continua intacta; nenhum texto técnico ou template foi reaberto.

O navegador real também reproduziu perda de foco ao desabilitar o botão durante geração e resposta perdida após o backend concluir o render. O nome permanece estável, aria-disabled conserva o foco e o handler impede duplicação; falha de transporte oferece leitura de verificação sem repetir a geração. A prova nativa posterior confirmou foco preservado e Word/PDF verificados.

Evidências locais sintéticas: `C:/tmp/export3b-20261009-evidence/`. Recibos de render, lifecycle, stale e reissue registram downloads/hash/tamanhos e preservação das decisões. A matriz desktop cobre os 16 cenários solicitados em três larguras. Nenhum documento real foi usado ou enviado nesta fase.

## Limites

FILES_DELETED=0; HUMAN_RC_READY=FALSE; #291 OPEN; NO_3C/NO_3D/NO_HUMAN_RC/NO_PACKAGING/NO_NEW_PREDECESSOR/NO_MEGA_REFACTOR. STALE não apaga; histórico entregue imutável; supporting file não é fonte; protocolo/assinatura fora do produto; AI proposal only; privado sem egress. Não reabrir template ou fidelidades do 3A sem defeito causal reproduzido.
