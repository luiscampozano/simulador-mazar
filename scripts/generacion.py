"""Datos de las pestañas Hidroeléctricas, Térmicas, Otras fuentes y Clima e hidrología (registro/generacion.json).

No toca el modelo: el robot lo llama al final de cada corrida (cada 2 h), después de guardar datos.json y
serie_cenace.json. Solo lee lo que el robot ya guardó y consulta fuentes públicas:
  - Cenace, información operativa: generación acumulada del día por central hidroeléctrica (la curva sale de la
    diferencia entre corridas) y térmica / gas natural / renovable del día.
  - Cenace, informe de balance energético diario (SMEC): generación por tecnología e importación de Colombia
    del día anterior. Ese servidor usa un certificado autofirmado: se lee sin verificarlo (datos públicos, sin
    credenciales).
  - Inamhi: pronóstico oficial por ciudad y lluvia en tiempo real de sus estaciones.
  - Open-Meteo: lluvia pronosticada (ECMWF) en las cuencas y caudales pronosticados por GloFAS (Copernicus).
Si una fuente falla se conserva lo último que se tenía de ella.
"""
import json
import os
import re
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone

EC = timezone(timedelta(hours=-5))
F_OUT = os.path.join("registro", "generacion.json")
F_HIST = os.path.join("registro", "generacion_hist.json")
F_BAL = os.path.join("registro", "balance_diario.json")
PLANTAS = ["Coca Codo", "Paute", "Sopladora", "Mazar", "San Francisco", "Agoyán", "Minas San Francisco",
           "Delsitanisagua"]
UA = {"User-Agent": "Mozilla/5.0 (simulador-mazar-robot)"}
SMEC = "https://smec.cenace.gob.ec/SMEC/ResultadoInforme1.do?fecha="
SMEC_CLAVES = {"Generación Hidráulica": "hidro", "Generación Vapor Bunker": "vapor",
               "Generación Turbinas a Gas": "gas", "Generación Turbinas a Diesel": "diesel",
               "Generación Motores Bunker": "motores", "Generación de Otros Tipos": "otros",
               "Total Generación": "total", "Importación de Colombia": "imp_col",
               "Exportación a Colombia": "exp_col", "Importación de Perú": "imp_peru",
               "Exportación a Perú": "exp_peru"}
INAMHI_BANNER = "https://servicios.inamhi.gob.ec/wp-json/inamhi/v1/banner"
INAMHI_RT = "https://servicios.inamhi.gob.ec/wp-json/inamhi/v1/tiempo-real?lat={lat}&lon={lon}"
CIUDADES = ["Guayaquil", "Cuenca", "Tena", "Nueva Loja"]
ESTACIONES = [("paute", "Cuenca del Paute (Mazar)", -2.59, -78.62),
              ("coca", "Cuenca del Coca (Coca Codo)", -0.20, -77.70),
              ("gye", "Guayaquil", -2.19, -79.89)]
LLUVIA = ("https://api.open-meteo.com/v1/forecast?latitude=-2.75,-2.55,-0.20,-0.05,-2.19"
          "&longitude=-78.85,-78.60,-77.70,-77.55,-79.89&daily=precipitation_sum,temperature_2m_max"
          "&past_days=7&forecast_days=10&timezone=America%2FGuayaquil")
RIOS = [("paute", "Paute", "Mazar, Molino y Sopladora", -2.575, -78.575),
        ("coca", "Coca", "Coca Codo Sinclair", -0.20, -77.70),
        ("pastaza", "Pastaza", "Agoyán y San Francisco", -1.425, -78.375),
        ("zamora", "Zamora", "Delsitanisagua", -3.975, -78.925),
        ("jubones", "Jubones", "Minas San Francisco", -3.325, -79.475)]


def _leer(path, defecto):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def _guardar(path, obj, compacto=True):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":") if compacto else None)


