---
name: ARCD — Calibrated Process Ledger
description: Um ledger técnico sóbrio que mantém o fluxo pericial visível, preciso e auditável.
colors:
  mineral: "#f2f4f1"
  paper: "#fcfdfb"
  graphite: "#18201d"
  graphite-soft: "#25302b"
  slate: "#5c655f"
  rule: "#d6dcd7"
  rule-dark: "#3b4741"
  ochre: "#7b570d"
  ochre-bright: "#c59a2a"
  error: "#9a3f2f"
  focus: "#185f72"
typography:
  display:
    fontFamily: '"Aptos Display", Aptos, "Segoe UI", sans-serif'
    fontSize: "clamp(2.35rem, 4vw, 4.4rem)"
    fontWeight: 580
    lineHeight: 1
    letterSpacing: "-0.035em"
  headline:
    fontFamily: '"Aptos Display", Aptos, "Segoe UI", sans-serif'
    fontSize: "1.35rem"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "-0.015em"
  body:
    fontFamily: 'Aptos, "Segoe UI", Arial, sans-serif'
    fontSize: "1.03rem"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: 'Aptos, "Segoe UI", Arial, sans-serif'
    fontSize: "0.72rem"
    fontWeight: 400
    lineHeight: 1.5
  data:
    fontFamily: '"Cascadia Mono", "SFMono-Regular", Consolas, monospace'
    fontSize: "0.82rem"
    fontWeight: 700
    lineHeight: 1.5
rounded:
  sheet: "0.18rem"
  control: "0.38rem"
  pill: "999px"
spacing:
  1: "0.25rem"
  2: "0.5rem"
  3: "0.75rem"
  4: "1rem"
  5: "1.5rem"
  6: "2rem"
  7: "3rem"
  8: "4.5rem"
components:
  button-primary:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.paper}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0.65rem 0.9rem 0.65rem 1rem"
    height: "2.75rem"
  button-primary-hover:
    backgroundColor: "{colors.graphite-soft}"
    textColor: "{colors.paper}"
  workflow-link:
    backgroundColor: "transparent"
    textColor: "{colors.slate}"
    rounded: "{rounded.control}"
    padding: "0.36rem 0.65rem 0.36rem 0.2rem"
    height: "2.55rem"
  workflow-index-active:
    backgroundColor: "{colors.ochre-bright}"
    textColor: "{colors.graphite}"
    size: "1.75rem"
  empty-sheet:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.sheet}"
    padding: "1.2rem 0.75rem"
    width: "4.1rem"
    height: "5.2rem"
---

# Design System: ARCD

## Overview

**Creative North Star: "The Calibrated Process Ledger"**

O sistema visual trata o trabalho pericial como um ledger de processo calibrado: um trilho de grafite mantém a sequência inteira à vista, enquanto um plano de papel mineral oferece espaço silencioso para cada etapa. A aparência é sóbria, técnica, auditável e humana; a precisão vem de alinhamentos, numeração tabular, regras finas e hierarquia tipográfica, não de ornamentação.

A densidade é compacta na navegação e deliberadamente aberta no conteúdo. A profundidade permanece quase toda plana, construída por contraste tonal entre grafite, papel e mineral. O shell não simula dados, dashboards ou atividade inexistente: estados vazios e de prontidão explicam honestamente o que o produto pode fazer agora.

**Key Characteristics:**

- Trilho de workflow grafite fixo ao lado de um plano de conteúdo mineral.
- Ocre usado com parcimônia para posição, progresso e pequenos sinais de leitura.
- Hierarquia humana em Aptos Display, corpo neutro em Aptos e dados em Cascadia Mono.
- Regras de 1px, cantos compactos e uma única sombra ambiente no símbolo de folha vazia.
- Estados explícitos e conteúdo factual, sem inventar casos, métricas ou evidências.

## Colors

A paleta combina neutros minerais levemente verdes com grafite profundo; ocre marca progressão, azul-petróleo garante foco e ferrugem comunica erro.

### Primary

