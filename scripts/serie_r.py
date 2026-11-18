"""Serie R: valores diarios de ERA5 (Copernicus C3S, licencia CC-BY 4.0) en puntos fijos del Ecuador y del Pacífico, 1981–hoy.

Dos partes (17 nov: la cola general del CDS para ERA5 en rejilla tiene miles de pedidos esperando):
  python3 scripts/serie_r.py puntos            → superficie por punto con el conjunto de series de tiempo (rápido, sin cola):
                                                 r/s_<punto>.json.gz
  python3 scripts/serie_r.py rejilla s|p MIN   → CAPE y afines (s, por semestre) o niveles de presión (p, por trimestre) en
                                                 rejilla, pedazo por pedazo, guardando cada uno apenas llega
                                                 (r/g_<año>_<pedazo>.json.gz) hasta agotar MIN minutos. Retoma lo que falte.
Días de Ecuador (UTC−5). Necesita el secreto CDS_API_KEY. Corre en GitHub Actions (repo público, sin costo de minutos)."""
import csv, gzip, io, json, math, os, subprocess, sys, tempfile, time, zipfile
from datetime import date, datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.join(AQUI, "..")
PUNTOS = {k: tuple(v) for k, v in json.load(open(os.path.join(AQUI, "puntos_clima.json"))).items()}
PUNTOS.update({"Bahía de Caráquez": (-0.598, -80.424), "Piñas": (-3.681, -79.681),
               "x_golfo": (-3.0, -80.6), "x_humboldt": (-8.0, -80.5), "x_choco": (5.0, -79.0), "x_amazonia": (-1.5, -76.5),
               "x_galapagos": (-0.9, -89.6), "x_81o": (-2.0, -81.0)})
LEJOS = {"x_anticiclon": (-30.0, -90.0), "x_pascua": (-27.1, -109.4)}
AREA = [8, -92, -10, -74]                 # N, O, S, E
LATS_81 = [x / 2 for x in range(8, -13, -1)]
INICIO = 1981
SERIE_VARS = ["2m_temperature", "2m_dewpoint_temperature", "boundary_layer_height", "mean_sea_level_pressure",
              "sea_surface_temperature", "surface_solar_radiation_downwards", "total_precipitation", "10m_u_component_of_wind",
              "10m_v_component_of_wind", "total_cloud_cover", "surface_latent_heat_flux"]
G_SUP = ["convective_available_potential_energy", "convective_inhibition", "total_column_water_vapour", "low_cloud_cover",
         "volumetric_soil_water_layer_1", "k_index", "total_totals_index"]
G_NIV = ["relative_humidity", "u_component_of_wind", "v_component_of_wind", "temperature", "vertical_velocity", "divergence"]
NIVELES = ["850", "700", "500", "200"]
RHO = {"850": 1.06, "700": 0.91, "500": 0.69}   # densidad típica (kg/m³): omega (Pa/s) → m/s
DATOS = os.environ.get("SERIE_DATOS", os.path.join(RAIZ, "_serie_r"))   # clon de la rama serie-r (lo prepara el workflow)


def cliente():
    import cdsapi
    tok = os.environ.get("CDS_API_KEY", "").strip()
    if not tok: sys.exit("Falta el secreto CDS_API_KEY")
    return cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=tok, quiet=False, progress=False)


def fin_datos():
    return date.today() - timedelta(days=8)          # ERA5 sale con ~5 días de atraso


def pedir(c, conj, req, dest, intentos=8):
    """Un pedido a la vez. Si la cola personal está llena, espera y reintenta."""
    for i in range(intentos):
        try:
            c.retrieve(conj, req, dest)
            return dest
        except Exception as e:
            msg = str(e)
            r = getattr(e, "response", None)
            if r is not None:
                try: msg += " | " + r.text[:500]
                except Exception: pass
            print(f"  {conj}: intento {i + 1} falló: {msg[:300]}", flush=True)
            if "too large" in msg.lower() or "cost limits" in msg.lower(): raise RuntimeError("too large: " + msg[:200])
            time.sleep(300 if "queued" in msg.lower() else 60 * min(i + 1, 5))
    raise RuntimeError(f"{conj} sin datos tras {intentos} intentos")


