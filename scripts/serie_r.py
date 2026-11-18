"""Serie R: valores diarios de ERA5 (Copernicus C3S, licencia CC-BY 4.0) en puntos fijos del Ecuador y del Pacífico, 1981–hoy.

Uso: python3 scripts/serie_r.py AÑO salida.json.gz
Baja por trimestre tres pedidos al CDS (superficie, niveles de presión y presión lejana), toma la celda más cercana a cada
punto y guarda un valor por día de Ecuador (UTC−5) con las horas 12, 15, 18 y 21 UTC (07–16 h locales).
Necesita el secreto CDS_API_KEY. Corre en GitHub Actions (repo público, sin costo de minutos)."""
import gzip, json, math, os, sys, tempfile, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import xarray as xr

AQUI = os.path.dirname(os.path.abspath(__file__))
PUNTOS = {k: tuple(v) for k, v in json.load(open(os.path.join(AQUI, "puntos_clima.json"))).items()}
PUNTOS.update({"Bahía de Caráquez": (-0.598, -80.424), "Piñas": (-3.681, -79.681),
               "x_golfo": (-3.0, -80.6), "x_humboldt": (-8.0, -80.5), "x_choco": (5.0, -79.0), "x_amazonia": (-1.5, -76.5),
               "x_galapagos": (-0.9, -89.6)})
LEJOS = {"x_anticiclon": (-30.0, -90.0), "x_pascua": (-27.1, -109.4)}
AREA = [8, -92, -10, -74]            # N, O, S, E
AREA_LEJOS = [-26, -110, -31, -89]
CAJA_N12 = (0.0, -10.0, -90.0, -80.0)  # lat N, lat S, lon O, lon E (Niño 1+2)
HORAS = ["12:00", "15:00", "18:00", "21:00"]
SUP = ["convective_available_potential_energy", "convective_inhibition", "total_column_water_vapour", "2m_temperature",
       "2m_dewpoint_temperature", "low_cloud_cover", "volumetric_soil_water_layer_1", "sea_surface_temperature", "k_index",
       "total_totals_index", "mean_sea_level_pressure", "10m_u_component_of_wind", "10m_v_component_of_wind",
       "boundary_layer_height"]
NIV = ["relative_humidity", "u_component_of_wind", "v_component_of_wind"]
NIVELES = ["850", "700", "500", "200"]
VARS = ["cape_max", "cin_min", "tcwv", "t2_max", "td2", "lcc", "suelo", "sst", "k_max", "tt_max", "msl", "v10", "blh_max",
        "hr850", "hr700", "hr500", "v850", "d850", "v700", "d700", "v500", "d500", "v200", "d200"]
LOCK = threading.Lock()


def cliente():
    import cdsapi
    tok = os.environ.get("CDS_API_KEY", "").strip()
    if not tok: sys.exit("Falta el secreto CDS_API_KEY")
    return cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=tok, quiet=True, progress=False)


def abrir(f):
    """El CDS a veces entrega un zip con varios .nc (uno por tipo de variable): se juntan."""
    if zipfile.is_zipfile(f):
        d = tempfile.mkdtemp()
        with zipfile.ZipFile(f) as z: z.extractall(d)
        return xr.merge([xr.open_dataset(os.path.join(d, n)).load() for n in sorted(os.listdir(d)) if n.endswith(".nc")], compat="override")
    return xr.open_dataset(f).load()


def pedir(c, conj, req, intentos=4):
    for i in range(intentos):
        f = tempfile.mktemp(suffix=".nc")
        try:
            c.retrieve(conj, req, f)
            return abrir(f)
        except Exception as e:
            msg = str(e)
            print(f"  {conj} {req.get('month')}: intento {i + 1} falló: {msg[:200]}", flush=True)
            if "too large" in msg.lower() or "cost limits" in msg.lower(): raise
            time.sleep(60 * (i + 1))
        finally:
            if os.path.exists(f): os.remove(f)
    raise RuntimeError(f"{conj} sin datos tras {intentos} intentos")


def base(anio, meses, fin):
    ult = 31 if (anio, meses[-1]) != (fin.year, fin.month) else fin.day      # el mes en curso solo hasta lo publicado
    dias = [f"{d:02d}" for d in range(1, ult + 1)]
    return {"product_type": ["reanalysis"], "year": [str(anio)], "month": [f"{m:02d}" for m in meses], "day": dias,
            "time": HORAS, "data_format": "netcdf", "download_format": "unarchived"}


def tiempo(ds):
    return "valid_time" if "valid_time" in ds.coords else "time"


def celda(ds, la, lo):
    return ds.sel(latitude=la, longitude=lo, method="nearest")


def por_dia(da, t, fn):
    """Agrupa una serie (horas UTC) por día de Ecuador y aplica fn (np.nanmax, np.nanmin o np.nanmean)."""
    out = {}
    tt = (da[t].values - np.timedelta64(5, "h")).astype("datetime64[D]").astype(str)
    v = da.values.astype(float)
    for dia in np.unique(tt):
        x = v[tt == dia]
        x = x[~np.isnan(x)]
        if len(x): out[dia] = float(fn(x))
    return out


def viento(u, v):
    return math.hypot(u, v), (math.degrees(math.atan2(-u, -v)) + 360) % 360


