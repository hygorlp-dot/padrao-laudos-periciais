# ADR — Base-owned timing custody V1

## Status

Autorizada pelo proprietário humano para o Stage A de
`BASE_OWNED_TIMING_CUSTODY_TRANSITION_V1`.

## Problema

O protótipo do PR #110 permitia que o próprio candidato fornecesse o runner e
o evaluator capazes de reinterpretar uma falha temporal do `verify_core`. A
mesma execução compartilhava dependências entre BASE e HEAD, não verificava os
bytes rastreados antes e depois de cada amostra, não vinculava o inventário
exato de testes e usava tolerância fixa de 6 segundos.

## Decisão

Reutilizar o control plane `capability-protected` existente. O Stage A rotaciona
somente `scripts/quality/capability_bootstrap.py` e
`scripts/quality/verify_core.py`, ambos já presentes no registry capability
protegido. O `pull_request_target` continua carregando e executando esses bytes
exclusivamente a partir do protected base.

No próprio Stage A os novos bytes permanecem inertes: o workflow protegido é
executado a partir da base anterior. Depois do merge, `main` passa a ser dono
dos bytes e o mesmo workflow existente executa a atribuição pareada nos PRs
seguintes.

O runner cria ambientes Python distintos para BASE e HEAD, verifica commit,
tree e bytes rastreados antes e depois de cada amostra e vincula o inventário
Git completo de `tests/` e de `requirements-dev.txt`. A ordem é
`BASE → HEAD → HEAD → BASE`.

O alvo absoluto continua sendo 60,0 segundos. Não existe tolerância fixa. Uma
travessia de BASE dentro do alvo para HEAD fora do alvo bloqueia. Quando ambas
as árvores permanecem acima do alvo, somente intervalos observados que se
sobrepõem podem ser classificados como variação ambiental; HEAD estritamente
mais lento que todo o intervalo BASE bloqueia.

## Invariantes

- falha semântica sempre bloqueia;
- evidência ausente, malformada, incompleta ou divergente bloqueia;
- remoção de path de teste bloqueia;
- alteração de bytes rastreados durante qualquer amostra bloqueia;
- o modo default do `verify_core` continua dispositivo no Stage A;
- o candidato não fornece nem seleciona o evaluator protegido;
- nenhuma mudança de produto, Core pericial ou armazenamento privado.

## Ativação posterior

O Stage B somente poderá retirar a decisão temporal do workflow candidato
depois que estes bytes estiverem incorporados a `main` e o check
`capability-protected` base-owned estiver exercendo a política contra o HEAD
exato. A transição não cria nova família de judge nem novo trust anchor.