def guardar(rel, obj):
    """Escribe el archivo en la rama serie-r y lo empuja enseguida (si la tarea se corta, lo bajado no se pierde)."""
    datos = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    sh = lambda *a: subprocess.run(a, cwd=DATOS, check=True, capture_output=True, text=True)
    for i in range(6):
        try:
            sh("git", "fetch", "-q", "origin", "serie-r"); sh("git", "reset", "-q", "--hard", "origin/serie-r")
            ruta = os.path.join(DATOS, rel); os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with gzip.open(ruta, "wb") as f: f.write(datos)
            sh("git", "add", rel)
            if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=DATOS).returncode == 0: return
            sh("git", "commit", "-q", "-m", f"Serie R: {rel} [skip ci]"); sh("git", "push", "-q", "origin", "HEAD:serie-r")
            print("  guardado", rel, flush=True); return
        except subprocess.CalledProcessError as e:
            print("  guardar: reintento", i + 1, (e.stderr or "")[:200], flush=True); time.sleep(5 + 7 * i)
    raise RuntimeError("no se pudo guardar " + rel)


def existentes():
    try: return set(subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/serie-r"], cwd=DATOS, capture_output=True,
                                   text=True, check=True).stdout.split())
    except Exception: return set()


# ---------- superficie por punto (series de tiempo, sin cola) ----------
def leer_series(ruta):
    textos = []
    if zipfile.is_zipfile(ruta):
        with zipfile.ZipFile(ruta) as z: textos = [z.read(n).decode() for n in z.namelist() if n.endswith(".csv")]
    else: textos = [open(ruta, encoding="utf-8").read()]
    S = {}
    for texto in textos:
        filas = list(csv.DictReader(io.StringIO(texto)))
        if not filas: continue
        ct = next(c for c in filas[0] if "time" in c.lower())
        for c in filas[0]:
            if c in (ct, "latitude", "longitude"): continue
            s = S.setdefault(c, {})
            for f in filas:
                try:
                    v = f[c]
                    if v in ("", "nan"): continue
                    s[datetime.fromisoformat(f[ct].replace("Z", "")[:19])] = float(v)
                except Exception: pass
    return S


def diarios_superficie(S):
    """Horas UTC → valores por día de Ecuador."""
    por = {}
    for var, s in S.items():
        for t, v in s.items():
            lt = t - timedelta(hours=5)
            por.setdefault(lt.date().isoformat(), {}).setdefault(var, []).append((lt.hour, v))
    out = {}
    rango = lambda L, a, b: [v for h, v in L if a <= h <= b]
    prom = lambda x: sum(x) / len(x) if x else None
    for d, V in por.items():
        o = {}
        g = lambda *k: next((sorted(V[x]) for x in k if x in V), [])
        t2, td, blh, msl, sst = g("t2m"), g("d2m"), g("blh"), g("msl"), g("sst")
        ssr, tp, u, v, tcc, lhf = g("ssrd"), g("tp"), g("u10"), g("v10"), g("tcc"), g("slhf")
        if t2: o["t2_max"] = max(x for _, x in t2) - 273.15; o["t2_min"] = min(x for _, x in t2) - 273.15
        if rango(td, 7, 16): o["td2"] = prom(rango(td, 7, 16)) - 273.15
        if blh: o["blh_max"] = max(x for _, x in blh)
        if msl: o["msl"] = prom([x for _, x in msl]) / 100
        if sst: o["sst"] = prom([x for _, x in sst]) - 273.15
        if rango(ssr, 7, 10): o["sol_man"] = prom(rango(ssr, 7, 10)) / 3600
        if len(tp) >= 20: o["pr"] = sum(x for _, x in tp) * 1000
        if rango(u, 7, 16) and len(u) == len(v): o["v10"] = prom([math.hypot(a, b) for (h, a), (_, b) in zip(u, v) if 7 <= h <= 16])
        if rango(tcc, 7, 12): o["nubes_man"] = prom(rango(tcc, 7, 12))
        if lhf: o["lhf"] = -prom([x for _, x in lhf]) / 3600
        out[d] = {k: round(x, 2) for k, x in o.items() if x is not None}
    return dict(sorted(out.items()))


