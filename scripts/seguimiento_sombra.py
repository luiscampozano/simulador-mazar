"""DataLab Ec · llegada de tormentas SIGUIENDO CADA TORMENTA, en SOMBRA (Luis, 13 nov). NO cambia los avisos ni la página.

Por qué: el aviso "tormenta en camino" usa el movimiento por bloques de ~88 km entre dos imágenes de 30 min. Ese campo
sigue la masa de nubes de arriba (el yunque) y sale "a saltos" (píxeles enteros); el 13 nov a las 13:00 daba ~42 km/h
para una tormenta que, seguida imagen a imagen, avanzaba a ~24 km/h. Aquí se prueba la alternativa:
  - en las imágenes de hace 40, 20 y 0 min (salida/lluvia3d.json) se separan las nubes frías (≤ 225 K, ≥ 4 píxeles),
  - cada nube de ahora se empareja con la de hace 20 min con la que más se superpone (y esa con la de hace 40),
  - dos velocidades a comparar: por el CENTRO (ajuste lineal de 2–3 posiciones) y por la FORMA (corrimiento de su forma que mejor calza con lo frío de hace 20 (y 40) min); tendencia = cambio de área,
  - para cada punto PÚBLICO fijo (scripts/puntos_satelite.json) se extrapola cada píxel de la tormenta (≤ 215 K) con la
    velocidad de SU tormenta y se mira si pasa a ≤ 7 km en ≤ 2 h (misma regla que el aviso, otra velocidad).
Salida: salida/seguimiento_sombra.json (última) y salida/seguimiento_sombra_hist.json (48 h) para verificar después
contra las imágenes siguientes y contra el aviso actual."""
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


