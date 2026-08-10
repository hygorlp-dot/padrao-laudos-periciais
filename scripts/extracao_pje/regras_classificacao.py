"""Regras genéricas, ordenadas e explicáveis de classificação documental."""

# Regra de score: correspondência exata em título/tipo = 1,0; ocorrência
# inequívoca = 0,9; combinação de evidências estruturais = 0,8; sem regra = 0,3.
REGRAS_EXATAS = (
    ("contestacao", "CONTESTACAO"), ("decisao", "DECISAO"),
    ("despacho", "DESPACHO"), ("intimacao", "INTIMACAO"),
    ("citacao", "CITACAO"), ("certidao", "CERTIDAO"),
    ("procuracao", "PROCURACAO"), ("substabelecimento", "SUBSTABELECIMENTO"),
    ("declaracao", "DECLARACAO"), ("replica", "REPLICA"),
    ("manifestacao", "MANIFESTACAO"), ("peticao inicial", "PETICAO_INICIAL"),
)

REGRAS_CONTEM = (
    ("peticao inicial", "PETICAO_INICIAL"), ("emenda a inicial", "EMENDA_INICIAL"),
    ("substabelecimento", "SUBSTABELECIMENTO"), ("procuracao", "PROCURACAO"),
    ("contestacao", "CONTESTACAO"), ("intimacao", "INTIMACAO"),
    ("ato ordinatorio", "ATO_ORDINATORIO"), ("comprovante de residencia", "COMPROVANTE_RESIDENCIA"),
    ("documento de identificacao", "DOCUMENTO_IDENTIFICACAO"),
    ("relatorio fotografico", "RELATORIO_FOTOGRAFICO"),
    ("memorial descritivo", "MEMORIAL_DESCRITIVO"), ("art", "ART_RRT"), ("rrt", "ART_RRT"),
)
