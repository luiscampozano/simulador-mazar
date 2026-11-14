"""DataLab Ec · llegada de tormentas SIGUIENDO CADA TORMENTA, en SOMBRA (Luis, 13 nov). NO cambia los avisos ni la página.

Por qué: el aviso "tormenta en camino" usa el movimiento por bloques de ~88 km entre dos imágenes de 30 min. Ese campo
sigue la masa de nubes de arriba (el yunque) y sale "a saltos" (píxeles enteros); el 13 nov a las 13:00 daba ~42 km/h
para una tormenta que, seguida imagen a imagen, avanzaba a ~24 km/h. Aquí se prueba la alternativa:
  - en las imágenes de hace 40, 20 y 0 min (salida/lluvia3d.json) se separan las nubes frías (≤ 225 K, ≥ 4 píxeles),
  - cada nube de ahora se empareja con la de hace 20 min con la que más se superpone (y esa con la de hace 40),
  - dos velocidades a comparar: por el CENTRO (ajuste lineal de 2–3 posiciones) y por la FORMA (corrimiento de su forma que mejor calza con lo frío de hace 20 (y 40) min); tendencia = cambio de área,
  - para cada punto PÚBLICO fijo (scripts/puntos_satelite.json) se extrapola cada píxel de la tormenta (≤ 215 K) con la
    velocidad de SU tormenta y se mira si pasa a ≤ 7 km en ≤ 2 h (misma regla que el aviso, otra velocidad).
Además (Luis, 13 nov), el NIVEL DE FUERZA de cada nube antes de llegar: tope, enfriamiento en 10 min y rayos (función
nivel(), regla fija), para verificarlo con los mm por hora de las estaciones.
Salida: salida/seguimiento_sombra.json (última) y salida/seguimiento_sombra_hist.json (48 h) para verificar después
contra las imágenes siguientes y contra el aviso actual.
Y (Luis, 13 nov, pestaña "Tormentas" de la página): salida/tormentas.json = TODAS las tormentas activas (tope ≤ 215 K) del
mar y del país en la última imagen: dónde está (respecto a la ciudad pública más cercana), área, tope, nivel de fuerza,
si crece, hacia dónde va y a qué velocidad, y las ciudades públicas que tendría en su camino en ≤ 2 h SI MANTIENE el
rumbo (extrapolación, no pronóstico). Solo lo observado y su extrapolación; ninguna ubicación privada."""
import base64, io, json, os, time
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy import ndimage

N, O, PASO, FILAS, COLS = 2.0, -82.0, 0.05, 150, 140
LAT = N - (np.arange(FILAS) + 0.5) * PASO
LON = O + (np.arange(COLS) + 0.5) * PASO
AQUI = os.path.dirname(os.path.abspath(__file__))
FRIO, TORMENTA, KM, HORAS = 225, 215, 7.0, 2.0


def cuadros():
    L = json.load(open("salida/lluvia3d.json"))
    out = []
    for c in sorted(L["cuadros"], key=lambda c: c["t"]):
        a = np.frombuffer(base64.b64decode(c["tb"]), np.uint8).reshape(FILAS, COLS)
        out.append((datetime.fromisoformat(c["t"]), np.where(a == 255, np.nan, a.astype(np.float32) + 150)))
    return out


def objetos(T):
    lab, n = ndimage.label(np.nan_to_num(T, nan=999) <= FRIO)
    tam = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
    return lab, [k + 1 for k in range(n) if tam[k] >= 4]


def centro(lab, k):
    i, j = np.nonzero(lab == k)
    return float(LAT[i].mean()), float(LON[j].mean()), len(i)


def pareja(lab_ahora, k, lab_antes, ids_antes):
    sup = lab_antes[lab_ahora == k]
    sup = sup[np.isin(sup, ids_antes)]
    if not len(sup): return None
    v, c = np.unique(sup, return_counts=True)
    return int(v[np.argmax(c)])


