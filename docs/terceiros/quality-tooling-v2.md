# Third-party intake — Quality Hardening V2

## Decisão aprovada para a Issue #11

| Ferramenta | Necessidade | Origem | Licença | Pin | Egress/telemetria | Decisão |
|---|---|---|---|---|---|---|
| mutmut | Piloto profundo de mutation testing Python | `github.com/boxed/mutmut` / PyPI | BSD-3-Clause | `3.7.0` | Não requer rede nem telemetria para executar; altera cópia local em `mutants/`; exige `fork`, portanto Windows somente via WSL | ADOTADA apenas como dependência dev e campanha manual/agendada |
| Cosmic Ray | Alternativa de mutation testing | `github.com/sixty-north/cosmic-ray` / PyPI | Apache-2.0 | avaliada em `8.7.0` | Execução local, mas traz scheduler, banco e conjunto transitivo maior | NÃO ADOTADA; complexidade desnecessária ao piloto seletivo |
| coverage.py | Branch/line coverage local | `github.com/coveragepy/coveragepy` / PyPI | Apache-2.0 | `7.15.4` | Sem egress/telemetria; grava relatórios locais | ADOTADA como dependência dev; já é dependência transitiva do mutmut, pinada diretamente |
| Radon | Complexidade ciclomática | `github.com/rubik/radon` / PyPI | MIT | avaliada em `6.0.1` | Sem egress/telemetria | NÃO ADOTADA; documentação oficial não declara Python 3.14, e a medição necessária é pequena e reproduzível com `ast` first-party |
| Ruff/Vulture | Lint/código morto | repositórios oficiais / PyPI | MIT | avaliadas, não instaladas | Sem egress normal | ADIADAS; o baseline exigiria limpeza ampla fora do escopo e não há ganho direto para os mutantes críticos |

## Supply chain

- Autoridade declarativa única: `pyproject.toml`, separando dependências de runtime do grupo `dev`.
- Resolução determinística: `uv.lock`, gerado e validado por `uv 0.12.6`.
- Instalação CI: `uv sync --locked --no-install-project`; execução: `uv run --no-sync`.
- Scripts de instalação arbitrários: nenhum script do repositório é executado na instalação; os artefatos resolvidos pelo lock provêm do PyPI.
- Filesystem: mutmut cria exclusivamente `mutants/`, ignorado pelo Git; a suíte histórica first-party usa diretório temporário.
- CI: `core-safety` não executa a campanha profunda. O workflow opcional `quality-depth` roda em Ubuntu, sem secrets ou deploy.
- Privacidade: alvos limitados a source code first-party; `referencias/privadas/` nunca integra source paths, cópia ou testes.
- Compatibilidade comercial futura: BSD-3-Clause e Apache-2.0 são permissivas.

Para atualizar dependências deliberadamente, altere `pyproject.toml`, execute
`uv lock --python 3.13` com `uv 0.12.6` e valide `uv lock --check`. Os antigos
arquivos `requirements*.txt` são exports hash-pinned gerados pelo próprio
`uv`; não são uma segunda autoridade declarativa.

Fontes primárias consultadas em 2026-08-11:

- <https://github.com/boxed/mutmut>
- <https://mutmut.readthedocs.io/en/latest/>
- <https://github.com/sixty-north/cosmic-ray>
- <https://cosmic-ray.readthedocs.io/en/stable/>
- <https://github.com/coveragepy/coveragepy>
- <https://github.com/rubik/radon>
