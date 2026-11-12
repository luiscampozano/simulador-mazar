"""DataLab Clima · instrumentos públicos del mar (Luis, 1 nov: "los instrumentos que se puedan sumar para ayudar al clima").

  1. Mareógrafos de la UNESCO (IOC Sea Level Monitoring, API v1 sin clave; uso no comercial): nivel del mar medido.
     Tiempo real: La Libertad, Baltra, Santa Cruz. Con ~1 día de retraso (Inocar): Río Guayas (Guayaquil), Puerto
     Bolívar, Puná, Esmeraldas, Puerto López, Bahía, San Lorenzo, Puerto Atún (Manta).
     Se guarda el promedio horario y la anomalía frente a la media de los 3 días (sirve para ver la marea real frente
     a la tabla del Inocar y si el mar está más alto de lo normal: oleaje, viento, El Niño).
  2. Boyas y flotadores (NOAA OSMC, ERDDAP, sin clave): boyas TAO a 95° O (0°, 2° N, 2° S), flotadores Argo y barcos
     frente a Ecuador: temperatura del mar, del aire, presión y viento.
  3. Temperatura del mar por satélite (NOAA OISST v2.1, diaria) y su anomalía en puntos de la costa y Galápagos.
Salida: clima/registro/instrumentos/ultimo.json (y una copia diaria). Si una fuente falla, las demás siguen."""
import csv, io, json, os, statistics as st, urllib.request
from datetime import datetime, timedelta, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(AQUI, "registro", "instrumentos")
EC = timezone(timedelta(hours=-5))
UA = {"User-Agent": "DataLab Ec (clima; datalabecuador.com)"}
MAREOGRAFOS = {"lali": "La Libertad", "balt": "Baltra (Galápagos)", "sant": "Santa Cruz (Galápagos)", "gyer": "Guayaquil (Río Guayas)",
               "pbol": "Puerto Bolívar", "puna": "Puná", "esme": "Esmeraldas", "plop": "Puerto López", "bcar": "Bahía de Caráquez",
               "slor": "San Lorenzo", "patu": "Puerto Atún (Manta)"}
PREF_SENSOR = ("rad", "prs", "ras", "pr1", "enc", "flt")
PUNTOS_SST = {"Golfo de Guayaquil": (-2.875, 279.875), "Salinas": (-2.125, 278.875), "Manta": (-0.875, 279.125),
              "Esmeraldas": (1.125, 280.125), "Galápagos (Santa Cruz)": (-0.875, 269.625)}


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def mareografos(ahora):
    t1 = ahora.astimezone(timezone.utc); t0 = t1 - timedelta(days=3)
    out = {}
    for code, nom in MAREOGRAFOS.items():
        try:
            j = json.loads(get("https://www.ioc-sealevelmonitoring.org/service.php?query=data&code=" + code +
                               f"&timestart={t0:%Y-%m-%dT%H:%M:%S}&timestop={t1:%Y-%m-%dT%H:%M:%S}&format=json"))
        except Exception as e:
            out[code] = {"nombre": nom, "error": str(e)[:100]}; continue
        sens = {}
        for x in j if isinstance(j, list) else []:
            if isinstance(x.get("slevel"), (int, float)): sens.setdefault(x.get("sensor"), []).append(x)
        s = next((k for k in PREF_SENSOR if len(sens.get(k, [])) > 20), None)
        if not s:
            out[code] = {"nombre": nom, "error": "sin datos recientes"}; continue
        hor = {}
        for x in sens[s]:
            h = (datetime.fromisoformat(x["stime"]).replace(tzinfo=timezone.utc).astimezone(EC)).strftime("%Y-%m-%dT%H")
            hor.setdefault(h, []).append(x["slevel"])
        horas = {h: round(st.median(v), 3) for h, v in sorted(hor.items()) if len(v) >= 2}
        if len(horas) < 6:
            out[code] = {"nombre": nom, "error": "pocas horas"}; continue
        if max(horas.values()) - min(horas.values()) < 0.05:
            out[code] = {"nombre": nom, "error": "sensor sin variación (dato congelado)"}; continue
        media = st.mean(horas.values())
        ult = max(horas)
        out[code] = {"nombre": nom, "sensor": s, "ultima_hora": ult, "nivel_m": horas[ult],
                     "anomalia_m": round(horas[ult] - media, 3), "rango_3d_m": round(max(horas.values()) - min(horas.values()), 2),
                     "retraso_h": round((ahora - datetime.fromisoformat(ult + ":00").replace(tzinfo=EC)).total_seconds() / 3600, 1),
                     "serie": {h: round(v - media, 3) for h, v in list(horas.items())[-72:]}}
    return out