- **Graphite Rail** (`graphite`): estrutura o trilho lateral e a ação primária; é a âncora visual do shell.
- **Soft Graphite** (`graphite-soft`): oferece uma mudança tonal discreta no hover da ação primária.

### Secondary

- **Ledger Ochre** (`ochre`): marca índices de página, sublinhados de ação e linhas de progresso.
- **Calibrated Brass** (`ochre-bright`): identifica exclusivamente o índice da etapa ativa no trilho.

### Tertiary

- **Focus Teal** (`focus`): reserva-se a seleção de texto e ao contorno de foco visível.
- **Forensic Rust** (`error`): comunica falha sem competir com o eixo principal do workflow.

### Neutral

- **Mineral Ground** (`mineral`): plano principal do workspace e pista do scrollbar.
- **Clean Paper** (`paper`): topbar, folha vazia, superfícies claras e texto invertido sobre grafite.
- **Technical Slate** (`slate`): texto secundário, rótulos de contexto e descrições.
- **Pale Rule** (`rule`): divisores, bordas e linhas da folha no plano claro.
- **Dark Rule** (`rule-dark`): divisores e trilho de conexão sobre grafite.

### Named Rules

**The Rare Ochre Rule.** O ocre nunca preenche grandes superfícies; ele existe como marca calibrada de posição, avanço ou ênfase linear.

**The Honest State Color Rule.** Azul-petróleo significa foco e ferrugem significa erro; nenhum deles é usado como decoração.

## Typography

**Display Font:** Aptos Display (com Aptos e Segoe UI como fallback)

**Body Font:** Aptos (com Segoe UI e Arial como fallback)

**Label/Mono Font:** Cascadia Mono (com SFMono-Regular e Consolas como fallback)

**Character:** A família display traz autoridade sem teatralidade; o corpo permanece familiar e legível em sessões longas. A face monoespaçada separa coordenadas de fluxo e índices do texto narrativo.

### Hierarchy

- **Display** (580, `clamp(2.35rem, 4vw, 4.4rem)`, 1): título único da etapa, com tracking fechado para formar um bloco firme.
- **Headline** (700, `1.35rem`, 1.5): título dos estados operacionais dentro do plano de conteúdo.
- **Body** (400, `1.03rem`, 1.7): descrições de página com largura de até `60ch`; mensagens de estado ficam em até `58ch`.
- **Label** (400, `0.72rem`, 1.5): contexto compacto na topbar e metadados auxiliares.
- **Data** (700, `0.82rem`, 1.5): índices de página e coordenadas de etapa, sempre com numerais tabulares.

### Named Rules

**The Two Voices Plus Coordinates Rule.** Aptos Display nomeia, Aptos explica e Cascadia Mono localiza; não misture essas responsabilidades.

**The One Display Moment Rule.** Cada vista tem um único título display dominante; subtítulos e estados permanecem na escala headline.

## Layout

O shell desktop é uma grade de duas colunas: trilho lateral fixo de `15.5rem` e workspace fluido. Abaixo de `1000px`, o trilho contrai para `13.5rem`; o documento mantém largura mínima de `760px`, coerente com o uso técnico em desktop. A sidebar permanece sticky, ocupa `100vh` e rola independentemente quando necessário.

A topbar tem altura mínima de `5.25rem` e padding horizontal fluido entre `2rem` e `4.5rem`. O conteúdo principal usa respiro vertical entre `3.5rem` e `5.5rem`, padding horizontal entre `2.25rem` e `6.5rem`, e limita a rota a `65rem`. Cabeçalhos ficam em até `50rem`. O ritmo base segue a escala de `0.25rem` a `4.5rem`; espaços amplos separam capítulos, enquanto incrementos menores mantêm a navegação compacta.

**The Rail-and-Plane Rule.** O workflow completo permanece no trilho; o plano claro mostra somente a etapa ou estado em foco.

**The Narrow Reading Rule.** Mesmo quando o workspace cresce, descrições não ultrapassam aproximadamente 60 caracteres por linha.

## Elevation & Depth