def main():
    t_ini = time.time()
    C = cuadros()
    if len(C) < 5: print("seguimiento sombra: faltan imágenes"); return
    t0, T0 = C[-1]
    if (datetime.now(timezone.utc) - t0).total_seconds() > 35 * 60:
        print("seguimiento sombra: imagen vieja", t0.isoformat()); return
    prev = {round((t0 - c[0]).total_seconds() / 60 / 10) * 10: c for c in C[:-1]}
    if 20 not in prev: print("seguimiento sombra: falta la imagen de hace 20 min"); return
    lab0, ids0 = objetos(T0)
    lab20, ids20 = objetos(prev[20][1])
    lab40, ids40 = objetos(prev[40][1]) if 40 in prev else (None, [])
    celdas = []
    for k in ids0:
        la0, lo0, n0 = centro(lab0, k)
        k20 = pareja(lab0, k, lab20, ids20)
        if k20 is None: continue                       # nació hace menos de 20 min: sin velocidad confiable
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
        if abs(di) == 6 or abs(dj) == 6: continue          # tocó el borde de la búsqueda (≥ 100 km/h): no confiable
        u = dj * PASO * 111.2 * np.cos(np.radians(la0)) * 3; v = -di * PASO * 111.2 * 3   # km/h
        if 40 in prev:                                       # confirmar con hace 40 min (promedio de los dos tramos)
            frio40 = np.nan_to_num(prev[40][1], nan=999) <= FRIO
            di2, dj2 = desplazamiento(lab0 == k, frio40, 10)
            if abs(di2) < 10 and abs(dj2) < 10:
                u = (u + dj2 * PASO * 111.2 * np.cos(np.radians(la0)) * 1.5) / 2; v = (v - di2 * PASO * 111.2 * 1.5) / 2
        celdas.append({"k": k, "u": float(u), "v": float(v), "vel": float(np.hypot(u, v)), "uc": float(uc), "vc": float(vc), "n": n0,
                       "crece": (n0 - n20) / max(n20, 1), "tmin": float(np.nanmin(T0[lab0 == k])), "puntos": len(pts)})
    P = json.load(open(os.path.join(AQUI, "puntos_satelite.json")))
    edad = (datetime.now(timezone.utc) - t0).total_seconds() / 60
    llegadas = {}
    for ciudad, lista in P.items():
        filas = []
        for nombre, la, lo in lista:
            kmLon = 111.2 * np.cos(np.radians(la)); mejor = None
            for c in celdas:
                if c["tmin"] > TORMENTA or c["vel"] < 5: continue
                i, j = np.nonzero((lab0 == c["k"]) & (np.nan_to_num(T0, nan=999) <= TORMENTA))
                dx = (LON[j] - lo) * kmLon; dy = (LAT[i] - la) * 111.2
                d = np.hypot(dx, dy)
                if d.min() < 6: mejor = {"min": 0, "encima": True}; break
                if d.min() > 150: continue
                def eta(u, v):
                    vel = np.hypot(u, v)
                    if vel < 5: return None
                    t = -(dx * u + dy * v) / (vel ** 2)
                    ok = (t > 0) & (t <= HORAS) & (np.hypot(dx + u * t, dy + v * t) <= KM)
                    return round(float(t[ok].min() * 60 - edad)) if ok.any() else None
                mf, mc = eta(c["u"], c["v"]), eta(c["uc"], c["vc"])
                m = min(x for x in (mf, mc, 9e9) if x is not None)
                if m < 9e9 and (mejor is None or m < mejor["min"]):
                    mejor = {"min": m, "min_forma": mf, "min_centro": mc, "vel": round(c["vel"]), "vel_centro": round(float(np.hypot(c["uc"], c["vc"]))),
                             "crece": round(c["crece"], 2), "puntos": c["puntos"]}
            if mejor: filas.append([nombre, mejor.get("min_forma"), mejor.get("vel"), mejor.get("min_centro"), mejor.get("vel_centro"),
                                    mejor.get("crece"), bool(mejor.get("encima"))])
        if filas: llegadas[ciudad] = filas
    out = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "imagen": t0.isoformat(),
           "metodo": "seguimiento de cada nube ≤225 K (superposición entre imágenes de hace 40, 20 y 0 min), extrapolación de sus píxeles ≤215 K",
           "estado": "SOMBRA: no se usa en avisos ni en la página",
           "campos_punto": ["nombre", "min_por_forma", "vel_forma_kmh", "min_por_centro", "vel_centro_kmh", "cambio_de_area_20min", "encima"],
           "celdas_seguidas": len(celdas), "segundos": round(time.time() - t_ini, 1), "llegadas": llegadas}
    with open("salida/seguimiento_sombra.json.tmp", "w") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace("salida/seguimiento_sombra.json.tmp", "salida/seguimiento_sombra.json")
    F = "salida/seguimiento_sombra_hist.json"
    try:
        H = json.load(open(F)) if os.path.exists(F) else json.load(io.StringIO(__import__("requests").get(
            "https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/seguimiento_sombra_hist.json", timeout=30).text))
    except Exception:
        H = {"registros": []}
    lim = (t0 - timedelta(hours=48)).isoformat()
    reg = [r for r in H.get("registros", []) if r[0] >= lim and r[0] != t0.isoformat()]
    reg += [[t0.isoformat(), c] + f for c, fs in llegadas.items() for f in fs]
    imgs = sorted({i for i in H.get("imagenes_procesadas", []) if i >= lim} | {t0.isoformat()})
    with open(F + ".tmp", "w") as fh:
        json.dump({"campos": ["imagen", "ciudad", "punto", "min_forma", "vel_forma", "min_centro", "vel_centro", "cambio_area", "encima"], "imagenes_procesadas": imgs,
                   "registros": reg}, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(F + ".tmp", F)
    print(f"seguimiento sombra {t0:%H:%M} UTC: {len(celdas)} nubes seguidas; {sum(len(v) for v in llegadas.values())} puntos con llegada; {out['segundos']} s")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:      # en sombra: nunca tumba al robot del satélite
        print("seguimiento sombra falló:", repr(e)[:200])
