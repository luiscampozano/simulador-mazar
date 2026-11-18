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
               "x_galapagos": (-0.9, -89.6), "x_81o": (-2.0, -81.0)})
LEJOS = {"x_anticiclon": (-30.0, -90.0), "x_pascua": (-27.1, -109.4)}
AREA = [8, -92, -10, -74]            # N, O, S, E
AREA_LEJOS = [-26, -110, -31, -89]
CAJA_N12 = (0.0, -10.0, -90.0, -80.0)  # lat N, lat S, lon O, lon E (Niño 1+2)
HORAS = ["12:00", "15:00", "18:00", "21:00"]
SUP = ["convective_available_potential_energy", "convective_inhibition", "total_column_water_vapour", "2m_temperature",
       "2m_dewpoint_temperature", "low_cloud_cover", "volumetric_soil_water_layer_1", "sea_surface_temperature", "k_index",
       "total_totals_index", "mean_sea_level_pressure", "10m_u_component_of_wind", "10m_v_component_of_wind",
       "boundary_layer_height", "surface_solar_radiation_downwards", "total_precipitation"]
NIV = ["relative_humidity", "u_component_of_wind", "v_component_of_wind", "temperature", "vertical_velocity", "divergence"]
NIVELES = ["850", "700", "500", "300", "200"]
HORAS_NIV = ["12:00", "18:00", "23:00", "01:00"]     # 07 y 13 h locales (día) + 18 y 20 h locales (tarde-noche)
DIA_NIV, TARDE_NIV = (12, 18), (23, 1)
RHO = {"700": 0.91, "500": 0.69}                     # densidad típica (kg/m³) para pasar omega (Pa/s) a m/s
LATS_81 = [x / 2 for x in range(8, -13, -1)]        # franja a 81° O, de 4° N a 6° S
VARS = ["cape_max", "cin_min", "tcwv", "t2_max", "td2", "lcc", "suelo", "sst", "k_max", "tt_max", "msl", "v10", "blh_max",
        "sol_man", "pr", "hr850", "hr700", "hr500", "t850", "t500", "u850", "v850", "u700", "v700", "u500", "v500",
        "u300", "v300", "u200", "v200", "w700_t", "w500_t", "w500_d", "div200_t", "div200_d", "div850_t"]
LOCK = threading.Lock()


def cliente():
    import cdsapi
    tok = os.environ.get("CDS_API_KEY", "").strip()
    if not tok: sys.exit("Falta el secreto CDS_API_KEY")
    return cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=tok, quiet=False, debug=os.environ.get("SERIE_DEBUG") == "1", progress=False)


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
            r = getattr(e, "response", None)
            if r is not None:
                try: msg += " | " + r.text[:600]
                except Exception: pass
            print(f"  {conj} {req.get('month')}: intento {i + 1} falló: {msg[:800]}", flush=True)
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


def horas(da, t, hs):
    """Solo las horas UTC indicadas."""
    return da.where(da[t].dt.hour.isin(list(hs)), drop=True)


