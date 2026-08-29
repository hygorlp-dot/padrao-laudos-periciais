# Contratos de dados

Esta pasta contém os contratos de dados iniciais do projeto em JSON Schema Draft 2020-12.

## Arquivos

- `plano-redacao.schema.json`: finalidade e cobertura de QT, QUE, PAT,
  evidências, certeza e ressalvas antes da redação.
- `laudo-redacao.schema.json`: modelo semântico do laudo e claims rastreáveis,
  sem propriedades de layout Word.

- `processo.schema.json`: dados extraídos dos autos, separados em documentos, alegações, quesitos, decisões, conflitos e pendências.
- `vistoria.schema.json`: planejamento e registro da vistoria, incluindo participantes, métodos, equipamentos, limitações, fotografias e constatações de campo.
- `patologia.schema.json`: unidade técnica `PAT-NNN`, suas evidências, análise causal, classificações, conclusão e elegibilidade orçamentária.
- `laudo.schema.json`: agregação rastreável do laudo, com referências às patologias, quesitos, orçamento, normas e validação final.
- `pje-comum.schema.json`: definições reutilizáveis de proveniência, confiança, paginação, reconciliação, conflitos e elementos extraídos do PJe.
- `manifesto-pje.schema.json`: inventário e segmentação do PDF consolidado, sem duplicar o conteúdo integral dos documentos.
- `documento-pje.schema.json`: conteúdo estruturado de um documento PJe e de suas seções e anexos internos.
- `delimitacao-pericial.schema.json`: classificação do tipo de perícia,
  delimitação técnica, quesitos, cobertura, ressalvas, conflitos, módulos e
  plano pericial preliminar.
- `inventario-referencias.schema.json`: catálogo incremental por hash das
  fontes privadas.
- `conhecimento-referencial.schema.json` e
  `conhecimento-normativo.schema.json`: derivados privados com níveis e
  proveniência.
- `plano-vistoria.schema.json`: atividades, medições, fotografias,
  equipamentos, cobertura, autonomia e gate pré-vistoria.
- `inventario-vistoria.schema.json`: arquivos de campo e metadados incrementais.
- `analise-motor-vicios.schema.json`: manifestações, hipóteses, PAT, QT,
  quesitos, autoauditoria e gate de redação.
- `fonte-online.schema.json`: proveniência, vigência e controle de uso de
  fontes técnicas pesquisadas online.
- `auditoria-grounding-pericial.schema.json`: claim, evidências, saliência e
  veredito de grounding.
- `trilha-auditoria-agente.schema.json`: execução profissional auditável sem
  chain-of-thought ou raciocínio privado.
- `review-multiagente.schema.json`: output estruturado de revisão independente,
  com vínculo ao HEAD, prova de independência, findings e ranking auditável.

Os schemas rejeitam propriedades não declaradas. Alegações, documentos, constatações, inferências e resultados inconclusivos devem permanecer semanticamente separados.

## Dependência externa

A validação usa o pacote Python `jsonschema`, declarado em `pyproject.toml`. O pacote instala também `referencing`, usado para resolver referências entre os schemas. A resolução exata fica registrada em `uv.lock`.

```powershell
uv sync --locked --no-install-project
uv run --no-sync python scripts/validar_schemas.py
```

O validador confere os próprios schemas e os exemplos em
`tests/fixtures/schemas/` e `tests/fixtures/pje/`. Arquivos com sufixo
`-valido.json` ou `-valida.json` devem ser aceitos; os demais exemplos dessas
pastas são casos negativos e devem ser rejeitados.

## Fluxo de dados previsto

```text
PDF PJe
→ manifesto-pje.json
→ documento-pje.json
→ delimitacao-pericial.json
→ conhecimento pertinente
→ plano-vistoria.json
→ processo.json
→ vistoria.json
→ motor técnico
→ PAT-NNN
→ gate de redação
→ laudo.json futuro
```

Os contratos e mecanismos até o gate de redação estão implementados. A
execução semântica permanece orquestrada pelas Skills e condicionada à
evidência disponível.

## Limitações atuais

- Os schemas são contratos iniciais e não substituem a validação técnica do perito.
- A integridade interna da delimitação possui validador complementar; relações
  com arquivos distintos ainda exigem conferência contra o corpus-fonte.
- Não há OCR, motores especializados adicionais, laudo completo ou
  automação Word.
- Não há orçamento final nem respostas finais formatadas aos quesitos.
- Alterações nos enums e nas condicionais dependem de decisão canônica documentada.
