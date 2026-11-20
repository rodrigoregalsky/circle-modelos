# circle-modelos

Copia propia de los modelos abiertos de transcripción que usa la app de CIRCLE. Los celulares bajan los modelos
**solo de este repositorio** (los assets de sus releases) y verifican el tamaño y la huella SHA-256 de cada archivo
contra la ficha. Si el sitio de origen de un modelo lo borra o lo cambia, la app sigue bajando la copia de acá.

Acá no hay código, datos ni documentos de CIRCLE, ni ningún secreto: solo los modelos, sus licencias, la ficha y el
proceso que los mantiene al día.

## Qué hay

| Ruta | Qué es |
|---|---|
| `modelos.json` | **La ficha vigente**: versión, release, y por cada archivo su dirección, tamaño y SHA-256. La app la lee de `https://raw.githubusercontent.com/rodrigoregalsky/circle-modelos/main/modelos.json`. |
| `estado.json` | Estado legible de la última revisión diaria: si la copia propia está entera, qué pasó con cada modelo en su origen, las pruebas y los eventos. |
| Releases `modelos-vN` | Los 9 archivos de modelos de la versión N (y la librería sherpa-onnx para compilar la app). |
| `prueba/` | Audio de prueba en español (VoxPopuli, CC0) con su transcripción de referencia. |
| `herramientas/` | `actualizar.py` (la revisión diaria) y `evaluar.py` (la prueba con sherpa-onnx). |
| `ATRIBUCIONES.md`, `licencias/` | Licencia y atribución de cada modelo y del audio de prueba. |

## Modelos

| Modelo | Para qué | Licencia |
|---|---|---|
| Parakeet TDT 0.6B v3 (int8) | voz a texto | CC BY 4.0 |
| Canary 180M flash (int8) | voz a texto forzado al español | CC BY 4.0 |
| Silero VAD | detector de voz | MIT |
| TitaNet small | huella de voz (separar hablantes) | Apache 2.0 |

## Cómo se actualiza

Todos los días (y a mano con *Run workflow*) corre `.github/workflows/actualizar.yml`:

1. **Copia propia:** comprueba que los 9 archivos del release vigente estén y coincidan con la ficha. Si falta uno,
   registra el evento `SIN_VIGENTE`.
2. **Origen:** mira si en Hugging Face o en los releases de sherpa-onnx hay una revisión nueva **del mismo modelo**.
   - Si el origen desapareció: se sigue con la copia propia (para eso existe). No hace falta avisar.
   - Si la revisión nueva ya no trae los mismos archivos: es un cambio de **familia**. Nunca se hace solo: queda
     `REQUIERE_PERSONA` (necesita código y una persona).
3. **Prueba:** si hay una revisión nueva, la baja y corre sherpa-onnx 2.0.1 (la misma versión que la app), con los
   mismos parámetros que la app, sobre el audio de `prueba/`, con el juego vigente y con el candidato:
   error de palabras de Parakeet y de Canary (48 frases), error de la cadena completa detector de voz + Parakeet,
   acierto del detector de voz, y separación de hablantes con un audio de dos voces.
4. **Decisión:** solo si **ninguna** métrica empeora, publica el release `modelos-v(N+1)` con los 9 archivos, verifica
   cada asset subido contra su huella y actualiza `modelos.json` (evento `MODELO_CAMBIO`). Si alguna empeora, deja la
   vigente y lo registra (evento `PRUEBA_FALLO`); ese candidato no se vuelve a probar.

El servidor de CIRCLE lee `modelos.json` y `estado.json` una vez por día, comprueba por su cuenta que los archivos
vigentes se puedan bajar, y avisa al Fundador solo cuando: cambió un modelo, la prueba de uno nuevo falló, o ya no hay
un modelo vigente descargable.

## Licencia de este repositorio

Los modelos y el audio tienen la licencia de su autor (ver `ATRIBUCIONES.md`). La ficha, el estado y las
herramientas, con licencia MIT (`LICENSE`).
