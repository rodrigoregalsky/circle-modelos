"""Actualizacion diaria de los modelos de CIRCLE (la corre .github/workflows/actualizar.yml).

1. Comprueba que la copia propia (los assets del release vigente de este repositorio) siga entera: cada archivo con su
   tamano y su huella SHA-256 de la ficha (modelos.json).
2. Mira en el origen de cada modelo (Hugging Face o GitHub de sherpa-onnx) si hay una revision nueva del MISMO modelo,
   o si desaparecio. Si desaparecio, no pasa nada: los celulares siguen bajando de la copia propia.
3. Si hay una revision nueva: la baja, la prueba con sherpa-onnx contra la vigente (herramientas/evaluar.py) y solo si
   ninguna metrica empeora publica un release nuevo con los 9 archivos y actualiza la ficha. Si empeora, deja la vigente
   y lo registra. Un candidato rechazado no se vuelve a probar.
4. Un cambio de FAMILIA (otros archivos, otro tipo de modelo) nunca se hace solo: queda REQUIERE_PERSONA.
5. Deja estado.json legible. El servidor de CIRCLE lo lee y avisa al Fundador solo con los eventos MODELO_CAMBIO,
   PRUEBA_FALLO y SIN_VIGENTE.

Uso: python herramientas/actualizar.py [--sin-publicar]
Necesita GH_TOKEN (el GITHUB_TOKEN del workflow) y el comando gh. Nada mas: no hay secretos propios.
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.normpath(os.path.join(AQUI, '..'))
sys.path.insert(0, AQUI)
import evaluar  # noqa: E402

REPO = os.environ.get('GITHUB_REPOSITORY', 'rodrigoregalsky/circle-modelos')
FICHA = os.path.join(RAIZ, 'modelos.json')
ESTADO = os.path.join(RAIZ, 'estado.json')
AGENTE = 'circle-modelos-actualizador/1.0'
MAX_EVENTOS = 200
NOMBRE_METRICA = {'asr_wer': 'error de palabras', 'es_wer': 'error de palabras', 'vad_f1': 'acierto del detector de voz',
                  'voces_acierto': 'acierto de la separacion de hablantes'}
PRINCIPAL = {'parakeet-v3': 'asr_wer', 'canary-180m': 'es_wer', 'silero-vad': 'vad_f1', 'titanet-small': 'voces_acierto'}


def ahora():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


class NoExiste(Exception):
    pass


def pedir(url, json_=True, intentos=3):
    cab = {'User-Agent': AGENTE}
    if 'api.github.com' in url and os.environ.get('GH_TOKEN'):
        cab['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    ultimo = None
    for n in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=60) as r:
                datos = r.read()
                return json.loads(datos) if json_ else datos
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NoExiste(url)
            ultimo = e
        except Exception as e:  # red, tiempo de espera
            ultimo = e
        time.sleep(5 * (n + 1))
    raise RuntimeError(f'{url}: {ultimo}')


def bajar(url, destino, tamano=None, sha256=None):
    """Baja a un archivo y devuelve (tamano, sha256). Falla si no coincide con lo esperado."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    h = hashlib.sha256()
    n = 0
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': AGENTE})
            with urllib.request.urlopen(req, timeout=120) as r, open(destino, 'wb') as f:
                h, n = hashlib.sha256(), 0
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    n += len(b)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NoExiste(url)
            if intento == 2:
                raise
        except Exception:
            if intento == 2:
                raise
        time.sleep(10)
    huella = h.hexdigest()
    if tamano is not None and n != tamano:
        raise RuntimeError(f'{url}: llegaron {n} bytes, se esperaban {tamano}')
    if sha256 and huella != sha256:
        raise RuntimeError(f'{url}: la huella no coincide')
    return n, huella


def nombre_asset(archivo):
    return archivo.replace('/', '.')


# ───────────── La copia propia ─────────────

def assets_del_release(etiqueta):
    rel = pedir(f'https://api.github.com/repos/{REPO}/releases/tags/{etiqueta}')
    return {a['name']: a for a in rel.get('assets', [])}


def revisar_copia_propia(ficha):
    """Lista de problemas de la copia propia: [{archivo, detalle}]. Vacia si los 9 estan enteros."""
    problemas = []
    cache = {}
    for p in ficha['piezas']:
        etiqueta = p['url'].split('/releases/download/')[1].split('/')[0]
        try:
            if etiqueta not in cache:
                cache[etiqueta] = assets_del_release(etiqueta)
            a = cache[etiqueta].get(p['url'].rsplit('/', 1)[1])
        except NoExiste:
            a = None
        if not a:
            problemas.append({'archivo': p['archivo'], 'detalle': f'no esta en el release {etiqueta}'})
            continue
        digest = (a.get('digest') or '').removeprefix('sha256:')
        if a['size'] != p['tamano'] or (digest and digest != p['sha256']):
            problemas.append({'archivo': p['archivo'], 'detalle': f'el archivo del release {etiqueta} no coincide con la ficha'})
    return problemas


