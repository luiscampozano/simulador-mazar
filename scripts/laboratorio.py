"""Laboratorio en sombra del modelo de Mazar.

En cada corrida del robot (cada 2 h) se calcula, con los MISMOS datos, la trayectoria del modelo titular y la de cada
modelo candidato (una variante: otra forma de tratar el río Coca, sin autoajuste, etc.). Nada de esto cambia la página:
solo se guarda en laboratorio/ y se compara después con la cota real de Celec a la misma hora.

Regla de reemplazo (laboratorio/config.json):
  - un candidato "listo" le gana al titular a 1 día con al menos `mejora_min` (10 %) durante `dias_min` días con
    datos, y no empeora a 3 ni a 7 días más de `tolerancia` (5 %/10 %);
  - si `promocion_automatica` es true y el candidato es de promoción "auto", pasa a titular solo (se anota en
    laboratorio/historial.json y el auditor avisa a Luis). Los de promoción "luis" (cambian la metodología del
    número grande) siempre esperan su visto bueno.
  - el titular anterior queda en sombra: si durante 3 días vuelve a ganar, se revierte solo.

Cada candidato es una función que recibe copias de P y ctx (las mismas entradas de simular_py) y el bloque `mod`, y
devuelve (P, ctx, cambios_mod): cambios_mod son los campos de datos.json que hay que publicar si se vuelve titular,
para que la página (modelo.js) haga exactamente el mismo cálculo (paridad sin tocar modelo.js).
"""
import json
import math
import os
from datetime import datetime, timedelta

DIR = "laboratorio"
F_CONF = os.path.join(DIR, "config.json")
F_PRED = os.path.join(DIR, "predicciones.json")
F_MARC = os.path.join(DIR, "marcador.json")
F_TIT = os.path.join(DIR, "titular.json")
F_HIST = os.path.join(DIR, "historial.json")
HORIZ = (1, 2, 3, 5, 7, 10, 14)
HORIZ_REGION = 30   # días de la trayectoria completa que se guarda de la última corrida

CONF_DEF = {"promocion_automatica": True, "activar_desde": "2026-10-31", "dias_min": 7, "casos_min": 40, "mejora_min": 0.10,
            "tolerancia_3d": 0.05, "tolerancia_7d": 0.05, "tolerancia_14d": 0.05, "ventana_dias": 7, "ventana_largo_dias": 14,
            "dias_min_7d": 5, "dias_min_14d": 5, "objetivo_cm": 5, "posible_cm": 7, "revertir_dias": 3}
# Regla de Luis (30 oct): la meta es un modelo con error típico (mediana) de 5 cm o menos a 1 día ("objetivo"); 7 cm o
# menos es "posible". Antes de reemplazar al titular, el candidato también debe probarse a 7 y a 14 días (no puede
# empeorar), porque el modelo titular queda para siempre: un candidato nuevo tarda al menos ~19 días en poder calificar.


def _leer(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def _escribir(ruta, obj, compacto=False):
    os.makedirs(DIR, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        if compacto:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- candidatos
def c_coca_rio_real(P, ctx, mod):
    """El río Coca sigue el pronóstico de GloFAS del RÍO (sin la bajada por la historia del río). Es el 'modelo en
    prueba desde el 28 oct' de la pestaña Región."""
    s = mod.get("serieCocaRio")
    if not s:
        return None
    ctx["serieCoca"] = list(s)
    return P, ctx, {"serieCoca": list(s)}


def c_sin_autoajuste(P, ctx, mod):
    """Sin el factor que corrige la bajada según los aciertos recientes (¿el autoajuste ayuda o estorba?)."""
    ctx["ajuste"] = 1.0
    return P, ctx, {"ajuste": 1.0}


def c_paute_sin_ajuste(P, ctx, mod):
    """El caudal que llega a Mazar como lo promete la lluvia, sin el ajuste aprendido de lo que de verdad llegó."""
    s = mod.get("serieMazarBruta")
    if not s:
        return None
    ctx["serieMazar"] = list(s)
    return P, ctx, {"serieMazar": list(s)}


def c_sin_memoria(P, ctx, mod):
    """Solo la corrida de ahora, sin el promedio de las corridas de las últimas 48 h."""
    ctx["memoria"] = None
    return P, ctx, {"memoria": None}


CANDIDATOS = {
    "coca_rio_real": {"f": c_coca_rio_real, "nombre": "Río Coca con su caudal real", "promocion": "auto", "origen": "auditoría Mazar 29 oct",
                      "hipotesis": "El modelo es pesimista a 7 días porque baja a Coca Codo con la historia del río; con el pronóstico del río real acertaría más."},
    "sin_autoajuste": {"f": c_sin_autoajuste, "nombre": "Sin el autoajuste", "promocion": "auto", "origen": "laboratorio",
                       "hipotesis": "Comprobar si el factor de autoajuste mejora o empeora el pronóstico."},
    "paute_sin_ajuste": {"f": c_paute_sin_ajuste, "nombre": "Paute sin el ajuste aprendido", "promocion": "auto", "origen": "laboratorio",
                         "hipotesis": "Comprobar si el ajuste del caudal del Paute (≈42 % de lo que promete la lluvia) ayuda."},
    "sin_memoria": {"f": c_sin_memoria, "nombre": "Sin la memoria de 48 h", "promocion": "luis", "origen": "laboratorio",
                    "hipotesis": "Comprobar si promediar las corridas de 48 h estabiliza sin perder acierto."},
}


def c_sin_paro_hoy(P, ctx, mod):
    paro = mod.get("ccs_paro") or {}
    f_paro = paro.get("factor")
    fac = ctx.get("ccsFactor")
    if not paro.get("paro") or not f_paro or not fac:
        return None
    nuevo = []
    for d, v in enumerate(fac):
        fp = f_paro[min(d, len(f_paro) - 1)]
        nuevo.append(round(v / fp, 3) if fp > 0 else 1.0)
    if all(abs(x - 1.0) < 0.005 for x in nuevo):
        nuevo = None
    ctx["ccsFactor"] = nuevo
    return P, ctx, {"ccsFactor": nuevo}


CANDIDATOS["sin_paro_hoy"] = {"f": c_sin_paro_hoy, "nombre": "Sin el paro de hoy (conserva crecida)", "promocion": "luis", "origen": "Gemini 2026-10-30", "hipotesis": "Desactivar la proyección del paro actual de Coca Codo (conservando el descuento por riesgo de crecida de los días 1 a 14) reduce el error a 1 día cuando hay paros cortos por sedimentos."}


# ---------------------------------------------------------------- tanda Claude 30 oct (Luis: "muchos modelos sombra en paralelo")
# Diagnóstico: el titular es PESIMISTA y el sesgo crece con el plazo (aciertos.por_horizonte al 30 oct: −0,13 m a 1 día,
# −0,39 a 2, −0,86 a 3, −2,32 a 5, −4,19 a 7; err = predicho − real) y el error a 1 día está autocorrelacionado
# (−0,74 … −0,26 m en 8 corridas seguidas). Esta tanda prueba: (a) la misma maquinaria con otra fuerza (auto) y
# (b) corrección del error reciente o del sesgo por plazo (luis: mecanismo nuevo). OJO si alguno de memoria se promueve:
# hay que cambiar robot.py para aplicar la corrección DESPUÉS del paso de memoria (aplicar_titular corre antes y la
# memoria la sobreescribe) y sumarla al campo modelo.memoria.

def _dvdz(ctx, mod):
    """hm³ por metro de cota en la cota de hoy (curva de Mazar)."""
    c = mod.get("curva_mazar") or {"a": 3.6595, "b": 0.12497}
    return c["a"] + c["b"] * max(0.0, float(ctx["cota"]) - 2115)


def _sumar_memoria(ctx, corr):
    """Suma una corrección de caudal (m³/s por día) a la memoria; la página la usa igual (campo modelo.memoria)."""
    base = list(ctx.get("memoria") or [])
    n = max(len(base), len(corr))
    out = [round((base[i] if i < len(base) else 0.0) + (corr[i] if i < len(corr) else 0.0), 2) for i in range(n)]
    ctx["memoria"] = out
    return out


def _corr_error(P, ctx, mod, k, tau):
    """Corrige con el error a 1 día de las últimas k verificaciones (de la corrida anterior: sin datos del futuro).
    Si el modelo viene diciendo e metros de menos, suma el caudal que explica esos e metros en un día y lo apaga
    con constante de tiempo tau días."""
    ac = mod.get("aciertos") or {}
    rec = [x for x in (ac.get("recientes_1d") or []) if isinstance(x.get("err"), (int, float))]
    if len(rec) < max(2, k):
        return None
    rec = sorted(rec, key=lambda x: x["obj_ts"])[-k:]
    try:
        hoy = datetime.fromisoformat(str(mod.get("_ts") or rec[-1]["obj_ts"]))
        if (hoy - datetime.fromisoformat(rec[-1]["obj_ts"])).total_seconds() > 12 * 3600:
            return None           # verificaciones viejas: no corrige
    except Exception:
        pass
    e = sum(x["err"] for x in rec) / len(rec)
    q0 = -e * _dvdz(ctx, mod) / 0.0864
    q0 = max(-60.0, min(60.0, q0))
    corr = [q0 * math.exp(-d / tau) for d in range(60)]
    m = _sumar_memoria(ctx, corr)
    return P, ctx, {"memoria": m}


def c_corrige_error_3(P, ctx, mod):
    return _corr_error(P, ctx, mod, 3, 1.0)


def c_corrige_error_6(P, ctx, mod):
    return _corr_error(P, ctx, mod, 6, 1.0)


def c_corrige_error_6_lento(P, ctx, mod):
    return _corr_error(P, ctx, mod, 6, 3.0)


def _sesgo_plazo(P, ctx, mod, fuerza, desde=0):
    """Quita el sesgo medido por plazo (aciertos.por_horizonte, solo plazos con ≥30 casos), repartido día a día como caudal.
    desde = primer día en que se corrige (antes, 0); lo usa la combinación con la corrección del error reciente."""
    ph = (mod.get("aciertos") or {}).get("por_horizonte") or {}
    pts = [(0, 0.0)] + sorted((int(h), v["sesgo_m"]) for h, v in ph.items() if (v.get("n") or 0) >= 30 and v.get("sesgo_m") is not None)
    if len(pts) < 3:
        return None
    def s(t):
        for (h0, v0), (h1, v1) in zip(pts, pts[1:]):
            if t <= h1:
                return v0 + (v1 - v0) * (t - h0) / (h1 - h0)
        return pts[-1][1]
    k = _dvdz(ctx, mod) / 0.0864
    corr = [0.0 if d < desde else max(-80.0, min(80.0, -(s(d + 1) - s(d)) * k * fuerza)) for d in range(60)]
    m = _sumar_memoria(ctx, corr)
    return P, ctx, {"memoria": m}


def c_sesgo_plazo_50(P, ctx, mod):
    return _sesgo_plazo(P, ctx, mod, 0.5)


def c_sesgo_plazo_100(P, ctx, mod):
    return _sesgo_plazo(P, ctx, mod, 1.0)


def c_autoajuste_completo(P, ctx, mod):
    """El autoajuste usa el valor medido entero (ratio_mediana) en vez del recortado por pocos días."""
    r = (mod.get("ajuste_info") or {}).get("ratio_mediana")
    if not isinstance(r, (int, float)) or r <= 0:
        return None
    v = round(max(0.5, min(1.3, r)), 3)
    ctx["ajuste"] = v
    return P, ctx, {"ajuste": v}


def _paute_fuerza(P, ctx, mod, cual):
    bruta, info = mod.get("serieMazarBruta"), mod.get("ajuste_paute") or {}
    f = info.get(cual)
    if not bruta or not isinstance(f, (int, float)):
        return None
    actual = ctx.get("serieMazar") or bruta
    f = max(0.0, min(1.5, float(f)))                       # mismo criterio que el robot: solo donde la lluvia promete más (b > 1)
    serie = [round(1 + (b - 1) * f, 4) if b > 1 else a for a, b in zip(actual, bruta)]
    ctx["serieMazar"] = serie
    return P, ctx, {"serieMazar": serie}


def c_paute_ajuste_completo(P, ctx, mod):
    """El caudal del Paute con el ajuste observado entero (lo que de verdad llegó por cada m³/s que prometía la lluvia)."""
    return _paute_fuerza(P, ctx, mod, "observado")


def c_coca_mitad(P, ctx, mod):
    """Río Coca a medio camino entre la serie del titular y el pronóstico del río real."""
    a, b = ctx.get("serieCoca"), mod.get("serieCocaRio")
    if not a or not b:
        return None
    s = [round((x + y) / 2, 4) for x, y in zip(a, b)]
    ctx["serieCoca"] = s
    return P, ctx, {"serieCoca": s}


def c_otros_rios_planos(P, ctx, mod):
    """Las otras centrales siguen solo al río Coca (sin la serie propia de Pastaza, Zamora y Jubones)."""
    if not ctx.get("otrasRios"):
        return None
    ctx["otrasRios"] = None
    return P, ctx, {"otrasRios": None}


def c_dia_semana_suave(P, ctx, mod):
    """La diferencia de demanda entre días de la semana a la mitad."""
    dd = ctx.get("deltaDia")
    if not dd:
        return None
    v = [round(x * 0.5, 1) for x in dd]
    ctx["deltaDia"] = v
    return P, ctx, {"deltaDia": v}


def c_humedo_completo(P, ctx, mod):
    """Combinación: río Coca real + Paute con el ajuste observado entero."""
    r = c_coca_rio_real(P, ctx, mod)
    if not r:
        return None
    P, ctx, _ = r
    r2 = _paute_fuerza(P, ctx, mod, "observado")
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {"serieCoca": ctx["serieCoca"], "serieMazar": ctx["serieMazar"]}


def c_cortes_siguen_7d(P, ctx, mod):
    """Los cortes de hoy siguen 7 días más (el esquema a empresas continúa), en vez de valer solo hoy. A 1 día no cambia nada: se mide a 3, 7 y 14 días."""
    plan = list(ctx.get("cutPlan") or [])
    hoy = plan[0] if plan and isinstance(plan[0], (int, float)) else None
    if not hoy:
        return None
    plan = plan + [None] * max(0, 8 - len(plan))
    for d in range(1, 8):
        if plan[d] is None:
            plan[d] = hoy
    ctx["cutPlan"] = plan
    return P, ctx, {"cutPlan": plan}


# ---------- Demanda real del Cenace + clima de la Costa (Luis, 1 nov) ----------
# El titular deduce la demanda de lo que generó Paute en los últimos días (vida media ~3 días), así que tarda 2–3 días en
# notar una baja brusca (lluvia en la Costa, menos aire acondicionado, fin de semana o feriado). El 31 oct supuso Paute
# ~890 MW y fue ~270. Estos candidatos parten de la demanda REAL de las últimas 24 h (Cenace, cada 30 min) y la mueven
# día a día con el pronóstico de Guayaquil (temperatura máxima: 50 MW por °C, el mismo coeficiente del titular; y, en
# una variante, lluvia). Como la memoria de 48 h del titular compensa justamente el sesgo de su Paute, aquí se apaga o
# se reduce (si no, se corregiría dos veces).
def _corte_dia_lab(manual, cut, fecha):
    """Copia de robot.corte_del_dia (el laboratorio no importa robot): registro > plan > cut_dias > cut; 0–700 MW."""
    k = fecha.isoformat()
    v = (manual.get("cortes_registro") or {}).get(k)
    if v is None: v = (manual.get("cortes_plan") or {}).get(k)
    if isinstance(v, (int, float)) and not isinstance(v, bool): return float(max(0, min(700, v)))
    cd = manual.get("cut_dias")
    if isinstance(cd, list) and len(cd) == 7: return float(cut) if cd[(fecha.weekday() + 1) % 7] else 0.0
    return float(cut)


def _patron_demanda():
    """Patrón semanal de la DEMANDA nacional (MW sobre su promedio, 0 = domingo), de los días SIN cortes a empresas
    (balance diario del Cenace antes del 11 oct). Distinto del de Paute (deltaDia): domingo ≈ −350, sábado ≈ −150."""
    from datetime import date as _d
    b = (_leer_json_lab("registro/generacion.json") or {}).get("balance") or {}
    por = {}
    for k, v in b.items():
        if k >= "2026-10-11" or k in ("2026-08-10", "2026-10-09") or not isinstance(v.get("total"), (int, float)): continue   # sin cortes ni feriados
        dem = v["total"] + (v.get("imp_col") or 0) + (v.get("imp_peru") or 0) - (v.get("exp_col") or 0) - (v.get("exp_peru") or 0)
        por.setdefault((_d.fromisoformat(k).weekday() + 1) % 7, []).append(dem)
    if len(por) < 7 or min(len(x) for x in por.values()) < 3: return None
    m = sum(sum(x) / len(x) for x in por.values()) / 7
    return [round(sum(por[i]) / len(por[i]) - m, 1) for i in range(7)]


def _demanda_real(P, ctx, mod, lluvia_mw=0.0, memoria=0.0):
    try:
        from datetime import date as _d
        ts = str(mod.get("_ts") or "")
        if len(ts) < 16: return None
        t0 = ts[:16]                                             # hora local de ESTA corrida (no la de datos.json, que es la anterior)
        f0 = _d.fromisoformat(ts[:10])
        t_ini = (datetime.fromisoformat(t0) - timedelta(hours=72)).isoformat(timespec="minutes")
        pts = (_leer_json_lab("serie_cenace.json") or {}).get("puntos") or {}
        ks = [k for k in sorted(pts) if t_ini < k <= t0 and isinstance(pts[k].get("d"), (int, float))]
        if len(ks) < 96: return None                             # al menos 48 h de datos en las últimas 72 h
        if (datetime.fromisoformat(t0) - datetime.fromisoformat(ks[-1])).total_seconds() > 4 * 3600: return None   # Cenace caído
        pat = _patron_demanda()
        if not pat: return None
        man = (_leer_json_lab("datos.json") or {}).get("manual") or {}
        fer = set((man.get("feriados") or {}).keys())
        efecto = lambda f: pat[0] if f.isoformat() in fer else pat[(f.weekday() + 1) % 7]   # feriado = domingo
        # base: demanda medida (72 h) + los cortes que ya la bajaron − el efecto de cada día (semana y feriados)
        vals = [pts[k]["d"] + _corte_dia_lab(man, P["cut"], _d.fromisoformat(k[:10])) - efecto(_d.fromisoformat(k[:10])) for k in ks]
        P["demanda"] = round(sum(vals) / len(vals), 1)
        # hacia adelante se usa el patrón del titular (demanda × parte que toma Paute); el patrón completo solo sirve
        # para quitarle a la demanda medida el efecto de cada día
        # pronóstico de Guayaquil por día (Open-Meteo, lo guarda el robot): máxima y lluvia (≥ 2 mm = día lluvioso)
        g = _leer_json_lab("registro/gye_pronostico.json") or {}
        por = {t: (float(mx), (ll or 0) >= 2) for t, mx, ll in zip(g.get("dias") or [], g.get("tmax") or [], g.get("lluvia_mm") or []) if mx is not None}
        dias_v = [k[:10] for k in ks]
        cl = [por[d] for d in dias_v if d in por]
        if len(cl) < len(dias_v) * 0.8: return None
        tb = sum(x[0] for x in cl) / len(cl); lb = sum(1 for x in cl if x[1]) / len(cl)   # clima de la ventana medida
        plan = list(ctx.get("cutPlan") or []); plan += [None] * max(0, 61 - len(plan))
        for k in range(61):
            f = f0 + timedelta(days=k); dia = (ctx["diaSemana0"] + k) % 7
            v = plan[k] if isinstance(plan[k], (int, float)) and not isinstance(plan[k], bool) else (P["cut"] if (not ctx.get("cutDias") or ctx["cutDias"][dia]) else 0)
            x = por.get(f.isoformat())
            extra = (50 * (x[0] - tb) - lluvia_mw * (int(x[1]) - lb)) if x else 0.0        # sin pronóstico: sin ajuste
            plan[k] = round(v - extra, 1)                        # corte equivalente (negativo = más demanda que en la ventana)
        ctx["cutPlan"] = plan
        mem = ctx.get("memoria")
        ctx["memoria"] = [round(v_ * memoria, 3) for v_ in mem] if (mem and memoria) else None
        # PARA PROMOVER (requiere a Luis): la página no lee modelo.demanda ni deltaDia propios, el cutPlan publicado se corta
        # a 15 días y aplicar_titular corre antes de la memoria; habría que adaptar robot.py, index.html y pestanas.js.
        return P, ctx, {"demanda": P["demanda"], "cutPlan": plan[:15], "memoria": ctx["memoria"]}
    except Exception:
        return None


def _leer_json_lab(ruta):
    try:
        with open(ruta, encoding="utf-8") as f: return json.load(f)
    except Exception: return None


def c_demanda_real(P, ctx, mod): return _demanda_real(P, ctx, mod)
def c_demanda_real_mem(P, ctx, mod): return _demanda_real(P, ctx, mod, memoria=0.5)
def c_demanda_real_lluvia(P, ctx, mod): return _demanda_real(P, ctx, mod, lluvia_mw=100.0)


# ---------- Patrón semanal con distintas ventanas del historial de Paute (Luis, 1 nov) ----------
# El titular usa los últimos 91 días de demanda nacional × la parte de Paute. Aquí se prueba el patrón medido directo en
# Paute (Celec Sur 2010–2026) con otras ventanas: 1 año, la misma temporada de años anteriores y todo el historial.
# Cada día se compara con el promedio de su semana centrada (quita la tendencia) y se toma la MEDIANA por día de la
# semana (resiste feriados y paros).
def _patron_paute(filtro, fin):
    try:
        from datetime import date as _d
        h = dict(_leer_json_lab("historial/celec_2010_2022.json") or {}); h.update(_leer_json_lab("historial/celec_diario.json") or {})
        P = {}
        for k, v in h.items():
            try: P[_d.fromisoformat(k)] = ((v.get("maz") or 0) + (v.get("mol") or 0) + (v.get("sop") or 0)) / 24
            except Exception: pass
        por = {}
        for d0 in P:
            if d0 > fin - timedelta(days=4) or not filtro(d0) or P[d0] < 50: continue
            w = [P.get(d0 + timedelta(days=i)) for i in range(-3, 4)]
            if None in w: continue
            por.setdefault((d0.weekday() + 1) % 7, []).append(P[d0] - sum(w) / 7)
        if len(por) < 7 or min(len(x) for x in por.values()) < 8: return None
        med = lambda x: sorted(x)[len(x) // 2]
        pat = [med(por[i]) for i in range(7)]; m = sum(pat) / 7
        return [round(x - m, 1) for x in pat]
    except Exception:
        return None


def _con_patron(P, ctx, mod, filtro_de):
    from datetime import date as _d
    ts = str(mod.get("_ts") or "")
    if len(ts) < 10: return None
    fin = _d.fromisoformat(ts[:10])
    pat = _patron_paute(filtro_de(fin), fin)
    if not pat: return None
    ctx["deltaDia"] = pat
    return P, ctx, {"deltaDia": pat}


def c_patron_1ano(P, ctx, mod): return _con_patron(P, ctx, mod, lambda fin: (lambda d: d >= fin - timedelta(days=365)))
def c_patron_temporada(P, ctx, mod):   # mismos meses (±1) de los 3 años anteriores
    def f(fin):
        meses = {(fin.month - 2) % 12 + 1, fin.month, fin.month % 12 + 1}
        return lambda d: fin.year - 3 <= d.year < fin.year and d.month in meses
    return _con_patron(P, ctx, mod, f)
def c_patron_historico(P, ctx, mod): return _con_patron(P, ctx, mod, lambda fin: (lambda d: True))


# ---------- Cortes medidos (Luis, 1 nov: "habría que ver cuánto fue lo que se cortó a las empresas") ----------
F_CORTE_MED = os.path.join(DIR, "corte_medido.json")


def _clima_gye(desde, hasta):
    """Máxima y lluvia diarias medidas en Guayaquil (Open-Meteo, archivo histórico + últimos días)."""
    import urllib.request
    out = {}
    for url in (f"https://archive-api.open-meteo.com/v1/archive?latitude=-2.19&longitude=-79.89&start_date={desde}&end_date={hasta}"
                "&daily=temperature_2m_max,precipitation_sum&timezone=America%2FGuayaquil",
                "https://api.open-meteo.com/v1/forecast?latitude=-2.19&longitude=-79.89&past_days=10&forecast_days=1"
                "&daily=temperature_2m_max,precipitation_sum&timezone=America%2FGuayaquil"):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "DataLab Ec"}), timeout=60).read())
            d = j["daily"]
            for t, tx, pr in zip(d["time"], d["temperature_2m_max"], d["precipitation_sum"]):
                if tx is not None and t not in out: out[t] = (tx, pr or 0.0)
        except Exception:
            pass
    return out