def boyas(ahora):
    t0 = (ahora - timedelta(days=2)).astimezone(timezone.utc)
    url = ("https://osmc.noaa.gov/erddap/tabledap/OSMC_30day.csv?platform_code,platform_type,time,latitude,longitude,sst,atmp,slp,windspd"
           f"&time>={t0:%Y-%m-%dT%H:%M:%SZ}&latitude>=-6&latitude<=4&longitude>=-96&longitude<=-78")
    filas = list(csv.reader(io.StringIO(get(url.replace(">=", "%3E=").replace("<=", "%3C="), 90))))[2:]
    plat = {}
    for p, tipo, t, la, lo, sst, atmp, slp, ws in filas:
        def n(v, lo_, hi_):
            try:
                v = float(v); return v if lo_ <= v <= hi_ else None
            except Exception: return None
        r = {"t": t, "lat": n(la, -90, 90), "lon": n(lo, -180, 180), "sst": n(sst, 15, 35), "aire": n(atmp, 10, 40),
             "presion": n(slp, 980, 1040), "viento": n(ws, 0, 60)}
        if not any(r[k] is not None for k in ("sst", "aire", "presion", "viento")): continue
        q = plat.setdefault(p, {"tipo": tipo, "lecturas": []}); q["lecturas"].append(r)
    out = {}
    for p, q in plat.items():
        L = sorted(q["lecturas"], key=lambda r: r["t"])
        u = L[-1]
        ult = {k: next((r[k] for r in reversed(L) if r[k] is not None), None) for k in ("sst", "aire", "presion", "viento")}
        sst24 = [r["sst"] for r in L if r["sst"] is not None and r["t"] >= (ahora - timedelta(hours=24)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H")]
        out[p] = {"tipo": {"TROPICAL MOORED BUOYS": "boya TAO", "PROFILING FLOATS AND GLIDERS": "flotador Argo",
                           "VOLUNTEER OBSERVING SHIPS": "barco", "DRIFTING BUOYS": "boya a la deriva"}.get(q["tipo"], q["tipo"]),
                  "ultima": u["t"], "lat": u["lat"], "lon": u["lon"], **ult,
                  "sst_media_24h": round(st.mean(sst24), 2) if sst24 else None, "lecturas": len(L)}
    return out


def sst_satelite():
    out = {}
    for nom, (la, lo) in PUNTOS_SST.items():
        try:
            t = get("https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21NrtAgg.csv?"
                    f"sst[(last)][(0.0)][({la})][({lo})],anom[(last)][(0.0)][({la})][({lo})]", 90)
            r = list(csv.reader(io.StringIO(t)))[2]
            out[nom] = {"fecha": r[0][:10], "sst": round(float(r[4]), 2), "anomalia": round(float(r[5]), 2)}
        except Exception as e:
            out[nom] = {"error": str(e)[:100]}
    return out


def main():
    ahora = datetime.now(EC)
    res = {"actualizado": ahora.isoformat(timespec="minutes"),
           "fuentes": "IOC Sea Level Monitoring (UNESCO, uso no comercial); NOAA OSMC (boyas TAO, Argo, barcos); NOAA OISST v2.1"}
    for k, f in (("mareografos", lambda: mareografos(ahora)), ("boyas", lambda: boyas(ahora)), ("sst", sst_satelite)):
        try:
            res[k] = f()
        except Exception as e:
            res[k] = {"error": str(e)[:150]}
        print(k, json.dumps(res[k], ensure_ascii=False)[:700])
    os.makedirs(D, exist_ok=True)
    for p in (os.path.join(D, "ultimo.json"), os.path.join(D, ahora.date().isoformat() + ".json")):
        with open(p, "w", encoding="utf-8") as fh: json.dump(res, fh, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
