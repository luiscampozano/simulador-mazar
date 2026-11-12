"""DataLab Clima · El Niño a fondo (Luis, 4 nov: "quiero todo lo que no tenemos para que el modelo funcione también a
largo plazo, y si incluye salinidad"). Junta, de fuentes públicas sin clave, lo que mira la NOAA para saber si El Niño
se va a fortalecer o a debilitar en los próximos meses:

  · Boyas TAO/TRITON en la línea ecuatorial (2°S–2°N), diarias (NOAA PMEL vía ERDDAP de CoastWatch):
      temperatura del mar de 0 a 500 m → profundidad de la isoterma de 20 °C (la termoclina) en cada longitud;
      salinidad cerca de la superficie; viento zonal (los alisios: negativo = hacia el oeste).
  · Índices de la NOAA CPC: contenido de calor de los primeros 300 m del Pacífico ecuatorial, Índice de Oscilación
      del Sur (presión Tahití − Darwin), radiación de onda larga (convección) y viento zonal a 850 hPa.
  · Oscilación de Madden-Julian (MJO): fase y amplitud diarias (índice ROMI de la NOAA PSL).

Cada fuente va aparte: si una falla, las demás se guardan. Salida: clima/registro/enso_profundo.json.
No cambia ningún pronóstico: es para la pestaña de El Niño, los cerebros y el laboratorio."""
import csv, io, json, math, os, re, sys, time
from datetime import datetime, timedelta, timezone
import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
SAL = os.path.join(AQUI, "registro", "enso_profundo.json")
EC = timezone(timedelta(hours=-5))
UA = {"User-Agent": "DataLab Ec (clima; datalabecuador.com)"}
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap"
CPC = "https://www.cpc.ncep.noaa.gov/data/indices/"


def bajar(u, intentos=4, timeout=120):
    err = None
    for i in range(intentos):
        try:
            r = requests.get(u, timeout=timeout, headers=UA); r.raise_for_status(); return r.text
        except requests.RequestException as e:
            err = e; time.sleep(20 * (i + 1))   # ERDDAP a veces responde 503 un rato
    raise err


# ---------------------------------------------------------------- boyas TAO (ERDDAP)
def variables(ds):
    """Nombres de las variables de datos de un dataset de ERDDAP (sin banderas de calidad ni de fuente)."""
    j = json.loads(bajar(f"{ERDDAP}/info/{ds}/index.json"))
    cols = j["table"]["columnNames"]; ix = {c: i for i, c in enumerate(cols)}
    out = []
    for r in j["table"]["rows"]:
        if r[ix["Row Type"]] != "variable": continue
        n = r[ix["Variable Name"]]
        if n in ("array", "station", "wmo_platform_code", "longitude", "latitude", "time", "depth"): continue
        if n.startswith("Q") or re.fullmatch(r"S[A-Z]*_6\d{3}", n): continue   # banderas de calidad y de fuente
        out.append(n)
    return out


def tao(ds, var, dias=45, con_prof=True):
    """Filas (estación, lon, lat, día, profundidad, valor) de la franja ecuatorial del Pacífico."""
    t0 = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT00:00:00Z")
    campos = "station,longitude,latitude,time," + ("depth," if con_prof else "") + var
    u = (f"{ERDDAP}/tabledap/{ds}.csv?{campos}&time>={t0}&latitude>=-2.1&latitude<=2.1"
         f"&longitude>=130&longitude<=275" + ("&depth<=500" if con_prof else ""))
    filas = list(csv.reader(io.StringIO(bajar(u, timeout=240))))[2:]
    out = []
    for f in filas:
        try:
            v = float(f[-1])
            if v != v: continue
            out.append({"est": f[0], "lon": float(f[1]), "lat": float(f[2]), "dia": f[3][:10],
                        "prof": float(f[4]) if con_prof else 0.0, "v": v})
        except (ValueError, IndexError):
            continue
    return out


def lon_txt(lon):
    lon = lon if lon <= 180 else lon - 360
    return "180°" if abs(lon) == 180 else f"{abs(lon):.0f}°{'O' if lon < 0 else 'E'}"


def iso20(perfil):
    """Profundidad (m) donde la temperatura cruza 20 °C, interpolando entre las dos lecturas que la rodean."""
    p = sorted(perfil)
    for (z0, t0), (z1, t1) in zip(p, p[1:]):
        if t0 >= 20 > t1 and t0 != t1:
            return z0 + (t0 - 20) / (t0 - t1) * (z1 - z0)
    return None


