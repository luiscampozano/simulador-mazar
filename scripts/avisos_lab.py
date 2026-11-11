"""DataLab Ec · laboratorio de los avisos de tormenta (Luis, 11 nov).

En cada imagen del satélite (cada 10 min) y para cada punto público de la página (ciudades y sectores de
puntos_satelite.json), cada VARIANTE estima si una nube de tormenta llegará al punto en ≤ 2 h (misma regla que el aviso al
celular: extrapolar el movimiento y ver si pasa a ≤ margen km). Luego se califica sola con las imágenes siguientes:
  - acierto: la "verdad" (celda ≤ 215 K a ≤ 7 km del punto) aparece entre 30 min antes y 30 min después de la hora estimada;
  - falsa alarma: no aparece;
  - sorpresa: aparece sin que la variante lo haya avisado en las 2 h y media anteriores.
Guarda salida/avisos_lab.json (se publica con ahora.json en la rama "satelite"). Solo puntos públicos; nunca suscriptores."""
import json, math, os
from datetime import datetime, timedelta, timezone

import numpy as np

VARIANTES = {   # nombre: (umbral K de la nube que se sigue, margen km de paso)
    "base_215K_7km": (215, 7.0),      # = la regla de los avisos publicados
    "tibia_220K_7km": (220, 7.0),
    "ancha_215K_10km": (215, 10.0),
}
VERDAD_K, VERDAD_KM, VENTANA_MIN, HORIZ_H = 215, 7.0, 30, 2.0
URL = "https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/avisos_lab.json"


def _puntos():
    P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "puntos_satelite.json"), encoding="utf-8"))
    return [(f"{c}|{nom}", la, lo) for c, ps in P.items() for nom, la, lo in ps]


def _celdas(T, umbral, N, O, PASO):
    i, j = np.nonzero(np.isfinite(T) & (T <= umbral))
    return N - (i + 0.5) * PASO, O + (j + 0.5) * PASO


def _vector_de(cla, clo, V):
    """Para cada celda: (u, v) del vector de movimiento más cercano a ≤ 70 km, o nan."""
    u = np.full(cla.shape, np.nan); v = np.full(cla.shape, np.nan)
    if not len(V) or not cla.size: return u, v
    V = np.asarray(V, float)
    kl = 111.2 * np.cos(np.radians(cla))[:, None]
    d = np.hypot((V[None, :, 1] - clo[:, None]) * kl, (V[None, :, 0] - cla[:, None]) * 111.2)
    k = d.argmin(1); ok = d[np.arange(len(k)), k] <= 70
    u[ok] = V[k[ok], 2]; v[ok] = V[k[ok], 3]
    return u, v


def llegada(cla, clo, cu, cv, la, lo, margen):
    """Minutos hasta que la primera celda que viene hacia el punto pase a ≤ margen km (≤ 2 h), o None."""
    if not cla.size: return None
    kl = 111.2 * math.cos(math.radians(la))
    dx, dy = (clo - lo) * kl, (cla - la) * 111.2
    dist = np.hypot(dx, dy); vel2 = cu * cu + cv * cv
    with np.errstate(invalid="ignore", divide="ignore"):
        t = -(dx * cu + dy * cv) / vel2
        dmin = np.hypot(dx + cu * t, dy + cv * t)
    ok = (dist >= 6) & (dist <= 90) & np.isfinite(t) & (vel2 >= 25) & (t > 0) & (t <= HORIZ_H) & (dmin <= margen)
    return float(t[ok].min() * 60) if ok.any() else None