def desplazamiento(mask0, frio_antes, maxpx=6):
    """Desplazamiento (filas, columnas) de la nube entre la imagen anterior y la actual: el corrimiento de su forma que
    más se superpone con lo frío de antes. Más robusto que el centro, que salta cuando la nube crece o se une con otra."""
    i, j = np.nonzero(mask0)
    best, bd = -1, (0, 0)
    for di in range(-maxpx, maxpx + 1):
        for dj in range(-maxpx, maxpx + 1):
            ii, jj = i - di, j - dj
            ok = (ii >= 0) & (ii < FILAS) & (jj >= 0) & (jj < COLS)
            sc = frio_antes[ii[ok], jj[ok]].sum() - 0.02 * (di * di + dj * dj)   # leve preferencia por moverse poco
            if sc > best: best, bd = sc, (di, dj)
    return bd


def nivel(tmin, enfria, rayos):
    """Nivel de fuerza ANTES de que llegue (Luis, 13 nov), regla fija a priori (no ajustada a datos):
    'tormenta fuerte' = tope ≤ 205 K (−68 °C) y (≥ 10 rayos en 15 min o enfriándose ≥ 4 K en 10 min);
    'aguacero' = tope ≤ 215 K; 'lluvia' = el resto. Se verifica después con los mm por hora de las estaciones."""
    if tmin <= 205 and ((rayos or 0) >= 10 or (enfria is not None and enfria <= -4)): return "tormenta fuerte"
    return "aguacero" if tmin <= 215 else "lluvia"


def rayos_malla(t0):
    try:
        A = json.load(open("salida/ahora.json"))
        if A.get("imagen") != t0.isoformat() or (A.get("filas"), A.get("cols"), A.get("norte"), A.get("oeste"), A.get("paso")) != (FILAS, COLS, N, O, PASO):
            return None                                   # otra imagen u otra malla: sin rayos antes que rayos desalineados
        return np.frombuffer(base64.b64decode(A["rayos_u8"]), np.uint8).reshape(FILAS, COLS).astype(int)
    except Exception:
        return None


NUCLEO = 205.0    # K (≈ −68 °C): dentro de una tormenta, cada zona así de fría es un núcleo (Luis, 13 nov: "una sola con varios núcleos")


def nucleos_de(obj, T0, Tn, prev, RY, ciudades):
    """Núcleos de una tormenta: zonas conectadas con tope ≤ 205 K (≥ 3 píxeles ≈ 90 km²) dentro de la misma nube."""
    lab, n = ndimage.label(obj & (Tn <= NUCLEO))
    out = []
    for k in range(1, n + 1):
        m = lab == k
        if m.sum() < 3: continue
        i, j = np.nonzero(m)
        la, lo = float(LAT[i].mean()), float(LON[j].mean())
        tmin = float(np.nanmin(T0[m]))
        x = np.nanmean(T0[m] - prev[10][1][m]) if 10 in prev and np.isfinite(prev[10][1][m]).any() else np.nan
        enf = float(x) if np.isfinite(x) else None
        ry = int(RY[ndimage.binary_dilation(m, iterations=1)].sum()) if RY is not None else None
        dist = {c: float(np.hypot((lo - v[1]) * 111.2 * np.cos(np.radians(la)), (la - v[0]) * 111.2)) for c, v in ciudades.items()}
        c = min(dist, key=dist.get); d = dist[c]; cla, clo = ciudades[c]
        out.append({"la": round(la, 3), "lo": round(lo, 3), "tope_C": round(tmin - 273.15),
                    "area_km2": int(round(float(np.sum(111.2 * PASO * 111.2 * PASO * np.cos(np.radians(LAT[i])))) / 10) * 10),
                    "enfria_K_10min": None if enf is None else round(enf, 1),
                    "tendencia": None if enf is None else ("creciendo" if enf < -2 else "debilitándose" if enf > 2 else "estable"),
                    "rayos_15min": ry,
                    "donde": f"sobre {c}" if d < 8 else f"a {round(d)} km al {rumbo((lo - clo) * np.cos(np.radians(la)), la - cla, CORTO)} de {c}",
                    "_m": np.flatnonzero(m)})
    out.sort(key=lambda z: z["tope_C"])
    return out