def corte_medido(hoy_txt, tendencia=False):
    """MW que de verdad bajó la demanda nacional en los días con cortes, separado en laborable y fin de semana.
    Regresión con la demanda diaria del Cenace (generación + importación − exportación, generacion.json 'balance'):
    demanda = día de la semana + b·máxima de Guayaquil + c·lluvia (tope 30 mm) [+ tendencia lineal] + g_lab·corte_lab + g_fin·corte_fin.
    Días con corte = manual.cortes_registro > 0 (antes del primer registro, sin cortes). Sin feriados.
    OJO (revisor, 1 nov): los cortes empiezan el 14 oct y la demanda ya venía bajando (~−228 MW/mes antes de los cortes),
    así que "corte" se confunde con la tendencia: sin tendencia ~339 MW, con tendencia ~140 MW. Por eso hay dos
    candidatos (con y sin tendencia) y el laboratorio dirá cuál proyecta mejor. Se recalcula una vez al día (si falla,
    se reintenta en la próxima corrida). "fin" es None si hay menos de 6 días de corte en fin de semana."""
    prev = _leer(F_CORTE_MED, {})
    clave = "tendencia" if tendencia else "simple"
    if prev.get("fecha") == hoy_txt and (prev.get(clave) or {}).get("laborable") is not None: return prev[clave]
    if prev.get("fecha") != hoy_txt: prev = {"fecha": hoy_txt}
    try:
        import numpy as np
        bal = (_leer_json_lab(os.path.join("registro", "generacion.json")) or {}).get("balance") or {}
        man = (_leer_json_lab("datos.json") or {}).get("manual") or {}
        reg = man.get("cortes_registro") or {}
        fer = set((man.get("feriados") or {}).keys()) | FERIADOS_LAB
        primero = min(reg) if reg else "9999"
        dias = sorted(d for d, v in bal.items() if isinstance(v.get("total"), (int, float)) and d not in fer and d < hoy_txt)
        if len(dias) < 30: raise ValueError("pocos días")
        clima = _clima_gye(dias[0], dias[-1])
        t0 = datetime.fromisoformat(dias[0])
        X, y, info = [], [], {"lab": 0, "fin": 0, "sin": 0, "sin_clima": 0}
        for d in dias:
            if d not in clima: info["sin_clima"] += 1; continue
            v = bal[d]
            dem = v["total"] + (v.get("imp_col") or 0) + (v.get("imp_peru") or 0) - (v.get("exp_col") or 0) - (v.get("exp_peru") or 0)
            w = datetime.fromisoformat(d).weekday()   # 0 = lunes
            c = (reg.get(d) or 0) > 0 if d >= primero else False
            fin = w >= 5
            tx, pr = clima[d]
            fila = [1.0 if w == k else 0.0 for k in range(7)] + [tx, min(pr, 30.0)]
            if tendencia: fila.append((datetime.fromisoformat(d) - t0).days / 30.0)
            X.append(fila + [1.0 if (c and not fin) else 0.0, 1.0 if (c and fin) else 0.0])
            y.append(dem)
            info["lab" if (c and not fin) else "fin" if c else "sin"] += 1
        if info["lab"] < 6 or info["sin"] < 15: raise ValueError(f"pocos días con y sin cortes {info}")
        X, y = np.array(X), np.array(y)
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
        sig = float(np.sqrt((resid ** 2).sum() / max(len(y) - X.shape[1], 1)))
        cov = sig ** 2 * np.linalg.pinv(X.T @ X)
        il, ifn = X.shape[1] - 2, X.shape[1] - 1
        lab = -float(coef[il]); fin = -float(coef[ifn])
        res = {"laborable": round(max(0.0, min(700.0, lab))), "error_laborable": round(float(np.sqrt(cov[il, il]))),
               "fin": (round(max(0.0, min(700.0, fin))) if info["fin"] >= 6 else None),
               "fin_crudo": round(fin), "error_fin": round(float(np.sqrt(cov[ifn, ifn]))),
               "mw_por_grado": round(float(coef[7]), 1), "mw_por_mm_lluvia": round(float(coef[8]), 1),
               "tendencia_mw_mes": (round(float(coef[9]), 1) if tendencia else None),
               "dias": info, "desde": dias[0], "hasta": dias[-1]}
    except Exception as e:
        prev[clave + "_error"] = {"ts": datetime.now().isoformat(timespec="minutes"), "error": str(e)[:150]}
        _escribir(F_CORTE_MED, prev)
        return None   # sin resultado del día: se reintenta en la próxima corrida
    prev[clave] = res; prev.pop(clave + "_error", None)
    _escribir(F_CORTE_MED, prev)
    return res


FERIADOS_LAB = {"2026-08-10", "2026-10-09", "2026-11-02", "2026-11-03"}


def _con_corte_medido(P, ctx, mod, tendencia):
    """En los días con corte del plan (cutPlan), escala los MW por lo medido / valor de siempre (300): laborable o fin de
    semana. Feriados cuentan como fin de semana. Si el fin de semana no tiene estimación (menos de 6 días), ese día queda
    como en el titular. Fuera de los días con corte no cambia nada."""
    plan = list(ctx.get("cutPlan") or [])
    if not any(isinstance(x, (int, float)) and x > 0 for x in plan): return None
    hoy_txt = str(mod.get("_ts") or datetime.now().isoformat())[:10]
    m = corte_medido(hoy_txt, tendencia)
    if not m: return None
    cut = float(P.get("cut") or 300.0) or 300.0
    d0 = mod.get("diaSemana0", 0)   # 0 = domingo (JS), índice 0 = hoy
    fer = list(ctx.get("feriados") or mod.get("feriados") or [])
    for k, x in enumerate(plan):
        if isinstance(x, (int, float)) and x > 0:
            libre = ((d0 + k) % 7 in (0, 6)) or (k < len(fer) and bool(fer[k]))
            est = m["fin"] if libre else m["laborable"]
            if est is None: continue
            plan[k] = round(x * est / cut, 1)
    ctx["cutPlan"] = plan
    return P, ctx, {"cutPlan": plan}


def c_corte_medido(P, ctx, mod): return _con_corte_medido(P, ctx, mod, False)
def c_corte_medido_tend(P, ctx, mod): return _con_corte_medido(P, ctx, mod, True)


def _cand(cid, f, prom, nombre, hip):
    CANDIDATOS[cid] = {"f": f, "promocion": prom, "origen": ("Claude 2026-11-01 (demanda y clima)" if cid.startswith("demanda_real") else "Claude 2026-11-01 (patrón semanal)" if cid.startswith("patron_") else "Claude 2026-11-01 (cortes medidos)" if cid.startswith("corte_medido") else "Claude 2026-10-30 (tanda)"), "nombre": nombre, "hipotesis": hip}


