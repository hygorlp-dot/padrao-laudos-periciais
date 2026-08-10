# Padrão de triagem e delimitação pericial

## Princípios aprovados

- Autonomia máxima por padrão; perguntar somente por exceção material.
- Saneamento técnico do tema controvertido como finalidade central.
- Evidência atual prevalece sobre experiência e modelos anteriores.
- Normas e modelos alimentam conhecimento rastreável, nunca fatos do caso.
- Quesitos pertinentes influenciam o plano do laudo futuro.
- Inconclusividade fundamentada é resultado técnico válido.
- `NÃO CONSTATADO` não equivale automaticamente a `INEXISTENTE`.

## Sequência

`ASSUNTO → CONTROVÉRSIA → TEMA TÉCNICO → OBJETO → OBJETIVO → QUESTÕES TÉCNICAS → PLANO`.

O laudo futuro terá por objetivo promover o saneamento técnico do tema
controvertido. A redação é consequência, não finalidade autônoma da triagem.

## Autoridade e conhecimento

Para o encargo, prevalece a decisão delimitadora. Para a análise, prevalecem
evidência e documentação do caso. Normas verificadas antecedem regras
canônicas, experiência e casos anteriores.

Modelos podem gerar `EXPERIENCIA_REFERENCIAL` ou `REGRA_CANDIDATA`; somente
aprovação expressa cria `REGRA_APROVADA`. Norma exige arquivo, hash, edição,
página/item quando disponível e status de verificação.

### Memória referencial privada

Quando `referencias/privadas/modelos-referenciais/` existir, a Skill deve
inventariar os arquivos, fazer engenharia reversa e registrar derivados apenas
em `referencias/privadas/conhecimento/`. Cada item deve ser classificado como
`PADRAO_CANONICO`, `EXPERIENCIA_REFERENCIAL`, `CASO_ANTERIOR`,
`REGRA_CANDIDATA` ou `REGRA_APROVADA`. Fatos, pessoas, locais, valores e
conclusões do caso anterior não podem migrar para o caso atual.

### Conhecimento normativo privado

Quando `referencias/privadas/normas/` existir, os derivados privados devem
separar entidade, número, título, edição, vigência, escopo, sistemas, temas,
definições, requisitos, critérios, métodos de verificação, ensaios, limitações,
referências cruzadas e aplicabilidade temporal. A proveniência deve registrar
arquivo, hash, norma, edição, página, seção/item quando disponível, método de
extração e status de verificação. Não copiar trechos extensos para documentação
versionável nem aplicar item não verificado.

Aplicabilidade temporal deve ser classificada como `APLICAVEL_PRINCIPAL`,
`APLICAVEL_COMPLEMENTAR`, `NAO_APLICAVEL` ou
`APLICABILIDADE_INCONCLUSIVA`, conforme as datas demonstráveis do caso.

Se as pastas privadas não existirem ou estiverem vazias, registrar
`INDISPONIVEL`; isso não autoriza inventar conhecimento nem necessariamente
impede o planejamento preliminar.

## Quesitos, ressalvas e conflitos

Preservar texto e numeração dos quesitos e gerar a relação `QUE-NNN ↔ QT-NNN ↔
seção futura`. Quesito jurídico não é descartado: separar a parcela técnica e
delimitar a matéria reservada ao Juízo. Toda limitação recebe `RES-NNN`; toda
divergência recebe `CNF-NNN` e não pode ser resolvida silenciosamente.

## Gates

`APTO_PARA_PLANEJAMENTO` exige tipo, tema, objeto, objetivo, questões, quesitos,
ressalvas e conflitos delimitados. `APTO_PARA_REDACAO` não pertence a esta etapa.
