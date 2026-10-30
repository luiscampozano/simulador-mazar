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

CONF_DEF = {"promocion_automatica": True, "activar_desde": "2026-10-31", "dias_min": 7, "casos_min": 40, "mejora_min": 0.10,
            "tolerancia_3d": 0.05, "tolerancia_7d": 0.10, "ventana_dias": 7, "revertir_dias": 3}


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
    "coca_rio_real": {"f": c_coca_rio_real, "promocion": "auto", "origen": "auditoría Mazar 29 oct",
                      "hipotesis": "El modelo es pesimista a 7 días porque baja a Coca Codo con la historia del río; con el pronóstico del río real acertaría más."},
    "sin_autoajuste": {"f": c_sin_autoajuste, "promocion": "auto", "origen": "laboratorio",
                       "hipotesis": "Comprobar si el factor de autoajuste mejora o empeora el pronóstico."},
    "paute_sin_ajuste": {"f": c_paute_sin_ajuste, "promocion": "auto", "origen": "laboratorio",
                         "hipotesis": "Comprobar si el ajuste del caudal del Paute (≈42 % de lo que promete la lluvia) ayuda."},
    "sin_memoria": {"f": c_sin_memoria, "promocion": "luis", "origen": "laboratorio",
                    "hipotesis": "Comprobar si promediar las corridas de 48 h estabiliza sin perder acierto."},
}


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


def correr(P, ctx, par, mod, datos, simular, log=print, base=None):
    """Calcula titular y candidatos con los mismos datos y guarda sus trayectorias. Devuelve el resumen del marcador.
    base = (P, ctx) antes de aplicar los promovidos: se sigue corriendo como 'anterior' para poder revertir."""
    conf = {**CONF_DEF, **_leer(F_CONF, {})}
    if not os.path.exists(F_CONF):
        _escribir(F_CONF, conf)
    ts = datetime.fromisoformat(datos["fecha"]).isoformat(timespec="minutes")
    tray = {}
    d_tit, _ = simular(_copia(P), _copia(ctx), par, horizonte=max(HORIZ))
    tray["titular"] = [round(d_tit[h]["cota"], 3) for h in HORIZ]
    if base and (_leer(F_TIT, {"promovidos": []}).get("promovidos")):
        try:
            d_ant, _ = simular(_copia(base[0]), _copia(base[1]), par, horizonte=max(HORIZ))
            tray["anterior"] = [round(d_ant[h]["cota"], 3) for h in HORIZ]
        except Exception as e:
            log(f"Laboratorio: anterior falló: {e}")
    for cid, c in CANDIDATOS.items():
        if cid in (_leer(F_TIT, {"promovidos": []}).get("promovidos") or []):
            continue
        try:
            r = c["f"](_copia(P), _copia(ctx), mod)
            if not r:
                continue
            di, _ = simular(r[0], r[1], par, horizonte=max(HORIZ))
            tray[cid] = [round(di[h]["cota"], 3) for h in HORIZ]
        except Exception as e:
            log(f"Laboratorio: {cid} falló: {e}")
    reg = _leer(F_PRED, {"corridas": []})
    reg["corridas"] = [x for x in reg["corridas"] if x["ts"] != ts] + [
        {"ts": ts, "cota": datos["cota"], "tray": tray, "rasgos": _rasgos(P, ctx, mod, datos)}]
    lim = (datetime.fromisoformat(ts) - timedelta(days=40)).isoformat()
    reg["corridas"] = sorted([x for x in reg["corridas"] if x["ts"] >= lim], key=lambda x: x["ts"])
    _escribir(F_PRED, reg, compacto=True)
    marc = marcador(reg, conf, ts)
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
    desde = t_ahora - timedelta(days=conf["ventana_dias"])
    err = {}            # err[modelo][h] = [(fecha_objetivo, |error|, error)]
    casos_imp = []      # (rasgos, error del titular a 1 día)
    for x in reg["corridas"]:
        t0 = datetime.fromisoformat(x["ts"])
        for i, h in enumerate(HORIZ):
            obj = (t0 + timedelta(days=h)).isoformat(timespec="minutes")
            if obj not in real or datetime.fromisoformat(obj) < desde:
                continue
            for m, tr in x["tray"].items():
                e = tr[i] - real[obj]
                err.setdefault(m, {}).setdefault(h, []).append((obj[:10], abs(e), e))
            if h == 1 and "titular" in x["tray"]:
                casos_imp.append((x.get("rasgos") or {}, x["tray"]["titular"][i] - real[obj]))
    res = {"actualizado": ts_ahora, "ventana_dias": conf["ventana_dias"], "modelos": {}}
    for m, porh in err.items():
        res["modelos"][m] = {str(h): {"n": len(v), "dias": len({d for d, _, _ in v}),
                                      "error_medio_m": round(sum(a for _, a, _ in v) / len(v), 3),
                                      "sesgo_m": round(sum(e for _, _, e in v) / len(v), 3)} for h, v in sorted(porh.items())}
        if m in CANDIDATOS:
            res["modelos"][m]["_info"] = {k: CANDIDATOS[m][k] for k in ("hipotesis", "origen", "promocion")}
    # veredicto de cada candidato frente al titular
    tit = res["modelos"].get("titular", {})
    ver = {}
    for m, v in res["modelos"].items():
        if m == "titular":
            continue
        a1, t1 = v.get("1"), tit.get("1")
        if not a1 or not t1:
            ver[m] = {"estado": "sin datos"}; continue
        mejora = 1 - a1["error_medio_m"] / t1["error_medio_m"] if t1["error_medio_m"] > 0 else 0
        def peor(h, tol):
            a, t = v.get(h), tit.get(h)
            return bool(a and t and a["error_medio_m"] > t["error_medio_m"] * (1 + tol))
        suficiente = a1["dias"] >= conf["dias_min"] and a1["n"] >= conf["casos_min"]
        if not suficiente:
            estado = "midiendo"
        elif mejora >= conf["mejora_min"] and not peor("3", conf["tolerancia_3d"]) and not peor("7", conf["tolerancia_7d"]):
            estado = "listo"
        elif mejora <= -conf["mejora_min"]:
            estado = "pierde"
        else:
            estado = "empate"
        ver[m] = {"estado": estado, "mejora_1d": round(mejora, 3), "dias": a1["dias"], "casos": a1["n"],
                  "falta_dias": max(0, conf["dias_min"] - a1["dias"])}
    res["veredicto"] = ver
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