_cand("corrige_error_3", c_corrige_error_3, "luis", "Corrige el error de las 3 últimas", "Si el titular viene fallando en la misma dirección, sumar el caudal que explica el error de las 3 últimas verificaciones a 1 día (apagándose en ~1 día) baja el error a 1 día hacia 5 cm.")
_cand("corrige_error_6", c_corrige_error_6, "luis", "Corrige el error de las 6 últimas", "Igual que la anterior pero con 6 verificaciones: más estable, reacciona más lento.")
_cand("corrige_error_6_lento", c_corrige_error_6_lento, "luis", "Corrige el error (6) y lo arrastra 3 días", "La corrección del error reciente se apaga en ~3 días: debería ayudar también a 3 y 7 días si el sesgo es persistente.")
_cand("sesgo_plazo_50", c_sesgo_plazo_50, "luis", "Quita la mitad del sesgo por plazo", "El titular es pesimista y más a más plazo (−0,13 m a 1 día, −4,2 m a 7); quitar la mitad del sesgo medido mejora 3–14 días sin sobrecorregir.")
_cand("sesgo_plazo_100", c_sesgo_plazo_100, "luis", "Quita todo el sesgo por plazo", "Igual, quitando el sesgo entero: prueba el límite (puede sobrecorregir: el sesgo mezcla verificaciones de versiones anteriores del modelo).")
_cand("autoajuste_completo", c_autoajuste_completo, "auto", "Autoajuste con el valor medido entero", "El autoajuste recortado (0,84) se queda corto frente a lo medido (0,66): usarlo entero reduce el pesimismo de la bajada.")
_cand("paute_ajuste_completo", c_paute_ajuste_completo, "auto", "Paute con el ajuste observado entero", "Llegó 135 % de lo que prometía la lluvia y el titular usa 111 %: con lo observado entero el caudal de entrada se acerca a la realidad.")
_cand("coca_mitad", c_coca_mitad, "auto", "Río Coca a medio camino", "Punto medio entre el titular y el río real: menos riesgo que cambiar todo a la serie del río.")
_cand("otros_rios_planos", c_otros_rios_planos, "auto", "Otras centrales sin su serie propia", "Comprobar si la serie de Pastaza, Zamora y Jubones ayuda o solo mete ruido.")
_cand("dia_semana_suave", c_dia_semana_suave, "auto", "Demanda por día de la semana a la mitad", "El patrón semanal de demanda pesa demasiado en épocas de cortes; a la mitad se acerca más.")
_cand("humedo_completo", c_humedo_completo, "auto", "Río Coca real + Paute observado", "Combinación de los dos cambios que apuntan contra el pesimismo del titular.")
_cand("demanda_real", c_demanda_real, "luis", "Demanda real del Cenace + calor de la Costa", "Partir de la demanda medida en las últimas 72 h, con el patrón semanal de la propia demanda (no de lo que generó Paute en 3 días ni de su patrón) y moverla con la máxima pronosticada de Guayaquil hace que el modelo note al instante las bajas por lluvia, fin de semana o feriado (el 31 oct supuso Paute ~890 MW y fue ~270).")
_cand("demanda_real_mem", c_demanda_real_mem, "luis", "Demanda real + media memoria", "Igual, conservando la mitad de la memoria de 48 h por si la memoria corrige algo más que el sesgo de Paute.")
_cand("demanda_real_lluvia", c_demanda_real_lluvia, "luis", "Demanda real + calor y lluvia en la Costa", "Igual que demanda real, y además un día con lluvia pronosticada en Guayaquil baja ~100 MW la demanda (menos aire acondicionado) frente a uno seco.")
_cand("patron_1ano", c_patron_1ano, "luis", "Patrón semanal de Paute del último año", "Un año de historial suaviza los 3 meses del titular (domingo ≈ −207 MW en vez de −308): menos sensible a una racha de cortes o lluvias.")
_cand("patron_temporada", c_patron_temporada, "luis", "Patrón semanal de la misma temporada", "Los mismos meses de los 3 años anteriores (oct–dic): el uso de Paute cambia con la época de lluvias y sequía (domingo ≈ −147 MW).")
_cand("patron_historico", c_patron_historico, "luis", "Patrón semanal de todo el historial", "Todo el historial de Celec Sur desde 2010 (domingo ≈ −141 MW): el más estable, pero de cuando Paute trabajaba distinto.")
_cand("corte_medido", c_corte_medido, "luis", "Cortes medidos (sin tendencia)", "Los 300 MW fijos por día de corte no son lo medido. Con la demanda real del Cenace, separando día de la semana, calor y lluvia de Guayaquil, el ahorro entre semana sale ~339 MW (±55); el fin de semana se usa recién con 6 días medidos. Puede exagerar si la demanda ya venía bajando por la temporada.")
_cand("corte_medido_tend", c_corte_medido_tend, "luis", "Cortes medidos (con tendencia)", "Igual, pero descontando que la demanda ya venía bajando antes de los cortes (~−228 MW/mes): el ahorro entre semana sale ~140 MW (±55). El laboratorio dirá cuál de las dos lecturas proyecta mejor a Paute.")
_cand("cortes_siguen_7d", c_cortes_siguen_7d, "luis", "Los cortes siguen 7 días", "Si el esquema de cortes a empresas continúa, la demanda baja también los próximos días y Mazar sube más de lo que dice el titular.")


def c_memoria_desde_dia3(P, ctx, mod):
    """Auditor 31 oct (versión corregida de memoria_solo_largo de Gemini, rechazada por el revisor: al poner en 0 la
    memoria de los días 0 y 1 el volumen quitado faltaba para siempre). Aquí la memoria de 48 h no actúa los días 0 y 1
    (a 1 y 2 días = sin_memoria) y ese caudal se devuelve a medias en los días 2 y 3: desde el día 4 la cota acumulada es
    la del titular. Mide si la memoria solo estorba a corto plazo."""
    mem = ctx.get("memoria")
    if not isinstance(mem, list) or not mem:
        return None
    L = len(mem)
    full = [float(mem[min(i, L - 1)] or 0) for i in range(max(L, 5))]   # el último valor se repite igual que en el robot
    quitado = full[0] + full[1]
    full[0] = full[1] = 0.0
    full[2] += quitado / 2; full[3] += quitado / 2
    nueva = [round(x, 2) for x in full]
    ctx["memoria"] = nueva
    return P, ctx, {"memoria": nueva}


def c_sin_memoria_paute_bruto(P, ctx, mod):
    """Auditor 31 oct: combina los dos candidatos que mejor van a 1 día (sin_memoria +44 %, paute_sin_ajuste +12 %,
    1 día medido): solo la corrida de ahora y el caudal del Paute como lo promete la lluvia."""
    s = mod.get("serieMazarBruta")
    if not s:
        return None
    ctx["memoria"] = None
    ctx["serieMazar"] = list(s)
    return P, ctx, {"memoria": None, "serieMazar": list(s)}


def c_memoria_mitad(P, ctx, mod):
    """Gemini 31 oct (aprobado por el auditor y el Claude independiente): la memoria de 48 h a la mitad."""
    mem = ctx.get("memoria")
    if not mem:
        return None
    nueva = [round(float(x) * 0.5, 2) for x in mem]
    ctx["memoria"] = nueva
    return P, ctx, {"memoria": nueva}


CANDIDATOS["memoria_mitad"] = {"f": c_memoria_mitad, "promocion": "luis", "origen": "Gemini 2026-10-31", "nombre": "Memoria de 48 h a la mitad",
                               "hipotesis": "Reducir a la mitad el caudal de corrección de la memoria de 48 h disminuye el error por rezago a 1 día hacia la meta de 5 cm sin perder toda la estabilidad de promediar corridas."}
CANDIDATOS["memoria_desde_dia3"] = {"f": c_memoria_desde_dia3, "promocion": "luis", "origen": "auditor 2026-10-31", "nombre": "Memoria solo desde el día 3",
    "hipotesis": "La memoria de 48 h (hoy +17 m³/s el día 0) mete el rezago que hace que el titular diga de más a 1 día (sesgo +12 cm); quitándola los días 0–1 y devolviendo ese caudal en los días 2–3, el error a 1 día baja como sin_memoria y desde el día 4 la cota es la del titular (no empeora a 7 y 14 días)."}
CANDIDATOS["sin_memoria_paute_bruto"] = {"f": c_sin_memoria_paute_bruto, "promocion": "luis", "origen": "auditor 2026-10-31", "nombre": "Sin memoria + Paute sin ajuste",
    "hipotesis": "Los dos cambios que mejor van a 1 día (sin_memoria y paute_sin_ajuste) suman: el error a 1 día baja más que con cada uno por separado."}


def c_memoria_mitad_coca_real(P, ctx, mod):
    mem = ctx.get("memoria")
    s = mod.get("serieCocaRio")
    if not mem or not s:
        return None
    nueva_mem = [round(float(x) * 0.5, 2) for x in mem]
    nueva_coca = list(s)
    ctx["memoria"] = nueva_mem
    ctx["serieCoca"] = nueva_coca
    return P, ctx, {"memoria": nueva_mem, "serieCoca": nueva_coca}


CANDIDATOS["memoria_mitad_coca_real"] = {"f": c_memoria_mitad_coca_real, "promocion": "luis", "origen": "Gemini 2026-11-04", "nombre": "Media memoria + río Coca real", "hipotesis": "Combinar la reducción a la mitad de la memoria de 48 h (que baja el error por rezago a 1 día) con la serie del río Coca real (que reduce el error a 3 y 5 días) mejora tanto el corto como el mediano plazo frente al titular."}


def c_memoria_mitad_y_sesgo50_largo(P, ctx, mod):
    mem = ctx.get("memoria")
    if not mem:
        return None
    base = [float(x) * 0.5 for x in mem]
    ph = (mod.get("aciertos") or {}).get("por_horizonte") or {}
    pts = [(0, 0.0)]
    for h, v in ph.items():
        if (v.get("n") or 0) >= 30 and v.get("sesgo_m") is not None:
            pts.append((int(h), float(v["sesgo_m"])))
    pts.sort()
    if len(pts) < 3:
        return None
    c = mod.get("curva_mazar") or {"a": 3.6595, "b": 0.12497}
    dvdz = c["a"] + c["b"] * max(0.0, float(ctx["cota"]) - 2115.0)
    k = dvdz / 0.0864
    corr = []
    for d in range(60):
        if d < 1:
            corr.append(0.0)
        else:
            t0 = d
            s0 = pts[-1][1]
            for (h0, v0), (h1, v1) in zip(pts, pts[1:]):
                if t0 <= h1:
                    s0 = v0 + (v1 - v0) * (t0 - h0) / (h1 - h0)
                    break
            t1 = d + 1
            s1 = pts[-1][1]
            for (h0, v0), (h1, v1) in zip(pts, pts[1:]):
                if t1 <= h1:
                    s1 = v0 + (v1 - v0) * (t1 - h0) / (h1 - h0)
                    break
            val = -(s1 - s0) * k * 0.5
            corr.append(max(-80.0, min(80.0, val)))
    n = max(len(base), len(corr))
    out = [round((base[i] if i < len(base) else 0.0) + (corr[i] if i < len(corr) else 0.0), 2) for i in range(n)]
    ctx["memoria"] = out
    return P, ctx, {"memoria": out}


CANDIDATOS["memoria_mitad_y_sesgo50_largo"] = {"f": c_memoria_mitad_y_sesgo50_largo, "promocion": "luis", "origen": "Gemini 2026-11-04", "nombre": "Media memoria + mitad de sesgo desde día 2", "hipotesis": "Reducir la memoria a la mitad en todos los plazos y quitar la mitad del sesgo por plazo únicamente desde el día 2 disminuye el rezago a 1 día sin sobrecorregir mañana y corrige el pesimismo de 3 a 14 días."}


def aplicar_titular(P, ctx, mod, log=print):
    """Aplica los candidatos que ya pasaron a titular (laboratorio/titular.json). Sin promovidos no hace nada."""
    tit = _leer(F_TIT, {"promovidos": []})
    hechos = []
    for cid in tit.get("promovidos", []):
        c = CANDIDATOS.get(cid)
        if not c:
            continue
        r = c["f"](P, ctx, mod)
        if r:
            P, ctx, cambios = r
            mod.update(cambios)
            hechos.append(cid)
    if hechos:
        log(f"Laboratorio: titular con {', '.join(hechos)}")
    return P, ctx, hechos


# ---------------------------------------------------------------- corrida
def _copia(x):
    return json.loads(json.dumps(x))


def _rasgos(P, ctx, mod, datos):
    """Variables de la corrida, para ver después cuáles se relacionan con el error."""
    paro = (mod.get("ccs_paro") or {}).get("paro")
    ll = datos.get("lluvia_paute_mm")
    return {"q_mazar": round(float(P.get("qMazar") or 0), 1), "q_coca": round(float(P.get("qCoca") or 0), 1),
            "demanda": round(float(P.get("demanda") or 0)), "corte": round(float(P.get("cut") or 0)),
            "importacion": round(float(P.get("imp") or 0)), "termica": round(float(P.get("therm") or 0)),
            "paro_coca": 1 if paro else 0, "ajuste": round(float(ctx.get("ajuste") or 1), 3),
            "lluvia_paute_mm": (round(float(ll), 1) if isinstance(ll, (int, float)) else None),
            "q_mazar_3d": round(float(P.get("qMazar") or 0) * float((ctx.get("serieMazar") or [1, 1, 1, 1])[3]), 1),
            "hora": int(str(datos.get("fecha", "T00"))[11:13] or 0)}


def _con_previo(mod, ts):
    """Los aciertos se calculan después del laboratorio: los candidatos que los usan leen los de la corrida anterior
    (datos.json en disco, de hace ~2 h). Devuelve una copia; no cambia el bloque que se publica."""
    m = dict(mod)
    m["_ts"] = ts
    if mod.get("aciertos"):
        return m
    try:
        prev = _leer("datos.json", {}).get("modelo", {}).get("aciertos")
        if prev:
            m["aciertos"] = prev
    except Exception:
        pass
    return m


def correr(P, ctx, par, mod, datos, simular, log=print, base=None):
    """Calcula titular y candidatos con los mismos datos y guarda sus trayectorias. Devuelve el resumen del marcador.
    base = (P, ctx) antes de aplicar los promovidos: se sigue corriendo como 'anterior' para poder revertir."""
    conf = {**CONF_DEF, **_leer(F_CONF, {})}
    if not os.path.exists(F_CONF):
        _escribir(F_CONF, conf)
    ts = datetime.fromisoformat(datos["fecha"]).isoformat(timespec="minutes")
    tray, completa = {}, {}
    d_tit, _ = simular(_copia(P), _copia(ctx), par, horizonte=HORIZ_REGION)
    tray["titular"] = [round(d_tit[h]["cota"], 3) for h in HORIZ]
    completa["titular"] = [round(x["cota"], 2) for x in d_tit]
    if base and (_leer(F_TIT, {"promovidos": []}).get("promovidos")):
        try:
            d_ant, _ = simular(_copia(base[0]), _copia(base[1]), par, horizonte=max(HORIZ))
            tray["anterior"] = [round(d_ant[h]["cota"], 3) for h in HORIZ]
        except Exception as e:
            log(f"Laboratorio: anterior falló: {e}")
    mod = _con_previo(mod, ts)
    mod["_datos_robot"] = {"ccs_rendimiento": ((datos.get("robot") or {}).get("ccs_rendimiento"))}   # factor de Coca Codo de esta corrida (ccs_por_regimen)
    mod["_tit_1d"] = round(d_tit[1]["cota"], 3)
    mod["_par"] = par; mod["_fisica"] = datos.get("fisica") or {}   # reparto_reciente: parámetros y balance real de Celec   # cota a 1 día del titular de ESTA corrida (la usan entrada_por_pendiente*)
    for cid, c in CANDIDATOS.items():
        if cid in (_leer(F_TIT, {"promovidos": []}).get("promovidos") or []):
            continue
        try:
            r = c["f"](_copia(P), _copia(ctx), _copia(mod))
            if not r:
                continue
            par_c = r[1].pop("_par", None) or par          # un candidato puede cambiar un parámetro calibrado (solo en su copia)
            di, _ = simular(r[0], r[1], par_c, horizonte=HORIZ_REGION)
            tray[cid] = [round(di[h]["cota"], 3) for h in HORIZ]
            completa[cid] = [round(x["cota"], 2) for x in di]
        except Exception as e:
            log(f"Laboratorio: {cid} falló: {e}")
    reg = _leer(F_PRED, {"corridas": []})
    reg["corridas"] = [x for x in reg["corridas"] if x["ts"] != ts] + [
        {"ts": ts, "cota": datos["cota"], "tray": tray, "rasgos": _rasgos(P, ctx, mod, datos)}]
    lim = (datetime.fromisoformat(ts) - timedelta(days=40)).isoformat()
    reg["corridas"] = sorted([x for x in reg["corridas"] if x["ts"] >= lim], key=lambda x: x["ts"])
    _escribir(F_PRED, reg, compacto=True)
    marc = marcador(reg, conf, ts)
    marc["ultima_corrida"] = {"ts": ts, "cota": datos["cota"], "trayectorias": completa}   # para la región de proyección de los mejores
    _escribir(F_MARC, marc)
    return marc


def _reales(reg):
    """Cota real de Celec en cada corrida (la del laboratorio y, para los primeros días, registro/predicciones.json)."""
    real = {}
    for x in _leer(os.path.join("registro", "predicciones.json"), []):
        if x.get("ts") and isinstance(x.get("cota"), (int, float)):
            real[x["ts"]] = float(x["cota"])
    for x in reg["corridas"]:
        real[x["ts"]] = float(x["cota"])
    return real


def _spearman(xs, ys):
    n = len(xs)
    if n < 8:
        return None
    def rango(v):
        o = sorted(range(n), key=lambda i: v[i]); r = [0.0] * n; i = 0
        while i < n:
            j = i
            while j + 1 < n and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2.0
            i = j + 1
        return r
    rx, ry = rango(xs), rango(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx)); sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return round(sxy / (sx * sy), 2) if sx > 0 and sy > 0 else None


