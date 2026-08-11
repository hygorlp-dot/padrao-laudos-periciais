"""Regras explícitas e auditáveis de classificação documental."""

REGRAS_EXATAS = (
    ("contestacao", "CONTESTACAO"), ("decisao", "DECISAO"), ("despacho", "DESPACHO"),
    ("intimacao", "INTIMACAO"), ("citacao", "CITACAO"), ("certidao", "CERTIDAO"),
    ("procuracao", "PROCURACAO"), ("substabelecimento", "SUBSTABELECIMENTO"),
    ("declaracao", "DECLARACAO"), ("replica", "REPLICA"), ("manifestacao", "MANIFESTACAO"),
    ("peticao inicial", "PETICAO_INICIAL"),
)

# estratégia, expressão, classe. TOKEN nunca é usado para abreviações ambíguas.
REGRAS_CLASSIFICACAO = (
    ("PHRASE", "peticao inicial", "PETICAO_INICIAL"), ("PHRASE", "emenda a inicial", "EMENDA_INICIAL"),
    ("TOKEN", "substabelecimento", "SUBSTABELECIMENTO"), ("TOKEN", "procuracao", "PROCURACAO"),
    ("TOKEN", "contestacao", "CONTESTACAO"), ("TOKEN", "intimacao", "INTIMACAO"),
    ("PHRASE", "ato ordinatorio", "ATO_ORDINATORIO"), ("PHRASE", "comprovante de residencia", "COMPROVANTE_RESIDENCIA"),
    ("PHRASE", "documento de identificacao", "DOCUMENTO_IDENTIFICACAO"),
    ("PHRASE", "relatorio fotografico", "RELATORIO_FOTOGRAFICO"),
    ("PHRASE", "memorial descritivo", "MEMORIAL_DESCRITIVO"),
    ("PHRASE", "anotacao de responsabilidade tecnica", "ART_RRT"),
    ("PHRASE", "registro de responsabilidade tecnica", "ART_RRT"),
)

# Compatibilidade para consumidores antigos; não contém ART/RRT ambíguos.
REGRAS_CONTEM = tuple((expressao, classe) for _, expressao, classe in REGRAS_CLASSIFICACAO)
