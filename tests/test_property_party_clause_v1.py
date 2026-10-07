"""#293 — endereço de parte nunca vira proposta do imóvel; o do imóvel continua.

Todo texto é sintético. O vínculo de um endereço é decidido pela oração: o
logradouro (e o número, o bairro e o CEP que o seguem) pertence ao marcador mais
próximo antes dele na frase.

Duas regras separadas:

    BACKUP_REPLAY_LEGACY = ALLOWED
    NEW_PROPOSAL_FROM_PARTY_ADDRESS = PROHIBITED

new ⊆ legacy aqui tem sentido exato, sobre a identidade já usada pelo
backup (proposal_id, que cobre campo, valor e evidência inteira):

- toda proposta nova (include_legacy_labels=False) é reproduzível pela
  verificação do backup (include_legacy_labels=True) sobre os mesmos bytes;
- tudo o que a main 8941b2c reproduzia (golden congelado abaixo, calculado
  naquela main) continua reproduzível: evidência confirmada antes desta
  correção continua conferível.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.backend_contract.property_record import property_proposals


def _page(text, number=1, mode="NATIVE_TEXT"):
    return SimpleNamespace(number=number, text=text, extraction_mode=SimpleNamespace(value=mode), confidence=None if mode == "NATIVE_TEXT" else 0.91)


def _proposals(text, *, legacy=False):
    return property_proposals("w", "d", "a" * 64, "autos.pdf", [_page(text)], include_legacy_labels=legacy)


def _found(text):
    return {(p.field, p.value, p.strength) for p in _proposals(text)}


PROBES = {
    "issue_moradora": "FULANA SINTÉTICA, moradora da Rua da Parte, nº 10, proprietária do imóvel objeto da ação situado na Rua do Imóvel, nº 20.\n",
    "issue_comprador_morador": "COMPRADOR: Fulano Sintético, morador na Rua da Parte, nº 10, adquire o imóvel objeto deste contrato, situado na Rua do Imóvel, nº 20.\n",
    "issue_re_estabelecida": "A RÉ, CONSTRUTORA SINTÉTICA LTDA, estabelecida na Rua da Parte, nº 10, quanto ao imóvel objeto da ação, situado na Rua do Imóvel, nº 20, nada opôs.\n",
    "issue_vendedora_localizada": "A VENDEDORA, localizada na Rua da Parte, nº 10, vende o imóvel objeto deste contrato, situado na Rua do Imóvel, nº 20.\n",
    "issue_testemunha_mora": "Testemunha Beltrano Sintético, que mora na Rua da Parte, nº 10, afirmou que o imóvel objeto da ação, situado na Rua do Imóvel, nº 20, tem infiltrações.\n",
    "issue_foro_contrato": "CONTRATO DE COMPRA E VENDA\nFica eleito o foro da comarca, situado na Rua da Parte, nº 10. O imóvel objeto deste contrato está situado na Rua do Imóvel, nº 20.\n",
    "autora_residente": "A autora, FULANA SINTÉTICA, residente e domiciliada na Rua da Parte, nº 10, é proprietária do imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "reu_domiciliado": "O réu, FULANO SINTÉTICO, domiciliado na Rua da Parte, nº 10, vendeu à autora o imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "advogado_escritorio": "Por seu advogado, com escritório na Rua da Parte, nº 10, a autora descreve o imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "empresa_com_sede": "CONSTRUTORA SINTÉTICA LTDA, com sede na Rua da Parte, nº 10, entregou o imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "juizo_endereco": "O Juízo da Vara Sintética, com endereço na Rua da Parte, nº 10, determinou a vistoria do imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "foro_mesma_frase": "Fica eleito o foro da comarca, situado na Rua da Parte, nº 10, para dirimir dúvidas sobre o imóvel objeto deste contrato, situado na Rua do Imóvel, nº 20.\n",
    "precedente": "Conforme julgado na Apelação nº 0000000-00.2020.4.05.0000 (Rel. Des. Sintético), o imóvel situado na Rua da Parte, nº 10, apresentava vícios. O imóvel objeto da ação está situado na Rua do Imóvel, nº 20.\n",
    "testemunha_residente": "A testemunha Beltrana Sintética, residente na Rua da Parte, nº 10, confirmou que o imóvel objeto da ação fica na Rua do Imóvel, nº 20.\n",
    "assistente_tecnico": "O assistente técnico da ré, com endereço profissional na Rua da Parte, nº 10, vistoriou o imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "re_sediada_cnpj": "A RÉ, sediada na Rua da Parte, nº 10, inscrita no CNPJ 00.000.000/0001-00, construiu o imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "parte_bairro_cep": "FULANA SINTÉTICA, moradora da Rua da Parte, nº 10, Bairro Parte Sintética, CEP 51111-111, proprietária do imóvel objeto da ação, situado na Rua do Imóvel, nº 20, Bairro Imóvel Sintético, CEP 52222-222.\n",
    "onde_reside_imovel": "A autora é proprietária do imóvel objeto da ação, onde reside, situado na Rua do Imóvel, nº 20.\n",
    "onde_parentetico_controlado": "A autora adquiriu a unidade habitacional, financiada em 2015, onde reside, na Rua do Imóvel, nº 20.\n",
    "onde_cidade": "A autora deixou o imóvel objeto da ação e reside em Recife, onde mora na Rua da Parte, nº 10.\n",
    "onde_capital": "A autora deixou o imóvel objeto da ação e mudou-se para a capital, onde reside na Rua da Parte, nº 10.\n",
    "onde_bairro": "A autora vendeu o imóvel objeto da ação e hoje mora no bairro vizinho, onde reside na Rua da Parte, nº 10.\n",
    "onde_interior": "O autor saiu do imóvel objeto da ação e foi para o interior, onde reside na Rua da Parte, nº 10.\n",
    "outra_unidade_onde": "A autora deixou o imóvel objeto da ação e adquiriu outra unidade habitacional, onde reside, na Rua da Parte, nº 10.\n",
    "nova_unidade_situada": "A autora deixou o imóvel objeto da ação e recebeu nova unidade habitacional, situada na Rua da Parte, nº 10.\n",
    "parentetico_com_deslocamento": "A autora deixou a unidade habitacional, transferida para Recife, onde reside na Rua da Parte, nº 10.\n",
    "parentetico_participio_com_deslocamento": "A autora ocupava a unidade habitacional, removida para Recife, onde reside, na Rua da Parte, nº 10.\n",
    "onde_nao_adjacente": "A autora é proprietária do imóvel objeto da ação e da casa de praia, onde reside, na Rua da Parte, nº 10.\n",
    "vive_hoje": "A autora deixou o imóvel objeto da ação e hoje vive na Rua da Parte, nº 10.\n",
    "localizada_genero_parte": "A autora, proprietária do imóvel objeto da ação, localizada na Rua da Parte, nº 10, requer a perícia.\n",
    "outro_imovel": "A ré possui outro imóvel situado na Rua da Parte, nº 10, e vendeu o imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "ambiguo_dois_numeros": "O imóvel objeto da ação está situado na Rua do Imóvel, nº 20, ou na Rua do Imóvel, nº 22, conforme a matrícula.\n",
    "ambiguo_duas_unidades": "O imóvel objeto da ação abrange o apartamento nº 101 e o apartamento nº 102.\n",
    "narrativa_suportada": "A parte autora adquiriu o imóvel objeto da ação, situado na Rua das Acácias Sintéticas, nº 120, Bairro Jardim Sintético, CEP 50000-000, no Residencial Flores Sintéticas, apartamento nº 302, Bloco B.\n",
    "localizado_suportado": "O imóvel objeto da ação, localizado na Avenida Sintética, nº 5, Bairro Centro Sintético, CEP 50000-000, Recife - PE, apresenta fissuras.\n",
    "rua_com_nome_de_forum": "O imóvel objeto da ação está situado na Rua do Fórum Velho Sintético, nº 20.\n",
    "timbre_advogado": "LAUDO\nRua do Sossego Sintetica, 120, Bairro Boa Vista Sintetica, Recife/PE - CEP 50050-080 - Tel (81) 0000-0000\n",
    "contrato_qualificacao": "CONTRATO DE COMPRA E VENDA\nVENDEDORA: CONSTRUTORA SINTÉTICA LTDA, estabelecida na Avenida da Vendedora, nº 900, Recife - PE.\nO imóvel objeto deste contrato, situado na Rua do Imóvel, nº 20, Caruaru - PE, tem área privativa de 41,85 m².\n",
    "cidade_da_parte": "FULANA SINTÉTICA, moradora da Rua da Parte, nº 10, Caruaru - PE, proprietária do imóvel objeto da ação situado na Rua do Imóvel, nº 20, Recife - PE.\n",
    "quadra_lote": "O imóvel objeto da ação, lote 7 da quadra 3, situa-se na Rua do Loteamento Sintético, nº 15.\n",
    "situado_abre_a_frase": "O laudo descreve o caso. Situado na Rua do Imóvel, nº 20, o imóvel objeto da ação apresenta fissuras.\n",
    # Quebra de linha do PDF não abre frase: "localizada" ainda qualifica a vendedora.
    "quebra_de_linha_vendedora": "A VENDEDORA,\nlocalizada na Rua da Parte, nº 10, vende o imóvel objeto deste contrato.\n",
    # Reproduções da revisão independente da PR #294.
    # P1-1: endereco de parte que a main bloqueava nao pode virar proposta.
    "r_telefone_depois": "FULANA, proprietária do imóvel objeto da ação, na Rua da Parte, nº 10, telefone (81) 0000-0000.\n",
    "r_email_depois": "FULANA, proprietária do imóvel objeto da ação, Rua da Parte, nº 10, e-mail fulana@x.com.\n",
    "r_oab_depois": "O imóvel objeto da ação, situado na Rua da Parte, nº 10, Dr. Fulano, OAB/PE 0000.\n",
    "r_construtora_situada_cnpj": "A unidade habitacional foi vendida pela construtora, situada na Rua da Parte, nº 10, CNPJ 00.000.000/0001-00.\n",
    "r_re_localizada_cnpj": "A casa foi construída pela ré, localizada na Rua da Parte, nº 10, inscrita no CNPJ 00.000.000/0001-00.\n",
    "r_onde_residia_para": "A autora, CPF 000.000.000-00, deixou o imóvel objeto da ação, onde residia, para a Rua da Parte, nº 10.\n",
    "r_onde_nao_mais_reside": "A autora, CPF 000.000.000-00, deixou o imóvel objeto da ação, onde não mais reside, na Rua da Parte, nº 10.\n",
    "r_filial": "O réu, CNPJ 00.000.000/0001-00, construiu o imóvel objeto da ação e mantém filial na Rua da Parte, nº 10.\n",
    "r_endereco_rotulo": "FULANA, CPF 000.000.000-00, proprietária do imóvel objeto da ação, endereço: Rua da Parte, nº 10.\n",
    # P1-2: participio feminino qualificando parte feminina.
    "r_entregue_pela_construtora": "A unidade habitacional foi entregue pela construtora, localizada na Rua da Parte, nº 10.\n",
    "r_construida_pela_vendedora": "A casa objeto da ação foi construída pela vendedora, situada na Rua da Parte, nº 10.\n",
    # P1-3: endereco do imovel que a main achava continua achado.
    "r_unidade_apartamento_situada": "CONTRATO DE COMPRA E VENDA\nA unidade habitacional, apartamento nº 302, situada na Rua do Imóvel, nº 20, Bairro Imóvel Sintético.\n",
    "r_apartamento_unidade_autonoma": "O apartamento nº 302, unidade autônoma do Bloco B, situado na Rua do Imóvel, nº 20.\n",
    "r_bem_objeto": "O bem objeto da ação, situado na Rua do Imóvel, nº 20, apresenta fissuras.\n",
    "r_sobrado_objeto": "O sobrado objeto da ação, situado na Rua do Imóvel, nº 20, apresenta fissuras.\n",
    "r_objeto_da_lide": "Trata-se do objeto da lide, situado na Rua do Imóvel, nº 20.\n",
    "r_alcance_longo": "A unidade habitacional objeto desta ação, construída no âmbito do programa habitacional federal em 2014, situada na Rua do Imóvel, nº 20.\n",
    "r_nesta_comarca": "O imóvel objeto da ação, situado nesta Comarca, na Rua do Imóvel, nº 20, apresenta fissuras.\n",
    "r_municipio_e_comarca": "O imóvel objeto da ação, localizado no Município e Comarca de Recife, na Rua do Imóvel, nº 20, apresenta fissuras.\n",
    "r_matricula_cidade_comarca": "MATRÍCULA 12345\nIMÓVEL: casa residencial, situada nesta cidade e comarca, na Rua do Imóvel, nº 20.\n",
    # P2-1: marcadores de narrativa nao apagam o endereco do imovel.
    "r_assistentes_vistoria": "LAUDO\nA vistoria, acompanhada pelos assistentes técnicos, ocorreu na Rua do Imóvel, nº 20, imóvel objeto da ação.\n",
    "r_onde_vive": "A autora é proprietária do imóvel objeto da ação, onde vive, na Rua do Imóvel, nº 20.\n",
    "r_apos_a_mudanca": "Após a mudança, a autora notou fissuras na casa da Rua do Imóvel, nº 20, objeto da ação.\n",
    "r_transferiu_a_posse": "A construtora transferiu à autora a posse da casa da Rua do Imóvel, nº 20, objeto da ação.\n",
    # P2-3: outras formas de domicilio e hifenizacao do PDF.
    "r_com_domicilio": "FULANA, com domicílio na Rua da Parte, nº 10, proprietária do imóvel objeto da ação situado na Rua do Imóvel, nº 20.\n",
    "r_cuja_residencia": "FULANA, cuja residência fica na Rua da Parte, nº 10, é proprietária do imóvel objeto da ação situado na Rua do Imóvel, nº 20.\n",
    "r_habita": "FULANA, que habita na Rua da Parte, nº 10, é proprietária do imóvel objeto da ação situado na Rua do Imóvel, nº 20.\n",
    "r_hifenizacao": "FULANA, mora-\ndora da Rua da Parte, nº 10, proprietária do imóvel objeto da ação situado na Rua do Imóvel, nº 20.\n",
    # Demais sondas adversariais da revisao.
    "r_endereco_antes_reside": "Na Rua da Parte, nº 10, reside a autora, proprietária do imóvel objeto da ação situado na Rua do Imóvel, nº 20.\n",
    "r_endereco_antes_moradora": "Rua da Parte, nº 10, é o endereço de FULANA, moradora, proprietária do imóvel objeto da ação.\n",
    "r_onde_bairro_vizinho": "A autora é proprietária do imóvel objeto da ação, onde reside, no bairro vizinho, na Rua da Parte, nº 10.\n",
    "r_parentetico_abandonado": "A autora possuía o imóvel objeto da ação, abandonado em 2019, onde reside, na Rua da Parte, nº 10.\n",
    "r_parentetico_vendido": "A autora vendeu o imóvel objeto da ação, vendido em 2019, onde reside, na Rua da Parte, nº 10.\n",
    "r_onde_residia_no_imovel": "A autora vendeu o imóvel objeto da ação, onde residia na Rua do Imóvel, nº 20.\n",
    "r_predio_ao_lado": "O imóvel objeto da ação fica ao lado do prédio, situado na Rua da Parte, nº 10.\n",
    "r_transferida_para": "A autora foi transferida para a Rua da Parte, nº 10, e o imóvel objeto da ação, situado na Rua do Imóvel, nº 20, ficou vazio.\n",
    "r_realocada": "A família foi realocada na Rua da Parte, nº 10, e o imóvel objeto da ação, situado na Rua do Imóvel, nº 20, foi interditado.\n",
    "r_mora_no_imovel": "A autora, que mora no imóvel desde 2015, aponta vícios na casa da Rua do Imóvel, nº 20, objeto da ação.\n",
    "r_novo_imovel_objeto": "A autora recebeu as chaves do novo imóvel objeto da ação, situado na Rua do Imóvel, nº 20, em 2015.\n",
    "r_nova_unidade_objeto": "A autora adquiriu nova unidade habitacional, objeto da ação, situada na Rua do Imóvel, nº 20.\n",
    "r_residencia_objeto": "A residência da autora, imóvel objeto da ação, situada na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r_dois_enderecos_mesma_pista": "O imóvel objeto da ação, situado na Rua do Imóvel, nº 20, e a casa de FULANA, na Rua da Parte, nº 10.\n",
    # Rodada 2 da revisão independente da PR #294.
    # P1-1: agente de participio atributivo e "parte" comum nao apagam o endereco do imovel.
    "r2_adquirida_pela_autora": "A unidade habitacional adquirida pela autora, situada na Rua do Imóvel, nº 20, apresenta fissuras.\n",
    "r2_faz_parte": "A unidade habitacional, que faz parte do Residencial Sintético, situada na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r2_parte_integrante": "A unidade habitacional, parte integrante do conjunto, situada na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r2_financiado_pelo_banco": "O imóvel objeto da ação, financiado pelo banco, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r2_construida_pela_construtora_re": "A casa construída pela construtora ré, situada na Rua do Imóvel, nº 20, é objeto da ação.\n",
    "r2_entregue_a_autora": "A unidade habitacional entregue à autora em 2015, situada na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r2_adquirido_pelo_requerente": "O imóvel adquirido pelo requerente, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    # P1-2: CPF/CNPJ entre o imovel e o participio.
    "r2_vendida_a_fulana_cpf": "A unidade habitacional foi vendida a FULANA, CPF 000.000.000-00, situada na Rua da Parte, nº 10.\n",
    "r2_vendida_pela_ltda_cnpj": "A unidade habitacional foi vendida pela SINTÉTICA LTDA, CNPJ 00.000.000/0001-00, situada na Rua da Parte, nº 10.\n",
    # P2-1: onde a regra anterior bloqueava, so a pista do imovel objeto liga.
    "r2_casa_sem_pista_com_cnpj": "O réu, CNPJ 00.000.000/0001-00, construiu a casa, situada na Rua da Parte, nº 10, onde mantém filial.\n",
    # P2-2: "foi para" na narrativa do laudo nao e endereco de parte.
    "r2_perito_foi_para": "LAUDO\nO perito foi para a Rua do Imóvel, nº 20, imóvel objeto da ação, em 10/05/2024.\n",
    "r2_autos_foram_para": "LAUDO\nOs autos foram para vistoria na Rua do Imóvel, nº 20, imóvel objeto da ação.\n",
    # P3: "Vizinha" no nome da rua.
    "r2_rua_vizinha": "O imóvel objeto da ação, situado na Rua Vizinha Sintética, nº 20, tem fissuras.\n",
    # Sondas adversariais da rodada 2 que a main também errava.
    "r2_vendida_a_fulana": "A unidade habitacional foi vendida a FULANA, situada na Rua da Parte, nº 10.\n",
    "r2_vendida_pela_ltda": "A unidade habitacional foi vendida pela SINTÉTICA LTDA, localizada na Rua da Parte, nº 10.\n",
    "r2_hifen_com_espaco": "A autora, resi- dente na Rua da Parte, nº 10, é proprietária do imóvel objeto da ação, situado na Rua do Imóvel, nº 20.\n",
    "r2_cuja_sede": "A construtora, cuja sede fica na Rua da Parte, nº 10, entregou o imóvel objeto da ação.\n",
    "r2_com_matriz": "A construtora, com matriz na Rua da Parte, nº 10, entregou o imóvel objeto da ação.\n",
    "r2_trabalha_na": "A autora, proprietária do imóvel objeto da ação, trabalha na Rua da Parte, nº 10.\n",
    "r2_mudou_se_a": "A autora vendeu o imóvel objeto da ação e mudou-se à Rua da Parte, nº 10.\n",
    "r2_endereco_atual": "A autora vendeu o imóvel objeto da ação, endereço atual Rua da Parte, nº 10.\n",
    "r2_imovel_ao_lado_do_objeto": "O imóvel ao lado do objeto da ação, situado na Rua da Parte, nº 10, não foi vistoriado.\n",
    "r2_novo_bairro": "O imóvel objeto da ação fica no novo bairro, na Rua do Imóvel, nº 20.\n",
    # Rodada 3 da revisão independente da PR #294.
    # P1-1: relativa do proprio imovel e conjuncao "e" nao sao copula de parte.
    "r3_que_foi_adquirido": "O imóvel objeto da ação, que foi adquirido pela autora em 2015, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r3_que_foi_financiado": "O imóvel objeto da ação, que foi financiado pelo banco, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r3_que_foi_entregue": "A unidade habitacional, que foi entregue à autora em 2015, situada na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r3_adquirida_e_quitada": "A unidade habitacional adquirida e quitada pela autora, situada na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r3_financiada_e_entregue": "A unidade habitacional, financiada e entregue à autora, situada na Rua do Imóvel, nº 20, tem fissuras.\n",
    # P2-1: onde a regra anterior bloqueava, agente que concorda tira a ancora.
    "r3_cpf_construida_pela_incorporadora": "FULANA, CPF 000.000.000-00, comprou a unidade habitacional construída pela incorporadora, localizada na Rua da Parte, nº 10.\n",
    "r3_cnpj_adquirida_pela_autora": "A ré, CNPJ 00.000.000/0001-00, vendeu a unidade habitacional, adquirida pela autora, localizada na Rua da Parte, nº 10.\n",
    "r3_oab_adquirida_da_construtora": "O advogado, OAB/PE 0000, representa a autora quanto à unidade habitacional adquirida da construtora, localizada na Rua da Parte, nº 10.\n",
    # P2-2: introdutores estreitos.
    "r3_tem_como_endereco_atual": "LAUDO\nO imóvel objeto da ação, antiga Rua Velha, tem como endereço atual a Rua do Imóvel, nº 20.\n",
    "r3_mudou_a_fachada": "A construtora mudou a fachada da casa da Rua do Imóvel, nº 20, objeto da ação.\n",
    "r3_mudar_a_tubulacao": "O réu se recusou a mudar a tubulação da casa da Rua do Imóvel, nº 20, objeto da ação.\n",
    "r3_trabalhava_na_obra": "O pedreiro que trabalhava na obra da Rua do Imóvel, nº 20, objeto da ação, relatou falhas.\n",
    # P2-3: vizinhanca presa ao participio do imovel.
    "r3_situado_proximo_ao_conjunto": "O imóvel objeto da ação, situado próximo ao Conjunto Habitacional Sintético, na Rua do Imóvel, nº 20, tem fissuras.\n",
    # Rodada 4 da revisão independente da PR #294.
    # P1-1: relativa do proprio imovel em qualquer forma.
    "r4_que_quebra_de_linha": "O imóvel objeto da ação, que\nfoi adquirido pela autora, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r4_que_dois_espacos": "O imóvel objeto da ação, que  foi adquirido pela autora, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r4_que_ja_foi": "O imóvel objeto da ação, que já foi adquirido pela autora, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r4_o_qual_foi": "O imóvel objeto da ação, o qual foi adquirido pela autora, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    "r4_que_em_2015_foi": "O imóvel objeto da ação, que em 2015 foi financiado pelo banco, situado na Rua do Imóvel, nº 20, tem fissuras.\n",
    # P1-2: no regime B, relativa com agente nomeado tira a ancora.
    "r4_cnpj_que_foi_vendida_a_fulana": "A ré, CNPJ 00.000.000/0001-00, informa que a unidade habitacional, que foi vendida a FULANA, situada na Rua da Parte, nº 10, tem fissuras.\n",
    "r4_cpf_que_foi_vendida_pela_ltda": "FULANA, CPF 000.000.000-00, comprou a unidade habitacional, que foi vendida pela SINTÉTICA LTDA, localizada na Rua da Parte, nº 10.\n",
    # P2-1: vizinhanca vale para o sintagma inteiro da pista.
    "r4_cpf_proximo_ao_imovel_objeto": "FULANA, CPF 000.000.000-00, tem casa situada próximo ao imóvel objeto da ação, na Rua da Parte, nº 10.\n",
    # P2-2: "tem endereço atual" do proprio imovel.
    "r4_tem_endereco_atual": "LAUDO\nO imóvel objeto da ação tem endereço atual Rua do Imóvel, nº 20, após renomeação.\n",
}


MAIN_8941B2C_REPLAY_IDS = {
    "issue_moradora": (
        "5b10be9f12e0cb984ce97c4f664c5e5e633ec5ae49ce967c10bbf6d61ea3ece8",
        "80bf0181930763fffb06da596ba70efb401031792003a923195042b5c38d2117",
        "831fbeb4622f21e01369068c0479f67d856a4b5c7e812caa142a259e3178adcd",
        "8e1336ec104b984442afb3760a3280b922432538546bc42be98f063597ae12fb",
    ),
    "issue_comprador_morador": (
        "0da68864b9ff91e9a38c7ffd0843c5b2f37a6ca098656ff6d7b833cd2bb83713",
        "3ca5cb4a1525809ec58f9059ff1ad4e4ce384ba5e65c2f69c34622434e3ff2fd",
        "98e3c17c0d6ebc184f4d9d689c53212ceacf3e4d518dbd7fdd9a4e2925124f5a",
        "a09337c99285cb10cd380fc94ed3f5bfd3fddc133d96e49ec0ceec2f8d61ecf8",
    ),
    "issue_re_estabelecida": (
        "09997ade3a8edcbbc6b4fdc5fa8642bb9a6a8cb0002733c95270c8bdd885f5ad",
        "209be62083e6bde6497e624a4dfb80f44fef0c74175810bde1481dfb6cc5ea86",
        "795028af9f3a1f296b8c51a8706b1e38beb1cfb037f87b2e6068a00836ff6bbb",
        "c858da05eb1b354f2ff204903a9774019902fb6aaefa1bab0c35d0e0f4112e5a",
    ),
    "issue_vendedora_localizada": (
        "1edbb06b8070aa1c0cbeff3c0262dcead4ac062823e5879e223c5713ec267aab",
        "78657f662e092b0873d7b0eeb43decef1580b6eced479691fb0b27210d86844c",
        "8eb24493711848080b01f3265acc2682492e9a9669909bd6f59d949b49fc80a1",
        "f179e9601db5d47e775a42367f4fe69e4832a17671da56ae9b0ed05f1ed963bc",
    ),
    "issue_testemunha_mora": (
        "4f60079ea0fde0a1d9773b514f9346d007f7dd3310a5b3cfc5e8fe9043fbcd59",
        "5e010e7555f5d48babd4001cfe62b9a1407736bd029cfce603a9361bf0c5a9f2",
        "a4f1ab08c703f6b91dcef68ebd255e25e2a87c830dee10aabce6144fe0904959",
        "e71c48b21770ff3d6b7ea8292b70d536bfdf701f16623820c3ff0dfc0cf6b600",
    ),
    "issue_foro_contrato": (
        "501cfa7c99fac197b7815be0fe6724fb257c9870655a3b73c99fda6719a0fed9",
        "61aad622342bf169e968e43953151aaad6feca31a320d308fe5b199474bc2e5e",
        "654ee4c756734e227048cf9723c093bbe6e2d040d7e8535f7cc0a8278e8d44be",
        "73114bec9810e7676cbe2693a83f791d26b4a5b27face8aaac472f724bb6770d",
    ),
    "autora_residente": (),
    "reu_domiciliado": (),
    "advogado_escritorio": (),
    "empresa_com_sede": (),
    "juizo_endereco": (),
    "foro_mesma_frase": (
        "09a7b9cb6c1d50d52c5398b9de03416edab223e9ae41256d947787a5f3c2ba38",
        "2e8dd61490b89319521eb9d2d7cc9f61916713fe01fe8db2559873e98640d492",
        "a061152bbb05936b8e44ea2f7869f051661a4ac110aa865178c3c13b6e3b436d",
        "bc58ad402ee95f16496307f576b98f0b6e80f1eee0afcca915627822ae5cc71a",
    ),
    "precedente": (
        "100ba6e96a88a9d55fade708b6aa27abd3650002495baa2f1bf55dbb000c5b46",
        "f073a0ed88a43d7eaabcbef4036910fdf2806009e74fc0912dc5c8d0e330a805",
    ),
    "testemunha_residente": (),
    "assistente_tecnico": (),
    "re_sediada_cnpj": (),
    "parte_bairro_cep": (
        "13241dfb655333f17e951fa91745c29603da3542c87ed9fd32f8356a42e45648",
        "5c0b6edbb5a6d89b0ab925151487ab4abd7242b5f660e56c09f1a0ed82837dee",
        "88db9349d0d260bc752584be0e906c6014ae3ecaec0fc4a34ad2c40591b738c7",
        "a171ec583e65143e768ec0d42245192faf916e471719a65c9ccc3dd1166b814d",
        "adfe9dccf37e2eef8c5d6ead2770fbec5066cadf341302af4fd3a7ddf363ae92",
        "b0f4c8f0e22011669097f16f0af2cc4cbc2d8e8a9d400882e78ab3ca37d7cba1",
        "c95b6e5bc70df6b6cbc88b60abba47f8789c91d35df8abfd90304bc93a3ff5d2",
        "ee8f44965e94ce8f5e744dc89e7dbe6cdfe544fb0a2bf134613dce0a261a9165",
    ),
    "onde_reside_imovel": (
        "77d31b936f830992490f7d4e9decace51c3ed565f377bbd2bc0e180b99d0b815",
        "f9cf0f375c0f47099cb13f8721f6e24cd9a42f5612da7213697db03dc7650790",
    ),
    "onde_parentetico_controlado": (
        "4a11af06a496bc5395a70424a9f814e09140bbd81fb105a863bed69054a991d5",
        "eeeeac2e053dda28518a09d2c9337d57dcf53ae6fa5f0370d6f2aacbec525ecd",
    ),
    "onde_cidade": (
        "220b8ff8661c1078232bf6cda2d161738bd5784258154875c3cc659a5eed4514",
        "c66ed8c689221b96d66f66091f3bece21f4787ae83f596dafefb060bdd349fff",
    ),
    "onde_capital": (
        "2f08724e2bd6985e00c979e93e6882ac748e0ac8a5bb97fd58d5fb4a9687aeb3",
        "36806ce77a2693a0afe6f00a64cd3290c17af178627cc239840ec3de6515a796",
    ),
    "onde_bairro": (
        "566845df7934b3a2c98b6b11ea7031e37770d43494e2188f23699ab19dbbd06b",
        "70fc77d492b7e3a290fd5fbf3ca7fcd2225b3a22c8fd6d203ed17cf6e0b70944",
        "c1a611f20c48ae9bf56bb7d378914142d0d3c6caae751188b72b9955a7090083",
    ),
    "onde_interior": (
        "6eab59f74bb7257746f107ab93f14db5751ed44192148d2d4e8af1002fcc8479",
        "8e078c5018992287d499f4f0cf8ea80fbc4f61068ed69fdb2d934fb2be6f4b62",
    ),
    "outra_unidade_onde": (
        "ce5d04e79d7ca17a0d9d7bea70bf63feaca8bc4150472e40e6c391c02fb4b64a",
        "f97260ba41f4a2d97270b2d7f0bc0f88d0faf7a9def7e04fd79dd869a819f299",
    ),
    "nova_unidade_situada": (
        "8d2a99e7c6a864c9eda8848221d665fe045c4ce9e71a6852a2e75d779f55edd4",
        "fc2bfe2237851fe2ab66f6b03c991c652aafaef55ceca0f8adf000f61fdc3e1d",
    ),
    "parentetico_com_deslocamento": (
        "47a300b351d90db6c730829768e6c407cc30d86d17b0c8471eb4fb19cee57b68",
        "dfa71040e810ecf5ee059a7f4ca7fdf7b3d7ef168b226674cf5d1db5008001d1",
    ),
    "parentetico_participio_com_deslocamento": (
        "595319481532382b8e5c941546c6b927e10888407837e5a77d90d188fa97eeee",
        "751487fb80153c404c9e91f63dac723230f4011984d73337d95b4872f635aa51",
    ),
    "onde_nao_adjacente": (
        "979e8f7b96d0a8395ea9afb50b7c5cc79ca262880f2ad6fde355e41b0fcff8f7",
        "a7955c74bc5850a5b223c37a1c00e4b4b30b345af05a64ee4ef94099f08a2386",
    ),
    "vive_hoje": (
        "2628e6c483a3d1a15c3009de9905a4536965de6a7734bf03081b4e6a4218ded0",
        "ab964d4bea53e97d3cff6292e8630d1a7b9961928f6637c08dbcb71cecc2dfe5",
    ),
    "localizada_genero_parte": (
        "b0c6fa3a2299d8ed60c8508492e2bf1fe55f2fe9310c360e0abbcf7e3cafb976",
        "d2caae300e1c805368a0653e823896c67c720ace740d35a9a2e0e7a20086de11",
    ),
    "outro_imovel": (
        "16639dc889641cedf5de313f6c3151c5662e3e4609f3f29f261c1ce26ade27cc",
        "553cbe0b4fe2281304a3e24ce37d1864c84f0efebbf1bf0f07b76f86cc58bb60",
        "746b918ececaa9edd6850eb4ff9864a9a3e72e74d1972c54a4d35487bcad3241",
        "ae680e493a83eebaaebf8ee5b1d2d3c15227125072bffc31681c6caf36d384ed",
    ),
    "ambiguo_dois_numeros": (
        "22d110b7e772a09744ade3278c92224c55d87a0b3c0b0d64d7a1d91b68b331a6",
        "29345aa9b65bc86ca192580e40ce82b2cae6bdc4afadc7b4829f27f3e6453744",
        "f8ac39b62d1379e3c4d2e8ca8218688b966fceceb5609e0b81b3ba60d4121c75",
    ),
    "ambiguo_duas_unidades": (
        "5ca857394bf2a1409fd2fa7ee5f3d5be98a99758ebf612a2bc1ea722108cfbb2",
        "a87479821fab0b09c0170a5408bca4dd217c25d49c1a54438f841de0cdb07e08",
    ),
    "narrativa_suportada": (
        "10d9c919a718f26ab1135d2a47e7f1f4353d662a7dd8fe73ebef33717632b343",
        "19f99e21e2e4a37cca7670dd40794583b2050b9dab452e4358fbf4854ac8dd69",
        "2541e77e8ac15b5ff329973d93376a96428e8e7402d1ae6afcabbc98491aa31a",
        "289c64c1796ca4bcd07a5629c41322967e9e8d4cf6f5a81eb37c808e718c3635",
        "2d604ba7fd6ddafd7ab72a1ef585ad26fb0ada9c4fc68ec6d5a9b4bbbbfe0756",
        "78f5efa7f494eddbe63421e2585906d5790a0bc7543f77ed3ebe92185091f429",
        "c7a496d9e6d4418dc6cf1ddc7caf1ccbb71abaa3546b595e991cf3f22ddcfb8d",
    ),
    "localizado_suportado": (
        "0cd21dbfa018e04ceec95bab9266223bd2afbec4e24ce71376a4a03b1cc4cfdf",
        "1fd740f34393c730cede8a7e9423ea941c3daf2fe4f2dd41ef52f146f849d899",
        "2b16ed6d3c23e319fc7f99f0aad4faa436ff16f3cf99d6da217e9713fc8141c8",
        "4865be89e32d3812372d883ff4dc80ae7e3904b2fb919ee4ac2297be5f83404a",
        "9bdf830ba724048f67ea9a32ff885cc7b365826d80f6af41486f6aa9368f11ba",
        "eb79d3f5f7c3b235b4a5247ecf008cc24789f05aa837e82b688c0f477ac7bd1b",
    ),
    "rua_com_nome_de_forum": (),
    "timbre_advogado": (),
    "contrato_qualificacao": (
        "115573c1e2111bd279ecf6c7c11d56626d0b4fde183fb7839d0507be50ac2443",
        "1ec998c8f4d77349813809dd5624eb723e98381bbe235fae846f7072c3b7cc17",
        "5d60b5b8ad65ee77b9691c32a2bae59c96d013b5aa3f7c19c7461e67b8963456",
        "79fa46f8d589555f120040283a6de1e0c4a24095356587d682ba37102ead67e2",
        "ac366ad72bf7d9609be937cdf65b82feb546460d3c5e9429e8570957946f1409",
        "c79ac6abab358126fb0147ab0472fe0c5d555efa69958d775ed51eefef9dff11",
        "d58df0700fe9d0e52db3a43715e8d376ba73302a60e9dc55f36b91a6bd42e3a7",
    ),
    "cidade_da_parte": (
        "1e796899eb12ce2803e0d1ebefda51f75d8090ca205d38d424be9b76a48c3dbb",
        "2e489f94a098b31462aad138ddf3f3dbbf681019c1d11d15b767e7eb788e916e",
        "85226664c6a7f1a0ee6d07c8c5b2ea5bc93eb74e9d1679a27c1f7a0401d156a3",
        "d9baa567c2cf4d71727d428b31dee8f1f2a5c22debd2a3bb97bbacfd6c4db429",
    ),
    "quadra_lote": (
        "27f924f7825b11cf5fd71271256cd17d56eac0483bb8783ff706fbddf1ab6823",
        "54ad4bdc7f3f8154f420ebacdfa1c4c0aa18c8671a0efbd906a9134e1551b48e",
        "e482509627711bb8e4d569fe75e79aa571eadfda823f95bb7c7fc1c82b68bc2e",
    ),
    "situado_abre_a_frase": (
        "5120d4658bae83e8531f4a6c70a6ddd8abcfb745021ead63d8b41079c0badf58",
        "69f47777d325c3b08ae912b0a70ee3a20ee1065ac74d38e313cdb200cc243728",
    ),
    "quebra_de_linha_vendedora": (
        "7576af8d93a517be3eeb90d845c5f36b2e57724367106b2e54b854c4d9ca8042",
        "f5afbc605f4e469cb726d61d9e206d51746ac85a5a1109f4d4def0c7e96169e0",
    ),
    "r_telefone_depois": (),
    "r_email_depois": (),
    "r_oab_depois": (),
    "r_construtora_situada_cnpj": (),
    "r_re_localizada_cnpj": (),
    "r_onde_residia_para": (),
    "r_onde_nao_mais_reside": (),
    "r_filial": (),
    "r_endereco_rotulo": (),
    "r_entregue_pela_construtora": (
        "46859bec846cbde103494270c07cbecf894aef1811e4a737ee5bb26b61ac25d6",
        "6a5ab10b3fbb5a7eb33280adba43c704fa5e3cb9c112cb342f7e4d74076ad8de",
    ),
    "r_construida_pela_vendedora": (
        "26048a26776383cac169d5cb9061df77434dacd3e8fc6c6ab2ba54161390c05f",
        "4ede6ad8d5502bd3e6fe83e5b76121948cc2085bb06559324922528e23c162cb",
    ),
    "r_unidade_apartamento_situada": (
        "004403aa34d7b850b6c3c3f35c1479876a58eb0f03305a14a7c8adf8afb8982f",
        "0fa2b2f5267c4b2f4668f5c3c0d746a33e5846187bc8537debe8c7eb2b9487f8",
        "babe9721de9258dacccc3b68149d59ea41c4e6db0ca81adb4772e3bc13d2bb96",
        "cdc30571dbf42dd4a0df77a1fc8b1652135ce1d675cf4d604b99a3584db89014",
    ),
    "r_apartamento_unidade_autonoma": (
        "173e87af0a8714f4cb84124f30192e713fd6d15aeec85973fb9cf85174c182f1",
        "3eef45ed68486499656932881c2f962f460e4095bbe5f23f5b8bbbbd3b84d5e0",
        "4c9d022c68af77fe4d86a95df803e7cf92c9ee2132eff0106b3aa99ec83ef998",
        "c55d84b7709241480ff44a3b9a32e95874974f8358ee665ad4eb4b2592377625",
    ),
    "r_bem_objeto": (
        "ab0df8c97c703a684ba9d7e6622e86d5b70e125d58c4c87e323633873d75191f",
        "e6e7ef9a49b6b47b8da3a23d714b9f0caf38540a3df0d8ad2af5b2021ecd4792",
    ),
    "r_sobrado_objeto": (
        "1157c53f6a7f55cac9537f68900cec0c1b084c6501dbe91c9cb8b77eb3cc9eda",
        "60c490054810452ae4a4def457edfb2097ed455a1b0fc94123fd38d44aa12c5e",
    ),
    "r_objeto_da_lide": (
        "08bf7da8dfdeb482d34f9e9cb4bb31408083c67b029cb9a7211583a6ba885320",
        "55cb9bebdfb4075b03722398623c6f9115db983e98022f74e41bce1f824a3b3c",
    ),
    "r_alcance_longo": (
        "bb2bc4416ef098354fde4889ebc4bbc91a6caad40b052d1ddbeabaabf50fd7ab",
        "dd1ae80f36b80ebc6a6474b9f02d4f836e19b9dc9334a4be5c6ee98bca40fdd3",
    ),
    "r_nesta_comarca": (
        "047996c1991ad0ed1de46049da88c9cafeaa4cbdea5637ec63068085b00a38d7",
        "44c467e8f6ff3163e631ab43bfa3b510191ecffbf1d8b98122f29e9e00711841",
    ),
    "r_municipio_e_comarca": (
        "3754768b8436e069eae52efd1500409f445de38853a9480f6ffe045ea881a974",
        "6842537e61307b5724e819d6272970e928a16fed10e6fe711979d67b2d8caf62",
    ),
    "r_matricula_cidade_comarca": (
        "2bd2051fbaf7fa67a291343627ca0724bff826c736743014a506b96eb466690c",
        "5299b5612ffc08f7c6c0a9dc207aa4a03553a86365e7fe703558d4dac4da7923",
    ),
    "r_assistentes_vistoria": (
        "236239fb3f699cd928e7f517e496b27f16453b53d019c885edc0991793b34dbb",
        "62bf234e50551727eff263c599405019a53b05b22e3a55d93643cd7ed6c5a76f",
    ),
    "r_onde_vive": (
        "58b544151ea8c157deb8c227093e214b1910d41e994b5c2fb4c27d118cad1f93",
        "93fb12598a6b78d81e351469334eef4c336fd4d2da0435ab67f5255f53a5ccb8",
    ),
    "r_apos_a_mudanca": (
        "9013b8a11fa00900d72c083ac9855f4db3e7ca7d11fec0fc3a556e96e3acb219",
        "966f70605b9df590674d72911d2df609419cbfb62bda6ca36bf47d2539ad2af0",
    ),
    "r_transferiu_a_posse": (
        "9de9dece97e1aea09d3f497ac511ee982a38e33437779134dff7e4c75d49a4a8",
        "c95151e85de4a5cf97b6265a0b055a1160459da0c0dbe47789df1ee6e5633edf",
    ),
    "r_com_domicilio": (
        "1487c34bf23d534d69fd9fd1376be104291f163f357c2121490839d36457a5c6",
        "2b861fc96316e26c3dc4b05c00482a5a6f648e6cfc179775d9893e616023260c",
        "490ec4d5fb1567726cd6e61cf5aa204b643ed0b00a785fe8e9da2cb117a4f44c",
        "b6c2f83e84df583001202cda7e63e2d557de334a0af910777d0cfc5b6db8df9e",
    ),
    "r_cuja_residencia": (
        "0ace770a84040e94482cd679fb2759ec730c4562c13ad56d4d715762376faa20",
        "9265fbbb8c85e14ebdb9aa352f6dc6c89f85559fad19b0d1225a8b920e72c50c",
        "c4151957efb7a55274338d08f158747607120f17d4d2af2362783b7df4c471b9",
        "ed95c7b467aa09fe16c1286d48c939650c3a4c1ef767784aa7de665e38394f2f",
    ),
    "r_habita": (
        "318e7bc3b67e748564af3a86942cfe68863bb7a9edd42eeb75a005d82c6779c0",
        "5687c44063ef9153ac1e2cebe03002372c8f17e17b395e65854dd1b89b15f423",
        "5b0d8f523b0f3bdfbdf36c44b3842bb8d3365cebf290cd8bc6e9503e982d0150",
        "aab1265f953d2eb54f119af952efb124f654bff198b1ab598007abc43abb5167",
    ),
    "r_hifenizacao": (
        "1cfbb8a8a1d8aa88f11be44d1d39bc10d0b52437df09388d5aa6b2cf696db85b",
        "2dcf6d69110254e49234f87304f103e219124f9d952032e88a05bf73be5ecc44",
        "47334936f9591aaf103e5846b8e9ed735ec0b8aa0bb882e633331ab858c8f46f",
        "84fd9aad366e82e443ea11f5c8326738c006ac3b7b2592243defe854602c3c55",
    ),
    "r_endereco_antes_reside": (
        "1d2876750046064273da8aa67d5d70d9e35b095a238c79f9b26556cbd4b3542a",
        "3b27d31aa1ba5ec0392d9177f935f5b0745f9b76e1221ee83921a43c90d01a95",
        "80c07622805af335ac89339e88aa48406a239e519bde45c23622f13d1ad3907a",
        "bcf9e39e0e17a57568b19b52cc0b20863a3d9a05b16c361ed44db4ac2dc180b3",
    ),
    "r_endereco_antes_moradora": (
        "524c689786d2cbe435d3b0c828fcf34332b37dec74b82354b17805618e37411d",
        "ba6ef5aa81600f0c509c31e1dcd7589dd0c6ce425364e73ceff668c29907a3b1",
    ),
    "r_onde_bairro_vizinho": (
        "e5bef7b4e7bdea9264365ec425763595e3129383696e6a4d00bf52ab041e8302",
        "ea1bcce89d1b68843b50b9bb9528e5cad8bf049ca8560fd925119b6436f07e45",
        "ef4713490fe8fff1bfcdcee392c8072253435182adb71a2d6660ae6fa15c3d1a",
    ),
    "r_parentetico_abandonado": (
        "656477ced3bacb7fe430c62608183fc97eb6f3923526c6947effe4c3208a1f2e",
        "c3d802417f924b052fbb7100884ef8e192e566f48bce1b6a978b7cebc3deb425",
    ),
    "r_parentetico_vendido": (
        "9095fccacaaf42ec762bfdf4632f2ece9b7088450245ed6a42ffd35bc4dca925",
        "e82f03458f94673e5590ffdd3c9b383360ba23132836fa70d6fe2988013c1bfb",
    ),
    "r_onde_residia_no_imovel": (
        "39a7171752b16c97791d5a5396c31dee3ef47edae4fbcaa5fd024b8d784c3e29",
        "b7eaef91c5efac5758589def17a78736aa5aac12c8ea0266cc9446fb08f3bf51",
    ),
    "r_predio_ao_lado": (
        "6c933f1e892f66ab0a30ba0c7be69d905faa4d40665f5516c8bb26ef98e8b188",
        "c0a897bfca3dfa1acd95d085fdaf327e8dad5ead095bca8dd3deb4f5cf8ec109",
    ),
    "r_transferida_para": (
        "23bb764cc8713eab9714dc46eec951fdf8a5c5a5f9c8ea05afe9425610c8ec89",
        "3c15e492108ba76ed89d0c1548023c8a23451c31b0f404b5affe3aaa1fddd5f6",
        "5a378fcc3e86129736fa0e68fa5ac768f4a87d30e03197ae4b55f22ff3429b2e",
        "d15145a74c9d57364ed25a286c5677a35c39488be489c57827336aa926f01085",
    ),
    "r_realocada": (
        "4a58b803a7aec877bcd4a3412e08ac41b204f9e4d5115f831f2481bbea4d2717",
        "5f757387c2a97e2024cb4a3c4ad770cf5e7bf5f1bda8be65945962f518fa6cd8",
        "acbd561d591a0436800b9200870f536ae7ed7e17eb9638a214907a215196de09",
        "cc89a617e50591d790bc842920210ab63e54c124d377b5ee0efdb152ea21c400",
    ),
    "r_mora_no_imovel": (
        "7b11249a2e83ac2edccf8f99b579d940def581cd01b00ee1d2c2e3fcf8dc8ac2",
        "a85190ba0e7002deb555b0221e171b1b901eb5969441631555ffb29042d5dada",
    ),
    "r_novo_imovel_objeto": (
        "65ee92a63b01cbb1202255a514993465d860c585b001e037a99fed61c76d219b",
        "fb89de5f1b8df5ae90123384c46ad74f49967e7faab8a48a75c7673381091b68",
    ),
    "r_nova_unidade_objeto": (
        "43eab2cbf833b1b946a4b869f063e8f0dcff206a5f0155f3b2f9cb5da9340579",
        "6551d718e933a37bd1b4f35b5bf05c16c1072de59fe97d5fb89a28dbfdc449ec",
    ),
    "r_residencia_objeto": (
        "21dab0c5e012bb03dba6c44d2bd4f7ee1decec6a1062ea07ca590be266fc8666",
        "37657c5fa37a06abc0a8de1a1a70559d67da7c3f47343a6518f5a409afd34dce",
    ),
    "r_dois_enderecos_mesma_pista": (
        "74494eedd297b63325f43e1b11d8dbd55c7d785d174f83bbaea4c716ad1c1dc0",
        "c4c57e39caff4dd076d4d9b76b3f94c4e4c6112355ff3a76250a14153b97bcff",
        "d1cf0925974b1041e664bfa5090c02e01301b1c48a23a8019d4c9f8649e524fa",
        "e6b9d8bd014ac86adab95dd38399932c19983bce37d87139dd284c69c5731525",
    ),
    "r2_adquirida_pela_autora": (
        "4730aad40ad89590e8ec34e22dadeee75afda1d73b066f21f02b0f6424fe8af7",
        "d4aa776ceabbeaa119c8336893c7e8d1564be9026d2fce5452a46ae8a962c323",
    ),
    "r2_faz_parte": (
        "7e6220fbc55c2f122f356bc872f99e5ee6f115c6b986f1666bce0eca614be448",
        "7fb60eea3e8d211d281cfe14c73f0abbc3f8691f3409d59d8c91753c494c986a",
        "87bc2dde624c8bbda3cd449b2bcc5591143019b21f61c3e195ee9adc043057fe",
    ),
    "r2_parte_integrante": (
        "7a988fadb653855fa79b2941a1fbe81d219052a5e4c2923a84c76e1e69252f76",
        "7eeeae09dd4ad18f0b0e0fd4590f86d8f01673e01371c56bb7ed78102a242c3f",
    ),
    "r2_financiado_pelo_banco": (
        "08f198ce144accf4c28ba34aaffed92749fb096935458ff999f9313f1495d76d",
        "d1cfaa706a8fc3d14edf1ab83c0b6f6b4c6cc7417af5f06c331d5f6dba415832",
    ),
    "r2_construida_pela_construtora_re": (
        "3484eb1b3d507b803c7f98e4415ad00f21e4b91dc896329229c27a54925cb995",
        "cbcae90a57001428c85cffcab95b307e399d7b878cc12898e839a8cb64194ab2",
    ),
    "r2_entregue_a_autora": (
        "5c71afaf44f54e0ec88b5a5259e0a64ec8d25e08616efd85eb2fd8117dd478fc",
        "8080291ebfbce1b11663f5ac2f867aa0a83c295c166bd718fe51011616a54337",
    ),
    "r2_adquirido_pelo_requerente": (
        "785330969ce709de89e3b404f9f51e342b99bce1b45d25906934ff31ba593cc9",
        "e0c5f48afe92237d346f2319a3850ae878a2baadcdd03c55632072d2578d1435",
    ),
    "r2_vendida_a_fulana_cpf": (),
    "r2_vendida_pela_ltda_cnpj": (),
    "r2_casa_sem_pista_com_cnpj": (),
    "r2_perito_foi_para": (
        "73bc503b8f18959c9dce389c2e62c6cbc510b47565fb7896a2d2a4b8dd65a84f",
        "f245e24a37ec0afa64880d49c09050cfab25a4c16a234ea79b8353c25c6b4901",
    ),
    "r2_autos_foram_para": (
        "60db0bd3538a4f673fe4a67aa6b7980eed7e967acfe2aaff4ddcd9cc0e39117a",
        "747978ee302b0c6b012abee9e4511bf782e6893eedefdd71803cc5d17628f61d",
    ),
    "r2_rua_vizinha": (
        "b27a2adcdbb2db1aeebc1f9770635bbd6c9c05b929e09c13638f76021f3905f0",
        "f268cdaeea3aea2d857410e10a470f5ef87d8663cf9fc24d5bba3ac4d12b1573",
    ),
    "r2_vendida_a_fulana": (
        "0a74eb5a96ee92d0c7c6cedebc2a139b2a4b6b125a8e6878019de7e2a653e56f",
        "9927c497f88f4f8b7250a19fb1824f2705368ebbc00eb703cf5e6ca134f9cd2c",
    ),
    "r2_vendida_pela_ltda": (
        "8f03854c947f20f8d24eb1d5be974de8f2d9022ccd41d8889ed8a71b1d549369",
        "f630acbb2405f68a6bf152e03d42b07ea826595c63640e1de2c2a83444c3c487",
    ),
    "r2_hifen_com_espaco": (
        "7c1c7c4721144577d02ea9fe9bec53bd117dac0041d5a68fa9d8c952c2f288b9",
        "807fc94b6c0a7bc56eb4c1aa85c99397339ed67032af601d1e1f8c635614017c",
        "d29f0205cbbe1a06eda0325c4b4d7187e0b9a21c3dd0e81e065c977976dfca7d",
        "f49661b84eb61a2eb15cdb3094d6c533925a85423d910240ae0f475569cef0c5",
    ),
    "r2_cuja_sede": (
        "0ad109211f66bb5958a1147d409291223060a3c7f9c0f71923a920c30195eb6d",
        "3950cbc555215abffd0edd9941a74ad70071465dda63085772045753193e5be8",
    ),
    "r2_com_matriz": (
        "a87e14516abc14a7a52e00b0df8becf26a78dd4eebee56bda25f4c6c794744e0",
        "f297fde246ded9a967c9e8a6aa2dff8137823f311d9ff7f421e8eca8c03371a5",
    ),
    "r2_trabalha_na": (
        "05f3551f69d0d462f3a903760edac7a807ad5cc2ec37b2664ac8c30620de728d",
        "c3f63b4f627f9d9dda384e75d1197bc76ed23956cb1ee3c7e1917bf7807bc221",
    ),
    "r2_mudou_se_a": (
        "aa432a79523e9cbd79ad30859dc71474b37263558ad08acf8a135358a44e5258",
        "c46726614feb9ad980a74673e8aa7884ffcbfdfa43d087608cb2e7b0cbdbe833",
    ),
    "r2_endereco_atual": (
        "9ec428e096ce810a88f1fce6127897d9fad4e66fb8984e7b83f26213cd469974",
        "dbe26fb2b3ec3c73779b3652338b32d7ad4954362dff6596f4dfd68da00ba3f1",
    ),
    "r2_imovel_ao_lado_do_objeto": (
        "4bb9209184bbb15742aa00dbc3d2d84935e2cae97b97a44d5ce36eb5ab891d6d",
        "fd1976bb833a5d2854697d260246deff28be273c1ba8eae4deae85cf14dd4655",
    ),
    "r2_novo_bairro": (
        "153413e2e61f642762b8abbd911dfb4b15060f17b3f37c04b10ce92072676c7c",
        "9cb60d49fcf09b0d5ebab4549fbd1a969089883f2cf34c46c82f3e85bef07ed5",
    ),
    "r3_que_foi_adquirido": (
        "d33189754cac1b96fe2810d14a6f0024753447108909d5f113c9d6738afb918a",
        "ef77016d0f72835ac6bba537564208613838b6d0077a1da8a570dff51e3dfc20",
    ),
    "r3_que_foi_financiado": (
        "7ec19c688b6c339ec25e259255a204cfcf52231b85e6024fa155742323b44ee3",
        "c7fc60a8134bbaa32f64663ad1981699263b6464ad177b157c3b1aa673595dfe",
    ),
    "r3_que_foi_entregue": (
        "c70db56831c406fed7aee8c8fc50ea4d1c83b554453b5a2411388d2dc87c5c05",
        "fc095dd8a54cac517ba9cfee95753c090b4a91b44ff563ff31480adc49beb688",
    ),
    "r3_adquirida_e_quitada": (
        "3725bdd5ccb72fd8341b1e2f997205e46aa147b887ce4f1600cb8f4627cd3b60",
        "8240af4faaa0b328597c66e05b65d1fca13b9a70034f444ab9a8ce2e17cbf907",
    ),
    "r3_financiada_e_entregue": (
        "8ddbe3205aecc6237a81759d1ca91ba233d6df06e42ef362b1dd5b2483825405",
        "96b62070e25b77309ed0aff1b64a462884bde3d505714389d9d7822ccd7b6466",
    ),
    "r3_cpf_construida_pela_incorporadora": (),
    "r3_cnpj_adquirida_pela_autora": (),
    "r3_oab_adquirida_da_construtora": (),
    "r3_tem_como_endereco_atual": (
        "1e260fca01ff7cd3cbf30efb4b8ded5ba9f364e4d3988ca611e62de259af4ce1",
        "2109c6f95db1ab37b3f93663679d9dcd88649f53a7f7f1163d6d3011749286a8",
        "5d403389a3286a56d4d51c47a77b46ca3c928483874beca80a7491bd900b64a8",
    ),
    "r3_mudou_a_fachada": (
        "86a7ec095298f5c80d99d3965afc1d33122b078111c5d137495240a080b89621",
        "c1ac9bb383e9ce16e2d56b6c7e7dd6a38bfbc94b296c202e8b95670a185430fd",
    ),
    "r3_mudar_a_tubulacao": (
        "0767801caeec809a6176c5ca30ccd4d2387fcb57b4e65d9e63331e0eefed8ac3",
        "11449a539326507a526df95f0e8edfca05bb97db279dd9b00d112bbbcc12822a",
    ),
    "r3_trabalhava_na_obra": (
        "15861f8e21663e057e6a4153116956d3b995630f9d415d766b8d232b7611680a",
        "3c1a66c279b4eed03b2fe262c083700f3eda7900824a74d2da86774434a974b5",
    ),
    "r3_situado_proximo_ao_conjunto": (
        "29a6654713bd3cb4475cfff1d09fc58e231fac40a3df62664930c88528a7a391",
        "499424faf0f838b64a41718f32da01b73e881f6caa1c9848192b96476861f211",
        "905894d3531981a2229ed698d879cdd7dac6417c4536fd380502daf20dc02100",
    ),
    "r4_que_quebra_de_linha": (
        "740dfd38fb0b373cddd7a52f4f8cf9eb516adae95c17657407dc28be8c5cc5f9",
        "f5008b912ca90eb018f7c9c2d647880070ee6033b1f376ee0ea065ced74936b9",
    ),
    "r4_que_dois_espacos": (
        "970fca6ef760aaf0c4540efcfb23cbd713bd0ae346a60b01e200e5c68c68bfe0",
        "9ceb1c0d4c6bc7513bded3f22e9eda3a37e11b2dc3ad9582550737d469d27f35",
    ),
    "r4_que_ja_foi": (
        "5d91a2c152da3d90a433936d5b4216315b66c3ee4f766827cf177e96c6292ac0",
        "f7a8b4fc2402e1d0f31df2880fdca594c522f660f13c139bbe0eab6fe434152d",
    ),
    "r4_o_qual_foi": (
        "6e728ee063bef6358f8b730cb4cf45b60991f5a8943abb78fd55ced659005c8c",
        "ac23c8b0ffb17de1ea8c31e2bb671308995ea8b3388a29d389a2dc380902cf6e",
    ),
    "r4_que_em_2015_foi": (
        "167d9f8a4acb5e15eb0147b26d89d2cec6a5ca156c44f4e4b018c821a1f1d19e",
        "61d8489ccaf5e69c522fd2b956376d97250ed635cf7770b24a17c92fb82cd064",
    ),
    "r4_cnpj_que_foi_vendida_a_fulana": (),
    "r4_cpf_que_foi_vendida_pela_ltda": (),
    "r4_cpf_proximo_ao_imovel_objeto": (),
    "r4_tem_endereco_atual": (
        "39f3473e769f8bc0ec3104362b6299f80f0af777966ce8d4918266ebcd4410a4",
        "c0b4d83a99a44edb2e0b6fcfe5632225c2c5e0bb9131cb02eac07310b8c0df29",
    ),
}

_ROAD = {("street", "Rua do Imóvel", "STRONG"), ("number", "20", "STRONG")}
# Resultado exato da busca nova por sonda (campo, valor, força).
EXPECTED = {
    **{name: _ROAD for name in (
        "issue_moradora", "issue_comprador_morador", "issue_re_estabelecida", "issue_vendedora_localizada",
        "issue_testemunha_mora", "issue_foro_contrato", "autora_residente", "reu_domiciliado",
        "advogado_escritorio", "empresa_com_sede", "juizo_endereco", "foro_mesma_frase", "precedente",
        "testemunha_residente", "assistente_tecnico", "re_sediada_cnpj", "cidade_da_parte", "outro_imovel",
        "onde_reside_imovel", "onde_parentetico_controlado", "situado_abre_a_frase",
    )},
    **{name: set() for name in (
        "onde_cidade", "onde_capital", "onde_bairro", "onde_interior", "outra_unidade_onde",
        "nova_unidade_situada", "parentetico_com_deslocamento", "parentetico_participio_com_deslocamento",
        "onde_nao_adjacente", "vive_hoje", "localizada_genero_parte", "timbre_advogado", "quebra_de_linha_vendedora",
    )},
    "parte_bairro_cep": _ROAD | {("neighborhood", "Imóvel Sintético", "STRONG"), ("postal_code", "52222-222", "STRONG")},
    "ambiguo_dois_numeros": {("street", "Rua do Imóvel", "STRONG"), ("number", "20", "POSSIBLE"), ("number", "22", "POSSIBLE")},
    "ambiguo_duas_unidades": {("unit", "101", "POSSIBLE"), ("unit", "102", "POSSIBLE")},
    "narrativa_suportada": {
        ("street", "Rua das Acácias Sintéticas", "STRONG"), ("number", "120", "STRONG"),
        ("neighborhood", "Jardim Sintético", "STRONG"), ("postal_code", "50000-000", "STRONG"),
        ("development", "Residencial Flores Sintéticas", "STRONG"), ("unit", "302", "STRONG"), ("block", "B", "STRONG"),
    },
    "localizado_suportado": {
        ("street", "Avenida Sintética", "STRONG"), ("number", "5", "STRONG"), ("neighborhood", "Centro Sintético", "STRONG"),
        ("postal_code", "50000-000", "STRONG"), ("city", "Recife", "STRONG"), ("state", "PE", "STRONG"),
    },
    # "Fórum" no próprio logradouro: a frase continua bloqueada como na main (fail-closed).
    "rua_com_nome_de_forum": set(),
    "contrato_qualificacao": _ROAD | {("city", "Caruaru", "STRONG"), ("state", "PE", "STRONG"), ("private_area_m2", "41,85", "STRONG")},
    "quadra_lote": {("street", "Rua do Loteamento Sintético", "STRONG"), ("number", "15", "STRONG"), ("quadra", "3", "STRONG")},
    # Revisão independente da PR #294 (resultado conferido caso a caso).
    "r_telefone_depois": set(),
    "r_email_depois": set(),
    "r_oab_depois": set(),
    "r_construtora_situada_cnpj": set(),
    "r_re_localizada_cnpj": set(),
    "r_onde_residia_para": set(),
    "r_onde_nao_mais_reside": set(),
    "r_filial": set(),
    "r_endereco_rotulo": set(),
    "r_entregue_pela_construtora": set(),
    "r_construida_pela_vendedora": set(),
    "r_unidade_apartamento_situada": {("neighborhood", "Imóvel Sintético", "STRONG"), ("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG"), ("unit", "302", "STRONG")},
    "r_apartamento_unidade_autonoma": {("block", "B", "STRONG"), ("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG"), ("unit", "302", "STRONG")},
    "r_bem_objeto": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_sobrado_objeto": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_objeto_da_lide": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_alcance_longo": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_nesta_comarca": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_municipio_e_comarca": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_matricula_cidade_comarca": {("number", "20", "POSSIBLE"), ("street", "Rua do Imóvel", "POSSIBLE")},
    "r_assistentes_vistoria": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_onde_vive": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_apos_a_mudanca": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_transferiu_a_posse": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_com_domicilio": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_cuja_residencia": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_habita": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_hifenizacao": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_endereco_antes_reside": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_endereco_antes_moradora": set(),
    "r_onde_bairro_vizinho": set(),
    "r_parentetico_abandonado": set(),
    "r_parentetico_vendido": set(),
    "r_onde_residia_no_imovel": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_predio_ao_lado": set(),
    "r_transferida_para": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_realocada": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_mora_no_imovel": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_novo_imovel_objeto": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_nova_unidade_objeto": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_residencia_objeto": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r_dois_enderecos_mesma_pista": {("number", "10", "POSSIBLE"), ("number", "20", "POSSIBLE"), ("street", "Rua da Parte", "POSSIBLE"), ("street", "Rua do Imóvel", "POSSIBLE")},
    # Rodada 2 da revisão independente da PR #294.
    "r2_adquirida_pela_autora": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_faz_parte": {("development", "Residencial Sintético", "STRONG"), ("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_parte_integrante": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_financiado_pelo_banco": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_construida_pela_construtora_re": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_entregue_a_autora": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_adquirido_pelo_requerente": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_vendida_a_fulana_cpf": set(),
    "r2_vendida_pela_ltda_cnpj": set(),
    "r2_casa_sem_pista_com_cnpj": set(),
    "r2_perito_foi_para": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_autos_foram_para": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_rua_vizinha": {("number", "20", "STRONG"), ("street", "Rua Vizinha Sintética", "STRONG")},
    "r2_vendida_a_fulana": set(),
    "r2_vendida_pela_ltda": set(),
    "r2_hifen_com_espaco": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r2_cuja_sede": set(),
    "r2_com_matriz": set(),
    "r2_trabalha_na": set(),
    "r2_mudou_se_a": set(),
    "r2_endereco_atual": set(),
    "r2_imovel_ao_lado_do_objeto": set(),
    "r2_novo_bairro": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    # Rodada 3 da revisão independente da PR #294.
    "r3_que_foi_adquirido": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r3_que_foi_financiado": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r3_que_foi_entregue": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r3_adquirida_e_quitada": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r3_financiada_e_entregue": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r3_cpf_construida_pela_incorporadora": set(),
    "r3_cnpj_adquirida_pela_autora": set(),
    "r3_oab_adquirida_da_construtora": set(),
    "r3_tem_como_endereco_atual": {("number", "20", "POSSIBLE"), ("street", "Rua Velha", "POSSIBLE"), ("street", "Rua do Imóvel", "POSSIBLE")},
    "r3_mudou_a_fachada": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r3_mudar_a_tubulacao": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r3_trabalhava_na_obra": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r3_situado_proximo_ao_conjunto": {("development", "Conjunto Habitacional Sintético", "STRONG"), ("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    # Rodada 4 da revisão independente da PR #294.
    "r4_que_quebra_de_linha": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r4_que_dois_espacos": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r4_que_ja_foi": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r4_o_qual_foi": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r4_que_em_2015_foi": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
    "r4_cnpj_que_foi_vendida_a_fulana": set(),
    "r4_cpf_que_foi_vendida_pela_ltda": set(),
    "r4_cpf_proximo_ao_imovel_objeto": set(),
    "r4_tem_endereco_atual": {("number", "20", "STRONG"), ("street", "Rua do Imóvel", "STRONG")},
}
_PARTY_VALUES = {"Rua da Parte", "10", "Parte Sintética", "51111-111", "Avenida da Vendedora", "900", "vizinho"}


def test_every_probe_has_an_expected_result():
    assert set(EXPECTED) == set(PROBES) == set(MAIN_8941B2C_REPLAY_IDS)


@pytest.mark.parametrize("name", sorted(PROBES))
def test_search_result_is_exact(name):
    assert _found(PROBES[name]) == EXPECTED[name]


# Resíduo conhecido: sem marcador nenhum ("e a casa de FULANA, na Rua..."), o
# texto não diz qual dos dois logradouros presos à mesma pista é o do imóvel.
# Os dois ficam só "possíveis" (a main propunha o da parte como forte).
_AMBIGUOUS_WITHOUT_MARKER = {"r_dois_enderecos_mesma_pista"}


@pytest.mark.parametrize("name", sorted(set(PROBES) - _AMBIGUOUS_WITHOUT_MARKER))
def test_party_address_is_never_a_new_proposal(name):
    assert not {value for _field, value, _strength in _found(PROBES[name])} & _PARTY_VALUES


def test_two_streets_bound_to_the_same_cue_are_never_strong():
    found = _found(PROBES["r_dois_enderecos_mesma_pista"])
    assert {strength for field, _value, strength in found if field in {"street", "number"}} == {"POSSIBLE"}


@pytest.mark.parametrize("text", [
    "LAUDO\nAssistente técnico da ré: Eng. Sintético\nLogradouro: Rua do Imóvel\nNúmero: 20\n",
    "TERMO DE VISTORIA\nTestemunha: Beltrano Sintético\nLogradouro: Rua do Imóvel\nNúmero: 20\n",
])
def test_witness_or_assistant_label_does_not_hide_the_property_label(text):
    assert ("street", "Rua do Imóvel", "STRONG") in _found(text)


@pytest.mark.parametrize("name", sorted(PROBES))
def test_every_new_proposal_is_replayable_by_the_backup(name):
    new = {p.proposal_id for p in _proposals(PROBES[name])}
    replay = {p.proposal_id for p in _proposals(PROBES[name], legacy=True)}
    assert new <= replay


@pytest.mark.parametrize("name", sorted(PROBES))
def test_evidence_replayed_by_main_8941b2c_still_replays(name):
    """BACKUP_REPLAY_LEGACY = ALLOWED: nada que a main reproduzia deixa de ser conferível."""
    replay = {p.proposal_id for p in _proposals(PROBES[name], legacy=True)}
    assert set(MAIN_8941B2C_REPLAY_IDS[name]) <= replay


def test_the_old_party_proposal_is_replayed_but_never_offered_again():
    text = PROBES["issue_moradora"]
    assert ("street", "Rua da Parte") in {(p.field, p.value) for p in _proposals(text, legacy=True)}
    assert ("street", "Rua da Parte") not in {(p.field, p.value) for p in _proposals(text)}


def test_number_and_district_stay_bound_to_their_own_street():
    proposals = _proposals(PROBES["parte_bairro_cep"])
    street = next(p for p in proposals if p.field == "street")
    for field, value in (("number", "20"), ("neighborhood", "Imóvel Sintético"), ("postal_code", "52222-222")):
        item = next(p for p in proposals if p.field == field)
        assert item.value == value and item.evidence.excerpt == street.evidence.excerpt


def test_zero_proposals_everywhere_is_not_the_fix():
    """O endereço real do imóvel continua sendo achado nas frases com parte."""
    found = [name for name, expected in EXPECTED.items() if ("street", "Rua do Imóvel", "STRONG") in expected]
    assert len(found) >= 20
    assert all(("street", "Rua do Imóvel", "STRONG") in _found(PROBES[name]) for name in found)


def test_ambiguous_numbers_and_units_stay_possible():
    assert {s for f, _v, s in _found(PROBES["ambiguo_dois_numeros"]) if f == "number"} == {"POSSIBLE"}
    assert {s for _f, _v, s in _found(PROBES["ambiguo_duas_unidades"])} == {"POSSIBLE"}


def test_search_never_confirms_anything():
    """Proposta é só proposta: não carrega decisão, autoria nem data de confirmação."""
    for text in PROBES.values():
        for proposal in _proposals(text):
            assert not {"confirmed", "confirmed_by", "captured_at", "decision"} & set(type(proposal).__dataclass_fields__)


def test_product_proposes_only_the_property_and_replays_an_old_party_confirmation(tmp_path):
    """Ponta a ponta: busca nova sem endereço de parte; backup antigo continua conferível."""
    import json
    from pathlib import Path

    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN, _http, _reseal, http_request
    from tests.test_property_record_v1 import _text_pdf

    line = (
        "FULANA SINTETICA, moradora da Rua da Parte Sintetica, n. 45, proprietaria do imovel objeto da acao "
        "situado na Rua do Imovel Sintetico, n. 120."
    )
    runtime = build_local_api(tmp_path / "property-293.db", token=TOKEN, private_root=tmp_path / "private")
    runtime.start()
    try:
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Imóvel e parte na mesma frase"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        profile = json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
        assert _http(runtime, "PUT", root + "/expert-profile", {"expected_revision": None, "profile": profile})[0] == 200
        status, _ = _http(runtime, "POST", root + "/materials", raw_body=_text_pdf([line]), headers={"Content-Type": "application/pdf", "X-Document-Filename": "inicial.pdf"})
        assert status == 201
        status, found = _http(runtime, "GET", root + "/property-record/proposals")
        assert status == 200 and found["pending_documents"] == []
        values = {(p["field"], p["value"]) for p in found["proposals"]}
        assert ("street", "Rua do Imovel Sintetico") in values and ("number", "120") in values
        assert not {value for _field, value in values} & {"Rua da Parte Sintetica", "45"}
        street = next(p for p in found["proposals"] if p["field"] == "street")
        status, saved = _http(runtime, "PUT", root + "/property-record", {"expected_revision": None, "changes": [{"field": "street", "value": street["value"], "proposal_id": street["proposal_id"]}]})
        assert status == 200
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
        VerifyWorkspaceBackup().execute(backup)
        # Antes do #293 a main propunha (e o perito podia confirmar) o endereço
        # da parte com esta mesma evidência: o backup antigo continua válido.
        old = json.loads(backup)
        revision = next(r for r in old["artifact_revisions"] if r["artifact_kind"] == "PROPERTY_RECORD_V1")
        value = revision["payload"]["values"][0]
        value["value"] = value["evidence"]["source_value"] = "Rua da Parte Sintetica"
        assert value["evidence"]["excerpt"] == line and value["evidence"]["method"] == "CONTEXT_BOUND_NATIVE_TEXT_V2"
        VerifyWorkspaceBackup().execute(_reseal(old))
    finally:
        runtime.close()