def parte_puntos():
    c, hasta, hay = cliente(), fin_datos().isoformat(), existentes()
    for n, (la, lo) in {**PUNTOS, **LEJOS}.items():
        rel = f"r/s_{n.replace('/', '-').replace(' ', '_')}.json.gz"
        if rel in hay and os.environ.get("SERIE_REHACER") != "1": continue
        tmp = tempfile.mktemp(suffix=".csv")
        try:
            pedir(c, "reanalysis-era5-single-levels-timeseries", {"variable": SERIE_VARS, "location": {"latitude": la, "longitude": lo},
                                                                    "date": [f"{INICIO}-01-01/{hasta}"], "data_format": "csv"}, tmp)
            D = diarios_superficie(leer_series(tmp))
            guardar(rel, {"punto": n, "la": la, "lo": lo, "fuente": "ERA5 series de tiempo (Copernicus C3S, CC-BY 4.0)", "dias": D})
            print(n, len(D), "días", flush=True)
        except Exception as e:
            print(n, "FALLÓ", str(e)[:300], flush=True)
        finally:
            if os.path.exists(tmp): os.remove(tmp)


# ---------- rejilla (cola del CDS), por pedazos ----------
def pedazos(tipo):
    f = fin_datos()
    grupos = ([1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]) if tipo == "s" else ([1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12])
    for a in range(INICIO, f.year + 1):
        for k, m in enumerate(grupos, 1):
            m = [x for x in m if a < f.year or x < f.month]      # solo meses completos
            if a == f.year and m and m[-1] != grupos[k - 1][-1]: continue   # pedazo del año en curso todavía incompleto
            if m: yield a, f"{tipo}{k}", m


def abrir(f):
    import xarray as xr
    if zipfile.is_zipfile(f):
        d = tempfile.mkdtemp()
        with zipfile.ZipFile(f) as z: z.extractall(d)
        return xr.merge([xr.open_dataset(os.path.join(d, n)).load() for n in sorted(os.listdir(d)) if n.endswith(".nc")], compat="override")
    return xr.open_dataset(f).load()


def por_dia(da, fn, horas=None):
    import numpy as np
    t = "valid_time" if "valid_time" in da.coords else "time"
    if horas is not None: da = da.where(da[t].dt.hour.isin(list(horas)), drop=True)
    tt = (da[t].values - np.timedelta64(5, "h")).astype("datetime64[D]").astype(str)
    v = da.values.astype(float); out = {}
    for d in np.unique(tt):
        x = v[tt == d]; x = x[~np.isnan(x)]
        if len(x): out[d] = float(fn(x))
    return out