def _json(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _r(v, d=0):
    return None if v is None else (round(v, d) if d else int(round(v)))


# ------------------------------------------------------------------ Cenace: centrales del día
def otra_generacion(get, url_cenace):
    """Térmica, gas natural y renovable acumuladas (MWh) de hoy y del último día completo, de la página de Cenace."""
    page = get(url_cenace, intermedio_cenace=True).decode("utf-8", "replace")
    dec = json.JSONDecoder()
    out = []
    for mm in re.finditer(r'Plotly\.newPlot\(\s*"[^"]+",\s*', page):
        obj, _ = dec.raw_decode(page, mm.end())
        nombres = [str(tr.get("name") or "").strip() for tr in obj]
        if "Gas Natural" in nombres and "Térmica" in nombres:
            out.append({str(tr.get("name")).strip(): float(tr["y"][0]) for tr in obj
                        if isinstance(tr.get("y"), list) and tr["y"]})
    return out


def snapshots(hist, serie, otra, hoy_d):
    """Guarda, por día, cada lectura acumulada (horas, MWh por central) para armar la curva del día."""
    pl = hist.setdefault("plantas", {})
    for dia, v in (serie.get("plantas") or {}).items():
        h = float(v.get("horas") or 0)
        if h <= 0:
            continue
        lst = pl.setdefault(dia, [])
        if not lst or h > lst[-1][0] + 0.25:
            lst.append([h, {k: round(float(v.get(k) or 0), 1) for k in PLANTAS}])
    if otra:
        og = hist.setdefault("otra", {})
        hoy = hoy_d.isoformat()
        h = float(((serie.get("plantas") or {}).get(hoy) or {}).get("horas") or 0)
        if h > 0:
            lst = og.setdefault(hoy, [])
            if not lst or h > lst[-1][0] + 0.25:
                lst.append([h, {k: round(v, 1) for k, v in otra[0].items()}])
        if len(otra) > 1:
            ayer = (hoy_d - timedelta(days=1)).isoformat()
            og[ayer] = [x for x in og.get(ayer, []) if x[0] < 24] + [[24.0, {k: round(v, 1) for k, v in otra[1].items()}]]
    limite = (hoy_d - timedelta(days=3)).isoformat()
    for k in ("plantas", "otra"):
        hist[k] = {d: v for d, v in hist.get(k, {}).items() if d >= limite}


def modelo_corrida(hist, datos):
    """Lo que el modelo usó en esta corrida para cada fuente (para la línea punteada)."""
    hoy = datos.get("hoy", {})
    m = re.search(r"aportar ≈ (\d+) MW", (datos.get("notas") or {}).get("calibracion", ""))
    ts = (datos.get("robot") or {}).get("ultima_ejecucion")
    if not ts:
        return
    reg = {"ts": ts, "ccs": min(1200, 5 * hoy.get("qCoca", 0)), "paute": int(m.group(1)) if m else None,
           "therm": hoy.get("therm"), "other": hoy.get("other"), "imp": hoy.get("imp")}
    lst = [x for x in hist.get("modelo", []) if x.get("ts") != ts] + [reg]
    corte = (datetime.fromisoformat(ts) - timedelta(days=4)).isoformat()
    hist["modelo"] = sorted([x for x in lst if x["ts"] >= corte], key=lambda x: x["ts"])


# ------------------------------------------------------------------ Cenace: balance diario (SMEC)
def _smec_ctx():
    c = ssl.create_default_context()
    c.set_ciphers("DEFAULT@SECLEVEL=1")
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE   # certificado autofirmado; datos públicos de solo lectura
    return c


def smec_dia(d):
    req = urllib.request.Request(SMEC + d.strftime("%Y/%m/%d"), headers=UA)
    with urllib.request.urlopen(req, timeout=40, context=_smec_ctx()) as r:
        raw = r.read()
    try:
        page = raw.decode("utf-8")
    except UnicodeDecodeError:
        page = raw.decode("latin-1")   # el servidor responde en ISO-8859-1
    celdas = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
              for c in re.findall(r'<td class="bordegris"[^>]*>(.*?)</td>', page, flags=re.S)]
    out = {}
    for i, c in enumerate(celdas[:-1]):
        if c in SMEC_CLAVES:
            try:
                out[SMEC_CLAVES[c]] = round(float(celdas[i + 1].replace(",", "")) / 24000.0, 1)   # kWh/día → MW medios
            except ValueError:
                pass
    return out if "total" in out and out["total"] > 0 else None


def balance(hoy_d, log):
    bal = _leer(F_BAL, {})
    faltan = [hoy_d - timedelta(days=k) for k in range(1, 61) if (hoy_d - timedelta(days=k)).isoformat() not in bal]
    for d in faltan[:12]:
        try:
            v = smec_dia(d)
            if v:
                bal[d.isoformat()] = v
        except Exception as e:
            log(f"Balance diario {d}: {e}")
            break
    limite = (hoy_d - timedelta(days=90)).isoformat()
    bal = {k: v for k, v in sorted(bal.items()) if k >= limite}
    _guardar(F_BAL, bal)
    return bal


# ------------------------------------------------------------------ Clima e hidrología
def inamhi_ciudades():
    b = _json(INAMHI_BANNER)
    out = {}
    for grupo in ("today", "next"):
        for x in b.get(grupo) or []:
            n = x.get("locality_name")
            if n in CIUDADES:
                out.setdefault(n, []).append({
                    "fecha": x.get("date"), "min": x.get("min_temperature"), "max": x.get("max_temperature"),
                    "lluvia": x.get("rain"), "uv": x.get("uv_radiation"),
                    "periodos": [{"p": f.get("period_name"), "c": f.get("condition_name")} for f in x.get("forecast") or []]})
    for n in out:
        out[n] = sorted({v["fecha"]: v for v in out[n]}.values(), key=lambda v: v["fecha"])
    return out


def inamhi_estaciones():
    out = {}
    for clave, nombre, lat, lon in ESTACIONES:
        j = _json(INAMHI_RT.format(lat=lat, lon=lon))
        est = []
        for s in (j.get("stations") or [])[:6]:
            est.append({"n": s.get("nombre"), "km": s.get("distancia_km"), "mm": s.get("precipitacion_mm"),
                        "mm15": s.get("lluvia_15min_mm"), "t": s.get("observado_local")})
        out[clave] = {"nombre": nombre, "estado": j.get("status"), "estaciones": est}
    return out