# ───────────── El origen ─────────────

def revisar_origen(modelo, piezas):
    """Devuelve {estado, detalle, candidato?}. estado: SIN_CAMBIOS, CANDIDATO, ORIGEN_DESAPARECIDO, REQUIERE_PERSONA,
    ORIGEN_SIN_RESPUESTA. candidato: {firma, revision, piezas: {archivo: {url, tamano, sha256 o None}}}."""
    o = modelo['origen']
    try:
        if o['sitio'] == 'HF':
            info = pedir(f"https://huggingface.co/api/models/{o['repo']}")
            cabeza = info.get('sha')
            if not cabeza:
                return {'estado': 'ORIGEN_SIN_RESPUESTA', 'detalle': 'Hugging Face no informa la revision'}
            arbol = {x['path']: x for x in pedir(f"https://huggingface.co/api/models/{o['repo']}/tree/{cabeza}?recursive=true")}
            nuevas, cambia = {}, False
            for p in piezas:
                x = arbol.get(p['origen'])
                if not x:
                    return {'estado': 'REQUIERE_PERSONA', 'detalle': f"la revision {cabeza[:10]} ya no trae {p['origen']}: "
                            'cambio de familia, necesita codigo y una persona', 'revision_vista': cabeza}
                tam = (x.get('lfs') or {}).get('size', x.get('size'))
                sha = (x.get('lfs') or {}).get('oid')
                url = f"https://huggingface.co/{o['repo']}/resolve/{cabeza}/{p['origen']}"
                if sha is None:  # no es LFS (tokens.txt): chico, se baja para saber su huella
                    tam, sha = bajar(url, os.path.join(tempfile.mkdtemp(), 'x'))
                if tam != p['tamano'] or sha != p['sha256']:
                    cambia = True
                nuevas[p['archivo']] = {'url': url, 'tamano': tam, 'sha256': sha}
            if not cambia:
                return {'estado': 'SIN_CAMBIOS', 'detalle': f"la revision {cabeza[:10]} trae los mismos archivos", 'revision_vista': cabeza}
            firma = hashlib.sha256(json.dumps(nuevas, sort_keys=True).encode()).hexdigest()
            return {'estado': 'CANDIDATO', 'detalle': f"revision nueva {cabeza[:10]} en Hugging Face",
                    'candidato': {'firma': firma, 'revision': cabeza, 'piezas': nuevas}}
        # GitHub (releases de k2-fsa/sherpa-onnx)
        rel = pedir(f"https://api.github.com/repos/{o['repo']}/releases/tags/{o['etiqueta']}")
        assets = {a['name']: a for a in rel.get('assets', [])}
        nuevas, cambia = {}, False
        for p in piezas:
            a = assets.get(p['origen'])
            if not a:
                return {'estado': 'ORIGEN_DESAPARECIDO', 'detalle': f"{p['origen']} ya no esta en el release {o['etiqueta']}; "
                        'se sigue con la copia propia'}
            sha = (a.get('digest') or '').removeprefix('sha256:') or None
            cambio_aqui = a['size'] != p['tamano'] or (sha and sha != p['sha256']) or \
                (not sha and a.get('updated_at') != p.get('origen_actualizado'))
            if cambio_aqui and not sha:  # sin huella publicada: se baja para saber si de verdad cambio
                _, sha = bajar(a['browser_download_url'], os.path.join(tempfile.mkdtemp(), 'x'), a['size'])
                cambio_aqui = sha != p['sha256'] or a['size'] != p['tamano']
            cambia = cambia or bool(cambio_aqui)
            nuevas[p['archivo']] = {'url': a['browser_download_url'], 'tamano': a['size'], 'sha256': sha,
                                    'origen_actualizado': a.get('updated_at')}
        if not cambia:
            return {'estado': 'SIN_CAMBIOS', 'detalle': 'el release de origen trae los mismos archivos'}
        firma = hashlib.sha256(json.dumps({k: (v['tamano'], v['sha256']) for k, v in nuevas.items()}, sort_keys=True).encode()).hexdigest()
        return {'estado': 'CANDIDATO', 'detalle': f"archivo nuevo en el release {o['etiqueta']} de {o['repo']}",
                'candidato': {'firma': firma, 'revision': None, 'piezas': nuevas}}
    except NoExiste:
        return {'estado': 'ORIGEN_DESAPARECIDO', 'detalle': 'el origen ya no existe (404); se sigue con la copia propia'}
    except Exception as e:
        return {'estado': 'ORIGEN_SIN_RESPUESTA', 'detalle': str(e)[:300]}


