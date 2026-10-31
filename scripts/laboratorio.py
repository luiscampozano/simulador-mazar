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


def _cand(cid, f, prom, nombre, hip):
    CANDIDATOS[cid] = {"f": f, "promocion": prom, "origen": "Claude 2026-10-30 (tanda)", "nombre": nombre, "hipotesis": hip}


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
_cand("cortes_siguen_7d", c_cortes_siguen_7d, "luis", "Los cortes siguen 7 días", "Si el esquema de cortes a empresas continúa, la demanda baja también los próximos días y Mazar sube más de lo que dice el titular.")


def c_memoria_mitad(P, ctx, mod):
    mem = ctx.get("memoria")
    if not mem:
        return None
    nueva = [round(float(x) * 0.5, 2) for x in mem]
    ctx["memoria"] = nueva
    return P, ctx, {"memoria": nueva}


CANDIDATOS["memoria_mitad"] = {"f": c_memoria_mitad, "promocion": "luis", "origen": "Gemini 2026-10-31", "nombre": "Memoria de 48 h a la mitad", "hipotesis": "Reducir a la mitad el caudal de corrección de la memoria de 48 h disminuye el error por rezago a 1 día hacia la meta de 5 cm sin perder toda la estabilidad de promediar corridas."}


def c_memoria_solo_largo(P, ctx, mod):
    mem = ctx.get("memoria")
    if not mem:
        return None
    pesos = [0.0, 0.5]
    nueva = [round(float(x) * (pesos[i] if i < len(pesos) else 1.0), 2) for i, x in enumerate(mem)]
    ctx["memoria"] = nueva
    return P, ctx, {"memoria": nueva}


CANDIDATOS["memoria_solo_largo"] = {"f": c_memoria_solo_largo, "promocion": "luis", "origen": "Gemini 2026-10-31", "nombre": "Sin memoria en los primeros 2 días", "hipotesis": "Apagar la memoria de 48 h en los días 0 y 1 y encenderla gradualmente desde el día 2 logra el acierto de `sin_memoria` a 1 día (~5 cm) conservando la estabilidad del número grande a 7 y 14 días."}


def c_paute_freno_medio(P, ctx, mod):
    bruta = mod.get("serieMazarBruta")
    info = mod.get("ajuste_paute") or {}
    f = info.get("factor")
    if not bruta or not isinstance(f, (int, float)):
        return None
    actual = ctx.get("serieMazar") or bruta
    f_med = max(0.0, min(1.5, 0.5 * (1.0 + float(f))))
    serie = [round(1.0 + (b - 1.0) * f_med, 4) if b > 1.0 else a for a, b in zip(actual, bruta)]
    ctx["serieMazar"] = serie
    return P, ctx, {"serieMazar": serie}


CANDIDATOS["paute_freno_medio"] = {"f": c_paute_freno_medio, "promocion": "auto", "origen": "Gemini 2026-10-31", "nombre": "Paute con mitad de ajuste aprendido", "hipotesis": "Aplicar la mitad del factor de ajuste de lluvia del Paute reduce el error a 1 día cuando el factor aprendido sobrecorrige en transiciones de lluvia a secano."}


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
    for cid, c in CANDIDATOS.items():
        if cid in (_leer(F_TIT, {"promovidos": []}).get("promovidos") or []):
            continue
        try:
            r = c["f"](_copia(P), _copia(ctx), _copia(mod))
            if not r:
                continue
            di, _ = simular(r[0], r[1], par, horizonte=HORIZ_REGION)
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