def actualizar(T1, t1, vectores, N, O, PASO, SES=None):
    try:
        L = json.load(open("salida/avisos_lab.json")) if os.path.exists("salida/avisos_lab.json") else (SES.get(URL, timeout=30).json() if SES else {})
        assert isinstance(L.get("pend"), list)
    except Exception:
        L = {}
    L.setdefault("pend", []); L.setdefault("obs", {}); L.setdefault("emit", {}); L.setdefault("dias", {}); L.setdefault("casos", [])
    ti = t1.isoformat(timespec="minutes")
    if L.get("ultima") == ti: return L   # misma imagen: nada nuevo
    P = _puntos()
    dia = lambda t: (datetime.fromisoformat(t) - timedelta(hours=5)).strftime("%Y-%m-%d")
    def cuenta(t, v, campo, val=1):
        d = L["dias"].setdefault(dia(t), {}).setdefault(v, {"avisos": 0, "aciertos": 0, "falsas": 0, "sorpresas": 0, "err_abs_min": 0, "antic_min": 0})
        d[campo] += val
    # 1) verdad de esta imagen: ¿hay nube de tormenta a ≤ 7 km de cada punto?
    vla, vlo = _celdas(T1, VERDAD_K, N, O, PASO)
    hoy = {}
    for p, la, lo in P:
        kl = 111.2 * math.cos(math.radians(la))
        hoy[p] = bool(vla.size and (np.hypot((vlo - lo) * kl, (vla - la) * 111.2) <= VERDAD_KM).any())
    lim = (t1 - timedelta(hours=3)).isoformat(timespec="minutes")
    for p in hoy:
        prev = [e for e in L["obs"].get(p, []) if e[0] >= lim]
        antes = prev[-1][1] if prev else None
        if hoy[p] and antes is False:   # empieza la tormenta en el punto: ¿alguna variante lo había avisado?
            for v in VARIANTES:
                e = L["emit"].get(f"{v}|{p}")
                if not e or (t1 - datetime.fromisoformat(e)).total_seconds() > 150 * 60: cuenta(ti, v, "sorpresas")
        L["obs"][p] = prev + [[ti, hoy[p]]]
    # 2) calificar los avisos cuya ventana ya pasó
    quedan = []
    for a in L["pend"]:
        eta = datetime.fromisoformat(a["eta"])
        if t1 < eta + timedelta(minutes=VENTANA_MIN): quedan.append(a); continue
        ini, fin = (eta - timedelta(minutes=VENTANA_MIN)).isoformat(timespec="minutes"), (eta + timedelta(minutes=VENTANA_MIN)).isoformat(timespec="minutes")
        vistos = [e[0] for e in L["obs"].get(a["p"], []) if ini <= e[0] <= fin and e[1]]
        if vistos:
            err = (datetime.fromisoformat(vistos[0]) - eta).total_seconds() / 60
            cuenta(a["t"], a["v"], "aciertos"); cuenta(a["t"], a["v"], "err_abs_min", round(abs(err)))
            cuenta(a["t"], a["v"], "antic_min", round((datetime.fromisoformat(vistos[0]) - datetime.fromisoformat(a["t"])).total_seconds() / 60))
        else:
            cuenta(a["t"], a["v"], "falsas"); err = None
        L["casos"] = (L["casos"] + [dict(a, resultado="acierto" if vistos else "falsa", error_min=None if err is None else round(err))])[-300:]
    L["pend"] = quedan
    # 3) avisos nuevos de cada variante (uno por tormenta: si ya hay uno abierto para el punto, no se repite)
    abiertos = {(a["v"], a["p"]) for a in L["pend"]}
    for v, (umbral, margen) in VARIANTES.items():
        cla, clo = _celdas(T1, umbral, N, O, PASO)
        cu, cv = _vector_de(cla, clo, vectores or [])
        ok = np.isfinite(cu); cla, clo, cu, cv = cla[ok], clo[ok], cu[ok], cv[ok]
        for p, la, lo in P:
            if (v, p) in abiertos or hoy[p]: continue   # ya avisado, o la tormenta ya está ahí
            m = llegada(cla, clo, cu, cv, la, lo, margen)
            if m is None: continue
            L["pend"].append({"v": v, "p": p, "t": ti, "eta": (t1 + timedelta(minutes=m)).isoformat(timespec="minutes"), "min": round(m)})
            L["emit"][f"{v}|{p}"] = ti; cuenta(ti, v, "avisos")
    # 4) limpiar: emisiones de más de 6 h, días de más de 60
    lim6 = (t1 - timedelta(hours=6)).isoformat(timespec="minutes")
    L["emit"] = {k: e for k, e in L["emit"].items() if e >= lim6}
    L["dias"] = dict(sorted(L["dias"].items())[-60:])
    L.update({"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ultima": ti,
              "variantes": {v: {"umbral_K": u, "margen_km": m} for v, (u, m) in VARIANTES.items()},
              "regla": f"verdad = celda ≤ {VERDAD_K} K a ≤ {VERDAD_KM:g} km del punto; acierto si aparece ±{VENTANA_MIN} min de la hora estimada; sorpresa = empieza sin aviso en 2 h 30 min"})
    json.dump(L, open("salida/avisos_lab.json", "w"), ensure_ascii=False, separators=(",", ":"))
    hoyd = L["dias"].get(dia(ti), {})
    print("Avisos (lab):", " · ".join(f"{v.split('_')[0]} {d['avisos']}a/{d['aciertos']}✓/{d['falsas']}✗/{d['sorpresas']}!" for v, d in hoyd.items()) or "sin avisos hoy",
          f"· pendientes {len(L['pend'])}")
    return L
