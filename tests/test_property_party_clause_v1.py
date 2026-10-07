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
    "rua_com_nome_de_forum": {("street", "Rua do Fórum Velho Sintético", "STRONG"), ("number", "20", "STRONG")},
    "contrato_qualificacao": _ROAD | {("city", "Caruaru", "STRONG"), ("state", "PE", "STRONG"), ("private_area_m2", "41,85", "STRONG")},
    "quadra_lote": {("street", "Rua do Loteamento Sintético", "STRONG"), ("number", "15", "STRONG"), ("quadra", "3", "STRONG")},
}
_PARTY_VALUES = {"Rua da Parte", "10", "Parte Sintética", "51111-111", "Avenida da Vendedora", "900"}


def test_every_probe_has_an_expected_result():
    assert set(EXPECTED) == set(PROBES) == set(MAIN_8941B2C_REPLAY_IDS)


@pytest.mark.parametrize("name", sorted(PROBES))
def test_search_result_is_exact(name):
    assert _found(PROBES[name]) == EXPECTED[name]


@pytest.mark.parametrize("name", sorted(PROBES))
def test_party_address_is_never_a_new_proposal(name):
    assert not {value for _field, value, _strength in _found(PROBES[name])} & _PARTY_VALUES


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