def termoclina():
    filas = tao("pmelTaoDyT", "T_20", dias=45)
    por = {}   # (lon redondeada, día) → [(prof, t)] (promedio de las boyas de 2°S a 2°N en esa longitud)
    for f in filas:
        por.setdefault((round(f["lon"]), f["dia"]), {}).setdefault(f["prof"], []).append(f["v"])
    serie = {}
    for (lon, dia), pf in por.items():
        z = iso20([(p, sum(v) / len(v)) for p, v in pf.items()])
        sup = [sum(v) / len(v) for p, v in pf.items() if p <= 2]
        serie.setdefault(lon, []).append({"dia": dia, "iso20_m": None if z is None else round(z, 1),
                                          "sst": round(sup[0], 2) if sup else None})
    out = {}
    for lon, s in sorted(serie.items()):
        s.sort(key=lambda x: x["dia"])
        ult = [x for x in s if x["iso20_m"] is not None]
        if not ult: continue
        hace30 = [x for x in ult if x["dia"] <= (datetime.fromisoformat(ult[-1]["dia"]) - timedelta(days=30)).date().isoformat()]
        out[str(lon)] = {"lon": lon_txt(lon), "dia": ult[-1]["dia"], "iso20_m": ult[-1]["iso20_m"], "sst": ult[-1]["sst"],
                         "iso20_hace30_m": hace30[-1]["iso20_m"] if hace30 else None,
                         "serie": [[x["dia"], x["iso20_m"]] for x in ult[-45:]]}
    # perfil vertical más reciente en la boya más al este con datos (la más cercana al Ecuador)
    este = max((int(k) for k in out), default=None)
    perfil = None
    if este is not None:
        dia = out[str(este)]["dia"]
        pf = por.get((este, dia)) or {}
        perfil = {"lon": lon_txt(este), "dia": dia, "puntos": [[p, round(sum(v) / len(v), 2)] for p, v in sorted(pf.items())]}
    return {"fuente": "Boyas TAO/TRITON (NOAA PMEL), diarias, vía ERDDAP de NOAA CoastWatch (pmelTaoDyT)",
            "explica": "Profundidad del agua a 20 °C (la termoclina). Más honda en el este = agua caliente acumulada = El Niño se sostiene o crece.",
            "por_longitud": out, "perfil_este": perfil}


def tao_superficie(ds_cands, nombre, unidad, prefer):
    """Salinidad o viento cerca de la superficie, promedio por longitud: último día y hace 30 días."""
    for ds in ds_cands:
        try:
            vs = variables(ds)
            var = next((v for v in vs if v.startswith(prefer)), vs[0] if vs else None)
            if not var: continue
            filas = tao(ds, var, dias=45)
            break
        except Exception as e:
            print(f"{nombre}: {ds} falló ({str(e)[:120]})")
    else:
        raise RuntimeError("ningún dataset respondió")
    por = {}
    for f in filas:
        if f["prof"] > 12: continue   # cerca de la superficie
        por.setdefault(round(f["lon"]), {}).setdefault(f["dia"], []).append(f["v"])
    out = {}
    for lon, d in sorted(por.items()):
        dias = sorted(d)
        val = lambda k: round(sum(d[k]) / len(d[k]), 2)
        h30 = [k for k in dias if k <= (datetime.fromisoformat(dias[-1]) - timedelta(days=30)).date().isoformat()]
        out[str(lon)] = {"lon": lon_txt(lon), "dia": dias[-1], "valor": val(dias[-1]), "hace30": val(h30[-1]) if h30 else None,
                         "serie": [[k, val(k)] for k in dias[-45:]]}
    return {"fuente": f"Boyas TAO/TRITON (NOAA PMEL) vía ERDDAP ({ds}, variable {var})", "unidad": unidad, "por_longitud": out}


# ---------------------------------------------------------------- índices de la NOAA CPC
def cpc_mensual(nombre, archivo):
    """Tablas de la CPC: varias secciones (original, anomalía, estandarizada), cada una con "YEAR" y 12 meses en
    columnas fijas de 6 caracteres (-999.9 = sin dato). Se usa la estandarizada; si no hay, la anomalía."""
    lineas = bajar(CPC + archivo).splitlines()
    secs, actual, titulo = {}, None, ""
    for l in lineas:
        if l.strip().startswith("YEAR"):
            actual = "STANDARDIZED" if "STANDARDIZED" in titulo.upper() else ("ANOMALY" if "ANOMALY" in titulo.upper() else "ORIGINAL")
            secs[actual] = []; continue
        if re.match(r"^(19|20)\d\d", l) and actual:
            vals = [l[4 + 6 * k: 10 + 6 * k] for k in range(12)]
            for m, v in enumerate(vals, 1):
                try:
                    x = float(v)
                    if x > -900: secs[actual].append([f"{l[:4]}-{m:02d}", x])
                except ValueError:
                    pass
        elif l.strip():
            titulo = (titulo + " " + l) if actual is None or not re.match(r"^(19|20)\d\d", l) else titulo
            if l.strip() and not re.match(r"^(19|20)\d\d", l): titulo = l if "DATA" in l.upper() or "ANOMALY" in l.upper() else titulo + " " + l
    tipo = "STANDARDIZED" if secs.get("STANDARDIZED") else "ANOMALY"
    return {"fuente": f"NOAA CPC ({archivo}), {'estandarizado' if tipo == 'STANDARDIZED' else 'anomalía'}", "serie": (secs.get(tipo) or [])[-24:]}


