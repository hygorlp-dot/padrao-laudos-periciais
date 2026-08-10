# Referências

Esta pasta versionada registra apenas orientações sobre referências. Laudos de
referência e autos autorizados para testes privados permanecem exclusivamente
na área local ignorada pelo Git.

## Referências privadas

`referencias/privadas/` contém laudos reais usados somente no ambiente local.
Esses arquivos não podem ser versionados e devem permanecer integralmente fora
do histórico do Git.

Quando autorizados pelo perito:

- `referencias/privadas/processos/` armazena PDFs reais usados como testes
  privados de integração;
- `referencias/privadas/derivados/` armazenará manifestos e documentos
  estruturados derivados desses PDFs.

Todo o conteúdo dessas duas pastas permanece protegido pela regra abrangente
`referencias/privadas/` do `.gitignore`.

Os arquivos deverão ser preferencialmente anonimizados antes da inclusão. A
anonimização deverá remover ou substituir dados pessoais, informações
sigilosas e elementos que permitam identificar processos, partes ou terceiros,
conforme decisão e conferência do perito.

## Finalidade

Os laudos de referência serão utilizados para análise de estrutura, estilo e
padronagem, incluindo organização, escolhas linguísticas, terminologia,
apresentação da análise e forma de responder quesitos.

Nenhuma conclusão existente nesses arquivos deverá ser tratada automaticamente
como regra correta. Da mesma forma, nenhuma característica observada deverá se
tornar regra antes de validação expressa do perito.

Antes de incluir um arquivo, conferir:

- autorização para uso como referência;
- anonimização adequada;
- representatividade do estilo atual do perito;
- indicação de eventuais trechos que não devem orientar o padrão;
- ausência de documentos dos autos que não sejam necessários à finalidade desta
  pasta.
