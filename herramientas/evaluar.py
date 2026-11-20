"""Prueba de calidad de un juego de modelos de CIRCLE con sherpa-onnx.

Corre los mismos modelos y los mismos parametros que la app Android (Transcriptor.kt y Diarizador.kt) sobre el audio
de prueba de la carpeta prueba/ (VoxPopuli, CC0; nunca audio de Sesiones reales) y devuelve las metricas:

  asr_wer         error de palabras de Parakeet sobre 48 frases en espanol (menor es mejor)
  es_wer          error de palabras de Canary forzado al espanol sobre las mismas frases (menor es mejor)
  vad_f1          acierto del detector de voz (Silero) en el audio de dos voces, por tramos de 10 ms (mayor es mejor)
  voces_acierto   parte del tiempo de habla atribuida a la persona correcta en el audio de dos voces (mayor es mejor)
  voces_personas  cuantas personas distintas encontro (lo correcto es 2; se compara la distancia a 2)
  voces_separacion  parecido medio entre frases de la misma persona menos el parecido entre personas distintas (mayor es mejor)
  cadena_wer      error de palabras de la cadena completa (detector de voz + Parakeet) en el audio de dos voces

Uso: python evaluar.py <carpeta_con_las_piezas> <ficha.json> [salida.json]
La carpeta tiene las piezas con su ruta de la ficha (por ejemplo parakeet-v3/encoder.int8.onnx).
"""
import json
import os
import re
import sys
import time
import unicodedata

import numpy as np
import sherpa_onnx
import soundfile as sf

FRECUENCIA = 16000
AQUI = os.path.dirname(os.path.abspath(__file__))
PRUEBA = os.path.join(AQUI, '..', 'prueba')

# Lo que se compara entre el modelo vigente y el candidato: (metrica, 'menor' o 'mayor' es mejor)
CRITERIOS = [('asr_wer', 'menor'), ('es_wer', 'menor'), ('cadena_wer', 'menor'), ('vad_f1', 'mayor'),
             ('voces_acierto', 'mayor'), ('voces_error_personas', 'menor'), ('voces_separacion', 'mayor')]
# Que metricas mueve cada modelo (el resto se informa igual, pero no deberia cambiar)
METRICAS_DE = {
    'parakeet-v3': ['asr_wer', 'cadena_wer'],
    'canary-180m': ['es_wer'],
    'silero-vad': ['vad_f1', 'cadena_wer', 'voces_acierto', 'voces_error_personas'],
    'titanet-small': ['voces_acierto', 'voces_error_personas', 'voces_separacion'],
}
EPSILON = 1e-9  # solo redondeo de coma flotante: cualquier empeoramiento real rechaza al candidato


def normalizar(t):
    t = unicodedata.normalize('NFKD', t.lower())
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9' ]+", ' ', t)
    return t.split()


def distancia(a, b):
    """Distancia de edicion por palabras (sustituciones + borrados + inserciones)."""
    previa = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        fila = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            fila[j] = min(previa[j] + 1, fila[j - 1] + 1, previa[j - 1] + (x != y))
        previa = fila
    return previa[-1]


def leer(nombre):
    a, sr = sf.read(os.path.join(PRUEBA, nombre), dtype='float32')
    if a.ndim > 1:
        a = a.mean(axis=1)
    assert sr == FRECUENCIA, f'{nombre}: {sr} Hz'
    return a


def ruta(carpeta, ficha, clave):
    return os.path.join(carpeta, ficha['rutas'][clave])


def parakeet(carpeta, ficha):
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=ruta(carpeta, ficha, 'asr_encoder'), decoder=ruta(carpeta, ficha, 'asr_decoder'),
        joiner=ruta(carpeta, ficha, 'asr_joiner'), tokens=ruta(carpeta, ficha, 'asr_tokens'),
        model_type=ficha['rutas']['asr_tipo'], num_threads=4, sample_rate=FRECUENCIA, feature_dim=80)


