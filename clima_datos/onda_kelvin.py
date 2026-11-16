"""DataLab Ec · seguimiento EN SOMBRA de la onda Kelvin fría (Luis, 16 nov: "¿esto apagará al Niño? ¿lo peor empieza en
diciembre o en enero?"). Solo registra; no se muestra en la página.

Qué es: una onda Kelvin "fría" (de surgencia) viaja por debajo del mar a lo largo del ecuador, de oeste a este. Al pasar,
sube la termoclina y el nivel del mar BAJA unos centímetros. Por eso se sigue con el NIVEL DEL MAR medido por satélite.
Dato: NOAA CoastWatch, altimetría combinada diaria (noaacwBLENDEDsshDaily, anomalía del nivel del mar "sla", 0,25°),
franja ecuatorial (0,125° S y N), cada 2° de longitud desde 180° hasta 80° O. Público, sin cuenta.

Método (CONGELADO el 16 nov, sin ajustar a nada):
  · suavizado de 7 días; cambio de cada longitud frente a 30 días antes (cm);
  · FRENTE FRÍO = la longitud más al este de la franja continua que empieza en el oeste (desde 180°) donde el nivel bajó
    ≥ 4 cm en 30 días (se permite 1 longitud suelta sin bajar, por ruido);
  · VELOCIDAD = recta de la posición del frente en los últimos 21 días (km/día; 1° de longitud ≈ 111 km en el ecuador);
  · LLEGADA ESTIMADA a 90° O (Galápagos) y a 82° O (costa del Ecuador) con esa velocidad, y también con la velocidad
    teórica de una onda Kelvin (2,4 m/s ≈ 207 km/día) como referencia;
  · también se guarda el cambio de 30 días en el extremo este (90–82° O): si sube, todavía llega agua caliente a la costa.
Verificación: cuando el nivel del mar en 90–82° O baje ≥ 4 cm en 30 días, se anota la fecha real y se compara con la
llegada que se estimó cada día antes (3 días seguidos bajo el umbral). Ojo: la "sla" incluye el ciclo de las estaciones del
año, así que una bajada de 4 cm puede ser estacional; y cuando el frente está quieto la velocidad medida no es fiable (la
teórica sirve de referencia). Es una medida indirecta (no mide temperatura bajo el agua); las boyas TAO están
caídas a ratos. Salida: registro/onda_kelvin.json"""
import json, math, os, time
from datetime import date, datetime, timedelta, timezone

import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
SAL = os.path.join(AQUI, "registro", "onda_kelvin.json")
URL = "https://coastwatch.noaa.gov/erddap/griddap/noaacwBLENDEDsshDaily.csv"
CAIDA_CM, DIAS_CAMBIO, DIAS_VEL, KELVIN_KM_DIA = 4.0, 30, 21, 207
KM_GRADO = 111.3
METAS = {"galapagos_90O": -90.0, "costa_82O": -82.0}


def bajar(desde, hasta):
    """{día: {lon: cm}} pidiendo por meses (el servidor rechaza pedidos grandes)."""
    S = {}
    a = desde
    while a <= hasta:
        b = min(hasta, (a.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1))
        fin = "last" if b == hasta else f"{b.isoformat()}T00:00:00Z"   # el último tramo hasta el último día publicado
        q = (f"?sla%5B({a.isoformat()}T00:00:00Z):1:({fin})%5D%5B(-0.125):1:(0.125)%5D"
             f"%5B(-179.875):8:(-80.125)%5D")
        for i in range(3):
            try:
                r = requests.get(URL + q, timeout=90)
                r.raise_for_status(); break
            except Exception:
                if i == 2: raise
                time.sleep(10)
        for ln in r.text.splitlines()[2:]:
            p = ln.split(",")
            if len(p) != 4: continue
            t, la, lo, v = p
            if v and v != "NaN":
                S.setdefault(t[:10], {}).setdefault(round(float(lo)), []).append(float(v) * 100)
        a = b + timedelta(days=1)
    return {d: {l: sum(v) / len(v) for l, v in L.items()} for d, L in S.items()}