def trimestre(c, anio, meses, fin):
    r = base(anio, meses, fin)
    with ThreadPoolExecutor(3) as ex:
        fs = ex.submit(pedir, c, "reanalysis-era5-single-levels", dict(r, variable=SUP, area=AREA))
        fp = ex.submit(pedir, c, "reanalysis-era5-pressure-levels", dict(r, variable=NIV, pressure_level=NIVELES, area=AREA,
                                                                          time=["12:00", "18:00"]))
        fl = ex.submit(pedir, c, "reanalysis-era5-single-levels", dict(r, variable=["mean_sea_level_pressure"], area=AREA_LEJOS,
                                                                       time=["12:00", "18:00"]))
        S, P, L = fs.result(), fp.result(), fl.result()
    out = {}
    ts, tp, tl = tiempo(S), tiempo(P), tiempo(L)
    niv = "pressure_level" if "pressure_level" in P.coords else "level"
    for k, (la, lo) in PUNTOS.items():
        s, p = celda(S, la, lo), celda(P, la, lo)
        col = {}
        col["cape_max"] = por_dia(s["cape"], ts, np.nanmax)
        col["cin_min"] = por_dia(s["cin"], ts, np.nanmin) if "cin" in s else {}
        col["tcwv"] = por_dia(s["tcwv"], ts, np.nanmean)
        col["t2_max"] = {d: x - 273.15 for d, x in por_dia(s["t2m"], ts, np.nanmax).items()}
        col["td2"] = {d: x - 273.15 for d, x in por_dia(s["d2m"], ts, np.nanmean).items()}
        col["lcc"] = por_dia(s["lcc"], ts, np.nanmean)
        col["suelo"] = por_dia(s["swvl1"], ts, np.nanmean)
        col["sst"] = {d: x - 273.15 for d, x in por_dia(s["sst"], ts, np.nanmean).items()}
        col["k_max"] = por_dia(s["kx"], ts, np.nanmax)
        col["tt_max"] = por_dia(s["totalx"], ts, np.nanmax)
        col["msl"] = {d: x / 100 for d, x in por_dia(s["msl"], ts, np.nanmean).items()}
        col["v10"] = por_dia(np.hypot(s["u10"], s["v10"]), ts, np.nanmean)
        col["blh_max"] = por_dia(s["blh"], ts, np.nanmax)
        for n in ("850", "700", "500", "200"):
            q = p.sel({niv: int(n)})
            if n != "200": col["hr" + n] = por_dia(q["r"], tp, np.nanmean)
            U, V = por_dia(q["u"], tp, np.nanmean), por_dia(q["v"], tp, np.nanmean)
            vv = {d: viento(U[d], V[d]) for d in U if d in V}
            col["v" + n] = {d: x[0] for d, x in vv.items()}
            col["d" + n] = {d: x[1] for d, x in vv.items()}
        for nombre, serie in col.items():
            for d, x in serie.items():
                out.setdefault(d, {}).setdefault(k, {})[nombre] = round(x, 3 if nombre == "suelo" else 2)
    for k, (la, lo) in LEJOS.items():
        for d, x in por_dia(celda(L, la, lo)["msl"], tl, np.nanmean).items():
            out.setdefault(d, {}).setdefault(k, {})["msl"] = round(x / 100, 2)
    n, s_, o, e = CAJA_N12
    caja = S["sst"].sel(latitude=slice(n, s_), longitude=slice(o, e)).mean(["latitude", "longitude"])
    for d, x in por_dia(caja, ts, np.nanmean).items():
        out.setdefault(d, {}).setdefault("x_nino12", {})["sst"] = round(x - 273.15, 2)
    return out


def main():
    anio, salida = int(sys.argv[1]), sys.argv[2]
    fin = date.today() - timedelta(days=7)          # ERA5 sale con ~5 días de retraso
    c = cliente()
    todo = {}
    for meses in ([1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12]):
        meses = [m for m in meses if date(anio, m, 1) <= fin]
        if not meses: break
        if anio == fin.year and fin.month in meses and len(meses) > 1:      # año en curso: el último mes va aparte
            meses_previos = [m for m in meses if m != fin.month]
            todo.update(trimestre(c, anio, meses_previos, fin)); meses = [fin.month]
        t0 = time.time()
        try:
            parte = trimestre(c, anio, meses, fin)
        except Exception as e:
            if "too large" in str(e).lower() or "cost limits" in str(e).lower():
                parte = {}
                for m in meses: parte.update(trimestre(c, anio, [m], fin))
            else: raise
        todo.update({d: v for d, v in parte.items() if d <= fin.isoformat() and d.startswith(str(anio))})
        print(f"{anio} meses {meses}: {len(parte)} días en {time.time() - t0:.0f} s", flush=True)
    pts = {**PUNTOS, **LEJOS, "x_nino12": None}
    with gzip.open(salida, "wt", encoding="utf-8") as f:
        json.dump({"fuente": "ERA5 (Copernicus C3S, CC-BY 4.0), celda más cercana; horas 12-21 UTC", "anio": anio,
                   "vars": VARS, "puntos": pts, "dias": dict(sorted(todo.items()))}, f, ensure_ascii=False, separators=(",", ":"))
    print(anio, "listo:", len(todo), "días")


if __name__ == "__main__":
    main()