O sistema é plano por padrão. Profundidade vem da estratificação tonal entre trilho, topbar, fundo mineral e superfícies de papel, além de regras de `1px`. Há uma única elevação ambiente: a pequena folha do estado vazio usa `0 0.75rem 1.8rem rgb(24 32 29 / 8%)` para parecer um artefato físico pousado no workspace.

### Shadow Vocabulary

- **Empty Sheet Ambient** (`0 0.75rem 1.8rem rgb(24 32 29 / 8%)`): somente para o símbolo de documento vazio.

### Named Rules

**The One Ambient Shadow Rule.** Navegação, topbar, botões e contêineres ficam planos; apenas a folha vazia recebe sombra.

## Shapes

Os cantos são discretamente arredondados e próximos da geometria retangular. Controles recorrentes usam o raio compacto `control`; a folha usa o raio ainda menor `sheet`. Pílulas aparecem apenas em linhas de estado e elementos funcionais estreitos, enquanto o círculo completo é reservado a marcas de estado com ícone. Regras finas e silhuetas contidas preservam a sensação de instrumento técnico.

**The Contained Geometry Rule.** Arredondamento suaviza a interação, mas nunca transforma o shell em uma coleção de cartões macios.

## Components

### Buttons

- **Shape:** retângulo compacto com cantos discretos (`control`) e altura mínima de `2.75rem`.
- **Primary:** papel sobre grafite, peso 680 e padding levemente maior à esquerda para equilibrar texto e seta.
- **Hover / Focus:** hover muda apenas para grafite suave; active comprime para `scale(0.985)`; foco usa contorno azul-petróleo de `3px` com offset de `3px`. As transições funcionais duram `140ms` na curva `cubic-bezier(0.22, 1, 0.36, 1)`.
- **Text action:** texto grafite com sublinhado ocre de `2px`, sem recipiente ou sombra.

### Cards / Containers

- **Corner Style:** os estados não são cartões; usam divisores horizontais. A única peça semelhante a cartão é a folha vazia (`sheet`).
- **Background:** o conteúdo permanece sobre Mineral Ground; Clean Paper é reservado à topbar e à folha.
- **Shadow Strategy:** somente a folha vazia segue a exceção descrita em Elevation & Depth.
- **Border:** regras de `1px` em Pale Rule.
- **Internal Padding:** o estado usa `3rem` vertical e nenhum preenchimento lateral próprio.

### Navigation

O trilho apresenta dez etapas e o início em uma sequência vertical conectada. Cada link combina um índice monoespaçado de `1.75rem` com um rótulo; o hover recebe papel sobre um véu branco de 5%, e o ativo recebe véu de 7% e peso 650. Somente o índice ativo muda para Calibrated Brass. A posição atual também aparece na topbar como coordenada monoespaçada com borda fina.

### Status States

Loading usa uma barra ocre curta; empty usa a folha física; ready e error usam marcas circulares com SVG linear. Todos compartilham uma grade de `5.25rem` para o sinal e uma coluna textual, altura mínima de `15rem` e divisores superior e inferior. O ícone é sempre SVG de traço, nunca glifo de fonte.

## Do's and Don'ts

### Do:

- **Do** mantenha o trilho grafite e o plano mineral como as duas massas principais do shell.
- **Do** use índices monoespaçados e numerais tabulares para tornar a posição do workflow verificável.
- **Do** preserve uma ação primária por vista e estados vazios que descrevam honestamente a ausência de caso.
- **Do** respeite foco visível e desative movimento funcional quando `prefers-reduced-motion` estiver ativo.
- **Do** use ícones SVG lineares pequenos somente quando eles comunicarem estado ou direção.

### Don't:

- **Don't** transforme etapas ou estados em um mosaico de cards de dashboard.
- **Don't** use ocre, azul-petróleo ou ferrugem como preenchimentos decorativos de grande área.
- **Don't** adicione sombras a navegação, topbar, botões ou contêineres comuns.
- **Don't** invente dados de caso, métricas, evidências, atividade ou alegações para preencher o shell.
- **Don't** introduza fontes remotas, glifos de fonte como ícones ou ornamentos sem função operacional.
