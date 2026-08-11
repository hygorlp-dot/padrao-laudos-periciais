# Padrão de vistoria estruturada e motor de vícios

## Regras aprovadas

- A finalidade é sanear tecnicamente o tema controvertido.
- Arquivo de campo é evidência; não constitui, isoladamente, causa ou origem.
- `FOT-PLANO-NNN` e `MED-PLANO-NNN` representam planejamento; `FOT-NNN` e
  `MED-NNN` representam evidências efetivamente produzidas.
- Declaração de parte, assistente ou terceiro não equivale a observação do
  perito judicial.
- `NAO_CONSTATADA` descreve resultado limitado e não autoriza inexistência.

### Ingestão e reconciliação de campo

- O inventário preserva hash, caminho, método, EXIF/GPS disponível e ID estável.
- Anotação somente gera observação, medição, declaração ou limitação quando sua natureza estiver explicitamente estruturada.
- Texto livre, nome de arquivo e fotografia isolada não autorizam conclusão causal.
- A associação entre foto executada e planejada registra candidatos, score e método; associação insegura permanece pendente.
- A cobertura planejada/executada decorre dos IDs efetivamente associados, nunca da mera existência de arquivos.
- `relacoes_evidencia` é a fonte explícita do vínculo `OBS ↔ MED/FOT`; registra
  a origem e o motivo. Mesma QT, sistema, ambiente ou proveniência, sem vínculo
  inequívoco adicional, não autoriza associação automática.
- Execução de um item de cobertura não equivale a suporte analítico da PAT. O
  Motor deve bloquear quando a evidência material executada não estiver ligada
  à observação e à PAT correspondentes.

### Equivalência de execução

- A equivalência V1 é suportada somente para `MEDICAO` e `FOTOGRAFIA`.
- A capability de `MEDICAO` é a grandeza; a de `FOTOGRAFIA` é a finalidade.
- Tipo, capability e QT devem coincidir, e método substituto e justificativa
  devem estar registrados.
- `ATIVIDADE`, `ENSAIO` e `DOCUMENTO` não suportam equivalência nesta versão;
  somente execução direta e identificável satisfaz esses requisitos.

## Sequência causal

`ALG → evidência → OBS → manifestação → mecanismo → HIP → causa →
origem → classificação → PAT → QT → QUE`.

Manifestação, mecanismo, causa e origem são dimensões distintas. Toda
hipótese deve registrar evidências favoráveis, contrárias e ausentes e o
motivo de seu status.

O motor pode produzir `CONCLUSAO_TECNICA_DO_AGENTE` quando a cadeia probatória
e a autoauditoria forem suficientes. `APROVACAO_PROFISSIONAL_FINAL` é metadado
posterior e não condiciona causalidade, origem, criticidade, vício, QT ou gate.

## Pesquisa e conhecimento

Usar primeiro o conhecimento privado rastreável. Quando insuficiente,
pesquisar fonte oficial e verificar entidade, documento, versão, vigência,
sucessão e aplicabilidade temporal. Fonte secundária serve para descoberta,
não para fundamentar requisito crítico. Todo cache real permanece privado.

Modelos referenciais fornecem estrutura, métodos e práticas candidatas. Fatos,
partes e conclusões de casos anteriores não podem fundamentar o caso atual.

## Gates

- `APTO_PARA_REDACAO`: nenhuma questão material ou auditoria bloqueante.
- `APTO_PARA_REDACAO_COM_RESSALVAS`: limitações permitem exposição honesta.
- `BLOQUEADO_PARA_REDACAO`: o estado produziria texto enganoso, contraditório
  ou indefensável.

## Limites atuais

O motor V1 atende somente `VICIOS_CONSTRUTIVOS`. Outros tipos retornam
`MOTOR_ESPECIALIZADO_NAO_IMPLEMENTADO`. A etapa não produz laudo, respostas
finais, orçamento final, Word, PDF ou assinatura.
