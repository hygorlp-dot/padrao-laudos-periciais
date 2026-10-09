# Manual operacional

## Finalidade

Este manual registra o fluxo efetivo verificável, suas fronteiras de
autoridade e o que ainda depende de aceitação profissional humana.

## Fluxo longitudinal sintético

1. Receber materiais autorizados e preservar a proveniência.
2. Extrair manifesto/documentos PJe sem inventar conteúdo.
3. Criar o Workspace e reconciliar o domínio judicial canônico plural.
4. Executar Case Analysis revisável e distinguir alegação, documento e decisão.
5. Criar e aprovar o Planning de vistoria.
6. Registrar Inspection, observações, medições, fotos originais e limitações.
7. Construir Evidence, PAT e Technical Findings com método e provenance.
8. Redigir e revisar o Report; texto não cria verdade técnica.
9. Finalizar o Word/DOCM autoritativo com binding e hash.
10. Controlar Budget separadamente do mérito técnico.
11. Fechar o Workspace, criar Backup e executar Verify → Stage → promoção humana
    explícita → Recovery/Reopen.

O percurso acima é provado por oráculos sintéticos sobre a superfície HTTP
`/app-api` (`tests/test_product_integration_oracle_v1.py`) e sobre o processo real
do produto (`tests/test_v7_final_rc_oracle_v1.py`), sem chamadas diretas aos
serviços; o terminal não faz parte do fluxo normal exercitado. Isso não prova a
UI/Data Layer nem a aceitação Human RC. O commit validado e o estado das rodadas ficam em
`config/product-maturity-v1.json` e nas Issues #256 e #238, não neste manual.

## Autoridade e segurança

- `REPRESENTATIVE != PARTY` e `ACCESS != PARTICIPATION`.
- `AI_PROPOSAL != EFFECTIVE_VALUE`.
- A cadeia de IA é `SOURCE_VALUE → AI_PROPOSAL → ENGINE_DECISION →
  PROFESSIONAL_OVERRIDE`.
- Provider, contexto/source, saída estruturada, revalidação, auditoria
  append-only e limites de tokens/custo são obrigatórios.
- Dados reais do produto ficam na raiz privada local configurada na instalação;
  `referencias/privadas/` é uma área local do repositório, nunca versionada.
  `PRIVATE_EGRESS = FALSE`.
- Recovery não promove automaticamente e não trata estado verificado como
  promovível sem decisão explícita.

## Delivery

O Word/DOCM aprovado é o artefato profissional autoritativo. Ao renderizar a
entrega, o produto deriva o PDF localmente pelo Microsoft Word 16 instalado na
máquina, sem serviço em nuvem. O PDF só é aceito após verificação de fidelidade
estrutural e visual e fica vinculado por SHA-256 ao Word exato. Se a conversão
for recusada ou o Word não estiver disponível, o Word permanece como entrega
completa e a interface informa o PDF como indisponível. PDF diagnóstico ou texto
extraído não prova fidelidade visual e não pode ser finalizado como PDF
profissional.

## Estado de implementação

Implementados: foundations das Stages 0–7, Budget, Productization/Recovery,
Field/Mobile, AI Gateway/proposals e o oracle longitudinal sintético.

Pendentes: Human RC no Windows, execução de caso real e
release/packaging distribuível. A dívida histórica de duração do `verify_core`
permanece registrada no Issue #192 e não é alterada por este manual.

A maturidade distingue a evidência de um candidato histórico do estado
operacional vivo. `HUMAN_RC_READY = FALSE`: mudanças materiais posteriores
exigem novo candidato; a readiness antiga não representa o HEAD atual e o
aceite humano continua pendente. A declaração versionada aponta a evidência
histórica, enquanto `python -m scripts.quality.product_maturity` lê o HEAD vivo.

## Histórico

As versões anteriores descreviam um fluxo inicial baseado em
`manifesto-pje.json → documento-pje.json → processo.json → vistoria.json →
PAT-NNN`, com Word/PDF como etapas futuras. Esse registro histórico é
preservado; o fluxo longitudinal acima é o estado efetivo atual.

## Auditoria

Antes de qualquer conclusão profissional, executar grounding, auditoria de
claims, verificação de provenance, revisão independente aplicável e registro
na trilha profissional. Conclusão e assinatura permanecem responsabilidade
indelegável do perito.