def pedazo(c, anio, tag, meses):
    import numpy as np
    req = {"product_type": ["reanalysis"], "year": [str(anio)], "month": [f"{m:02d}" for m in meses],
           "day": [f"{d:02d}" for d in range(1, 32)], "data_format": "netcdf", "download_format": "unarchived", "area": AREA}
    tmp = tempfile.mktemp(suffix=".nc"); out = {}

    def pon(d, k, n, x, nd=2):
        if str(d).startswith(str(anio)): out.setdefault(str(d), {}).setdefault(k, {})[n] = round(x, nd)
    try:
        if tag.startswith("s"):
            pedir(c, "reanalysis-era5-single-levels", dict(req, variable=G_SUP, time=["12:00", "15:00", "18:00", "21:00"]), tmp)
            S = abrir(tmp)
            for k, (la, lo) in PUNTOS.items():
                s = S.sel(latitude=la, longitude=lo, method="nearest")
                for n, var, fn in (("cape_max", "cape", np.nanmax), ("cin_min", "cin", np.nanmin), ("tcwv", "tcwv", np.nanmean),
                                   ("lcc", "lcc", np.nanmean), ("suelo", "swvl1", np.nanmean), ("k_max", "kx", np.nanmax),
                                   ("tt_max", "totalx", np.nanmax)):
                    for d, x in por_dia(s[var], fn).items(): pon(d, k, n, x, 3 if n == "suelo" else 2)
        else:
            pedir(c, "reanalysis-era5-pressure-levels", dict(req, variable=G_NIV, pressure_level=NIVELES, time=["18:00", "23:00"]), tmp)
            P = abrir(tmp)
            nv = "pressure_level" if "pressure_level" in P.coords else "level"
            for k, (la, lo) in PUNTOS.items():
                p = P.sel(latitude=la, longitude=lo, method="nearest")
                for suf, h in (("_d", [18]), ("_t", [23])):        # _d = 13 h local; _t = 18 h local
                    for n in NIVELES:
                        q = p.sel({nv: int(n)})
                        if n != "200":
                            for d, x in por_dia(q["r"], np.nanmean, h).items(): pon(d, k, f"hr{n}{suf}", x)
                        for d, x in por_dia(q["u"], np.nanmean, h).items(): pon(d, k, f"u{n}{suf}", x)
                        for d, x in por_dia(q["v"], np.nanmean, h).items(): pon(d, k, f"v{n}{suf}", x)
                        if n in ("850", "500"):
                            for d, x in por_dia(q["t"], np.nanmean, h).items(): pon(d, k, f"t{n}{suf}", x - 273.15)
                        if n in RHO:
                            for d, x in por_dia(q["w"], np.nanmean, h).items(): pon(d, k, f"w{n}{suf}", -x / (RHO[n] * 9.81), 3)
                        if n in ("200", "850"):
                            for d, x in por_dia(q["d"], np.nanmean, h).items(): pon(d, k, f"div{n}{suf}", x * 1e5)
            for la in LATS_81:   # franja a 81° O (ZCIT sur): convergencia en 850 hPa
                q = P.sel(latitude=la, longitude=-81.0, method="nearest").sel({nv: 850})
                for d, x in por_dia(q["d"], np.nanmean).items(): pon(d, "x_z81", f"c{la:+.1f}", -x * 1e5)
    finally:
        if os.path.exists(tmp): os.remove(tmp)
    return dict(sorted(out.items()))


def parte_rejilla(tipo, minutos):
    c, t0, hay = cliente(), time.time(), existentes()
    for anio, tag, meses in pedazos(tipo):
        rel = f"r/g_{anio}_{tag}.json.gz"
        if rel in hay: continue
        if time.time() - t0 > minutos * 60: print("sin tiempo; sigue en la próxima corrida", flush=True); break
        t1 = time.time()
        try: D = pedazo(c, anio, tag, meses)
        except Exception as e:
            print(anio, tag, "FALLÓ", str(e)[:300], flush=True); continue
        guardar(rel, {"anio": anio, "pedazo": tag, "meses": meses, "fuente": "ERA5 (Copernicus C3S, CC-BY 4.0), celda más cercana",
                      "horas": "s: 12-21 UTC; p: 18 UTC (_d, 13 h) y 23 UTC (_t, 18 h)", "dias": D})
        print(anio, tag, f"{len(D)} días en {(time.time() - t1) / 60:.0f} min", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "puntos": parte_puntos()
    elif len(sys.argv) > 3 and sys.argv[1] == "rejilla": parte_rejilla(sys.argv[2], float(sys.argv[3]))
    else: sys.exit("uso: puntos | rejilla s|p MIN")