def contenido_calor():
    """Anomalía de la temperatura media de los primeros 300 m del Pacífico ecuatorial, 180°–100°O (°C), mensual."""
    t = bajar("https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ocean/index/heat_content_index.txt")
    out = []
    for l in t.splitlines():
        p = l.split()
        if len(p) >= 5 and re.fullmatch(r"(19|20)\d\d", p[0]) and p[1].isdigit():
            try: out.append([f"{p[0]}-{int(p[1]):02d}", float(p[4])])
            except ValueError: pass
    if not out:
        raise RuntimeError("formato desconocido: " + t[:200].replace("\n", " | "))
    return {"fuente": "NOAA CPC · anomalía de temperatura media 0–300 m, 180°–100°O (°C, base 1981–2010)", "serie": out[-36:]}


def mjo():
    """MJO diaria con el índice ROMI de la NOAA PSL (OLR en tiempo real; el archivo RMM del Bureau of Meteorology de
    Australia dejó de actualizarse en feb 2024). La fase 1–8 se saca como en el RMM usando (PC2, −PC1); comparada con
    el RMM de la BoM en dic 2023–feb 2024 coincide con ±1 fase en 41 de 52 días activos: es una fase APROXIMADA."""
    t = bajar("https://psl.noaa.gov/mjo/mjoindex/romi.cpcolr.1x.txt")
    out = []
    for l in t.splitlines():
        p = l.split()
        if len(p) >= 7 and p[0].isdigit() and len(p[0]) == 4:
            try:
                pc1, pc2, amp = float(p[4]), float(p[5]), float(p[6])
            except ValueError:
                continue
            fase = int((math.atan2(-pc1, pc2) + math.pi) // (math.pi / 4)) + 1
            out.append([f"{p[0]}-{int(p[1]):02d}-{int(p[2]):02d}", min(fase, 8), round(amp, 3)])
    if not out:
        raise RuntimeError("ROMI sin datos")
    return {"fuente": "NOAA PSL · índice ROMI de la MJO (fase aproximada, ±1)",
            "explica": "Fases 8, 1 y 2 suelen favorecer la lluvia sobre el Pacífico oriental y el norte de Sudamérica; 4 a 6, menos. Amplitud mayor que 1: la MJO está activa.",
            "serie": out[-60:]}


def main():
    res = {"actualizado": datetime.now(EC).isoformat(timespec="minutes"), "fallas": {}}
    piezas = {
        "termoclina": termoclina,
        "salinidad": lambda: tao_superficie(["pmelTaoDyS"], "salinidad", "PSU", "S_"),
        "viento_zonal": lambda: tao_superficie(["pmelTaoDyW"], "viento", "m/s", "WU"),
        "contenido_calor": contenido_calor,
        "soi": lambda: cpc_mensual("SOI", "soi"),
        "olr": lambda: cpc_mensual("OLR", "olr"),
        "viento_850_pacifico_central": lambda: cpc_mensual("U850", "cpac850"),
        "mjo": mjo,
    }
    previo = {}
    try: previo = json.load(open(SAL, encoding="utf-8"))
    except Exception: pass
    for k, f in piezas.items():
        try:
            res[k] = f(); print(f"{k}: OK")
        except Exception as e:
            res["fallas"][k] = str(e)[:300]; print(f"{k}: FALLÓ {str(e)[:300]}")
            if k in previo: res[k] = previo[k]; res[k]["viejo"] = True   # se conserva lo último bueno
    if len(res["fallas"]) == len(piezas):
        sys.exit("ninguna fuente respondió; se conserva el archivo anterior")
    os.makedirs(os.path.dirname(SAL), exist_ok=True)
    json.dump(res, open(SAL, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({k: (v if k == "fallas" else "ok") for k, v in res.items() if k != "actualizado"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