def marcador(reg, conf, ts_ahora):
    real = _reales(reg)
    t_ahora = datetime.fromisoformat(ts_ahora)
    desde_corto = t_ahora - timedelta(days=conf["ventana_dias"])                     # 1 a 5 días
    desde_largo = t_ahora - timedelta(days=conf.get("ventana_largo_dias", 14))       # 7, 10 y 14 días
    err = {}            # err[modelo][h] = [(fecha_objetivo, |error|, error)]
    mov = {}            # mov[modelo][h] = [(movimiento real, movimiento predicho)] desde la cota de la corrida (análisis)
    pares = {}          # pares[modelo][h] = [(|error modelo|, |error titular|)] en las MISMAS corridas
    casos_imp = []      # (rasgos, error del titular a 1 día)
    for x in reg["corridas"]:
        t0 = datetime.fromisoformat(x["ts"])
        for i, h in enumerate(HORIZ):
            obj = (t0 + timedelta(days=h)).isoformat(timespec="minutes")
            if obj not in real or datetime.fromisoformat(obj) < (desde_largo if h >= 7 else desde_corto):
                continue
            et = x["tray"]["titular"][i] - real[obj] if "titular" in x["tray"] else None
            for m, tr in x["tray"].items():
                e = tr[i] - real[obj]
                err.setdefault(m, {}).setdefault(h, []).append((obj[:10], abs(e), e))
                if x.get("cota") is not None:
                    mov.setdefault(m, {}).setdefault(h, []).append((real[obj] - x["cota"], tr[i] - x["cota"]))
                if m != "titular" and et is not None:
                    pares.setdefault(m, {}).setdefault(h, []).append((abs(e), abs(et)))
            if h == 1 and "titular" in x["tray"]:
                casos_imp.append((x.get("rasgos") or {}, x["tray"]["titular"][i] - real[obj]))
    res = {"actualizado": ts_ahora, "ventana_dias": conf["ventana_dias"], "modelos": {}}
    for m, porh in err.items():
        res["modelos"][m] = {str(h): {"n": len(v), "dias": len({d for d, _, _ in v}),
                                      "error_medio_m": round(sum(a for _, a, _ in v) / len(v), 3),
                                      "sesgo_m": round(sum(e for _, _, e in v) / len(v), 3),
                                      "mediana_m": round(sorted(a for _, a, _ in v)[len(v) // 2], 3)} for h, v in sorted(porh.items())}
        for h, v in porh.items():   # análisis de aciertos (Luis, 31 oct): tramos acumulados, p90, dirección, eficiencia
            ab = sorted(round(a, 2) for _, a, _ in v); mv = (mov.get(m) or {}).get(h) or []
            st_h = res["modelos"][m][str(h)]
            st_h["hasta"] = {str(c): sum(1 for a in ab if a <= c / 100 + 1e-9) for c in (5, 10, 15, 20, 30, 40)}
            st_h["p90_m"] = ab[min(len(ab) - 1, int(0.9 * len(ab)))]
            if mv:
                # dirección: solo días en que Mazar de verdad se movió (≥ 1 cm); un pronóstico de "queda igual" (< 1 cm) no acierta
                dv = [(r_, p_) for r_, p_ in mv if abs(r_) >= 0.01 - 1e-9]
                if dv: st_h["direccion"] = round(sum(1 for r_, p_ in dv if abs(p_) >= 0.01 - 1e-9 and (r_ > 0) == (p_ > 0)) / len(dv), 3)
                st_h["persistencia_m"] = round(sum(abs(r_) for r_, _ in mv) / len(mv), 3)
        if m in CANDIDATOS:
            res["modelos"][m]["_info"] = {k: CANDIDATOS[m][k] for k in ("hipotesis", "origen", "promocion")}
    # veredicto de cada candidato frente al titular, comparando SOLO las corridas en que corrieron los dos
    ver = {}
    def rel(m, h):
        pp = (pares.get(m) or {}).get(h) or []
        if not pp: return None
        sm, st_ = sum(a for a, _ in pp), sum(b for _, b in pp)
        return 1 - sm / st_ if st_ > 0 else 0.0
    for m, v in res["modelos"].items():
        if m == "titular":
            continue
        a1 = v.get("1")
        mejora = rel(m, 1)
        if not a1 or mejora is None:
            ver[m] = {"estado": "sin datos"}; continue
        def peor(h, tol):
            r = rel(m, int(h))
            return bool(r is not None and r < -tol)
        def dias_h(h):
            return (v.get(str(h)) or {}).get("dias", 0)
        suficiente = a1["dias"] >= conf["dias_min"] and a1["n"] >= conf["casos_min"]
        largo_ok = dias_h(7) >= conf.get("dias_min_7d", 5) and dias_h(14) >= conf.get("dias_min_14d", 5)
        if mejora <= -conf["mejora_min"] and suficiente:
            estado = "pierde"
        elif not suficiente:
            estado = "midiendo"
        elif mejora < conf["mejora_min"]:
            estado = "empate"
        elif peor("3", conf["tolerancia_3d"]) or peor("7", conf["tolerancia_7d"]) or peor("14", conf.get("tolerancia_14d", 0.05)):
            estado = "empeora a largo plazo"
        elif not largo_ok:
            estado = "esperando 7 y 14 días"
        else:
            estado = "listo"
        med = a1.get("mediana_m")
        nivel = None if med is None else ("objetivo" if med * 100 <= conf.get("objetivo_cm", 5) else "posible" if med * 100 <= conf.get("posible_cm", 7) else "lejos")
        ver[m] = {"estado": estado, "mejora_1d": round(mejora, 3), "dias": a1["dias"], "casos": a1["n"],
                  "falta_dias": max(0, conf["dias_min"] - a1["dias"]), "mediana_1d_m": med, "nivel": nivel,
                  "mejora_7d": None if rel(m, 7) is None else round(rel(m, 7), 3), "mejora_14d": None if rel(m, 14) is None else round(rel(m, 14), 3),
                  "dias_7d": dias_h(7), "dias_14d": dias_h(14)}
    res["veredicto"] = ver
    t1 = (res["modelos"].get("titular") or {}).get("1") or {}
    if t1.get("mediana_m") is not None:
        mt = t1["mediana_m"] * 100
        res["titular_nivel"] = {"mediana_1d_cm": round(mt, 1), "nivel": "objetivo" if mt <= conf.get("objetivo_cm", 5) else "posible" if mt <= conf.get("posible_cm", 7) else "lejos"}
    # importancia de variables: qué tanto se relaciona cada una con el error del titular a 1 día
    imp = {}
    if len(casos_imp) >= 8:
        claves = sorted({k for r, _ in casos_imp for k, v in r.items() if isinstance(v, (int, float))})
        for k in claves:
            par_ = [(r[k], e) for r, e in casos_imp if isinstance(r.get(k), (int, float))]
            if len(par_) < 8 or len({a for a, _ in par_}) < 3:
                continue
            xs = [a for a, _ in par_]
            imp[k] = {"con_error": _spearman(xs, [e for _, e in par_]),
                      "con_error_abs": _spearman(xs, [abs(e) for _, e in par_]), "n": len(par_)}
        imp = dict(sorted(imp.items(), key=lambda kv: -abs(kv[1]["con_error_abs"] or 0)))
    res["importancia_1d"] = imp
    res["config"] = conf
    res["candidatos"] = {k: {kk: c[kk] for kk in ("hipotesis", "origen", "promocion", "nombre") if kk in c} for k, c in CANDIDATOS.items()}
    res["corridas_registradas"] = len(reg["corridas"])
    return res


def promover(marc, conf, log=print):
    """Reemplazo automático (solo si config.promocion_automatica = true). Devuelve el aviso para Luis o None.
    También revierte: si el titular anterior vuelve a ganar con la misma regla durante `revertir_dias`, se deshace el
    último reemplazo."""
    if not conf.get("promocion_automatica") or marc["actualizado"][:10] < conf.get("activar_desde", ""):
        return None
    tit = _leer(F_TIT, {"promovidos": []})
    va = (marc.get("veredicto") or {}).get("anterior")
    if tit.get("promovidos") and va and va.get("mejora_1d", 0) >= conf["mejora_min"] and va.get("dias", 0) >= conf["revertir_dias"]:
        m = tit["promovidos"].pop()
        _escribir(F_TIT, tit)
        hist = _leer(F_HIST, [])
        hist.append({"ts": marc["actualizado"], "accion": "revertido", "modelo": m, "mejora_anterior_1d": va["mejora_1d"]})
        _escribir(F_HIST, hist)
        aviso = f"Laboratorio: se revierte {m}; el modelo anterior acierta {round(va['mejora_1d'] * 100)} % más a 1 día"
        log(aviso)
        return aviso
    listos = [(m, v) for m, v in (marc.get("veredicto") or {}).items()
              if v.get("estado") == "listo" and m in CANDIDATOS and CANDIDATOS[m]["promocion"] == "auto"]
    if not listos:
        return None
    m, v = max(listos, key=lambda kv: kv[1]["mejora_1d"])
    if m in tit["promovidos"]:
        return None
    tit["promovidos"].append(m)
    tit["desde"] = marc["actualizado"]
    _escribir(F_TIT, tit)
    hist = _leer(F_HIST, [])
    hist.append({"ts": marc["actualizado"], "accion": "promovido", "modelo": m, "mejora_1d": v["mejora_1d"],
                 "dias": v["dias"], "casos": v["casos"]})
    _escribir(F_HIST, hist)
    aviso = f"Laboratorio: {m} pasa a titular (acierta {round(v['mejora_1d'] * 100)} % más a 1 día en {v['dias']} días)"
    log(aviso)
    return aviso


# ---------------------------------------------------------------- auditor Claude 30 oct (14:36): combinaciones
# Lo que se ve en aciertos al 30 oct: a 1 día el titular viene diciendo de menos varias corridas seguidas (−0,74 … −0,26 m)
# y a 5–10 días es mucho peor que "la cota no cambia" (semana: 2,41 m vs 1,22 a 5 días; 4,39 vs 1,14 a 7 días). Dos
# mecanismos de la tanda atacan cada cosa por separado; aquí se prueban juntos, sin contar dos veces el primer día.

def c_corrige_y_sesgo(P, ctx, mod):
    """Corrección del error de las 3 últimas verificaciones (día 0, se apaga en ~1 día) + media corrección del sesgo
    por plazo solo desde el día 1 (así el primer día no se corrige dos veces). Estricta: si falta una de las dos, no corre."""
    r = _corr_error(P, ctx, mod, 3, 1.0)
    if not r:
        return None
    P, ctx, _ = r
    r2 = _sesgo_plazo(P, ctx, mod, 0.5, desde=1)
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {"memoria": ctx["memoria"]}


def c_ajustes_completos(P, ctx, mod):
    """Autoajuste con el valor medido entero + Paute con el ajuste observado entero (los dos ajustes que el robot ya
    calcula y publica, sin recortar). Estricta: si falta uno, no corre."""
    r = c_autoajuste_completo(P, ctx, mod)
    if not r:
        return None
    P, ctx, _ = r
    r2 = _paute_fuerza(P, ctx, mod, "observado")
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {"ajuste": ctx["ajuste"], "serieMazar": ctx["serieMazar"]}


def _cand_auditor(cid, f, prom, nombre, hip):
    CANDIDATOS[cid] = {"f": f, "promocion": prom, "origen": "auditor 2026-10-30", "nombre": nombre, "hipotesis": hip}


_cand_auditor("corrige_y_sesgo", c_corrige_y_sesgo, "luis", "Corrige el error reciente y el sesgo largo",
              "Corregir el error de las 3 últimas verificaciones en el primer día y la mitad del sesgo por plazo desde el día 1 "
              "baja el error a 1 día hacia 5 cm y además mejora 7 y 14 días (cada mecanismo solo arregla una de las dos cosas).")
_cand_auditor("ajustes_completos", c_ajustes_completos, "auto", "Autoajuste y Paute sin recortar",
              "Usar enteros los dos ajustes medidos (autoajuste 0,66 en vez de 0,84 y Paute 135 % en vez de 111 %) quita el "
              "pesimismo de la bajada y de la entrada a la vez; si solo uno ayuda, se verá contra autoajuste_completo y paute_ajuste_completo.")


# ---------------------------------------------------------------- auditor Claude 1 nov (14:36): el sesgo por plazo
# Marcador al 1 nov (2 días medidos a 1 día): el titular vuelve a decir DE MENOS (sesgo −0,35 m; la cota subió 1,33 m
# en 24 h y predijo +0,38) y el mejor es sesgo_plazo_100 (+20 %), luego sesgo_plazo_50 (+11 %). El sesgo que usan mezcla
# verificaciones de versiones viejas del modelo (−0,15 m a 1 día con todo; −0,31 solo desde el modelo corregido del
# 28 oct 20:00). Tres variantes del mecanismo que va ganando, distintas entre sí:

VER_DESDE = "2026-10-28T20:00"   # verificaciones solo de corridas con el modelo corregido (CONTEXTO §4)


def _sesgo_reciente(mod, n_min=10):
    """Sesgo medio (predicho − real, m) por plazo, solo con verificaciones de corridas desde VER_DESDE cuyo objetivo
    ya pasó (obj_ts ≤ hora de esta corrida): sin datos del futuro. Devuelve {h: sesgo} con plazos de ≥ n_min casos."""
    ver = _leer_json_lab(os.path.join("registro", "verificacion.json"))
    if not isinstance(ver, list):
        return {}
    if not mod.get("_ts"):
        return {}            # sin la hora de la corrida no se puede asegurar que no hay datos del futuro (revisor)
    ahora = str(mod["_ts"])[:16]
    por, dias = {}, {}
    for x in ver:
        try:
            if str(x["pred_ts"])[:16] >= VER_DESDE and str(x["obj_ts"])[:16] <= ahora and isinstance(x.get("err"), (int, float)):
                por.setdefault(int(x["h"]), []).append(float(x["err"]))
                dias.setdefault(int(x["h"]), set()).add(str(x["pred_ts"])[:10])
        except Exception:
            continue
    return {h: sum(v) / len(v) for h, v in por.items() if len(v) >= n_min and len(dias.get(h, ())) >= 2}


def c_sesgo_plazo_reciente(P, ctx, mod):
    """Como sesgo_plazo_100, pero con el sesgo medido solo desde el modelo corregido (plazos con ≥ 10 casos; más allá
    del último plazo medido no se corrige nada más: la corrección acumulada se queda donde está)."""
    s_h = _sesgo_reciente(mod)
    if len(s_h) < 2:
        return None
    m2 = dict(mod)
    m2["aciertos"] = {"por_horizonte": {str(h): {"n": 30, "sesgo_m": v} for h, v in s_h.items()}}
    return _sesgo_plazo(P, ctx, m2, 1.0)


def c_sesgo_y_error6(P, ctx, mod):
    """Error de las 6 últimas verificaciones a 1 día en el día 0 (se apaga en ~1 día) + sesgo por plazo ENTERO desde
    el día 1 (sin corregir dos veces el primer día). Estricta: si falta una de las dos, no corre."""
    r = _corr_error(P, ctx, mod, 6, 1.0)
    if not r:
        return None
    P, ctx, _ = r
    r2 = _sesgo_plazo(P, ctx, mod, 1.0, desde=1)
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {"memoria": ctx["memoria"]}


def c_ajustes_y_sesgo50(P, ctx, mod):
    """ajustes_completos (autoajuste y Paute sin recortar: atacan la causa física) + la mitad del sesgo por plazo
    (lo que quede). Estricta: si falta una pieza, no corre."""
    r = c_ajustes_completos(P, ctx, mod)
    if not r:
        return None
    P, ctx, cm = r
    r2 = _sesgo_plazo(P, ctx, mod, 0.5)
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {**cm, "memoria": ctx["memoria"]}


def _cand_1nov(cid, f, nombre, hip, origen="auditor 2026-11-01"):
    CANDIDATOS[cid] = {"f": f, "promocion": "luis", "origen": origen, "nombre": nombre, "hipotesis": hip}


_cand_1nov("sesgo_plazo_reciente", c_sesgo_plazo_reciente, "Sesgo por plazo solo del modelo corregido",
           "El sesgo por plazo con todas las verificaciones mezcla versiones viejas del modelo (−0,15 m a 1 día); medido solo "
           "desde el modelo corregido del 28 oct es −0,31 m a 1 día y −1,24 a 3. Quitar ese sesgo reciente entero baja el "
           "error a 1 y 3 días más que sesgo_plazo_100 y, como no extrapola más allá de lo medido, no sobrecorrige a 7–14 días. "
           "Ojo: la ventana crece desde el 28 oct, así que los plazos de 5–14 días se irán sumando a medida que lleguen a 10 casos de ≥ 2 días.")
_cand_1nov("sesgo_y_error6", c_sesgo_y_error6, "Error de las 6 últimas + sesgo entero",
           "Las dos correcciones que van mejor por separado (sesgo_plazo_100 +20 % y corrige_error_6 +1 % a 1 día) juntas, sin "
           "contar dos veces el primer día (el sesgo empieza el día 1; la cola del error aún suma ~13 m³/s ese día): el error reciente arregla mañana y el sesgo entero los días 2–14.",
           origen="idea de Gemini 2026-11-01 (respuesta cortada), armada por el auditor")
_cand_1nov("ajustes_y_sesgo50", c_ajustes_y_sesgo50, "Ajustes sin recortar + mitad del sesgo",
           "Si parte del pesimismo es físico (autoajuste y Paute recortados), corregirlo en la causa (ajustes_completos) y "
           "quitar además la mitad del sesgo medido del titular acierta como sesgo_plazo_100 a 1 día sin sobrecorregir a 7 y 14 días.")


# ---------- Auditor 2 nov: 3 propuestas de Gemini (frenadas por la validación automática solo por usar una función
# interna o lambda, no por riesgo; armadas aquí con los mismos ayudantes) + 2 hipótesis del auditor. Todas "luis":
# cambian la metodología (memoria/corrección por error o sesgo, o la demanda).
# Marcador al 2 nov 13:00 (3 días, 27 casos a 1 día): titular mediana 44 cm ("lejos"), sesgo −0,45 m a 1 día; la cota
# subió +1,09 m en 24 h y el error a 1 día se fue cerrando (−0,70 → −0,05 → +0,06 m en las últimas corridas).

def _corr_error_pesos(P, ctx, mod, pesos, tau):
    """Como _corr_error, pero promedio PONDERADO de las últimas len(pesos) verificaciones a 1 día (la última pesa
    pesos[-1]): sigue antes el giro del error cuando la racha ya se está cerrando."""
    ac = mod.get("aciertos") or {}
    rec = [x for x in (ac.get("recientes_1d") or []) if isinstance(x.get("err"), (int, float)) and x.get("obj_ts")]
    k = len(pesos)
    if len(rec) < k:
        return None
    rec = sorted(rec, key=_obj_ts)[-k:]
    try:
        hoy = datetime.fromisoformat(str(mod.get("_ts") or rec[-1]["obj_ts"]))
        dif = (hoy - datetime.fromisoformat(rec[-1]["obj_ts"])).total_seconds()
        if dif > 12 * 3600 or dif < 0:
            return None           # verificaciones viejas (o posteriores a la corrida): no corrige
    except Exception:
        pass
    e = sum(x["err"] * w for x, w in zip(rec, pesos)) / float(sum(pesos))
    q0 = max(-60.0, min(60.0, -e * _dvdz(ctx, mod) / 0.0864))
    corr = [q0 * math.exp(-d / tau) for d in range(60)]
    m = _sumar_memoria(ctx, corr)
    return P, ctx, {"memoria": m}


def _obj_ts(x):
    return str(x.get("obj_ts"))


def c_sesgo_plazo_75(P, ctx, mod):
    return _sesgo_plazo(P, ctx, mod, 0.75)


def c_coca_real_y_sesgo50(P, ctx, mod):
    """coca_rio_real + la mitad del sesgo por plazo. Estricta: si falta una pieza, no corre."""
    r = c_coca_rio_real(P, ctx, mod)
    if not r:
        return None
    P, ctx, cm = r
    r2 = _sesgo_plazo(P, ctx, mod, 0.5)
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {**cm, "memoria": ctx["memoria"]}


def c_corrige_tendencia_3(P, ctx, mod):
    return _corr_error_pesos(P, ctx, mod, (1.0, 2.0, 3.0), 1.0)


def _sesgo_ventana(mod, dias=7, n_min=10):
    """Sesgo medio (predicho − real, m) por plazo con verificaciones de corridas de los últimos `dias` días (y desde el
    modelo corregido, VER_DESDE) cuyo objetivo ya pasó: sin datos del futuro."""
    ver = _leer_json_lab(os.path.join("registro", "verificacion.json"))
    if not isinstance(ver, list) or not mod.get("_ts"):
        return {}
    ahora = str(mod["_ts"])[:16]
    try:
        desde = max(VER_DESDE, (datetime.fromisoformat(ahora) - timedelta(days=dias)).isoformat(timespec="minutes")[:16])
    except Exception:
        return {}
    por, dd = {}, {}
    for x in ver:
        try:
            if str(x["pred_ts"])[:16] >= desde and str(x["obj_ts"])[:16] <= ahora and isinstance(x.get("err"), (int, float)):
                por.setdefault(int(x["h"]), []).append(float(x["err"]))
                dd.setdefault(int(x["h"]), set()).add(str(x["pred_ts"])[:10])
        except Exception:
            continue
    return {h: sum(v) / len(v) for h, v in por.items() if len(v) >= n_min and len(dd.get(h, ())) >= 2}


def c_sesgo_reciente_7d(P, ctx, mod):
    """Como sesgo_plazo_reciente, con ventana móvil de 7 días (sugerencia del revisor independiente, 1 nov): olvida
    los regímenes viejos (sequía de fines de octubre) cuando cambia el tiempo."""
    s_h = _sesgo_ventana(mod, 7)
    if len(s_h) < 2:
        return None
    m2 = dict(mod)
    m2["aciertos"] = {"por_horizonte": {str(h): {"n": 30, "sesgo_m": v} for h, v in s_h.items()}}
    return _sesgo_plazo(P, ctx, m2, 1.0)


def c_demanda_real_y_sesgo50(P, ctx, mod):
    """demanda_real (demanda medida del Cenace, sin memoria) + la mitad del sesgo por plazo. Estricta."""
    r = _demanda_real(P, ctx, mod)
    if not r:
        return None
    P, ctx, cm = r
    r2 = _sesgo_plazo(P, ctx, mod, 0.5)
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {**cm, "memoria": ctx["memoria"]}


def _cand_2nov(cid, f, nombre, hip, origen="auditor 2026-11-02"):
    CANDIDATOS[cid] = {"f": f, "promocion": "luis", "origen": origen, "nombre": nombre, "hipotesis": hip}


_cand_2nov("sesgo_plazo_75", c_sesgo_plazo_75, "Quita 75 % del sesgo por plazo",
           "Punto intermedio entre sesgo_plazo_50 (+9 % a 1 día) y sesgo_plazo_100 (+18 %): casi toda la ganancia a 1 día con "
           "menos riesgo de sobrecorregir a 7 y 14 días si cambia el régimen.",
           origen="Gemini 2026-11-02 (frenada por la validación por una función interna; armada por el auditor)")
_cand_2nov("coca_real_y_sesgo50", c_coca_real_y_sesgo50, "Río Coca real + mitad del sesgo",
           "El río Coca con su pronóstico real (menos pesimista a 2–3 días) más la mitad del sesgo por plazo (mejor a 1 día): "
           "juntos bajan el error a 1 día sin el pesimismo del titular a 3–14 días.",
           origen="Gemini 2026-11-02 (frenada por la validación por una función interna; armada por el auditor)")
_cand_2nov("corrige_tendencia_3", c_corrige_tendencia_3, "Corrige el error reciente (la última pesa más)",
           "Como corrige_error_3, pero con pesos 1-2-3 (la verificación más nueva pesa la mitad): cuando el error ya se está "
           "cerrando (−0,70 → −0,05 m el 2 nov) no arrastra tanto los errores viejos.",
           origen="Gemini 2026-11-02 (frenada por la validación por usar lambda; armada por el auditor)")
_cand_2nov("sesgo_reciente_7d", c_sesgo_reciente_7d, "Sesgo por plazo de los últimos 7 días",
           "El sesgo cambia con el régimen (31 oct +12 cm, 1–2 nov −35 a −45 cm a 1 día). Medirlo solo con la última semana "
           "(plazos con ≥ 10 casos de ≥ 2 días) sigue el cambio de sequía a lluvias y baja el error a 1–3 días; como no "
           "extrapola más allá de lo medido, no sobrecorrige a 7–14 días. Hasta el 4 nov es igual a sesgo_plazo_reciente "
           "(la ventana empieza en el modelo corregido del 28 oct 20:00); se separan desde el 4 nov a las 20:00.")
_cand_2nov("demanda_real_y_sesgo50", c_demanda_real_y_sesgo50, "Demanda real + mitad del sesgo",
           "Las dos mejores ideas por separado (demanda_real +39 % a 1 día con 5 casos; sesgo_plazo_50 +9 % con 21) atacan "
           "causas distintas (cuánto genera Paute y el pesimismo que crece con el plazo): juntas deberían sumar. Ojo: como "
           "demanda_real, va SIN la memoria de 48 h (la memoria es solo la corrección del sesgo) y el sesgo restado es el del titular.")


# ---------------------------------------------------------------- 3 nov: el caudal de hoy desde la pendiente de la cota
def _ts_dt(x):
    return datetime.fromisoformat(str(x)[:16])


def _entrada_por_pendiente(P, ctx, mod, horas):
    """Investigador (Fable) y Luis, 3 nov. Con Mazar en 0 MWh la subida de la cota ES el caudal de entrada, pero el titular
    usa el caudal del Celec de las 08:00 (del día anterior) más la memoria de 48 h: va ~1,5 días atrasado y dice de menos
    cuando la lluvia arrecia y de más cuando afloja. Cambia UNA pieza: el caudal de los días 0 y 1, que se acerca al que
    muestra la pendiente observada de la cota en las últimas `horas` horas. Del día 2 en adelante el caudal es igual al
    del titular (la cota queda desplazada ~2·corrección a 3, 7 y 14 días, lo que también se mide).
    Freno por desaceleración (revisor, 3 nov): no corrige hacia arriba si la pendiente de 6 h es menor que la de 12 h
    (el río ya está bajando), ni hacia abajo si es mayor.
    Freno antinervios: solo corrige si la diferencia entre la pendiente observada y la del titular pasa de 0,25 m/día, con
    el mismo signo, en esta corrida y en la anterior; peso 0,6 si llovió >10 mm en el Paute en 2 de los 3 días previos
    (si no, 0,3); la corrección tope es ±0,3 m/día. Si no corresponde corregir, devuelve el titular sin cambios (así se
    compara en todas las corridas). Solo usa datos anteriores a la corrida (sin datos del futuro)."""
    sin_cambio = (P, ctx, {"memoria": list(ctx.get("memoria") or [])})
    if not mod.get("_ts"):
        return None
    ahora = _ts_dt(mod["_ts"]); hoy = ahora.date().isoformat()
    cel = _leer_json_lab(os.path.join("historial", "celec_diario.json")) or {}
    dias_cel = [d for d in sorted(cel) if d < hoy]
    if not dias_cel or float(cel[dias_cel[-1]].get("maz") or 0) > 0:
        return sin_cambio                      # Mazar turbinando: la pendiente ya no es solo el caudal
    runs = []
    for x in _leer(os.path.join("registro", "predicciones.json"), []) or []:
        try:
            if isinstance(x.get("cota"), (int, float)) and _ts_dt(x["ts"]) < ahora:
                runs.append((_ts_dt(x["ts"]), float(x["cota"]), (x.get("cota_pred") or {}).get("1")))
        except Exception:
            continue
    runs.sort(key=lambda r: r[0])
    if len(runs) < 3 or (ahora - runs[-1][0]).total_seconds() > 5 * 3600:
        return sin_cambio
    def pendiente(t_fin, c_fin, h=horas):
        tol = 3 if h >= 12 else 2
        obj = t_fin - timedelta(hours=h)
        cand = [r for r in runs if r[0] < t_fin and abs((r[0] - obj).total_seconds()) <= tol * 3600]
        if not cand:
            return None
        r0 = min(cand, key=lambda r: abs((r[0] - obj).total_seconds()))
        dt_d = (t_fin - r0[0]).total_seconds() / 86400
        return (c_fin - r0[1]) / dt_d if dt_d > 0.1 else None

    def dif(t_fin, c_fin, previa):      # pendiente observada − pendiente a 1 día del titular de la corrida previa
        s = pendiente(t_fin, c_fin)
        if s is None or not isinstance(previa[2], (int, float)):
            return None
        return s - (float(previa[2]) - previa[1])

    s_hoy = pendiente(ahora, float(ctx["cota"]))
    tit1 = mod.get("_tit_1d")
    d_hoy = (s_hoy - (float(tit1) - float(ctx["cota"]))) if (s_hoy is not None and isinstance(tit1, (int, float))) else dif(ahora, float(ctx["cota"]), runs[-1])
    d_ant = dif(runs[-1][0], runs[-1][1], runs[-2])
    if d_hoy is None or d_ant is None or abs(d_hoy) < 0.25 or abs(d_ant) < 0.25 or d_hoy * d_ant < 0:
        return sin_cambio
    g = _leer(os.path.join("registro", "generacion.json"), {}) or {}
    ll = g.get("lluvia") or {}
    previos = [v for d, v in zip(ll.get("dias") or [], ll.get("paute") or []) if d < hoy][-3:]
    peso = 0.6 if sum(1 for v in previos if isinstance(v, (int, float)) and v > 10) >= 2 else 0.3
    corr_m = max(-0.3, min(0.3, peso * d_hoy))          # m/día
    s6, s12 = pendiente(ahora, float(ctx["cota"]), 6), pendiente(ahora, float(ctx["cota"]), 12)
    if s6 is not None and s12 is not None and ((corr_m > 0 and s6 < s12) or (corr_m < 0 and s6 > s12)):
        return sin_cambio                                # ya cambió el ritmo: seguir la pendiente vieja sería otro retraso
    q = corr_m * _dvdz(ctx, mod) / 0.0864               # m³/s que explican esa pendiente
    m = _sumar_memoria(ctx, [q, q] + [0.0] * 58)        # ceros: simular repite el último valor de la memoria
    _anotar_activacion(mod["_ts"], horas, corr_m)
    return P, ctx, {"memoria": m}


def _anotar_activacion(ts, horas, corr_m):
    """Registro de cuándo se activó (laboratorio/activaciones_pendiente.json): antes de promover se exige ver varios
    episodios, no solo días de empate con el titular."""
    try:
        f = os.path.join(DIR, "activaciones_pendiente.json")
        reg = _leer(f, []) or []
        cid = "entrada_por_pendiente" + ("" if horas >= 12 else "_6h")
        reg = [x for x in reg if not (x.get("ts") == str(ts)[:16] and x.get("cid") == cid)]
        reg.append({"ts": str(ts)[:16], "cid": cid, "corr_m": round(corr_m, 3)})
        _escribir(f, reg[-500:])
    except Exception:
        pass


def c_entrada_por_pendiente(P, ctx, mod):
    return _entrada_por_pendiente(P, ctx, mod, 12)


def c_entrada_por_pendiente_6h(P, ctx, mod):
    return _entrada_por_pendiente(P, ctx, mod, 6)


def _cand_3nov(cid, f, nombre, hip, origen="Investigador (Fable) 2026-11-03, encargo de Luis"):
    CANDIDATOS[cid] = {"f": f, "promocion": "luis", "origen": origen, "nombre": nombre, "hipotesis": hip}


_cand_3nov("entrada_por_pendiente", c_entrada_por_pendiente, "Caudal de hoy según la subida de la cota (12 h)",
           "Con Mazar en 0 MWh el error a 1 día ≈ (caudal de hace ~1,5 días − caudal de hoy)/60 m: el titular reacciona tarde "
           "(1 nov −0,70 m, 2 nov +0,33 m). Si la pendiente de la cota de las últimas 12 h se aparta más de 0,25 m/día de la "
           "del titular en dos corridas seguidas, los días 0 y 1 usan un caudal más cercano al observado (peso 0,6 con "
           "lluvia sostenida en el Paute, 0,3 si no; tope ±0,3 m/día). Del día 2 en adelante, igual al titular.")
_cand_3nov("entrada_por_pendiente_6h", c_entrada_por_pendiente_6h, "Caudal de hoy según la subida de la cota (6 h)",
           "Igual que entrada_por_pendiente con ventana de 6 h: reacciona antes al cambio de ritmo; sirve para medir cuánto "
           "nerviosismo agrega frente a la ventana de 12 h.")


# ---------- Auditor 3 nov: tendencia de 24 h + propuestas de Gemini corregidas ----------
# Marcador al 3 nov (4 días, 35 casos a 1 día): titular mediana 32,5 cm, error medio 0,45 m, sesgo −0,28 m; a 3 días
# sesgo −0,97 m. La familia "corrige con el error reciente" pierde 42 % a 1 día (el error cambia de signo de un día a otro:
# corregir con el de ayer lo amplifica) y el sesgo por plazo completo pierde a 1 día cuando cambia el régimen
# (sesgo_plazo_reciente −135 %, 8 casos), pero sesgo_plazo_50 gana ~38 % a 3 días. Prueba fuera de línea con las
# corridas guardadas (31 casos a 1 día): mover la cota a 1 día la mitad de la distancia entre lo que predice el titular
# y lo que la cota se movió de verdad en las últimas 24 h baja el error medio 0,425 → 0,383 m (−10 %), a 2 días −3 % y a
# 3 días −2 %.

def _cota_hace(mod, horas, tol_h=3):
    """Cota real de la corrida guardada más cercana a `horas` antes de esta (registro/predicciones.json, solo corridas
    ANTERIORES a esta: sin datos del futuro). None si no hay una a ±tol_h horas."""
    if not mod.get("_ts"):
        return None
    try:
        ahora = _ts_dt(mod["_ts"])
    except Exception:
        return None
    obj = ahora - timedelta(hours=horas)
    mejor = None
    for x in _leer(os.path.join("registro", "predicciones.json"), []) or []:
        try:
            if not isinstance(x.get("cota"), (int, float)):
                continue
            t = _ts_dt(x["ts"])
            if t >= ahora:
                continue
            dt = abs((t - obj).total_seconds())
            if dt <= tol_h * 3600 and (mejor is None or dt < mejor[0]):
                mejor = (dt, float(x["cota"]))
        except Exception:
            continue
    return mejor[1] if mejor else None


def _tendencia_24h(P, ctx, mod, peso=0.5, tope=0.5):
    """El día 0 suma el caudal que mueve la cota a 1 día `peso` × (movimiento real de las últimas 24 h − movimiento a
    1 día del titular de ESTA corrida), con tope ±`tope` m. Desde el día 1 el caudal es el del titular (la cota queda
    desplazada esa cantidad a 3, 7 y 14 días). Sin dato de hace 24 h: devuelve el titular sin cambios (se compara en
    todas las corridas)."""
    sin_cambio = (P, ctx, {"memoria": list(ctx.get("memoria") or [])})
    c24 = _cota_hace(mod, 24)
    tit1 = mod.get("_tit_1d")
    if c24 is None or not isinstance(tit1, (int, float)):
        return sin_cambio
    cota = float(ctx["cota"])
    mov_real, mov_tit = cota - c24, float(tit1) - cota
    if abs(mov_real) > 3.0:          # dato raro (más de 3 m en 24 h): no corrige
        return sin_cambio
    delta = max(-tope, min(tope, peso * (mov_real - mov_tit)))
    q = delta * _dvdz(ctx, mod) / 0.0864
    m = _sumar_memoria(ctx, [q] + [0.0] * 59)    # ceros: desde el día 1 la memoria del titular
    return P, ctx, {"memoria": m}


def c_tendencia_24h_mitad(P, ctx, mod):
    return _tendencia_24h(P, ctx, mod, 0.5)


def c_tendencia_y_sesgo50_largo(P, ctx, mod):
    """tendencia_24h_mitad en el día 0 + la mitad del sesgo por plazo desde el día 1 (el sesgo ayuda a 3 días y estorba
    a 1). Estricta: si falta el sesgo por plazo, no corre."""
    r = _tendencia_24h(P, ctx, mod, 0.5)
    P, ctx, _ = r
    r2 = _sesgo_plazo(P, ctx, mod, 0.5, desde=1)
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {"memoria": list(ctx.get("memoria") or [])}


def c_sesgo_semana(P, ctx, mod):
    """Propuesto por Gemini (3 nov), corregido por el auditor según el revisor independiente: como sesgo_plazo_100, pero
    el punto de 1 día usa el sesgo de la última semana (aciertos.semana_1d, con ≥ 30 casos); desde el día 2, el histórico."""
    ac = mod.get("aciertos") or {}
    s1 = ac.get("semana_1d") or {}
    if not isinstance(s1.get("sesgo_m"), (int, float)) or (s1.get("n") or 0) < 30:
        return None
    ph = dict(ac.get("por_horizonte") or {})
    if "1" not in ph:
        return None
    ph["1"] = {**ph["1"], "sesgo_m": float(s1["sesgo_m"]), "n": max(30, ph["1"].get("n") or 0)}
    m2 = dict(mod)
    m2["aciertos"] = {**ac, "por_horizonte": ph}
    return _sesgo_plazo(P, ctx, m2, 1.0)


def c_coca_real_cortes_7d(P, ctx, mod):
    """Propuesto por Gemini (3 nov), corregido por el auditor según el revisor independiente: coca_rio_real +
    cortes_siguen_7d. Estricta: si falta el pronóstico del río o no hay corte hoy, no corre. A 1 día no cambia nada."""
    r = c_coca_rio_real(P, ctx, mod)
    if not r:
        return None
    P, ctx, c1 = r
    r2 = c_cortes_siguen_7d(P, ctx, mod)
    if not r2:
        return None
    P, ctx, c2 = r2
    return P, ctx, {**c1, **c2}


def _cand_aud3(cid, f, nombre, hip, origen="auditor 2026-11-03"):
    CANDIDATOS[cid] = {"f": f, "promocion": "luis", "origen": origen, "nombre": nombre, "hipotesis": hip}


_cand_aud3("tendencia_24h_mitad", c_tendencia_24h_mitad, "Cota de mañana a medio camino de la tendencia de 24 h",
           "El titular va atrasado respecto al ritmo real de la cota. Mover la cota a 1 día la mitad de la distancia entre lo "
           "que predice el titular y lo que la cota se movió de verdad en las últimas 24 h (tope ±0,5 m) baja el error medio "
           "a 1 día ~10 % (prueba con 31 corridas: 0,425 → 0,383 m) sin empeorar a 2–3 días (−3 % y −2 %).")
_cand_aud3("tendencia_y_sesgo50_largo", c_tendencia_y_sesgo50_largo, "Tendencia de 24 h + medio sesgo desde el día 2",
           "tendencia_24h_mitad para el día 1 y la mitad del sesgo por plazo solo desde el día 2: a 1 día igual a "
           "tendencia_24h_mitad, y a 3–14 días corrige el pesimismo (sesgo −0,97 m a 3 días; sesgo_plazo_50 −38 % de error "
           "a 3 días en las mismas corridas).")
_cand_aud3("sesgo_semana", c_sesgo_semana, "Sesgo por plazo con el de la última semana a 1 día",
           "Como sesgo_plazo_100, pero a 1 día usa el sesgo de la última semana (semana_1d, ≥30 casos; hoy −0,135 m) en vez "
           "del acumulado: sigue antes los cambios de régimen. Desde el día 2, igual a sesgo_plazo_100.",
           origen="Gemini 2026-11-03 (corregido por el auditor)")
_cand_aud3("coca_real_cortes_7d", c_coca_real_cortes_7d, "Río Coca real + cortes siguen 7 días",
           "Suma dos fuentes independientes de pesimismo a 3–14 días: el pronóstico real del río Coca (coca_rio_real) y que "
           "los cortes de hoy sigan 7 días (cortes_siguen_7d). A 1 día no cambia nada; se mide a 3, 7 y 14 días.",
           origen="Gemini 2026-11-03 (corregido por el auditor)")


# ---------- Auditor 4 nov: reversión del caudal de Mazar hacia su promedio de 72 h ----------
# El error a 1 día del titular sube con el caudal de Mazar del día (Spearman +0,84 en importancia_1d): tras el pico del
# 1–2 nov (82 m³/s) el titular dijo de más. Hipótesis (revisada por el Claude independiente): NO quita rezago (el
# promedio de 72 h de corridas que ya usan el promedio de 24 h de Celec es MÁS lento que el titular); prueba una
# reversión a la media / suavizado tras picos. Se suma como caudal en la memoria: día 0 entero, día 1 a la mitad.
# PARA PROMOVER (requiere a Luis): memoria_corridas sobrescribe ctx["memoria"] después de aplicar_titular (robot.py),
# así que la corrección se perdería: habría que aplicarla después de la memoria; y conviene calcular el promedio con la
# serie cruda de Celec en vez de los rasgos de las corridas (repiten el valor viejo si Celec falla).

def _q_mazar_previo(mod, horas=72, n_min=6):
    """Promedio del caudal de Mazar (rasgo q_mazar) de las corridas del laboratorio de las últimas `horas`, solo
    ANTERIORES a esta corrida (sin datos del futuro). None si hay menos de n_min corridas."""
    if not mod.get("_ts"):
        return None
    try:
        ahora = _ts_dt(mod["_ts"])
    except Exception:
        return None
    vals = []
    for x in (_leer(F_PRED, {"corridas": []}).get("corridas") or []):
        try:
            t = _ts_dt(x["ts"])
            q = (x.get("rasgos") or {}).get("q_mazar")
            if ahora - timedelta(hours=horas) <= t < ahora and isinstance(q, (int, float)) and q > 0:
                vals.append(float(q))
        except Exception:
            continue
    return sum(vals) / len(vals) if len(vals) >= n_min else None


def _caudal_hacia_72h(P, ctx, mod, beta=0.5, tope=30.0):
    """Día 0: suma beta × (promedio 72 h − caudal de hoy), con tope ±tope m³/s; día 1: la mitad; después, nada.
    Estricta: sin promedio de 72 h no corre."""
    qb = _q_mazar_previo(mod)
    q0 = P.get("qMazar")
    if qb is None or not isinstance(q0, (int, float)):
        return None
    dq = max(-tope, min(tope, beta * (qb - float(q0))))
    m = _sumar_memoria(ctx, [dq, dq / 2.0] + [0.0] * 58)
    return P, ctx, {"memoria": m}


def c_caudal_72h_mitad(P, ctx, mod):
    return _caudal_hacia_72h(P, ctx, mod, 0.5)


def c_patron_hist_y_caudal72(P, ctx, mod):
    """patron_historico (deltaDia de todo el historial de Paute) + caudal_72h_mitad. Estricta: si falta uno, no corre."""
    r = c_patron_historico(P, ctx, mod)
    if not r:
        return None
    P, ctx, c1 = r
    r2 = _caudal_hacia_72h(P, ctx, mod, 0.5)
    if not r2:
        return None
    P, ctx, c2 = r2
    return P, ctx, {**c1, **c2}


def _cand_aud4(cid, f, nombre, hip, origen="auditor 2026-11-04"):
    CANDIDATOS[cid] = {"f": f, "promocion": "luis", "origen": origen, "nombre": nombre, "hipotesis": hip}


_cand_aud4("caudal_72h_mitad", c_caudal_72h_mitad, "Caudal de Mazar a medio camino de su promedio de 72 h",
           "Reversión a la media tras picos: el error a 1 día del titular sube con el caudal de Mazar del día. Llevar el "
           "caudal de los días 0–1 la mitad del camino hacia su promedio de las 72 h anteriores (día 1 a la mitad, tope ±30 "
           "m³/s) baja el error. Prueba aproximada con 41 corridas (30 oct–3 nov, la misma crecida de la que salió la idea): "
           "−7 % a 1 día, −19 % a 2 días, −9 % a 3 días; el revisor midió −5 % a 1 día en 58 corridas y vio que empeora en "
           "la bajada lenta del 3 nov. En subidas desde la base empuja en contra.")
_cand_aud4("patron_hist_y_caudal72", c_patron_hist_y_caudal72, "Patrón histórico + caudal hacia 72 h",
           "Combina el mejor a 1 día (patron_historico, −15 % en 21 casos) con caudal_72h_mitad (reversión del caudal a su "
           "media de 72 h): actúan sobre piezas distintas (día de la semana y caudal de entrada) y prueba si los efectos se "
           "suman. Prueba aproximada (21 casos de la misma muestra, 1–3 nov): −22 % a 1 día, casi todo de patron_historico; "
           "a 2–3 días muy pocos casos (13 y 3). Si caudal_72h_mitad no mejora solo en ~7 días, retirar también este.")


# ---------------------------------------------------------------- 5 nov: noviembre lluvioso en la Costa (Luis)
AC_MW_POR_C = 50.0         # el mismo coeficiente del aire acondicionado que usa el modelo (demanda = dBase + 50·(T − 32))
UMBRAL_LLUVIA_MM = 10.0


def _costa_lluviosa(P, ctx, mod, mw_dia_lluvioso):
    """Luis, 5 nov: "si las lluvias persisten en la Costa durante noviembre baja la demanda y por momentos habrá cortes
    por tormentas; lo demás se mantiene igual".
    OJO (revisor, 5 nov): el titular NO usa la temperatura de hoy para todo el mes; usa la demanda MEDIDA de la ventana
    reciente de Paute (robot.py: dBase = demanda medida + cortes − 50·(tCosta − 32), que se cancela), y esa ventana fue
    lluviosa. Por eso "si las lluvias persisten igual" ya es el titular. Este candidato agrega lo que el titular no sabe:
    los días con PRONÓSTICO en Guayaquil (registro/gye_pronostico.json, Open-Meteo; los días pasados de ese archivo son la
    serie del modelo, no mediciones) que sean más secos o más calurosos, o más lluviosos o frescos, que la ventana:
        Δ demanda = −50 MW por °C bajo la máxima media de la ventana − mw_dia_lluvioso × (lluvioso − fracción lluviosa)
    El efecto de un "día lluvioso" (nubes = menos aire acondicionado más allá de la máxima, y cortes de distribución por
    tormentas) es un SUPUESTO que el marcador calibra (dos variantes). Días sin pronóstico hasta el 30 nov: persistencia
    (Δ ≈ 0). Desde el 1 dic, nada. Solo cambia la demanda; en el modelo, todo MW menos de demanda sale de Paute.
    NO SE PUEDE PROMOVER ASÍ: va por cutPlan, que en la página es el plan de cortes anunciados (rompe el control de cortes
    y los escenarios) y la memoria de 48 h lo trataría como "corte conocido". Para promoverlo hace falta un campo de demanda
    propio (p. ej. ctx.demAjuste) con paridad en modelo.js."""
    if not mod.get("_ts"):
        return None
    ahora = datetime.fromisoformat(str(mod["_ts"])[:16]); hoy = ahora.date()
    if hoy.month != 11:
        return None
    g = _leer(os.path.join("registro", "gye_pronostico.json"), {}) or {}
    if str(g.get("generado") or "")[:10] != hoy.isoformat():
        return None                                   # pronóstico viejo: no se inventa nada
    dias, tmax, llu = g.get("dias") or [], g.get("tmax") or [], g.get("lluvia_mm") or []
    if not dias or len(dias) != len(tmax) or len(dias) != len(llu):
        return None
    serie = {d: (t, l) for d, t, l in zip(dias, tmax, llu) if t is not None and l is not None}
    ven = ((_leer("datos.json", {}) or {}).get("robot") or {}).get("cortes_semana_medida") or {}
    v0 = ven.get("desde") or (hoy - timedelta(days=7)).isoformat(); v1 = ven.get("hasta") or (hoy - timedelta(days=1)).isoformat()
    ref = [(t, l) for d, (t, l) in serie.items() if v0 <= d <= v1 and d < hoy.isoformat()]
    if len(ref) < 3:
        return None
    t_ref = sum(t for t, _ in ref) / len(ref)
    f_ref = sum(1 for _, l in ref if l >= UMBRAL_LLUVIA_MM) / len(ref)
    fin = datetime(hoy.year, 11, 30).date()
    plan = list(ctx.get("cutPlan") or []); n = 61
    plan += [None] * (n - len(plan))
    cambio = False
    for k in range(n):
        d = hoy + timedelta(days=k)
        if d > fin: break
        if d.isoformat() not in serie: continue      # sin pronóstico: persistencia = titular
        t, l = serie[d.isoformat()]
        menos = AC_MW_POR_C * (t_ref - t) + mw_dia_lluvioso * ((1.0 if l >= UMBRAL_LLUVIA_MM else 0.0) - f_ref)
        dia = (int(ctx.get("diaSemana0") or 0) + k) % 7
        base = plan[k] if isinstance(plan[k], (int, float)) and not isinstance(plan[k], bool) else \
            (P.get("cut", 0) if (not ctx.get("cutDias") or ctx["cutDias"][dia]) else 0)
        plan[k] = round(float(base) + menos, 1)       # negativo = más demanda (día seco o caluroso)
        cambio = True
    if not cambio:
        return None
    ctx["cutPlan"] = plan
    return P, ctx, {"cutPlan": plan}


def _nov_mas_lluvioso(P, ctx, mod, menos_c, mw_dia_lluvioso):
    """Luis, 5 nov: "¿qué tal si llueve MÁS de lo usual este noviembre?" (con 5 días ya casi iguala noviembre de 1997).
    Escenario, no pronóstico: hasta el 30 de noviembre TODOS los días en la Costa son lluviosos y `menos_c` °C más frescos
    que la semana medida (la que ya usa el titular). Δ demanda = −50 MW/°C × menos_c − mw_dia_lluvioso × (1 − fracción
    de días lluviosos de esa semana). Solo cambia la demanda de la Costa; el caudal del Paute, Coca Codo, térmicas y
    Colombia quedan como en el titular. Mismas salvedades que _costa_lluviosa (no se promueve vía cutPlan)."""
    if not mod.get("_ts"):
        return None
    hoy = datetime.fromisoformat(str(mod["_ts"])[:16]).date()
    if hoy.month != 11:
        return None
    g = _leer(os.path.join("registro", "gye_pronostico.json"), {}) or {}
    serie = {d: l for d, l in zip(g.get("dias") or [], g.get("lluvia_mm") or []) if l is not None}
    ven = ((_leer("datos.json", {}) or {}).get("robot") or {}).get("cortes_semana_medida") or {}
    v0 = ven.get("desde") or (hoy - timedelta(days=7)).isoformat(); v1 = ven.get("hasta") or (hoy - timedelta(days=1)).isoformat()
    ref = [l for d, l in serie.items() if v0 <= d <= v1 and d < hoy.isoformat()]
    f_ref = (sum(1 for l in ref if l >= UMBRAL_LLUVIA_MM) / len(ref)) if len(ref) >= 3 else 0.5
    menos = AC_MW_POR_C * menos_c + mw_dia_lluvioso * (1.0 - f_ref)
    fin = datetime(hoy.year, 11, 30).date()
    plan = list(ctx.get("cutPlan") or []); n = 61
    plan += [None] * (n - len(plan))
    for k in range(n):
        d = hoy + timedelta(days=k)
        if d > fin: break
        dia = (int(ctx.get("diaSemana0") or 0) + k) % 7
        base = plan[k] if isinstance(plan[k], (int, float)) and not isinstance(plan[k], bool) else \
            (P.get("cut", 0) if (not ctx.get("cutDias") or ctx["cutDias"][dia]) else 0)
        plan[k] = round(float(base) + menos, 1)
    ctx["cutPlan"] = plan
    return P, ctx, {"cutPlan": plan}


def c_nov_mas_lluvioso(P, ctx, mod): return _nov_mas_lluvioso(P, ctx, mod, 1.0, 40.0)
def c_nov_mucho_mas_lluvioso(P, ctx, mod): return _nov_mas_lluvioso(P, ctx, mod, 2.0, 100.0)


_HIP_NOV = ("Escenario de Luis (5 nov): noviembre más lluvioso que lo usual en la Costa (va camino al récord de 1997). Hasta el 30 nov "
            "todos los días lluviosos y {c} °C más frescos que la semana medida (que ya usa el titular); día lluvioso = {mw} MW menos "
            "de demanda. Solo cambia la demanda de la Costa: el caudal del Paute y lo demás, igual que el titular.")
CANDIDATOS["nov_mas_lluvioso"] = {"f": c_nov_mas_lluvioso, "promocion": "luis", "origen": "Luis 2026-11-05",
    "nombre": "Noviembre más lluvioso en la Costa (−1 °C, 40 MW)", "hipotesis": _HIP_NOV.format(c=1, mw=40)}
CANDIDATOS["nov_mucho_mas_lluvioso"] = {"f": c_nov_mucho_mas_lluvioso, "promocion": "luis", "origen": "Luis 2026-11-05",
    "nombre": "Noviembre mucho más lluvioso en la Costa (−2 °C, 100 MW)", "hipotesis": _HIP_NOV.format(c=2, mw=100)}


# ---------------------------------------------------------------- 5 nov (auditor): corrección del error reciente a media fuerza
def _corr_tendencia_fuerza(P, ctx, mod, fuerza=0.5):
    """corrige_tendencia_3 (pesos 1-2-3, tau 1 día) con el caudal de corrección multiplicado por `fuerza`.
    Usa solo verificaciones a 1 día anteriores a la corrida (las mismas guardas de _corr_error_pesos)."""
    base = list(ctx.get("memoria") or [])
    r = _corr_error_pesos(P, ctx, mod, (1.0, 2.0, 3.0), 1.0)
    if not r:
        return None
    P, ctx, _ = r
    nueva = list(ctx.get("memoria") or [])
    out = [round((base[i] if i < len(base) else 0.0) + fuerza * (nueva[i] - (base[i] if i < len(base) else 0.0)), 2)
           for i in range(len(nueva))]
    ctx["memoria"] = out
    return P, ctx, {"memoria": out}


def c_corrige_tendencia_mitad(P, ctx, mod):
    return _corr_tendencia_fuerza(P, ctx, mod, 0.5)


def c_patron_hist_y_tendencia_mitad(P, ctx, mod):
    """patron_historico + corrige_tendencia_mitad. Estricta: si falta una pieza, no corre."""
    r = c_patron_historico(P, ctx, mod)
    if not r:
        return None
    P, ctx, c1 = r
    r2 = _corr_tendencia_fuerza(P, ctx, mod, 0.5)
    if not r2:
        return None
    P, ctx, c2 = r2
    return P, ctx, {**c1, **c2}


def c_patron_tend_mitad_sesgo50_largo(P, ctx, mod):
    """patron_hist_y_tendencia_mitad + la mitad del sesgo por plazo desde el día 3 (no toca los días 0–2).
    Estricta: si falta una pieza, no corre."""
    r = c_patron_hist_y_tendencia_mitad(P, ctx, mod)
    if not r:
        return None
    P, ctx, c1 = r
    r2 = _sesgo_plazo(P, ctx, mod, 0.5, desde=3)
    if not r2:
        return None
    P, ctx, _ = r2
    return P, ctx, {**c1, "memoria": list(ctx.get("memoria") or [])}


def _cand_aud5(cid, f, nombre, hip, origen="auditor 2026-11-05"):
    CANDIDATOS[cid] = {"f": f, "promocion": "luis", "origen": origen, "nombre": nombre, "hipotesis": hip}


_cand_aud5("corrige_tendencia_mitad", c_corrige_tendencia_mitad, "Corrige el error reciente a media fuerza",
           "corrige_tendencia_3 es el mejor a 1 día (+18 % en 20 casos) pero a 2 días pierde (−22 % en 12 casos a ±1 h; "
           "−47 % en 9 a hora exacta): corrige de más. A la mitad de fuerza baja el error a 1 día sin empeorar a 2. Prueba aproximada "
           "(mitad de la diferencia guardada con el titular, 2–5 nov, cota real a ±1 h): 1 día 0,095 vs 0,148 m del titular "
           "(+36 %, 24 casos), 2 días +6 % (12). Con hora exacta, como el marcador: 1 día +38 % (20 casos) pero 2 días −17 % (9). "
           "Ojo: la fuerza se eligió con las mismas corridas y solo corre cuando hay verificación de < 12 h.")
_cand_aud5("patron_hist_y_tendencia_mitad", c_patron_hist_y_tendencia_mitad, "Patrón histórico + error reciente a media fuerza",
           "Combina las dos mejores piezas, que tocan cosas distintas: patron_historico (día de la semana de toda la historia "
           "de Paute; +7 % a 1 día, +32 % a 2, +15 % a 3) y corrige_tendencia_mitad (caudal de los días 0–2 según el error "
           "reciente). Prueba aproximada (suma de diferencias guardadas, 24 corridas pareadas): 1 día 0,090 vs 0,148 m (+39 %), "
           "2 días 0,128 vs 0,245 m (+48 %, 12 casos), con cota real a ±1 h; con hora exacta +41 % (20) y +43 % (9). Pocos casos y "
           "misma muestra: puede ir peor en vivo.")
_cand_aud5("patron_tend_mitad_sesgo50_largo", c_patron_tend_mitad_sesgo50_largo, "Patrón histórico + error reciente + mitad del sesgo desde día 3",
           "patron_hist_y_tendencia_mitad no corrige el pesimismo de largo plazo del titular (sesgo −0,35 m a 3 días y −1,48 "
           "a 5); sesgo_plazo_50 lo baja mucho a 5 días (+74 % en 15 casos) pero estorba a 1–2 días (−6 % y −3 %). Aplicar la "
           "mitad del sesgo por plazo solo desde el día 3 debería conservar lo de 1–3 días (idénticos a patron_hist_y_tendencia_mitad) y "
           "mejorar 5–14 días. Es parcial: quita la mitad de s(h) − s(3) (hoy ~60 % del efecto de sesgo_plazo_50 a 5 días). Sin prueba "
           "previa (ninguna corrida con la corrección del error tiene aún real a ≥ 3 días); el +74 % de sesgo_plazo_50 a 5 días es de 9–15 "
           "casos del 30–31 oct (régimen seco).")


# ---------------------------------------------------------------- 5 nov: propuesto por Gemini (segundo auditor), aprobado por Claude independiente
def c_dia_semana_suave_coca_real(P, ctx, mod):
    dd = ctx.get("deltaDia")
    s = mod.get("serieCocaRio")
    if not dd or not s:
        return None
    v = [round(float(x) * 0.5, 1) for x in dd]
    sc = list(s)
    ctx["deltaDia"] = v
    ctx["serieCoca"] = sc
    return P, ctx, {"deltaDia": v, "serieCoca": sc}


CANDIDATOS["dia_semana_suave_coca_real"] = {"f": c_dia_semana_suave_coca_real, "promocion": "auto", "origen": "Gemini 2026-11-05", "nombre": "Día de semana a la mitad + río Coca real", "hipotesis": "Combinar el patrón semanal a la mitad (que suaviza los saltos de corto plazo) con la serie del río Coca real (que hoy baja el error a 5 días de 1,48 a 0,80 m en el marcador) mejora tanto el corto como el mediano plazo con promoción automática. Estimación del revisor con trayectorias guardadas: +2 % a 1 día, +8 % a 2, −8 % a 3 y +18 % a 5 días (9 casos)."}


# ---------------------------------------------------------------- Luis 5 nov: rendimiento de Coca Codo separado (río normal / crecido)
# Prueba con 17–31 oct: río normal rinde ~99 % (factor con freno 0,988); crecido (≥250 m³/s o subida >30 % de un día
# a otro) 72–91 % (0,939 con solo 3 días). El titular mezcla ambos en un factor único (0,958 al 5 nov).
CCS_CRECIDO_M3S, CCS_SUBIDA = 250.0, 1.30


def _ccs_crecido(q, q_ant):
    return q >= CCS_CRECIDO_M3S or (q_ant is not None and q_ant > 0 and q > q_ant * CCS_SUBIDA)


def _ccs_factor_regimen(reg, hoy_d, crecido):
    """Mismo cálculo que rendimiento_ccs() de robot.py, pero solo con los días del mismo régimen del río."""
    ks, usa, ant = sorted(reg), [], None
    for k in ks:
        v = reg[k]
        q = float(v.get("rio_m3s") or 0)
        if _ccs_crecido(q, ant) == crecido and k >= (hoy_d - timedelta(days=21)).isoformat() and float(v.get("rendimiento") or 0) >= 0.5:
            usa.append((k, float(v["rendimiento"])))
        ant = q
    if len(usa) < 3:
        return None, len(usa)
    w = [0.5 ** ((hoy_d - datetime.strptime(k, "%Y-%m-%d").date()).days / 3.0) for k, _ in usa]
    m = sum(wi * math.log(max(0.3, min(1.3, r))) for wi, (_, r) in zip(w, usa)) / sum(w)
    n = len(usa)
    return max(0.6, min(1.0, math.exp(m * n / (n + 10)))), n


def c_ccs_por_regimen(P, ctx, mod):
    datos_r = (mod.get("_datos_robot") or {}).get("ccs_rendimiento") or {}
    f_tit = datos_r.get("factor")
    if not isinstance(f_tit, (int, float)) or f_tit <= 0 or not P.get("qCoca"):
        return None
    rio = _leer(os.path.join("registro", "coca_rio.json"), {}) or {}
    hs = sorted(rio)
    if len(hs) < 36:
        return None
    q24 = sum(rio[h] for h in hs[-24:]) / 24.0
    q_ant = sum(rio[h] for h in hs[-48:-24]) / max(1, len(hs[-48:-24]))
    crecido = _ccs_crecido(q24, q_ant)
    hoy_d = datetime.strptime(hs[-1][:10], "%Y-%m-%d").date()
    f_new, n = _ccs_factor_regimen(_leer(os.path.join("registro", "ccs_rendimiento.json"), {}) or {}, hoy_d, crecido)
    if f_new is None or abs(f_new - f_tit) < 0.002:
        return None
    P["qCoca"] = int(max(80, min(450, round(float(P["qCoca"]) / f_tit * f_new))))
    return P, ctx, {"qCoca": P["qCoca"], "regimen": "crecido" if crecido else "normal", "factor": round(f_new, 3), "dias": n}


_cand_3nov("ccs_por_regimen", c_ccs_por_regimen, "Coca Codo: rendimiento separado para río normal y crecido",
           "El titular descuenta a Coca Codo con un factor único (0,958 al 5 nov) que mezcla días de río normal (~99 %) y "
           "crecido (72–91 %, sedimentos). Con el río normal subestima ~20–25 MW. Este modelo usa el factor del régimen de "
           "hoy (crecido: ≥250 m³/s o subida >30 % frente al día anterior) para todo el horizonte; mismo promedio ponderado "
           "y freno n/(n+10) que el titular.", origen="Revisión programada de Luis, aprobada como sombra el 5 nov")


# ---------------------------------------------------------------- 6 nov (auditor): río Coca real solo desde el día 2
# Prueba con las trayectorias guardadas (pares exactos titular/candidato, cota real a ±1 h, 30 oct–6 nov):
# coca_rio_real a 1 día −5 % (88 casos), 2 días +2 % (74), 3 días +10 % (61), 5 días +30 % (37), 7 días +82 % (10).
# Gana a largo plazo pero estorba mañana; las piezas que mejor van a 1–3 días (patron_historico, corrección del error
# reciente a media fuerza) no tocan el largo plazo. Idea de Gemini del 6 nov (coca_real_y_tendencia_mitad, frenada por
# la validación automática solo por usar `str`) armada con los ayudantes existentes y con el río real desde el día 2.
def _coca_real_desde_dia2(P, ctx, mod):
    """serieCoca: días 0–1 = la del titular (o la que dejó la pieza anterior), día 2 = promedio, días 3+ = río real."""
    a, b = ctx.get("serieCoca"), mod.get("serieCocaRio")
    if not a or not b:
        return None
    s = []
    for i in range(min(len(a), len(b))):
        x, y = float(a[i]), float(b[i])
        s.append(round(x if i < 2 else ((x + y) / 2 if i == 2 else y), 4))
    ctx["serieCoca"] = s
    return P, ctx, {"serieCoca": s}


def _combinar(P, ctx, mod, *piezas):
    """Aplica las piezas en orden sobre las mismas copias. Estricta: si una pieza no corre, el candidato no corre."""
    cambios = {}
    for f in piezas:
        r = f(P, ctx, mod)
        if not r:
            return None
        P, ctx, c = r
        cambios.update(c)
    return P, ctx, cambios


def c_tend_mitad_coca_dia2(P, ctx, mod):
    return _combinar(P, ctx, mod, c_corrige_tendencia_mitad, _coca_real_desde_dia2)


def c_patron_hist_coca_dia2(P, ctx, mod):
    return _combinar(P, ctx, mod, c_patron_historico, _coca_real_desde_dia2)


def c_pht_mitad_coca_dia2(P, ctx, mod):
    return _combinar(P, ctx, mod, c_patron_hist_y_tendencia_mitad, _coca_real_desde_dia2)


def _cand_aud6(cid, f, nombre, hip, origen="auditor 2026-11-06", prom="luis"):
    CANDIDATOS[cid] = {"f": f, "promocion": prom, "origen": origen, "nombre": nombre, "hipotesis": hip}


_HIP_D2 = ("Ojo: hoy el río real (GloFAS sin la bajada por historia) promete MENOS que la serie del titular (día 3: 0,87 vs 0,95), "
           "así que hoy sería más pesimista. La ganancia de coca_rio_real a 2–7 días viene entera del 30 oct–1 nov (33 corridas: "
           "+12 %, +27 % y +31 % a 2, 3 y 5 días); desde el 1 nov 07:00 pierde (−23 % a 2 días en 41 casos, −39 % a 3 en 28, "
           "−70 % a 5 en 4). Con hora exacta, a 3 días el total es −1 % (49), no +10 %.")
_cand_aud6("tend_mitad_coca_dia2", c_tend_mitad_coca_dia2, "Error reciente a media fuerza + río Coca real desde el día 2",
           "corrige_tendencia_mitad ataca el error a 1 día (caudal de los días 0–2 según el error reciente); coca_rio_real "
           "gana a 3–7 días (+10 %, +30 %, +82 %) pero pierde 5 % a 1 día. Usar el río real solo desde el día 2 (día 2 a medio "
           "camino) debería dejar el 1 día igual a corrige_tendencia_mitad y bajar el pesimismo a 7 y 14 días. " + _HIP_D2,
           origen="Gemini 2026-11-06 (coca_real_y_tendencia_mitad), armado por el auditor 2026-11-06")
_cand_aud6("patron_hist_coca_dia2", c_patron_hist_coca_dia2, "Patrón histórico + río Coca real desde el día 2",
           "patron_historico mejora a 2 y 3 días (+19 % y +14 % en 42 y 29 casos, −2 % a 1 día) y corre en todas las corridas; "
           "sumarle el río real desde el día 2 debería conservar eso y corregir el largo plazo (sumar el río real entero dio "
           "solo +10 % a 2 días en una prueba aproximada por suma de diferencias, 41 casos; con el empalme desde el día 2 la misma "
           "aproximación da +19 % a 2 días pero solo +7 % a 3). " + _HIP_D2)
_cand_aud6("pht_mitad_coca_dia2", c_pht_mitad_coca_dia2, "Patrón histórico + error reciente + río Coca real desde el día 2",
           "patron_hist_y_tendencia_mitad (las dos mejores piezas de 1–2 días) + río real desde el día 2 para 5–14 días, en vez "
           "de restar la mitad del sesgo por plazo (patron_tend_mitad_sesgo50_largo): compara una corrección física (el río) "
           "con una estadística (el sesgo) sobre la misma base. " + _HIP_D2)


# ---------------------------------------------------------------- Luis 6 nov: las demás hidroeléctricas siguen a su río
# El titular deja fijas (salvo el factor de lluvia amazónica) a Daule-Peripa, Toachi-Pilatón, Baba, Manduriacu, Ocaña y
# Pucará, que el Cenace suma en "otras hidro" sin detalle. Aquí cada una sigue el cambio que pronostica GloFAS en su río
# (relativo a hoy, como Agoyán o Minas San Francisco en el titular), con su producción típica como punto de partida.
# Factor de planta típico (producción anual pública ÷ 8.760 h × potencia) y cuánto del cambio del río llega a la
# generación: las de embalse grande (Daule-Peripa, Pucará/Pisayambo) dependen más de lo que decide Celec que del río.
OH_CENTRALES = {   # clave GloFAS: (MW instalados, factor de planta típico, respuesta al río)
    "daule": (213, 0.32, 0.15), "toachi": (254, 0.45, 0.5), "baba": (42, 0.43, 0.5),
    "guayllabamba": (65, 0.62, 0.5), "canar": (26, 0.80, 0.5), "pisayambo": (73, 0.34, 0.15)}
_OH_CACHE = {}


def _oh_serie(dias=61):
    if "s" in _OH_CACHE:
        return _OH_CACHE["s"]
    import urllib.request
    try:
        from generacion import RIOS_EXTRA
    except Exception:
        _OH_CACHE["s"] = None; return None
    rios = [r for r in RIOS_EXTRA if r[0] in OH_CENTRALES]
    url = ("https://flood-api.open-meteo.com/v1/flood?latitude=" + ",".join(str(r[4]) for r in rios) + "&longitude=" +
           ",".join(str(r[5]) for r in rios) + f"&daily=river_discharge&past_days=1&forecast_days={dias}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "simulador-mazar (laboratorio)"}), timeout=40) as r:
            f = json.load(r)
    except Exception:
        _OH_CACHE["s"] = None; return None
    f = f if isinstance(f, list) else [f]
    mw0_t, mw_t, info = 0.0, [0.0] * dias, {}
    for r, x in zip(rios, f):
        cap, fp, resp = OH_CENTRALES[r[0]]
        v = ((x.get("daily") or {}).get("river_discharge") or [])[1:1 + dias]
        if not v or not v[0]:
            continue
        mw0 = cap * fp
        mw0_t += mw0
        for j in range(dias):
            rel = min(3.0, max(0.3, (v[j] if j < len(v) and v[j] else v[0]) / v[0]))
            w = 1.0 if j <= 10 else max(0.3, 1 - (j - 10) / 20)        # después de 10 días se atenúa
            mw_t[j] += min(cap, mw0 * (1 + (rel - 1) * resp * w))
        info[r[0]] = {"mw_tipico": round(mw0), "rel_7d": round(min(3.0, max(0.3, (v[min(7, len(v) - 1)] or v[0]) / v[0])), 3)}
    _OH_CACHE["s"] = (mw0_t, [m / mw0_t for m in mw_t], info) if mw0_t > 0 else None
    return _OH_CACHE["s"]


def c_otras_hidro_rios(P, ctx, mod):
    s = _oh_serie()
    other = float(P.get("other") or 0)
    if not s or other <= 0:
        return None
    mw0, serie, info = s
    fe = max(0.0, min(0.5, mw0 / other))                    # parte de "otras" que pasan a seguir a sus ríos
    otr = ctx.get("otrasRios") or {}
    f1, s1 = float(otr.get("frac") or 0), otr.get("serie") or []
    if f1 + fe > 0.95:
        return None
    n = max(len(s1), len(serie))
    s1x = lambda j: (s1[j] if j < len(s1) else (s1[-1] if s1 else 1.0))
    s2x = lambda j: (serie[j] if j < len(serie) else serie[-1])
    ftot = f1 + fe
    ctx["otrasRios"] = {"frac": round(ftot, 4), "serie": [round((f1 * s1x(j) + fe * s2x(j)) / ftot, 4) for j in range(n)]}
    return P, ctx, {"frac_extra": round(fe, 3), "mw_tipicos": round(mw0), "cambio_7d": round(s2x(7), 3), "rios": info}


_cand_3nov("otras_hidro_rios", c_otras_hidro_rios, "Las demás hidroeléctricas siguen a su río (Daule-Peripa, Toachi, Baba…)",
           "El titular deja casi fijas a Daule-Peripa, Toachi-Pilatón, Baba, Manduriacu, Ocaña y Pucará "
           "(dentro de 'otras hidroeléctricas', unos 290 MW típicos). Con El Niño sus ríos vienen de 1,7 a 38 veces lo normal para la fecha. Este "
           "modelo hace que cada una siga el cambio que pronostica GloFAS en su río desde hoy, con su factor de planta típico, "
           "respuesta 0,5 (0,15 en las de embalse grande) y tope en su potencia; atenúa después de 10 días como el titular.",
           origen="Luis, 6 nov (aprobado por Luis)")



# ---------------------------------------------------------------- Cerebro 7 nov (aprobado por Luis): reparto reciente
# Mazar volvió a turbinar fuerte (1.814 MWh el 6 nov, y de noche) y el titular dijo de más a 1 día (+30 a +47 cm).
# El modelo calcula cuánta agua sale de Mazar con el aporte entre presas calibrado en el historial (beta = 0,47 del
# caudal de entrada llega a Molino/Sopladora sin pasar por Mazar). Con el balance real de Celec de los 2 últimos días
# completos (Paute MW, caudal, variación de la cota → agua que salió) se despeja el beta que esos días cuadra y se usa
# en vez del calibrado. Si Mazar carga más del complejo, ese beta baja y sale más agua de Mazar por cada MW.
def c_reparto_reciente(P, ctx, mod):
    par, fis = mod.get("_par"), mod.get("_fisica") or {}
    det = [x for x in (fis.get("detalle") or []) if isinstance(x.get("salida"), (int, float)) and x.get("caudal")]
    if not par or len(det) < 2:
        return None
    kms, eta = par["k_molino_sopladora"], par["eficiencia_mazar"]
    amC = ctx.get("amaluzaCota") or 1975.0
    betas = []
    for x in det[-2:]:
        if x["salida"] <= 2:       # día que Mazar casi no soltó agua: el balance no informa del reparto
            continue
        kmz = 0.00981 * eta * max(20.0, x["cota"] - amC)
        betas.append((x["paute_mw"] - x["salida"] * (kmz + kms)) / (kms * x["caudal"]))
    if not betas:
        return None
    b0 = par["beta_cuenca_intermedia"]
    b = max(0.0, min(1.0, sum(betas) / len(betas)))
    if abs(b - b0) < 0.02:
        return None
    par2 = dict(par); par2["beta_cuenca_intermedia"] = round(b, 4)
    ctx["_par"] = par2
    return P, ctx, {"beta_calibrado": round(b0, 3), "beta_reciente": round(b, 3), "betas_dias": [round(v, 3) for v in betas]}


def c_reparto_reciente_y_tendencia_mitad(P, ctx, mod):
    return _combinar(P, ctx, mod, c_reparto_reciente, c_corrige_tendencia_mitad)


_cand_3nov("reparto_reciente", c_reparto_reciente, "Reparto de Paute con el balance real de los 2 últimos días",
           "El titular supone que 0,47 del caudal de entrada llega a Molino/Sopladora sin pasar por Mazar (calibrado en el "
           "historial). Con Mazar turbinando fuerte y de noche (6–7 nov) eso subestima el agua que sale de Mazar: a 1 día dijo "
           "de más +30 a +47 cm. Aquí ese aporte se despeja del balance real de Celec (Paute MW, caudal y cambio de cota) de los "
           "2 últimos días completos; el 6 nov da ~0 y el 5 nov ~0,44. Idea del cerebro de Mazar del 7 nov (el retador pidió que "
           "no se usara solo la parte diaria de Mazar porque de noche fue el doble: el balance del día ya la incluye).",
           origen="cerebro 2026-11-07 (aprobado por Luis)")
_cand_3nov("reparto_reciente_y_tendencia_mitad", c_reparto_reciente_y_tendencia_mitad,
           "Reparto reciente + error reciente a media fuerza",
           "Combinación propuesta por el cerebro de Mazar el 7 nov: corrige_tendencia_mitad lidera a 1 día (+2,5 %) pero corrige "
           "de más a 2 días; el reparto reciente cubre lo que la tendencia no ve cuando Mazar turbina de noche.",
           origen="cerebro 2026-11-07 (aprobado por Luis)")


# ---------------------------------------------------------------- Gemini 7 nov (revisados por el Claude independiente)
# sin_autoajuste_coca_real y sin_autoajuste_sesgo50_largo, armados con las piezas que ya existen (mismo resultado que el
# código de la rama candidato/gemini-2026-11-07; el revisor lo comprobó) y con las cifras corregidas al marcador del 7 nov.
# corrige_reciente_rapido fue RECHAZADO (la memoria se aplica por día entero: a 1 día es casi igual a corrige_tendencia_mitad).
def c_sin_autoajuste_coca_real(P, ctx, mod):
    return _combinar(P, ctx, mod, c_sin_autoajuste, c_coca_rio_real)


def c_sin_autoajuste_sesgo50_largo(P, ctx, mod):
    return _combinar(P, ctx, mod, c_sin_autoajuste, lambda P_, c_, m_: _sesgo_plazo(P_, c_, m_, 0.5, desde=1))


CANDIDATOS["sin_autoajuste_coca_real"] = {
    "f": c_sin_autoajuste_coca_real, "promocion": "auto", "origen": "Gemini 2026-11-07", "nombre": "Sin autoajuste + río Coca real",
    "hipotesis": "Sin el autoajuste (marcador 7 nov, 72 casos: 0,299 vs 0,306 m del titular a 1 día y 0,407 vs 0,422 a 2) y con el "
                 "río Coca real (0,721 vs 0,884 m a 5 días y 1,011 vs 1,684 a 7, solo 2 días a 7) el error baja a 5–7 días sin "
                 "empeorar a 1–3. Estimado con las trayectorias guardadas: +2,8 % a 1 día (lejos del 10 % que pide el reemplazo), "
                 "+5 % a 2, +4 % a 3, +23 % a 5, +30 % a 7. Ojo: la ganancia del río real vino sobre todo del 30 oct–1 nov."}
CANDIDATOS["sin_autoajuste_sesgo50_largo"] = {
    "f": c_sin_autoajuste_sesgo50_largo, "promocion": "luis", "origen": "Gemini 2026-11-07",
    "nombre": "Sin autoajuste + mitad de sesgo desde día 2",
    "hipotesis": "Sin el autoajuste y quitando la mitad del sesgo por plazo solo desde el día 2: a 1 día es igual a sin_autoajuste "
                 "(+2,2 %, 72 casos) y debe corregir el pesimismo de 5 a 14 días (sesgo del titular a 7 días −1,68 m) sin "
                 "empeorar más de 5 % a 3 días (estimado −4,5 %, al borde; +18 % a 5 y +77 % a 7 con 12 casos). Si se promueve, "
                 "la memoria del robot se calcula después de aplicar_titular y pisaría la corrección."}


# ---------------------------------------------------------------- Cerebro 7 nov (aprobado por Luis): recesión y calor
# Recesión del Paute: Celec 1–6 nov 82 → 54 → 48 → 39 → 38 → 29 m³/s con 1–5 mm de lluvia. El cerebro: el caudal cae
# ~25 % por día seco y tiende a 20–32 m³/s (los datos de Celec dan ~19 %/día: se usa 0,81). El titular sigue la serie relativa de GloFAS/lluvia (hoy baja a ~0,79 de lo
# de hoy al día 5 y sube con la lluvia del 15–16 nov). Aquí, mientras la serie del titular no sube (día "seco"), el
# caudal baja 19 % por día pero no por debajo de un piso de 26 m³/s (mitad del rango 20–32); si ya está debajo, queda
# plano. Cuando la serie sube (lluvia), se aplica la misma subida relativa del titular.
_REC_PISO, _REC_CAIDA = 26.0, 0.81     # 0,81 = (29/82)^(1/5): Celec 1–6 nov (revisor)


def c_recesion_paute_piso(P, ctx, mod):
    s = ctx.get("serieMazar")
    q0 = float(P.get("qMazar") or 0)
    if not s or len(s) < 3 or q0 <= 0 or not s[0]:
        return None
    q = [q0 * float(s[0])]
    for d in range(1, len(s)):
        a, b = float(s[d - 1] or 0), float(s[d] or 0)
        if a <= 0 or b >= a * 0.98:                   # la serie no baja de verdad (lluvia o plana): mismo cambio que el titular
            q.append(q[-1] * (b / a if a > 0 else 1.0))
        elif q[-1] > _REC_PISO:                       # día seco (la serie baja > 2 %): recesión hacia el piso
            q.append(max(_REC_PISO, q[-1] * _REC_CAIDA))
        else:
            q.append(q[-1])
    nueva = [round(x / q0, 4) for x in q]
    if max(abs(x - float(y or 0)) for x, y in zip(nueva, s)) < 0.01:
        return None
    ctx["serieMazar"] = nueva
    return P, ctx, {"serieMazar": nueva}


# Calor de la Costa: el titular usa la máxima de Guayaquil de HOY (tCosta) para toda la proyección, a 50 MW/°C (la misma
# elasticidad del robot). Aquí cada día usa la máxima pronosticada de ese día (registro/gye_pronostico.json, Open-Meteo,
# lo escribe el robot antes del laboratorio): demanda extra = 50 × (máx. del día − máx. de hoy), como corte equivalente.
# Solo la pieza de temperatura (la de lluvia de la Costa ya está dentro de demanda_real_lluvia; su elasticidad no se conoce).
def c_demanda_tmax_dia(P, ctx, mod):
    try:
        from datetime import date as _d
        ts = str(mod.get("_ts") or "")
        if len(ts) < 10:
            return None
        f0 = _d.fromisoformat(ts[:10])
        man = (_leer_json_lab("datos.json") or {}).get("manual") or {}
        hasta = man.get("tCosta_hasta")
        if man.get("tCosta") not in (None, "", False) and not (hasta and f0.isoformat() > str(hasta)):
            return None                               # Luis fijó la temperatura a mano (vigente): no se toca
        g = _leer_json_lab("registro/gye_pronostico.json") or {}
        por = {t: float(mx) for t, mx in zip(g.get("dias") or [], g.get("tmax") or []) if isinstance(mx, (int, float))}
        gen = str(g.get("generado") or "")
        if len(gen) < 13:
            return None
        # misma regla que el robot (pronostico()): desde las 18 h tCosta es la máxima de MAÑANA (revisor)
        f_t = _d.fromisoformat(gen[:10]) + timedelta(days=1 if int(gen[11:13]) >= 18 else 0)
        t_hoy = por.get(f_t.isoformat())
        if t_hoy is None:
            return None
        t_ref = max(28.0, min(36.0, round(t_hoy * 2) / 2))   # como el robot (tCosta)
        plan = list(ctx.get("cutPlan") or []); plan += [None] * max(0, 61 - len(plan))
        cambio = False
        for k in range(61):
            f = f0 + timedelta(days=k); dia = (ctx["diaSemana0"] + k) % 7
            v = plan[k] if isinstance(plan[k], (int, float)) and not isinstance(plan[k], bool) else (P["cut"] if (not ctx.get("cutDias") or ctx["cutDias"][dia]) else 0)
            x = por.get(f.isoformat())
            extra = 50.0 * (max(28.0, min(36.0, x)) - t_ref) if (x is not None and f > f_t) else 0.0
            cambio = cambio or abs(extra) > 0.5
            plan[k] = round(v - extra, 1)
        if not cambio:
            return None
        ctx["cutPlan"] = plan
        return P, ctx, {"cutPlan": plan[:15], "t_ref": t_ref}
    except Exception:
        return None


_cand_3nov("recesion_paute_piso", c_recesion_paute_piso, "Recesión del Paute con piso de 26 m³/s",
           "Los días en que la serie del titular baja más de 2 % (secos), el caudal que entra a Mazar baja 19 % por día hasta un piso de 26 m³/s "
           "(Celec 1–6 nov: 82 → 29 m³/s con 1–5 mm) en vez de seguir la serie relativa del titular, que hoy lo lleva a ~21 m³/s "
           "al día 5. Los demás días, el mismo cambio relativo que el titular. Mide si la recesión real tiene piso (a 3–7 días). "
           "Idea del cerebro de Mazar del 7 nov (pieza 'recesión' sola; el retador objetó la combinación con el Coca real, que "
           "hoy promete menos y no más).",
           origen="cerebro 2026-11-07 (aprobado por Luis)")
_cand_3nov("demanda_tmax_dia", c_demanda_tmax_dia, "Demanda con la máxima de Guayaquil de cada día",
           "El titular usa la máxima de Guayaquil de hoy (desde las 18 h, la de mañana) para toda la proyección; aquí cada día 1–6 (lo que trae Open-Meteo; después, sin ajuste) usa su máxima pronosticada (hoy 30,9 "
           "→ 31,2–32,9 °C los próximos días) a 50 MW/°C, la elasticidad del robot. Más calor = más demanda = más Paute: debe "
           "bajar el sesgo a 3–7 días si el calor pronosticado se cumple. Pieza de temperatura de la idea 'demanda_costa' del "
           "cerebro de Mazar del 7 nov (la de lluvia y la demanda medida ya están en demanda_real_lluvia; feriado del 20 nov y "
           "patrón semanal ya están en el titular).",
           origen="cerebro 2026-11-07 (aprobado por Luis)")
