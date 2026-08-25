# ADR — Base-owned timing custody V1

## Status

Autorizada pelo proprietário humano em
`BASE_OWNED_TIMING_CUSTODY_TRANSITION_V1`.

## Contexto

O protótipo do PR #110 deixava runner e evaluator dispositivos sob controle
do candidato. Ele também compartilhava dependências entre BASE e HEAD, não
vinculava os bytes rastreados antes e depois de cada amostra, não preservava o
inventário exato de testes e aplicava tolerância fixa de seis segundos.

Os módulos Python de enforcement existentes possuem exceções capability
vinculadas ao hash do arquivo inteiro. Alterá-los no mesmo PR tornaria a
baseline stale e exigiria outro predecessor, o que não é autorizado.

## Decisão

Reutilizar o workflow `capability-protected`, que já é um artefato
architecture-protected e executa via `pull_request_target`. O runner/evaluator
fica incorporado ao blob exato desse workflow; não existe novo arquivo de judge
nem nova família de trust.

No Stage A os novos bytes são inertes, pois o GitHub executa o workflow a
partir do protected base anterior. Depois do merge, o mesmo workflow passa a
executar o código já pertencente a `main` contra BASE e HEAD exatos.

O runner:

- cria ambientes Python distintos com os requisitos de cada árvore;
- executa `BASE → HEAD → HEAD → BASE`;
- verifica commit, tree e bytes rastreados antes e depois de cada amostra;
- vincula o inventário Git completo de `tests/` e `requirements-dev.txt`;
- bloqueia remoção de qualquer path de teste;
- exige a lista completa e fechada de checks do `verify_core --full`;
- falha fechado diante de evidência ausente, divergente ou malformada.

O alvo absoluto permanece 60,0 segundos. Não há tolerância fixa. Uma travessia
de BASE dentro do alvo para HEAD fora do alvo bloqueia. Quando todas as
amostras estão acima do alvo, HEAD estritamente mais lento que todo o intervalo
BASE bloqueia; intervalos observados sobrepostos podem ser classificados como
variação ambiental.

## Limites

O `core-safety` permanece byte a byte inalterado e dispositivo durante o Stage
A. Nenhum produto, Core pericial, armazenamento privado, provider, segredo,
required check ou proteção administrativa é alterado.

O Stage B somente poderá tornar a atribuição efetiva depois que este workflow
estiver incorporado a protected `main` e sua verificação pós-merge estiver
verde.