# ───────────── Pruebas y publicacion ─────────────

def armar(ficha, carpeta, base=None, reemplazos=None):
    """Arma en `carpeta` el juego completo: copia de `base` (o baja de la ficha) y reemplaza piezas del candidato."""
    reemplazos = reemplazos or {}
    for p in ficha['piezas']:
        destino = os.path.join(carpeta, p['archivo'])
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        if p['archivo'] in reemplazos:
            r = reemplazos[p['archivo']]
            tam, sha = bajar(r['url'], destino, r['tamano'], r['sha256'])
            r['sha256'] = sha
        elif base:
            shutil.copyfile(os.path.join(base, p['archivo']), destino)
        else:
            bajar(p['url'], destino, p['tamano'], p['sha256'])


def resumen(difs, modelo_id):
    principal = PRINCIPAL[modelo_id]
    d = next(x for x in difs if x['metrica'] == principal)
    return {'metrica': principal, 'nombre': NOMBRE_METRICA[principal], 'vigente': d['vigente'], 'candidato': d['candidato'],
            'porcentaje': True}


def publicar(ficha, carpeta, version, notas):
    etiqueta = f'modelos-v{version}'
    archivos = []
    for p in ficha['piezas']:
        dst = os.path.join(carpeta, '_assets', nombre_asset(p['archivo']))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(carpeta, p['archivo']), dst)
        archivos.append(dst)
    subprocess.run(['gh', 'release', 'create', etiqueta, '--repo', REPO, '--title', f'Modelos v{version}',
                    '--notes', notas, *archivos], check=True)
    # Despues de subir: cada asset tiene que coincidir con la ficha (GitHub calcula la huella del lado del servidor)
    for _ in range(10):
        assets = assets_del_release(etiqueta)
        if all(nombre_asset(p['archivo']) in assets for p in ficha['piezas']):
            break
        time.sleep(10)
    for p in ficha['piezas']:
        a = assets[nombre_asset(p['archivo'])]
        digest = (a.get('digest') or '').removeprefix('sha256:')
        if a['size'] != p['tamano'] or (digest and digest != p['sha256']):
            raise RuntimeError(f"{p['archivo']}: el asset subido no coincide con la ficha")
        p['url'] = f'https://github.com/{REPO}/releases/download/{etiqueta}/{nombre_asset(p["archivo"])}'
    return etiqueta