def canary(carpeta, ficha):
    return sherpa_onnx.OfflineRecognizer.from_nemo_canary(
        encoder=ruta(carpeta, ficha, 'es_encoder'), decoder=ruta(carpeta, ficha, 'es_decoder'),
        tokens=ruta(carpeta, ficha, 'es_tokens'), src_lang='es', tgt_lang='es', num_threads=4,
        sample_rate=FRECUENCIA, feature_dim=128)


def transcribir(reconocedor, audio):
    s = reconocedor.create_stream()
    s.accept_waveform(FRECUENCIA, audio)
    reconocedor.decode_stream(s)
    return s.result.text.strip()


def wer(reconocedor, frases):
    errores = palabras = 0
    detalle = []
    for f in frases:
        hip = transcribir(reconocedor, leer(f['archivo']))
        ref = normalizar(f['texto'])
        e = distancia(ref, normalizar(hip))
        errores += e
        palabras += len(ref)
        detalle.append({'archivo': f['archivo'], 'errores': e, 'palabras': len(ref), 'texto': hip})
    return errores / max(palabras, 1), errores, palabras, detalle


def segmentos_vad(carpeta, ficha, audio):
    """Como Transcriptor.kt: Silero con umbral 0,5, silencio minimo 0,5 s, habla minima 0,25 s, maximo 25 s."""
    c = sherpa_onnx.VadModelConfig()
    c.silero_vad.model = ruta(carpeta, ficha, 'vad')
    c.silero_vad.threshold = 0.5
    c.silero_vad.min_silence_duration = 0.5
    c.silero_vad.min_speech_duration = 0.25
    c.silero_vad.window_size = 512
    c.silero_vad.max_speech_duration = 25
    c.sample_rate = FRECUENCIA
    c.num_threads = 1
    vad = sherpa_onnx.VoiceActivityDetector(c, buffer_size_in_seconds=120)
    salida = []
    for i in range(0, len(audio), 512):
        vad.accept_waveform(audio[i:i + 512])
        while not vad.empty():
            salida.append((vad.front.start, np.array(vad.front.samples, dtype='float32')))
            vad.pop()
    vad.flush()
    while not vad.empty():
        salida.append((vad.front.start, np.array(vad.front.samples, dtype='float32')))
        vad.pop()
    return salida


class Diarizador:
    """Copia del algoritmo de Diarizador.kt (umbral 0,5; frases de menos de 1 s no ajustan el centroide)."""
    UMBRAL, DURACION_MINIMA, MAXIMO = 0.5, 1.0, 10

    def __init__(self, extractor):
        self.extractor = extractor
        self.centroides = []

    def persona(self, frase):
        h = huella(self.extractor, frase)
        corta = len(frase) / FRECUENCIA < self.DURACION_MINIMA
        mejor, sim = -1, -1.0
        for i, c in enumerate(self.centroides):
            s = float(np.dot(h, c) / np.linalg.norm(c))
            if s > sim:
                mejor, sim = i, s
        if mejor >= 0 and (sim >= self.UMBRAL or corta or len(self.centroides) >= self.MAXIMO):
            if not corta:
                self.centroides[mejor] = self.centroides[mejor] + h
            return mejor
        self.centroides.append(h.copy())
        return len(self.centroides) - 1


def extractor_voces(carpeta, ficha):
    return sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=ruta(carpeta, ficha, 'voces'), num_threads=2))


def huella(extractor, audio):
    s = extractor.create_stream()
    s.accept_waveform(FRECUENCIA, audio)
    s.input_finished()
    h = np.array(extractor.compute(s), dtype='float64')
    return h / np.linalg.norm(h)


