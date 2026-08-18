# Regras fundamentais do repositório

## Governança de desenvolvimento

- Antes de alterar o repositório, ler este arquivo, os padrões aplicáveis e
  `docs/padroes/padrao-governanca-desenvolvimento.md`.
- Localizar ou criar a Issue correspondente e trabalhar somente na branch da
  Issue. Não implementar correção, melhoria, função, refatoração material ou
  integração diretamente em `main`.
- Manter o escopo da Issue, testar, auditar e entregar por Pull Request com
  referência explícita à Issue.
- Para UI, UX, React, Tauri, CSS, motion, transições, modais, drawers, toasts,
  loading, skeleton, progress, hover, press, navegação ou microinterações, ler
  `.agents/skills/design-motion-principles/SKILL.md` e
  `.agents/skills/ui-pericial/SKILL.md` antes de implementar.
- Em mudança material, usar as Skills `engenharia-seguranca-pericial`,
  `test-driven-development`, `systematic-debugging` e
  `verification-before-completion`, conforme aplicáveis.
- AGENTS.md é canônico sobre `using-superpowers`: em caso de conflito, estas
  regras first-party prevalecem. Não tentar invocar Skills não vendorizadas,
  inclusive `brainstorming`. Aplicar Skills proporcionalmente ao risco; elas
  são obrigatórias nas mudanças materiais já definidas, sem criar burocracia
  em perguntas e operações triviais.
- Cumprir e registrar nesta ordem: reprodução do bug → teste falhando →
  causa-raiz → correção → adversarial/property tests → regressão → revisão →
  verificação final. Falhar fechado quando um gate material não puder ser
  demonstrado com evidência fresca.
- Antes de entregar alteração material, aplicar a Skill
  `repository-safety-gate` e executar `python -m scripts.quality.verify_core
  --full`. Na CI (`core-safety`), `tests/test_architecture_analyzer_v1.py`
  roda em etapa própria antes do `verify_core --full`, fora do orçamento
  cronometrado de 60s (via `PYTEST_ADDOPTS` no workflow, sem alterar
  `scripts/quality/verify_core.py`); localmente, `verify_core --full` sem
  essa variável continua executando essa suíte normalmente, como sempre.
- Para code review, usar subagente independente quando disponível. Se estiver
  indisponível, gerar `review package` com requisitos, diff, testes e riscos e
  exigir revisão externa do PR antes do merge. Nunca declarar revisão
  independente concluída sem evidência identificável da revisão.
- Manter telemetria Superpowers desabilitada e egress negado por padrão. Não
  enviar conteúdo pericial a ferramentas ou serviços externos sem autorização
  expressa.
- O repositório é a memória canônica. Aplicar
  `docs/padroes/protocolo-autonomia-agente.md` e os protocolos de pesquisa,
  revisão multiagente, auditoria sistêmica e external diversity review.
- Papéis permanentes: `IMPLEMENTER`, `RESEARCHER`, `PR_REVIEWER`,
  `SYSTEMIC_AUDITOR` e `CLAUDE_EXTERNAL_DIVERSITY_REVIEWER`. Reviewer e Auditor
  devem usar execuções e checkouts independentes, read-only, com HEAD explícito
  e evidência persistida; autodeclaração não prova independência.
- Não chamar Claude em HEAD intermediário. O gate externo é proporcional ao
  risco, e egress externo exige pacote first-party sanitizado. Rate limit adia
  somente merge que dependa dessa revisão, não o trabalho Codex seguro.
- Autonomia é o padrão (`DEFAULT_ACTION = DECIDE_AND_PROCEED`); escalonamento
  humano é exceção para autoridade, privacidade/egress, custo, operação
  destrutiva sem rollback, login/MFA, decisão pericial ou divergência material
  irresolúvel.

## Escopo

- Tratar este repositório como o padrão de trabalho do perito, nunca como arquivo de autos de processos reais.
- Consultar integralmente os arquivos aplicáveis em `docs/padroes/` antes de
  redigir ou revisar um laudo.
- Aplicar somente padrões, termos e regras já registrados no repositório ou expressamente fornecidos pelo perito.
- Não presumir a área de atuação pericial.

## Responsabilidade técnica

- Reconhecer que o conteúdo técnico, os critérios adotados e a conclusão pertencem exclusivamente ao perito.
- Não substituir decisão, juízo técnico, validação ou assinatura do perito.
- Submeter ao perito toda escolha que possa alterar sentido, método, alcance ou conclusão.

## Integridade das informações