def main():
    sin_publicar = '--sin-publicar' in sys.argv
    ficha = json.load(open(FICHA, encoding='utf-8'))
    estado = json.load(open(ESTADO, encoding='utf-8')) if os.path.exists(ESTADO) else {}
    eventos = estado.get('eventos', [])
    rechazados = estado.get('rechazados', {})  # modelo -> [firmas]
    hoy = ahora()

    def evento(tipo, modelo=None, detalle='', prueba=None, eid=None):
        eid = eid or f"{tipo}:{modelo['id'] if modelo else '-'}:{hoy}"
        if any(e['id'] == eid for e in eventos):
            return
        eventos.append({'id': eid, 'tipo': tipo, 'fecha': hoy, 'modelo': modelo['id'] if modelo else None,
                        'nombre': modelo['nombre'] if modelo else None, 'detalle': detalle, 'prueba': prueba,
                        'version': ficha['version']})

    resultado = {'revisado_en': hoy, 'version': ficha['version'], 'release': ficha['release'], 'modelos': []}
    copia = revisar_copia_propia(ficha)
    resultado['vigente_descargable'] = not copia
    resultado['copia_propia'] = copia or 'los 9 archivos coinciden con la ficha'
    if copia:
        evento('SIN_VIGENTE', detalle='; '.join(f"{x['archivo']}: {x['detalle']}" for x in copia)[:400],
               eid='SIN_VIGENTE:' + hashlib.sha256(json.dumps(copia, sort_keys=True).encode()).hexdigest()[:16])

    candidatos = []
    for m in ficha['modelos']:
        piezas = [p for p in ficha['piezas'] if p['modelo'] == m['id']]
        r = revisar_origen(m, piezas)
        fila = {'id': m['id'], 'nombre': m['nombre'], 'estado': r['estado'], 'detalle': r['detalle']}
        if r['estado'] == 'CANDIDATO':
            if r['candidato']['firma'] in rechazados.get(m['id'], []):
                fila['estado'], fila['detalle'] = 'CANDIDATO_YA_RECHAZADO', r['detalle'] + '; ya se probo y empeoraba: se mantiene la vigente'
            else:
                candidatos.append((m, r['candidato'], fila))
        resultado['modelos'].append(fila)

    if candidatos and not copia:
        trabajo = tempfile.mkdtemp(prefix='modelos-')
        vig = os.path.join(trabajo, 'vigente')
        armar(ficha, vig)
        m_vig = evaluar.evaluar(vig, ficha)
        resultado['prueba_vigente'] = {k: v for k, v in m_vig.items() if not k.endswith('_detalle')}
        aceptados = []
        for m, cand, fila in candidatos:
            carpeta = os.path.join(trabajo, m['id'])
            try:
                armar(ficha, carpeta, base=vig, reemplazos=cand['piezas'])
                m_c = evaluar.evaluar(carpeta, ficha)
            except Exception as e:
                fila['estado'], fila['detalle'] = 'CANDIDATO_FALLO', f'el candidato no se pudo bajar o no corrio: {str(e)[:200]}'
                rechazados.setdefault(m['id'], []).append(cand['firma'])
                evento('PRUEBA_FALLO', m, fila['detalle'], eid=f"PRUEBA_FALLO:{m['id']}:{cand['firma'][:16]}")
                continue
            pasa, difs = evaluar.comparar(m_vig, m_c)
            fila['prueba'] = difs
            if pasa:
                fila['estado'] = 'CANDIDATO_APROBADO'
                aceptados.append((m, cand, fila, difs, carpeta))
            else:
                fila['estado'] = 'CANDIDATO_RECHAZADO'
                fila['detalle'] += '; la prueba dio peor: se mantiene la vigente'
                rechazados.setdefault(m['id'], []).append(cand['firma'])
                evento('PRUEBA_FALLO', m, fila['detalle'], resumen(difs, m['id']), eid=f"PRUEBA_FALLO:{m['id']}:{cand['firma'][:16]}")
        if aceptados and not sin_publicar:
            final = os.path.join(trabajo, 'final')
            reemplazos = {}
            for _, cand, *_ in aceptados:
                reemplazos.update(cand['piezas'])
            if len(aceptados) == 1:
                final = aceptados[0][4]
            else:  # varios a la vez: el juego combinado tambien tiene que no empeorar
                armar(ficha, final, base=vig, reemplazos=reemplazos)
                pasa, _ = evaluar.comparar(m_vig, evaluar.evaluar(final, ficha))
                if not pasa:
                    for m, cand, fila, *_ in aceptados:
                        fila['estado'], fila['detalle'] = 'ESPERA', 'aprobado solo, pero junto con otro empeoraba: se prueba de a uno'
                    aceptados, reemplazos = aceptados[:1], dict(aceptados[0][1]['piezas'])
                    final = aceptados[0][4]
            nueva = json.loads(json.dumps(ficha))
            nueva['version'] = ficha['version'] + 1
            for p in nueva['piezas']:
                if p['archivo'] in reemplazos:
                    r = reemplazos[p['archivo']]
                    p['tamano'], p['sha256'] = r['tamano'], r['sha256']
                    if r.get('origen_actualizado'):
                        p['origen_actualizado'] = r['origen_actualizado']
            for m, cand, *_ in aceptados:
                mm = next(x for x in nueva['modelos'] if x['id'] == m['id'])
                if cand['revision']:
                    mm['origen']['revision'] = cand['revision']
            notas = 'Actualizacion automatica despues de la prueba (ninguna metrica empeoro): ' + \
                    ', '.join(m['nombre'] for m, *_ in aceptados) + '. Licencias y atribuciones: ver ATRIBUCIONES.md.'
            etiqueta = publicar(nueva, final, nueva['version'], notas)
            nueva['release'] = etiqueta
            nueva['publicado'] = hoy[:10]
            json.dump(nueva, open(FICHA, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            ficha = nueva
            resultado['version'], resultado['release'] = nueva['version'], etiqueta
            for m, cand, fila, difs, _ in aceptados:
                fila['estado'] = 'ACTUALIZADO'
                fila['detalle'] += f'; aprobado y publicado en {etiqueta}'
                evento('MODELO_CAMBIO', m, fila['detalle'], resumen(difs, m['id']), eid=f"MODELO_CAMBIO:{m['id']}:{cand['firma'][:16]}")
        shutil.rmtree(trabajo, ignore_errors=True)
    elif candidatos:
        for _, _, fila in candidatos:
            fila['detalle'] += '; no se prueba: la copia vigente no esta entera'

    hay_algo = [f for f in resultado['modelos'] if f['estado'] not in ('SIN_CAMBIOS',)]
    resultado['resumen'] = ('todo vigente, sin cambios' if not hay_algo and not copia else
                            '; '.join(f"{f['nombre']}: {f['estado']}" for f in hay_algo) or 'la copia propia tiene problemas')
    resultado['eventos'] = eventos[-MAX_EVENTOS:]
    resultado['rechazados'] = rechazados
    json.dump(resultado, open(ESTADO, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in resultado.items() if k not in ('eventos', 'rechazados')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