def evaluar(carpeta, ficha):
    refs = json.load(open(os.path.join(PRUEBA, 'referencias.json'), encoding='utf-8'))
    frases, dos = refs['frases'], refs['dos_voces']
    m = {}
    inicio = time.time()

    asr = parakeet(carpeta, ficha)
    m['asr_wer'], m['asr_errores'], m['asr_palabras'], m['asr_detalle'] = wer(asr, frases)
    es = canary(carpeta, ficha)
    m['es_wer'], m['es_errores'], m['es_palabras'], m['es_detalle'] = wer(es, frases)
    del es

    audio = leer(dos['archivo'])
    segs = segmentos_vad(carpeta, ficha, audio)
    # Detector de voz, por tramos de 10 ms, contra los tramos de habla conocidos
    n = len(audio) // 160
    ref = np.zeros(n, bool)
    for s in dos['segmentos']:
        ref[int(s['desde'] * 100):int(s['hasta'] * 100)] = True
    hip = np.zeros(n, bool)
    for desde, muestras in segs:
        hip[desde // 160:(desde + len(muestras)) // 160] = True
    vp = int((ref & hip).sum())
    precision, cobertura = vp / max(int(hip.sum()), 1), vp / max(int(ref.sum()), 1)
    m['vad_f1'] = 2 * precision * cobertura / max(precision + cobertura, 1e-12)
    m['vad_segmentos'] = len(segs)

    # Cadena completa: lo que la app hace con una Sesion
    texto = ' '.join(transcribir(asr, s) for _, s in segs)
    ref_txt = normalizar(' '.join(s['texto'] for s in dos['segmentos']))
    m['cadena_wer'] = distancia(ref_txt, normalizar(texto)) / max(len(ref_txt), 1)
    del asr

    # Separacion de hablantes, como la app: una persona por tramo del detector de voz
    ext = extractor_voces(carpeta, ficha)
    d = Diarizador(ext)
    tiempo = {}  # (persona, hablante real) -> segundos
    for desde, muestras in segs:
        p = d.persona(muestras)
        a, b = desde / FRECUENCIA, (desde + len(muestras)) / FRECUENCIA
        for s in dos['segmentos']:  # el tiempo de cada tramo se reparte segun quien hablaba de verdad
            o = min(b, s['hasta']) - max(a, s['desde'])
            if o > 0:
                tiempo[(p, s['hablante'])] = tiempo.get((p, s['hablante']), 0.0) + o
    personas = {p for p, _ in tiempo}
    bien = sum(max(tiempo.get((p, h), 0.0) for h in ('A', 'B')) for p in personas)
    total = sum(tiempo.values())
    m['voces_acierto'] = bien / max(total, 1e-12)
    m['voces_personas'] = len(d.centroides)
    m['voces_error_personas'] = abs(len(d.centroides) - 2)
    # Mismo hablante contra distintos, sobre las 48 frases (24 personas, 2 frases cada una)
    h = [huella(ext, leer(f['archivo'])) for f in frases]
    misma, distinta = [], []
    for i in range(len(frases)):
        for j in range(i + 1, len(frases)):
            (misma if frases[i]['hablante'] == frases[j]['hablante'] else distinta).append(float(np.dot(h[i], h[j])))
    m['voces_misma'] = float(np.mean(misma))
    m['voces_distinta'] = float(np.mean(distinta))
    m['voces_separacion'] = m['voces_misma'] - m['voces_distinta']
    m['segundos'] = round(time.time() - inicio, 1)
    return m


def comparar(vigente, candidato):
    """Devuelve (pasa, lista de diferencias). Pasa solo si ninguna metrica empeora."""
    difs, pasa = [], True
    for clave, mejor in CRITERIOS:
        v, c = vigente[clave], candidato[clave]
        peor = c > v + EPSILON if mejor == 'menor' else c < v - EPSILON
        if peor:
            pasa = False
        difs.append({'metrica': clave, 'vigente': round(v, 6), 'candidato': round(c, 6), 'empeora': peor})
    return pasa, difs


if __name__ == '__main__':
    carpeta, ficha = sys.argv[1], json.load(open(sys.argv[2], encoding='utf-8'))
    r = evaluar(carpeta, ficha)
    texto = json.dumps(r, ensure_ascii=False, indent=1)
    if len(sys.argv) > 3:
        open(sys.argv[3], 'w', encoding='utf-8').write(texto)
    print(json.dumps({k: v for k, v in r.items() if not k.endswith('_detalle')}, ensure_ascii=False, indent=1))