RUMBOS = ["norte", "noreste", "este", "sureste", "sur", "suroeste", "oeste", "noroeste"]
CORTO = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def rumbo(de_este, de_norte, nombres=RUMBOS):
    return nombres[int(((np.degrees(np.arctan2(de_este, de_norte)) + 360) % 360 + 22.5) // 45) % 8]


ESTADO = "salida/tormentas_estado.json"
ORDEN_NIVEL = {"lluvia": 0, "aguacero": 1, "tormenta fuerte": 2}


def balance_dia(t0, out):
    """Tormentas del DÍA DE TORMENTA (06:00 → 06:00 de Ecuador; Luis, 13 nov: "ver las tormentas del día y el estado de
    ellas y luego se van borrando día a día"). Cada tormenta de ahora hereda el número de la del día con la que más se
    superpone en la imagen anterior (≤ 40 min antes); si no se superpone con ninguna, es nueva y recibe el siguiente
    número. Se guarda el estado (con la máscara de cada tormenta activa) en salida/tormentas_estado.json, que el robot
    publica para continuar en la siguiente corrida."""
    loc = t0 - timedelta(hours=5)
    dia = (loc - timedelta(hours=6)).date().isoformat()
    if os.path.exists(ESTADO):
        E = json.load(open(ESTADO))
    else:   # bucle recién arrancado: se sigue con lo publicado; si no se puede leer (salvo que no exista), no se pisa
        r = __import__("requests").get("https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/tormentas_estado.json", timeout=15)
        if r.status_code == 404: E = {}
        else: r.raise_for_status(); E = r.json()
    if E.get("dia") != dia:
        E = {"dia": dia, "tormentas": []}
    if E.get("imagen") == t0.isoformat():          # misma imagen ya procesada: no duplicar la pista
        hecho = True
    else:
        hecho = False
    previa = E.get("imagen")
    if previa and t0 < datetime.fromisoformat(previa):
        raise ValueError("imagen más antigua que la ya procesada")
    seguido = previa is not None and 0 < (t0 - datetime.fromisoformat(previa)).total_seconds() <= 40 * 60
    activas = [x for x in E["tormentas"] if x.get("activa") and x.get("_mask")]
    pares = []
    if seguido or hecho:
        for a, f in enumerate(out):
            fo = set(f["_obj"].tolist())
            for x in activas:
                ov = len(fo.intersection(x["_mask"]))
                if ov: pares.append((ov, a, x["id"]))
    pares.sort(reverse=True)
    usado_f, usado_x, asig = set(), set(), {}
    for ov, a, i in pares:                           # uno a uno, de mayor a menor superposición
        if a in usado_f or i in usado_x: continue
        asig[a] = i; usado_f.add(a); usado_x.add(i)
    por_id = {x["id"]: x for x in E["tormentas"]}
    hora = loc.strftime("%H:%M")
    for a, f in enumerate(out):
        if a in asig:
            x = por_id[asig[a]]
        else:
            x = {"id": max([y["id"] for y in E["tormentas"]] or [0]) + 1, "nace": hora, "nace_donde": f["donde"],
                 "ya_estaba": not (seguido or hecho),     # sin imagen anterior seguida: no sabemos cuándo nació
                 "nivel_max": f["nivel"], "tope_min_C": f["tope_C"], "area_max_km2": 0, "rayos_max_15min": None,
                 "encima": [], "pista": []}
            E["tormentas"].append(x); por_id[x["id"]] = x
        f["n"] = x["id"]
        # núcleos: cada uno hereda su letra del núcleo de la imagen anterior con el que más se superpone; si no, letra nueva
        ant = x.get("_nuc", []) if (seguido or hecho) else []
        par = sorted(((len(set(z["_m"].tolist()).intersection(a["m"])), zi, a["l"]) for zi, z in enumerate(f.get("nucleos", [])) for a in ant), reverse=True)
        uz, ul, letra = set(), set(), {}
        for ov, zi, l in par:
            if ov and zi not in uz and l not in ul: letra[zi] = l; uz.add(zi); ul.add(l)
        sig = x.get("letras", 0)
        for zi, z in enumerate(f.get("nucleos", [])):
            if zi not in letra:
                letra[zi] = "abcdefghijklmnopqrstuvwxyz"[sig % 26] + ("" if sig < 26 else str(sig // 26)); sig += 1
            z["letra"] = letra[zi]
        x["letras"] = sig
        x["_nuc"] = [{"l": z["letra"], "m": z["_m"].tolist()} for z in f.get("nucleos", [])]
        x["nucleos_max"] = max(x.get("nucleos_max", 0), len(f.get("nucleos", [])))
        x.update({"activa": True, "ultima": hora, "donde": f["donde"], "_mask": f["_obj"].tolist(), "falta": 0})
        if ORDEN_NIVEL.get(f["nivel"], 0) > ORDEN_NIVEL.get(x["nivel_max"], 0): x["nivel_max"] = f["nivel"]
        x["tope_min_C"] = min(x["tope_min_C"], f["tope_C"]); x["area_max_km2"] = max(x["area_max_km2"], f["area_km2"])
        if f.get("rayos_15min") is not None: x["rayos_max_15min"] = max(x["rayos_max_15min"] or 0, f["rayos_15min"])
        x["encima"] = sorted(set(x["encima"]) | set(f["encima"]))
        if not hecho: x["pista"].append([round(f["la"], 2), round(f["lo"], 2), hora])   # con la hora: la página anima el satélite con los números
    vistas = {f["n"] for f in out}
    for x in E["tormentas"]:      # sin pareja en esta imagen: se espera una imagen más (el tope puede rozar −58 °C) antes de darla por terminada
        if x["id"] not in vistas and x.get("activa") and not hecho:
            x["falta"] = x.get("falta", 0) + 1
            if x["falta"] >= 2 or not seguido:
                x["activa"] = False; x.pop("_mask", None); x.pop("falta", None); x.pop("_nuc", None)
    E["imagen"] = t0.isoformat()
    with open(ESTADO + ".tmp", "w") as fh:
        json.dump(E, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(ESTADO + ".tmp", ESTADO)
    pub = [{k: v for k, v in x.items() if k not in ("_mask", "falta", "_nuc", "letras")} for x in E["tormentas"]]
    return {"dia": dia, "desde": "06:00", "tormentas": pub}


def lista_tormentas(t0, T0, lab0, celdas, sin_rumbo, P, edad, prev, RY):
    """salida/tormentas.json para la pestaña Tormentas (Luis, 13 nov). Una fila por nube con tope ≤ 215 K."""
    ciudades = {c: (float(np.mean([p[1] for p in v])), float(np.mean([p[2] for p in v]))) for c, v in P.items()}
    Tn = np.nan_to_num(T0, nan=999)
    filas = [(c["k"], c, False) for c in celdas] + [(k, None, nueva) for k, nueva in sin_rumbo]
    out = []
    for k, c, es_nueva in filas:
        obj = lab0 == k
        tmin = float(np.nanmin(T0[obj]))
        if tmin > TORMENTA: continue
        nucleo = obj & (Tn <= TORMENTA)
        i, j = np.nonzero(nucleo)
        if len(i) < 2: continue
        la, lo = float(LAT[i].mean()), float(LON[j].mean())
        io_, jo = np.nonzero(obj)
        area = int(round(float(np.sum(111.2 * PASO * 111.2 * PASO * np.cos(np.radians(LAT[io_])))) / 10) * 10)
        dist = {n: float(np.hypot((lo - x[1]) * 111.2 * np.cos(np.radians(la)), (la - x[0]) * 111.2)) for n, x in ciudades.items()}
        cerca = min(dist, key=dist.get); dk = dist[cerca]; cla, clo = ciudades[cerca]
        donde = f"sobre {cerca}" if dk < 8 else f"a {round(dk)} km al {rumbo((lo - clo) * np.cos(np.radians(la)), la - cla, CORTO)} de {cerca}"
        if c is None:
            x = np.nanmean(T0[obj] - prev[10][1][obj]) if 10 in prev and np.isfinite(prev[10][1][obj]).any() else np.nan
            enfria = float(x) if np.isfinite(x) else None
            ry = int(RY[ndimage.binary_dilation(obj, iterations=1)].sum()) if RY is not None else None
        else:
            enfria = c["enfria"]
        tend = None if enfria is None else ("creciendo" if enfria < -2 else "debilitándose" if enfria > 2 else "estable")
        f = {"la": round(la, 3), "lo": round(lo, 3), "donde": donde, "area_km2": area, "tope_C": round(tmin - 273.15),
             "nivel": c["nivel"] if c else nivel(tmin, enfria, ry), "tendencia": tend,
             "enfria_K_10min": None if enfria is None else round(enfria, 1),
             "rayos_15min": c["rayos"] if c else ry, "nueva": es_nueva}
        encima, camino = [], []
        if c is not None and c["vel"] >= 5:
            f.update({"vel_kmh": round(c["vel"]), "va_hacia": rumbo(c["u"], c["v"]),
                      "vla": round(c["v"] / 111.2, 3), "vlo": round(c["u"] / (111.2 * np.cos(np.radians(la))), 3)})   # grados por hora
        pi, pj = c["px"] if c is not None else (i, j)
        for n, lista in P.items():
            mejor, sobre = None, False
            for _, pla, plo in lista:
                dx = (LON[pj] - plo) * 111.2 * np.cos(np.radians(pla)); dy = (LAT[pi] - pla) * 111.2
                d = np.hypot(dx, dy)
                if d.min() < 6: sobre = True; break
                if c is None or c["vel"] < 5 or d.min() > 150: continue
                t = -(dx * c["u"] + dy * c["v"]) / (c["vel"] ** 2)
                ok = (t > 0) & (t <= HORAS) & (np.hypot(dx + c["u"] * t, dy + c["v"] * t) <= KM)
                if ok.any():
                    m = max(0, round(float(t[ok].min() * 60 - edad)))
                    mejor = m if mejor is None else min(mejor, m)
            if sobre:
                encima.append(n)
            elif mejor is not None:
                camino.append([n, mejor])
        f["encima"] = encima
        f["_obj"] = np.flatnonzero(obj)
        try:
            f["nucleos"] = nucleos_de(obj, T0, Tn, prev, RY, ciudades)
        except Exception as e:      # los núcleos nunca dejan sin la lista
            print("núcleos falló:", repr(e)[:120]); f["nucleos"] = []
        f["camino"] = sorted(camino, key=lambda x: x[1])
        out.append(f)
    orden = {"tormenta fuerte": 0, "aguacero": 1, "lluvia": 2}
    out.sort(key=lambda f: (orden.get(f["nivel"], 3), f["tope_C"]))
    try:
        dia = balance_dia(t0, out)
    except Exception as e:      # el balance del día nunca deja sin la lista de ahora
        print("balance del día falló:", repr(e)[:200]); dia = None
        for n, f in enumerate(out, 1):
            f["n"] = n
            for zi, z in enumerate(f.get("nucleos", [])): z["letra"] = "abcdefghijklmnopqrstuvwxyz"[zi % 26]
    for f in out:
        f.pop("_obj", None)
        for z in f.get("nucleos", []): z.pop("_m", None)
    res = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "imagen": t0.isoformat(),
           "nota": "Tormentas activas (tope de nube ≤ 215 K = −58 °C) en la última imagen del GOES-19. 'camino': ciudades públicas "
                   "que la tormenta alcanzaría en ≤ 2 h si mantiene rumbo y velocidad (extrapolación, no pronóstico).",
           "ciudades": {n: [round(x[0], 3), round(x[1], 3)] for n, x in ciudades.items()},   # centro de los puntos públicos
           "tormentas": out, "dia": dia}
    with open("salida/tormentas.json.tmp", "w") as fh:
        json.dump(res, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace("salida/tormentas.json.tmp", "salida/tormentas.json")
    print(f"tormentas.json: {len(out)} tormentas activas")


def main():
    t_ini = time.time()
    C = cuadros()
    if len(C) < 5: print("seguimiento sombra: faltan imágenes"); return
    t0, T0 = C[-1]
    if (datetime.now(timezone.utc) - t0).total_seconds() > 35 * 60:
        print("seguimiento sombra: imagen vieja", t0.isoformat()); return
    prev = {round((t0 - c[0]).total_seconds() / 60 / 10) * 10: c for c in C[:-1]}
    if 20 not in prev: print("seguimiento sombra: falta la imagen de hace 20 min"); return
    RY = rayos_malla(t0)
    lab0, ids0 = objetos(T0)
    lab20, ids20 = objetos(prev[20][1])
    lab40, ids40 = objetos(prev[40][1]) if 40 in prev else (None, [])
    celdas, sin_rumbo = [], []
    for k in ids0:
        la0, lo0, n0 = centro(lab0, k)
        k20 = pareja(lab0, k, lab20, ids20)
        if k20 is None: sin_rumbo.append((k, True)); continue  # nació hace menos de 20 min: sin velocidad confiable
        la20, lo20, n20 = centro(lab20, k20)
        pts = [(-20.0, la20, lo20), (0.0, la0, lo0)]
        if lab40 is not None:
            k40 = pareja(lab20, k20, lab40, ids40)
            if k40 is not None:
                la40, lo40, _ = centro(lab40, k40); pts.insert(0, (-40.0, la40, lo40))
        tt = np.array([p[0] for p in pts]) / 60.0             # velocidad por el CENTRO (para comparar en sombra)
        uc = np.polyfit(tt, [p[2] for p in pts], 1)[0] * 111.2 * np.cos(np.radians(la0)); vc = np.polyfit(tt, [p[1] for p in pts], 1)[0] * 111.2
        if not (0.5 <= n0 / max(n20, 1) <= 2) or np.hypot(uc, vc) > 100: uc = vc = 0.0   # se unió o partió: el centro salta
        frio20 = np.nan_to_num(prev[20][1], nan=999) <= FRIO
        di, dj = desplazamiento(lab0 == k, frio20)          # en 20 min (filas hacia el sur, columnas hacia el este)
        if abs(di) == 6 or abs(dj) == 6: sin_rumbo.append((k, False)); continue   # tocó el borde de la búsqueda (≥ 100 km/h): no confiable
        u = dj * PASO * 111.2 * np.cos(np.radians(la0)) * 3; v = -di * PASO * 111.2 * 3   # km/h
        if 40 in prev:                                       # confirmar con hace 40 min (promedio de los dos tramos)
            frio40 = np.nan_to_num(prev[40][1], nan=999) <= FRIO
            di2, dj2 = desplazamiento(lab0 == k, frio40, 10)
            if abs(di2) < 10 and abs(dj2) < 10:
                u = (u + dj2 * PASO * 111.2 * np.cos(np.radians(la0)) * 1.5) / 2; v = (v - di2 * PASO * 111.2 * 1.5) / 2
        pix = np.nonzero((lab0 == k) & (np.nan_to_num(T0, nan=999) <= TORMENTA))   # una vez por nube
        obj = lab0 == k
        x = np.nanmean(T0[obj] - prev[10][1][obj]) if 10 in prev and np.isfinite(prev[10][1][obj]).any() else np.nan
        enfria = float(x) if np.isfinite(x) else None        # K en 10 min (< 0 = crece); None si no hay dato
        ry = int(RY[ndimage.binary_dilation(obj, iterations=1)].sum()) if RY is not None else None   # rayos en la nube y su borde
        tmin = float(np.nanmin(T0[obj]))
        celdas.append({"px": pix, "k": k, "u": float(u), "v": float(v), "vel": float(np.hypot(u, v)), "uc": float(uc), "vc": float(vc), "n": n0,
                       "crece": (n0 - n20) / max(n20, 1), "tmin": tmin, "puntos": len(pts),
                       "enfria": None if enfria is None else round(enfria, 1), "rayos": ry, "nivel": nivel(tmin, enfria, ry)})
    P = json.load(open(os.path.join(AQUI, "puntos_satelite.json")))
    edad = (datetime.now(timezone.utc) - t0).total_seconds() / 60
    llegadas = {}
    for ciudad, lista in P.items():
        filas = []
        for nombre, la, lo in lista:
            kmLon = 111.2 * np.cos(np.radians(la)); mejor = None
            for c in celdas:
                if c["tmin"] > TORMENTA or max(c["vel"], float(np.hypot(c["uc"], c["vc"]))) < 5: continue
                i, j = c["px"]
                dx = (LON[j] - lo) * kmLon; dy = (LAT[i] - la) * 111.2
                d = np.hypot(dx, dy)
                if d.min() < 6: mejor = {"min": 0, "encima": True, "nivel": c["nivel"], "tmin": round(c["tmin"]), "enfria": c["enfria"], "rayos": c["rayos"]}; break
                if d.min() > 150: continue
                def eta(u, v):
                    vel = np.hypot(u, v)
                    if vel < 5: return None
                    t = -(dx * u + dy * v) / (vel ** 2)
                    ok = (t > 0) & (t <= HORAS) & (np.hypot(dx + u * t, dy + v * t) <= KM)
                    return max(0, round(float(t[ok].min() * 60 - edad))) if ok.any() else None   # < 0 = llegando ya
                mf, mc = eta(c["u"], c["v"]), eta(c["uc"], c["vc"])
                m = min(x for x in (mf, mc, 9e9) if x is not None)
                if m < 9e9 and (mejor is None or m < mejor["min"]):
                    mejor = {"min": m, "min_forma": mf, "min_centro": mc, "vel": round(c["vel"]), "vel_centro": round(float(np.hypot(c["uc"], c["vc"]))),
                             "crece": round(c["crece"], 2), "puntos": c["puntos"], "nivel": c["nivel"], "tmin": round(c["tmin"]),
                             "enfria": c["enfria"], "rayos": c["rayos"]}
            if mejor: filas.append([nombre, mejor.get("min_forma"), mejor.get("vel"), mejor.get("min_centro"), mejor.get("vel_centro"),
                                    mejor.get("crece"), bool(mejor.get("encima")), mejor.get("nivel"), mejor.get("tmin"),
                                    mejor.get("enfria"), mejor.get("rayos")])
        if filas: llegadas[ciudad] = filas
    out = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "imagen": t0.isoformat(),
           "metodo": "seguimiento de cada nube ≤225 K (superposición entre imágenes de hace 40, 20 y 0 min), extrapolación de sus píxeles ≤215 K",
           "estado": "SOMBRA: no se usa en avisos ni en la página",
           "campos_punto": ["nombre", "min_por_forma", "vel_forma_kmh", "min_por_centro", "vel_centro_kmh", "cambio_de_area_20min", "encima",
                            "nivel", "tope_K", "enfriamiento_K_10min", "rayos_15min"],
           "celdas_seguidas": len(celdas), "segundos": round(time.time() - t_ini, 1), "llegadas": llegadas}
    try:
        lista_tormentas(t0, T0, lab0, celdas, sin_rumbo, P, edad, prev, RY)
    except Exception as e:      # la lista de la página nunca tumba el seguimiento en sombra
        print("tormentas.json falló:", repr(e)[:200])
    with open("salida/seguimiento_sombra.json.tmp", "w") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace("salida/seguimiento_sombra.json.tmp", "salida/seguimiento_sombra.json")
    F = "salida/seguimiento_sombra_hist.json"
    try:
        H = json.load(open(F)) if os.path.exists(F) else json.load(io.StringIO(__import__("requests").get(
            "https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/seguimiento_sombra_hist.json", timeout=8).text))
    except Exception:
        H = {"registros": []}
    lim = (t0 - timedelta(hours=48)).isoformat()
    reg = [r for r in H.get("registros", []) if r[0] >= lim and r[0] != t0.isoformat()]
    reg += [[t0.isoformat(), c] + f for c, fs in llegadas.items() for f in fs]
    imgs = sorted({i for i in H.get("imagenes_procesadas", []) if i >= lim} | {t0.isoformat()})
    with open(F + ".tmp", "w") as fh:
        json.dump({"campos": ["imagen", "ciudad", "punto", "min_forma", "vel_forma", "min_centro", "vel_centro", "cambio_area", "encima",
                                         "nivel", "tope_K", "enfria_K_10min", "rayos_15min"], "imagenes_procesadas": imgs,
                   "registros": reg}, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(F + ".tmp", F)
    print(f"seguimiento sombra {t0:%H:%M} UTC: {len(celdas)} nubes seguidas; {sum(len(v) for v in llegadas.values())} puntos con llegada; {out['segundos']} s")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:      # en sombra: nunca tumba al robot del satélite
        print("seguimiento sombra falló:", repr(e)[:200])
