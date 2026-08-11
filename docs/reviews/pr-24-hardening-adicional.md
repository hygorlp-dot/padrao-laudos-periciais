# Review package — PR #24 hardening adicional

## Identificação

- Issue: `#23`
- PR: `#24`
- Branch: `fix/23-core-pericial-p0`
- Base revisada: `e2de6077c3501066f4111dbe946be1c0b3fbd087` mais o diff desta entrega
- Revisor independente: subagente `/root/revisao_hardening_final` (`Poincare`)
- Escopo: matriz anterior A–M e hardening adicional A–M
- Modo: somente leitura; sem acesso a `referencias/privadas/`

## Resultado

`APROVADO` — nenhum achado `CRÍTICO` ou `IMPORTANTE` remanescente.

Foram reexecutados adversariais de conflito entre regras documentais,
ambiguidade geométrica imagem–rótulo e independência causal com proveniência
estruturada. Os resultados foram conservadores, invariantes à ordem e sem
contagem duplicada de páginas da mesma fonte.

## Evidências verificáveis

- suíte integral: 303/303;
- hardening adicional: 7/7;
- schemas: 19;
- fixtures: 32;
- guards, privacidade e egress: 33/33;
- `compileall`: aprovado;
- `git diff --check`: aprovado;
- referências privadas rastreadas: zero.

## Riscos residuais não bloqueantes

- Classificação e associação geométrica são deliberadamente conservadoras e
  encaminham ambiguidades para revisão.
- A independência causal depende da identidade documental (`documento_id`,
  hash ou arquivo) corretamente preenchida na proveniência.
- O teste PDF com imagens reais não foi ampliado porque a fixture PDF digital
  existente não contém XObjects de imagem e não foi adicionada dependência para
  fabricá-los; a função produtiva possui cobertura geométrica direta.

Este registro não contém raciocínio privado nem substitui a revisão do PR no
GitHub. O SHA final da entrega deve ser registrado na descrição do PR após o
push.
