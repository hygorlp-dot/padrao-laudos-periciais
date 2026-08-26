# RapidOCR local V1

## Decisão

- Runtime: `rapidocr==3.9.2` com `onnxruntime==1.29.0`, CPU-only.
- Fonte: `RapidAI/RapidOCR` e modelos convertidos da família PaddleOCR.
- Licenças declaradas: Apache-2.0 (RapidOCR/modelos) e MIT
  (ONNX Runtime).
- Modelo de reconhecimento: `latin_PP-OCRv5_rec_mobile.onnx`, que inclui
  português.
- SHA-256: `b20bd37c168a570f583afbc8cd7925603890efbcdc000a59e22c269d160b5f5a`.
- Modelo de detecção empacotado: `PP-OCRv6_det_small.onnx`, SHA-256
  `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f`.
- Classificador empacotado: `ch_ppocr_mobile_v2.0_cls_mobile.onnx`, SHA-256
  `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c`.

O reconhecimento latino foi selecionado após benchmark sintético local:
preservou diacríticos portugueses, número CNJ e nomes de partes. O modelo
padrão chinês/inglês do RapidOCR foi rejeitado por perder diacríticos. Docling
e PaddleOCR completo não foram incorporados porque exigem pilhas/modelos
maiores sem benefício necessário para o boundary atual.

## Observacoes locais de recurso

Benchmark sintetico em CPU/Windows, executado em 2026-08-26 com rasterizacao
1,5x (observacao de produto, nao gate de performance):

- PDF nativo: 0,004 s, 0 paginas OCR, 1 pagina nativa, pico Python 0,15 MiB;
- PDF escaneado: 1,055 s, 1 pagina OCR, pico Python 58,78 MiB;
- PDF misto: 1,016 s, 1 pagina OCR e 1 pagina nativa, pico Python 58,02 MiB;
- reabertura com cache: 0,005 s, 0 paginas OCR, 1 cache hit, pico Python 0,09 MiB.

A integracao de classe 100 MiB processa somente uma pagina OCR e salta uma
pagina nativa; o transporte permanece em blocos e o pico combinado observado
ficou abaixo de 128 MiB. Os valores variam conforme CPU e carga do host.

## Provisionamento e privacidade

O modelo latino publico de 7,9 MiB e distribuido em
`scripts/backend_contract/assets/latin_PP-OCRv5_rec_mobile.onnx`. O runtime
valida seu SHA-256 antes de carregar e nunca baixa modelos. A dependencia
RapidOCR continua trazendo seus modelos padrao pelo gerenciador de pacotes;
todos os tres assets sao verificados pela identidade pinada antes da inferencia.

PDFs, imagens de páginas e texto extraído nunca são enviados a esse endpoint
nem a qualquer serviço externo. A inferência acontece localmente. Atualização
de versão, URL, modelo ou hash exige nova Issue, benchmark e auditoria.