def main():
    hoy = datetime.now(timezone.utc).date()
    M = bajar(hoy - timedelta(days=DIAS_CAMBIO + DIAS_VEL + 10), hoy - timedelta(days=1))
    dias = sorted(M)
    lons = sorted({l for d in M for l in M[d]})
    D = lambda d: date.fromisoformat(d)

    def sm(d, l):   # suavizado de 7 días del calendario, SOLO hacia atrás (d−6 … d): lo que se sabía ese día
        xs = [M.get((D(d) - timedelta(days=k)).isoformat(), {}).get(l) for k in range(7)]
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if len(xs) >= 4 else None

    def frente(d):
        ch = {}
        d0 = (D(d) - timedelta(days=DIAS_CAMBIO)).isoformat()
        for l in lons:
            a, b = sm(d, l), sm(d0, l)
            if a is not None and b is not None: ch[l] = round(a - b, 1)
        f, hueco = None, 0
        for l in lons:                       # de oeste a este
            if l not in ch: continue
            if ch[l] <= -CAIDA_CM:
                f, hueco = l, 0
            elif f is not None:
                hueco += 1
                if hueco > 1: break          # 2 longitudes seguidas sin bajar: ahí termina la franja fría
            elif l > lons[0] + 20:
                break                        # la franja debe empezar en el oeste (180°–160° O)
        return f, ch

    hist = []
    for d in dias:
        if D(d) - D(dias[0]) < timedelta(days=DIAS_CAMBIO + 6): continue
        f, ch = frente(d)
        hist.append((d, f, ch))
    d_hoy, f_hoy, ch_hoy = hist[-1] if hist else (None, None, {})
    pts = [(date.fromisoformat(d), f) for d, f, _ in hist[-DIAS_VEL:] if f is not None]
    vel = None
    if len(pts) >= 10:
        x0 = pts[0][0]
        xs = [(d - x0).days for d, _ in pts]; ys = [f for _, f in pts]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den: vel = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den * KM_GRADO   # km/día (positivo = hacia el este)
    llegadas = {}
    if f_hoy is not None:
        for k, lon in METAS.items():
            km = (lon - f_hoy) * KM_GRADO
            if km <= 0:
                llegadas[k] = {"km": 0, "ya_paso": True}; continue
            llegadas[k] = {"km": round(km),
                           "con_velocidad_medida": (date.fromisoformat(d_hoy) + timedelta(days=round(km / vel))).isoformat() if vel and vel > 20 else None,
                           "con_velocidad_teorica": (date.fromisoformat(d_hoy) + timedelta(days=round(km / KELVIN_KM_DIA))).isoformat()}
    este = [v for l, v in ch_hoy.items() if -90 <= l <= -82]
    R = json.load(open(SAL)) if os.path.exists(SAL) else {"diario": {}}
    if d_hoy:
        R["diario"].setdefault(d_hoy, {"frente_lon": f_hoy, "velocidad_km_dia": None if vel is None else round(vel),
                              "llegadas": llegadas, "cambio_30d_este_cm": round(sum(este) / len(este), 1) if este else None,
                              "cambio_30d_90O_cm": ch_hoy.get(-90)})   # la PRIMERA estimación de cada día queda congelada
        # llegada real: 3 días seguidos con el nivel bajando ≥ 4 cm en 30 días (90° O = Galápagos; promedio 90–82° O = costa)
        llego = R.get("llegada_real") or {}
        ult = [R["diario"][x] for x in sorted(R["diario"])[-3:]]
        for k, campo in (("galapagos_90O", "cambio_30d_90O_cm"), ("costa_82O", "cambio_30d_este_cm")):
            if k not in llego and len(ult) == 3 and all((u.get(campo) is not None and u[campo] <= -CAIDA_CM) for u in ult):
                llego[k] = sorted(R["diario"])[-3]
        R["llegada_real"] = llego
    R.update({"actualizado": datetime.now(timezone(timedelta(hours=-5))).isoformat(timespec="minutes"),
              "nota": __doc__.split("\n\n")[1][:1200] + "\n" + __doc__.split("\n\n")[2][:1400],
              "hoy": {"dia": d_hoy, "frente_lon": f_hoy, "velocidad_km_dia": None if vel is None else round(vel),
                      "llegadas": llegadas, "cambio_30d_cm_por_lon": ch_hoy},
              "serie_frente": [[d, f] for d, f, _ in hist]})
    os.makedirs(os.path.dirname(SAL), exist_ok=True)
    with open(SAL + ".tmp", "w") as fh:
        json.dump(R, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(SAL + ".tmp", SAL)
    print(f"Onda Kelvin fría {d_hoy}: frente en {f_hoy}° · velocidad {None if vel is None else round(vel)} km/día · "
          f"llegadas {json.dumps(llegadas)} · cambio 30 d en 90–82° O: {R['diario'].get(d_hoy, {}).get('cambio_30d_este_cm')} cm")


if __name__ == "__main__":
    main()
