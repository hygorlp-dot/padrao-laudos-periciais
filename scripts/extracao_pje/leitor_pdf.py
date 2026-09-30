"""Leitura somente leitura e acesso uniforme às duas bibliotecas de PDF."""

import hashlib
from pathlib import Path

import pdfplumber
from pypdf import PdfReader
from pypdf.errors import PyPdfError


class PdfIlegivel(PyPdfError):
    """Os dois leitores discordam sobre o arquivo; nada aqui e confiavel.

    Herda de `PyPdfError` de proposito: todo consumidor que ja trata "nao
    consegui ler este PDF" passa a tratar tambem este caso, sem precisar
    aprender um tipo novo.
    """


def _encerrar(leitor):
    """Fecha o que der, sem deixar a falha de um impedir a soltura do outro."""
    for alvo in (leitor, getattr(leitor, "stream", None)):
        fechar = getattr(alvo, "close", None)
        if fechar is None:
            continue
        try:
            fechar()
        except BaseException:
            # A unica coisa pior do que nao conseguir fechar e propagar isso e
            # deixar o outro handle aberto por causa disso.
            pass


class LeitorPdf:
    def __init__(self, caminho):
        self.caminho = Path(caminho).resolve()
        if not self.caminho.is_file():
            raise FileNotFoundError(self.caminho)
        self.sha256 = hashlib.sha256(self.caminho.read_bytes()).hexdigest()
        self.pypdf = PdfReader(str(self.caminho))
        try:
            self.plumber = pdfplumber.open(str(self.caminho))
            # Num PDF danificado os dois leitores podem enxergar quantidades
            # DIFERENTES de paginas. `total_paginas` vem do pypdf, mas o texto e
            # a geometria vem do pdfplumber: quem percorrer 1..total_paginas
            # estoura com IndexError no meio do processamento -- erro interno
            # para o que e, na verdade, um arquivo ilegivel. Pior, truncar para
            # o menor dos dois violaria a contagem exata de paginas. A unica
            # resposta honesta e recusar o arquivo.
            try:
                paginas_pypdf, paginas_plumber = len(self.pypdf.pages), len(self.plumber.pages)
            except PyPdfError:
                raise
            except Exception as falha:
                # Arvore de paginas corrompida: o pypdf estoura com erros crus
                # (AttributeError, KeyError...) ao percorre-la. Isso e "PDF ilegivel",
                # nao falha interna; sem esta conversao escapava como 500.
                raise PdfIlegivel(f"arvore de paginas ilegivel: {type(falha).__name__}") from falha
            if paginas_pypdf != paginas_plumber:
                raise PdfIlegivel(
                    f"leitores divergem no total de paginas: "
                    f"pypdf={paginas_pypdf}, pdfplumber={paginas_plumber}"
                )
        except BaseException:
            # pypdf ja tomou um handle do arquivo. Se a segunda abertura falha,
            # o objeto nunca chega a existir e ninguem tem como chama-lo depois:
            # sem soltar aqui, o handle sobrevive ate o processo terminar.
            _encerrar(getattr(self, "plumber", None))
            _encerrar(self.pypdf)
            raise

    @property
    def total_paginas(self):
        return len(self.pypdf.pages)

    def texto(self, pagina_pdf: int):
        return self.plumber.pages[pagina_pdf - 1].extract_text() or ""

    def pagina_geometrica(self, pagina_pdf: int):
        return self.plumber.pages[pagina_pdf - 1]

    def fechar(self):
        """Solta AMBOS os leitores, mesmo que um deles falhe ao fechar.

        `pdfplumber` faz analise preguicosa: num PDF danificado o parse so
        estoura dentro do proprio `close()`. Fechar sem protecao deixava o
        handle vivo -- e, no Windows, um handle vivo impede remover o diretorio
        temporario onde o PDF privado foi materializado, entao os autos ficavam
        no `%TEMP%` indefinidamente. O `pypdf`, por sua vez, nunca era fechado.
        """
        _encerrar(self.plumber)
        _encerrar(self.pypdf)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()