def trimestre(c, anio, meses, fin):
    r = base(anio, meses, fin)
    with ThreadPoolExecutor(3) as ex:
        fs = ex.submit(pedir, c, "reanalysis-era5-single-levels", dict(r, variable=SUP, area=AREA))
        fp = ex.submit(pedir, c, "reanalysis-era5-pressure-levels", dict(r, variable=NIV, pressure_level=NIVELES, area=AREA,
                                                                          time=HORAS_NIV))
        fl = ex.submit(pedir, c, "reanalysis-era5-single-levels", dict(r, variable=["mean_sea_level_pressure"], area=AREA_LEJOS,
                                                                       time=["12:00", "18:00"]))
        S, P, L = fs.result(), fp.result(), fl.result()
    out = {}
    ts, tp, tl = tiempo(S), tiempo(P), tiempo(L)
    niv = "pressure_level" if "pressure_level" in P.coords else "level"
    nv = lambda q, n: q.sel({niv: int(n)})
    pon = lambda d, k, nombre, x, nd=2: out.setdefault(d, {}).setdefault(k, {}).__setitem__(nombre, round(x, nd))
    for k, (la, lo) in PUNTOS.items():
        s, p = celda(S, la, lo), celda(P, la, lo)
        col = {}
        col["cape_max"] = por_dia(s["cape"], ts, np.nanmax)
        col["cin_min"] = por_dia(s["cin"], ts, np.nanmin)
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
        col["sol_man"] = {d: x / 3600 for d, x in por_dia(horas(s["ssrd"], ts, (12, 15)), ts, np.nanmean).items()}   # W/m², 07–10 h
        col["pr"] = {d: x * 1000 for d, x in por_dia(s["tp"], ts, np.nanmean).items()}                             # mm/h (muestra)
        pd_ = horas(p, tp, DIA_NIV)
        pt_ = horas(p, tp, TARDE_NIV)
        for n in ("850", "700", "500"):
            col["hr" + n] = por_dia(nv(pd_["r"], n), tp, np.nanmean)
        for n in ("850", "500"):
            col["t" + n] = {d: x - 273.15 for d, x in por_dia(nv(pd_["t"], n), tp, np.nanmean).items()}
        for n in NIVELES:
            col["u" + n] = por_dia(nv(pd_["u"], n), tp, np.nanmean)
            col["v" + n] = por_dia(nv(pd_["v"], n), tp, np.nanmean)
        for n in ("700", "500"):      # positivo = aire que sube (m/s)
            col[f"w{n}_t"] = {d: -x / (RHO[n] * 9.81) for d, x in por_dia(nv(pt_["w"], n), tp, np.nanmean).items()}
        col["w500_d"] = {d: -x / (RHO["500"] * 9.81) for d, x in por_dia(nv(pd_["w"], "500"), tp, np.nanmean).items()}
        col["div200_t"] = {d: x * 1e5 for d, x in por_dia(nv(pt_["d"], "200"), tp, np.nanmean).items()}   # ×10⁻⁵ /s
        col["div200_d"] = {d: x * 1e5 for d, x in por_dia(nv(pd_["d"], "200"), tp, np.nanmean).items()}
        col["div850_t"] = {d: x * 1e5 for d, x in por_dia(nv(pt_["d"], "850"), tp, np.nanmean).items()}
        for nombre, serie in col.items():
            for d, x in serie.items(): pon(d, k, nombre, x, 3 if nombre in ("suelo", "w700_t", "w500_t", "w500_d", "pr") else 2)
    for k, (la, lo) in LEJOS.items():
        for d, x in por_dia(celda(L, la, lo)["msl"], tl, np.nanmean).items(): pon(d, k, "msl", x / 100)
    n, s_, o, e = CAJA_N12
    caja = S["sst"].sel(latitude=slice(n, s_), longitude=slice(o, e)).mean(["latitude", "longitude"])
    for d, x in por_dia(caja, ts, np.nanmean).items(): pon(d, "x_nino12", "sst", x - 273.15)
    # franja a 81° O (ZCIT sur): convergencia en 850 hPa (día completo) y lluvia de muestra, por latitud
    for la in LATS_81:
        q, z = celda(P, la, -81.0), celda(S, la, -81.0)
        for d, x in por_dia(nv(q["d"], "850"), tp, np.nanmean).items(): pon(d, "x_z81", f"c{la:+.1f}", -x * 1e5)
        for d, x in por_dia(z["tp"], ts, np.nanmean).items(): pon(d, "x_z81", f"p{la:+.1f}", x * 1000, 3)
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
    pts = {**PUNTOS, **LEJOS, "x_nino12": None, "x_z81": {"lon": -81.0, "lats": LATS_81}}
    with gzip.open(salida, "wt", encoding="utf-8") as f:
        json.dump({"fuente": "ERA5 (Copernicus C3S, CC-BY 4.0), celda más cercana; superficie 12-21 UTC; niveles 12 y 18 UTC (_d) y 23 y 01 UTC (_t)", "anio": anio,
                   "vars": VARS, "puntos": pts, "dias": dict(sorted(todo.items()))}, f, ensure_ascii=False, separators=(",", ":"))
    print(anio, "listo:", len(todo), "días")


if __name__ == "__main__":
    main()
