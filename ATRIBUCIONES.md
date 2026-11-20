# Atribuciones y licencias

Este repositorio redistribuye, sin modificarlos, archivos publicados por terceros. Cada uno conserva su licencia.
Los textos completos de las licencias están en la carpeta `licencias/`.

| Archivo(s) | Modelo | Autor original | Conversión a ONNX | Licencia |
|---|---|---|---|---|
| `parakeet-v3.encoder.int8.onnx`, `parakeet-v3.decoder.int8.onnx`, `parakeet-v3.joiner.int8.onnx`, `parakeet-v3.tokens.txt` | Parakeet TDT 0.6B v3 | NVIDIA, [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | Proyecto sherpa-onnx (k2-fsa), [csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8](https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8), revisión `2bda32ec70b097a55adaa07d9a7173915b43cc78` | [CC BY 4.0](licencias/CC-BY-4.0.txt) |
| `canary-180m.encoder.int8.onnx`, `canary-180m.decoder.int8.onnx`, `canary-180m.tokens.txt` | Canary 180M flash | NVIDIA, [nvidia/canary-180m-flash](https://huggingface.co/nvidia/canary-180m-flash) | Proyecto sherpa-onnx (k2-fsa), [csukuangfj/sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8](https://huggingface.co/csukuangfj/sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8), revisión `9077164e0d3dd1d5353743e89ceaa1d3a770838c` | [CC BY 4.0](licencias/CC-BY-4.0.txt) |
| `silero_vad.onnx` | Silero VAD | Silero Team, [snakers4/silero-vad](https://github.com/snakers4/silero-vad) | Publicado por sherpa-onnx en el release [asr-models](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models) | [MIT](licencias/MIT-silero-vad.txt) — Copyright (c) 2020-present Silero Team |
| `nemo_en_titanet_small.onnx` | TitaNet small | NVIDIA NeMo, [titanet_small en NGC](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_small) («covered by the license of the NeMo Toolkit») | Publicado por sherpa-onnx en el release [speaker-recongition-models](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models) | [Apache 2.0](licencias/Apache-2.0.txt) (licencia de [NVIDIA/NeMo](https://github.com/NVIDIA/NeMo)) |
| `sherpa-onnx-2.0.1.aar` | Librería sherpa-onnx 2.0.1 para Android | Proyecto k2-fsa, [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | — | [Apache 2.0](licencias/Apache-2.0.txt) |

**Cambios (exigido por CC BY 4.0, sección 3(a)(1)(B)):** los archivos de Parakeet y Canary son la conversión a ONNX
y la cuantización a int8 que hizo el proyecto sherpa-onnx a partir de los modelos originales de NVIDIA. Este
repositorio no los cambia: son copias byte por byte, con su huella SHA-256 en `modelos.json`. Ni NVIDIA ni el
proyecto sherpa-onnx respaldan a CIRCLE ni a este repositorio.

## Audio de prueba (`prueba/`)

48 frases y un audio armado con dos voces, tomados de la partición `test` en español de **VoxPopuli**
([facebook/voxpopuli](https://huggingface.co/datasets/facebook/voxpopuli), revisión
`42f01879c780b4a2e90ec0b4f616c2ece526e4f1`), que se distribuye con licencia **[CC0 1.0](licencias/CC0-1.0.txt)**.
El audio original es de sesiones plenarias del Parlamento Europeo (fuente: Parlamento Europeo; ver su
[aviso legal](https://www.europarl.europa.eu/legal-notice/en/)). `dos_voces.flac` es una concatenación de 6 frases
de dos oradores distintos con 1,2 s de silencio entre cada una. No hay audio de Sesiones de CIRCLE en este repositorio.

Wang, C. et al. (2021). *VoxPopuli: A Large-Scale Multilingual Speech Corpus for Representation Learning,
Semi-Supervised Learning and Interpretation.* ACL 2021.
