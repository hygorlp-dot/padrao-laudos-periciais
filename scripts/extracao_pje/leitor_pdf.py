"""Leitura somente leitura e acesso uniforme às duas bibliotecas de PDF."""

import hashlib
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


class LeitorPdf:
    def __init__(self, caminho):
        self.caminho = Path(caminho).resolve()
        if not self.caminho.is_file():
            raise FileNotFoundError(self.caminho)
        self.sha256 = hashlib.sha256(self.caminho.read_bytes()).hexdigest()
        self.pypdf = PdfReader(str(self.caminho))
        self.plumber = pdfplumber.open(str(self.caminho))

    @property
    def total_paginas(self):
        return len(self.pypdf.pages)

    def texto(self, pagina_pdf: int):
        return self.plumber.pages[pagina_pdf - 1].extract_text() or ""

    def pagina_geometrica(self, pagina_pdf: int):
        return self.plumber.pages[pagina_pdf - 1]

    def fechar(self):
        self.plumber.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()
