# Safe UOW Bootstrap V1

`scripts.agentic.uow_bootstrap` cria uma única worktree isolada a partir do
HEAD exato de uma branch remota explicitamente informada e emite um
`UOW_MANIFEST_V1` local e efêmero.

## Autoridade e efeitos

- Issue, remote, branches, destino, risco, lanes, mutation owner, Skills e
  policies são entradas explícitas; o comando não os infere.
- O único egress é `git fetch --no-tags` para o remote informado.
- O remote deve existir, ter uma única URL de fetch e usar transporte local,
  `file` ou `https`; SSH, remote helpers, URL rewrites e upload-pack/vcs
  customizados são rejeitados no contrato V1.
- Fetch e checkout usam uma policy Git hermética: config global/system e
  injeções `GIT_CONFIG_*` são ignoradas; exec-path, SSH/askpass e prompts são
  removidos; credential helpers ficam vazios; protocolos são deny-by-default.
- O executável Git é resolvido uma vez para path absoluto real/não-reparse;
  alterações posteriores de `PATH` não substituem o host tool. Remotes local/
  `file` são resolvidos e não podem estar sob `referencias/privadas` nem aliases
  symlink/reparse. UNC/SMB, device namespaces e file URLs com query/fragment/
  userinfo são rejeitados; no Windows o remote precisa de drive local real.
- O manifesto é evidência local, não substitui GitHub, Issue, PR, branch
  protection, policy ou revisão.
- Skills, policies e lanes são declarações explícitas não confiáveis do caller;
  `declaration_authority=UNTRUSTED_CALLER_INPUT`. O mutation owner deve pertencer
  às lanes declaradas, mas o manifesto não concede autoridade a essa lane.
- Os manifests ficam em `<git-common-dir>/codex-uow/manifests/` e não entram no
  índice da worktree.

## Fail-closed

Antes de criar a worktree, o comando rejeita destino existente, dentro da
worktree fonte, na raiz do drive/home, sob `referencias/privadas`, com ancestry
symlink/reparse, branch local existente, filtro de checkout versionado ou
atributo local/global, `core.fsmonitor`, symlink versionado, gitlink/submódulo, ref/identidade
inválida, path privado versionado ou lock concorrente. Hooks são desabilitados
desde o fetch, inclusive para `reference-transaction`.

Depois da criação, exige HEAD/tree exatos, worktree limpa e upstream apontando
ao mesmo commit remoto. O checkout usa diretório de hooks exclusivo, novo,
vazio e não-reparse, desabilita atributos globais/sistêmicos e neutraliza
fsmonitor no status final. Diretórios de estado e manifests também devem ser
diretórios reais, não symlink/reparse. Qualquer
falha bloqueia a emissão do manifesto. Estado
parcial é preservado para diagnóstico; o comando nunca executa `reset --hard`,
`clean`, `prune`, remoção de worktree, exclusão de dados ou force operation.

## Manifesto

O contrato fechado está em `schemas/uow-manifest-v1.schema.json`. A serialização
é JSON canônico (chaves ordenadas, UTF-8, newline final) e inicia com
`terminal_state=OPEN` e `open_findings=[]`.
O payload vincula identidade hashed do repositório/URL, common-dir, git-dir,
destino, remote/branches e postconditions observadas de HEAD/tree/upstream/clean.

O lock coordena instâncias cooperativas do bootstrap. Um ator local com poder
para substituir diretórios do Git common-dir durante a execução está fora do
threat model V1; essa condição exige isolamento/ACL do sistema operacional.
