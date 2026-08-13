# Ativação do Architecture Analyzer V1

`PR_B1_SHADOW_ONLY = TRUE`. O PR-B1 entrega inventário, parser, analyzer, policy,
schema, baseline vazio e testes, mas não altera `verify_core` nem reivindica
autoridade bloqueante. Isso impede que o primeiro candidato autorize sua própria
policy ou implementação.

Após PR-B1 estar mergeado e verde em `main`, PR-B2 parte desse base protegido.
`PR_B2_PROTECTED_BASE_ACTIVATION = TRUE`: o workflow de pull request usa a
definição protegida da base e executa o analyzer/policy/schema provenientes do
base para validar a mudança de ativação. PR-B2 adiciona composição bloqueante ao
`verify_core` somente depois da prova de identidade dos blobs-base.

PR-B2 deve também concluir antes da ativação: leitura de exceções somente por
blob candidato exato; validação runtime do schema; SCC iterativo ou limite
fail-closed; superfícies de loader/import-hook class-wide; baseline/policy
ancorados ao base; owner/disposition relacionais. Nenhuma policy capability é
permitida em PR-B1 ou PR-B2.