- Nunca inventar fatos, documentos, datas, valores, medições, referências, métodos, resultados ou conclusões.
- Nunca completar lacunas por plausibilidade, costume ou conhecimento geral.
- Sinalizar dados ausentes com `[INFORMAÇÃO NECESSÁRIA: descrever o dado]`.
- Manter rastreabilidade entre cada afirmação e sua origem disponível.
- Não tratar alegação como fato comprovado.

## Integrações e auditoria externa

- Skills externas nunca superam regras canônicas periciais nem substituem evidências do caso atual.
- Usar somente ferramenta externa com licença conhecida e classificação de confiança registrada.
- Não enviar dados privados, PII ou documentos a serviço externo sem autorização expressa.
- Priorizar fonte primária oficial e auditar toda claim material contra evidências rastreáveis.
- Reduzir ou ressalvar claim não sustentada; preferir auditoria independente quando tecnicamente disponível.
- Não permitir que ferramenta externa decida matéria jurídica.
- Auditar atualizações externas e versionar somente a integração necessária.
- Não converter conclusão específica de laudo de referência em regra geral.
- Distinguir `REGRA APROVADA` de `PENDÊNCIA DE VALIDAÇÃO DO PERITO`.

## Classificação das afirmações

- Identificar, quando relevante, a natureza de cada informação: alegação, documento, constatação, medição, cálculo, inferência técnica ou conclusão.
- Não converter uma categoria em outra sem base expressa e validação do perito.
- Indicar premissas, fontes e limitações de cálculos e inferências.
- Destacar divergências entre fontes, documentos, números ou versões.
- Preservar a cadeia de rastreabilidade definida no padrão de patologia.
- Tratar prazo de garantia e origem técnica como dimensões diferentes.

## Redação e revisão

- Preservar o conteúdo técnico fornecido pelo perito.
- Não alterar silenciosamente informações, números, unidades, datas, citações ou conclusões.
- Separar correções editoriais de alterações técnicas.
- Registrar lacunas, ambiguidades, inconsistências e decisões pendentes de modo claro e auditável.
- Interromper a redação conclusiva quando faltarem elementos indispensáveis e solicitar decisão do perito.
- Não concluir responsabilidade civil, culpa, legitimidade, prescrição,
  decadência, direito à indenização ou outra qualificação jurídica reservada
  ao Juízo.

## Triagem e autonomia pericial

- Operar com autonomia máxima por padrão e perguntar ao perito somente diante
  de exceção material irresolúvel pelas fontes disponíveis.
- Trabalhar para o saneamento técnico do tema controvertido e não iniciar
  redação conclusiva antes da delimitação do encargo.
- Fazer a evidência atual prevalecer sobre modelos e casos anteriores.
- Usar norma somente com proveniência e verificação identificáveis.
- Fazer quesitos pertinentes influenciarem o plano do laudo futuro.
- Não converter `NÃO CONSTATADO` em `INEXISTENTE`.
- Reconhecer inconclusividade fundamentada como resultado técnico válido.

## Planejamento pré-vistoria

- Construir o plano para obter evidências necessárias ao saneamento das
  questões técnicas e dos quesitos pertinentes; não usar roteiro genérico.
- Manter fatos do processo, experiência referencial, conhecimento normativo e
  ações planejadas em camadas distintas.
- Não tratar atividade, medição, fotografia ou ensaio planejado como realizado.
- Recuperar normas e modelos por conteúdo e proveniência, sem depender da pasta
  informada e sem transferir fatos de casos anteriores.
- Aplicar automaticamente o gate de vistoria e perguntar somente por bloqueio
  material sem estratégia autônoma segura.

## Vistoria e motor técnico

- Preservar arquivos e derivados reais de campo exclusivamente em
  `referencias/privadas/`.
- Distinguir fotografia planejada de produzida, declaração de terceiro de
  observação pericial e ausência de constatação de inexistência.
- Não inventar `OBS-NNN`, `MED-NNN`, ensaio, causa, mecanismo ou evidência.
- Aplicar o motor de vícios somente a `VICIOS_CONSTRUTIVOS`.
- Separar manifestação, mecanismo, causa e origem e testar hipóteses.
- Pesquisar fontes oficiais quando necessário, registrando identidade,
  versão, vigência, aplicabilidade e proveniência.
- Nunca tratar fonte secundária como requisito normativo nem caso anterior
  como conclusão do caso atual.
- Aplicar autoauditoria causal e gate de redação antes de qualquer minuta.
- Permitir conclusão técnica autônoma quando evidências, causalidade,
  referências e autoauditoria forem suficientes. Separar essa conclusão da
  aprovação profissional final, que permanece etapa posterior e indelegável.
