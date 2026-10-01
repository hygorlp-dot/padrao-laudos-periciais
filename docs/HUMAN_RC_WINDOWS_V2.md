# HUMAN_RC_WINDOWS_V2 — aceitação humana no Windows

Sucessor da HUMAN_RC_WINDOWS_V1 (#238) após o Roadmap V7 (#256). É um roteiro
para o perito executar pela interface normal, não uma suíte automatizada.

| Parâmetro | Valor |
|---|---|
| Ambiente | `WINDOWS REAL` |
| Word | `MICROSOFT WORD 16` instalado localmente |
| Interface | `NORMAL UI` (navegador na origem local `http://127.0.0.1:<porta>/`) |
| Regra dominante | `NO DEVELOPMENT TERMINAL` no uso normal |
| Dados | somente sintéticos nesta rodada; `PRIVATE_EGRESS = FALSE` |
| SHA | `FINAL_RC_CANDIDATE_SHA` registrado nas Issues #256 e #238 |

## Preparação (uma vez, fora do fluxo avaliado)

Ainda não há instalador (`PACKAGING_GAP`). A preparação abaixo é feita uma vez e
não conta como uso de terminal no fluxo avaliado.

```powershell
git clone https://github.com/hygorlp-dot/padrao-laudos-periciais.git C:\SistemaPericial\app
cd C:\SistemaPericial\app
git checkout <FINAL_RC_CANDIDATE_SHA>
python -m pip install --require-hashes -r requirements-dev.txt
cd frontend; npm ci; npm run build; cd ..
```

Crie, **fora do repositório**, o atalho `C:\SistemaPericial\Iniciar Sistema Pericial.cmd`:

```bat
@echo off
cd /d C:\SistemaPericial\app
python -m scripts.planejamento_pericial.app_composition --database C:\SistemaPericial\dados\produto.sqlite3 --frontend C:\SistemaPericial\app\frontend\dist --private-root C:\SistemaPericial\dados\privado --port 8765
```

Depois, o uso normal é: duplo clique no atalho → abrir `http://127.0.0.1:8765/`
no navegador. A janela do atalho é o processo do produto; fechá-la encerra o
produto.

## Roteiro (o perito, pela interface)

Marque `PASS`, `FAIL` ou `N/A` em cada bloco e anote o que observou.

| Bloco | Ações humanas | Aceite |
|---|---|---|
| **A. Inicialização** | Duplo clique no atalho; abrir o endereço no navegador. | Tela inicial carrega; nenhum erro técnico visível. |
| **B. Workspace** | Criar um workspace; conferir a identificação; abrir um segundo workspace e voltar. | Criação e troca sem mistura de dados. |
| **C. Materiais / PJe** | Importar um PDF PJe sintético; conferir o processamento; excluir uma peça e reabilitá-la. | Bytes preservados; exclusão e reabilitação visíveis; histórico não reescrito; erro nunca aparece como sucesso. |
| **D. Processo / Imóvel** | Conferir os dados do processo extraídos; registrar o imóvel. | Fonte de cada dado identificável; correção profissional possível. |
| **E. Intake / Análise do Caso** | Aceitar quesitos propostos; revisar partes, alegações e documentos; confirmar ou corrigir. | Proposta de IA nunca vira decisão sozinha; revisão profissional registrada. |
| **F. Planejamento** | Criar o plano e aprovar os itens. Depois, aceitar um quesito novo na Análise e usar **Criar novo planejamento**. | Plano anterior marcado como desatualizado e preservado; novo plano nasce sem decisões. |
| **G. Vistoria** | Registrar observação, medição, foto e declaração. Após um novo plano, usar **Iniciar nova vistoria** e **Reaproveitar selecionados** apenas para os registros escolhidos. | Vistoria anterior preservada; só o escolhido entra, com data, conteúdo e foto originais; itens continuam pendentes. |
| **H. Evidências / Constatações** | Criar evidências e constatações; revisar a proposta PAT. Se a vistoria mudou, usar **Iniciar nova cadeia técnica** e **Gerar nova proposta PAT sobre a vistoria atual**. | Nada é promovido sem decisão profissional; cadeia anterior preservada. |
| **I. Laudo** | Revisar conteúdo, quesitos, tabelas, figuras e autoria profissional; aprovar. | Autoria e aprovação exatas; nenhuma autoridade genérica. |
| **J. Word / PDF / Entrega** | Gerar o Word; renderizar a entrega; baixar Word e PDF; anexar um PDF de apoio à entrega. | Word é o artefato autoritativo e o PDF é derivado; a UI distingue os dois; o anexo de apoio **não** aparece entre os materiais do caso. |
| **K. Orçamento** | Registrar horas, honorários e um pagamento. | Orçamento separado do laudo e da entrega. |
| **L. Backup** | Criar o backup pela UI e guardar o arquivo. | Backup gerado sem erro; nenhuma pendência offline escondida. |
| **M. Fechar processo** | Fechar o navegador e a janela do atalho (encerrar o produto por completo). | Nenhum processo do produto continua rodando. |
| **N. Reiniciar de verdade** | Duplo clique no atalho de novo; abrir o endereço. | Produto volta a funcionar sem passos extras. |
| **O. Reabrir** | Abrir o workspace; conferir materiais, análise, planejamento, vistoria (com o reaproveitamento), constatações, laudo, entrega e orçamento. | Tudo igual ao momento antes de fechar. |
| **P. Recovery** | Verificar o backup; preparar a recuperação (staging); promover explicitamente; reabrir o workspace recuperado. | Nenhuma promoção automática; nenhum dado perdido; workspace recuperado igual ao original. |

## O que observar durante toda a sessão

Erro técnico (stack trace) visível · jargão interno ou identificador sem
contexto · botão ambíguo · ação sem retorno · carregamento infinito · falso
sucesso · travamento aparente · beco sem saída · necessidade de terminal · não
saber o próximo passo · algo salvo que some depois de reiniciar.

Classifique cada achado como `P0` (perda de dado, falso sucesso, autoridade
promovida sem decisão), `P1` (fluxo bloqueado sem contorno pela UI), `P2`
(contornável) ou `UX`.

## Onde registrar falhas

- Um comentário na Issue #238 por rodada, com o checklist A–P, o SHA, as versões
  de Windows e Word e os horários.
- Cada `P0`/`P1` reproduzido em sua própria Issue causal (sem Issue guarda-chuva),
  com passos de reprodução pela UI.
- **Nunca** anexar dado real, nome de parte, número de processo real ou captura
  com informação privada em Issue, PR, log ou fixture públicos.

## Veredito

- `HUMAN_RC_WINDOWS_V2 = PASS` somente sem `P0`, sem `P1` material, com A–P
  alcançáveis pela UI, sem terminal no uso normal, com reinício, reabertura,
  Word/PDF e recovery aprovados.
- `HUMAN_RC_WINDOWS_V2 = BLOCKED` se um `P0`/`P1` for reproduzido; o reparo segue
  `REPRODUCE → RED → ROOT_CAUSE → MINIMUM_REPAIR → REGRESSION → REVIEW → POST_MAIN PROOF`.
- Após `PASS`: caso real de ponta a ponta, somente na fronteira privada.