def lluvia_cuencas():
    f = _json(LLUVIA)
    dias = f[0]["daily"]["time"]
    prom = lambda a, b, k: [None if (x is None or y is None) else round((x + y) / 2, 1)
                            for x, y in zip(f[a]["daily"][k], f[b]["daily"][k])]
    return {"dias": dias, "paute": prom(0, 1, "precipitation_sum"), "coca": prom(2, 3, "precipitation_sum"),
            "gye_lluvia": f[4]["daily"]["precipitation_sum"], "gye_tmax": f[4]["daily"]["temperature_2m_max"]}


def rios_glofas():
    lat = ",".join(str(r[3]) for r in RIOS)
    lon = ",".join(str(r[4]) for r in RIOS)
    f = _json("https://flood-api.open-meteo.com/v1/flood?latitude=" + lat + "&longitude=" + lon +
              "&daily=river_discharge,river_discharge_median,river_discharge_p25,river_discharge_p75,"
              "river_discharge_min,river_discharge_max&past_days=7&forecast_days=30")
    out = []
    for (clave, rio, centrales, _, _), x in zip(RIOS, f):
        d = x["daily"]
        out.append({"clave": clave, "rio": rio, "centrales": centrales, "dias": d["time"],
                    **{k: [_r(v, 1) for v in d.get("river_discharge" + s, [])]
                       for k, s in (("q", ""), ("med", "_median"), ("p25", "_p25"), ("p75", "_p75"),
                                    ("min", "_min"), ("max", "_max"))}})
    return out


def rios_reales(datos, hoy_d):
    """Caudal medido (Celec): entrada a Mazar por día y río Coca por día."""
    out = {"paute": [], "coca": []}
    for x in (datos.get("fisica") or {}).get("detalle") or []:
        out["paute"].append([x["dia"], x.get("caudal")])
    q = (datos.get("hoy") or {}).get("qMazar")
    if q:
        out["paute"].append([hoy_d.isoformat(), q])
    rio = _leer(os.path.join("registro", "coca_rio.json"), {})
    dias = {}
    for k, v in rio.items():
        if v is not None:
            dias.setdefault(k[:10], []).append(v)
    for d in sorted(dias)[-10:]:
        if len(dias[d]) >= 6:
            out["coca"].append([d, round(sum(dias[d]) / len(dias[d]), 1)])
    return out


# ------------------------------------------------------------------ principal
def actualizar(ahora, get, url_cenace, log=print):
    hoy_d = ahora.date()
    datos = _leer("datos.json", {})
    serie = _leer("serie_cenace.json", {})
    prev = _leer(F_OUT, {})
    hist = _leer(F_HIST, {})
    fuentes = dict(prev.get("fuentes") or {})

    def intenta(nombre, fn, defecto):
        try:
            v = fn()
            fuentes[nombre] = {"ok": True, "hora": ahora.isoformat(timespec="minutes")}
            return v
        except Exception as e:
            log(f"Pestañas · {nombre}: {e}")
            fuentes[nombre] = {"ok": False, "hora": ahora.isoformat(timespec="minutes"), "error": str(e)[:160],
                               "ultimo_ok": (fuentes.get(nombre) or {}).get("hora") if (fuentes.get(nombre) or {}).get("ok")
                               else (fuentes.get(nombre) or {}).get("ultimo_ok")}
            return defecto

    otra = intenta("cenace_termica", lambda: otra_generacion(get, url_cenace), [])
    snapshots(hist, serie, otra, hoy_d)
    modelo_corrida(hist, datos)
    _guardar(F_HIST, hist)

    puntos = serie.get("puntos") or {}
    claves = sorted(puntos)[-144:]
    out = {
        "actualizado": ahora.isoformat(timespec="minutes"),
        "fuentes": fuentes,
        "plantas": hist.get("plantas", {}),
        "otra": hist.get("otra", {}),
        "modelo": hist.get("modelo", []),
        "puntos": [[k] + [_r(puntos[k].get(c)) for c in ("h", "t", "r", "i", "e", "d")] for k in claves],
        "balance": balance(hoy_d, log),
        "ciudades": intenta("inamhi_pronostico", inamhi_ciudades, prev.get("ciudades") or {}),
        "estaciones": intenta("inamhi_estaciones", inamhi_estaciones, prev.get("estaciones") or {}),
        "lluvia": intenta("lluvia_ecmwf", lluvia_cuencas, prev.get("lluvia") or {}),
        "rios": intenta("glofas", rios_glofas, prev.get("rios") or []),
        "rios_reales": rios_reales(datos, hoy_d),
    }
    _guardar(F_OUT, out)
    ok = sum(1 for v in fuentes.values() if v.get("ok"))
    log(f"Pestañas de generación y clima: {ok}/{len(fuentes)} fuentes al día")
