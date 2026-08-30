# Safe UOW Bootstrap V1

`scripts.agentic.uow_bootstrap` cria uma única worktree isolada a partir do
HEAD exato de uma branch remota explicitamente informada e emite um
`UOW_MANIFEST_V1` local e efêmero.

## Autoridade e efeitos

- Issue, remote, branches, destino, risco, lanes, mutation owner, Skills e
  policies são entradas explícitas; o comando não os infere.
- O único egress é `git fetch --no-tags` para o remote informado.
- O manifesto é evidência local, não substitui GitHub, Issue, PR, branch
  protection, policy ou revisão.
- Os manifests ficam em `<git-common-dir>/codex-uow/manifests/` e não entram no
  índice da worktree.

## Fail-closed

Antes de criar a worktree, o comando rejeita destino existente, dentro da
worktree fonte, na raiz do drive/home, sob `referencias/privadas`, com ancestry
symlink, branch local existente, filtro de checkout versionado, ref/identidade
inválida ou lock concorrente. Hooks são desabilitados na criação.

Depois da criação, exige HEAD/tree exatos, worktree limpa e upstream apontando
ao mesmo commit remoto. Qualquer falha bloqueia a emissão do manifesto. Estado
parcial é preservado para diagnóstico; o comando nunca executa `reset --hard`,
`clean`, `prune`, remoção de worktree, exclusão de dados ou force operation.

## Manifesto

O contrato fechado está em `schemas/uow-manifest-v1.schema.json`. A serialização
é JSON canônico (chaves ordenadas, UTF-8, newline final) e inicia com
`terminal_state=OPEN` e `open_findings=[]`.
