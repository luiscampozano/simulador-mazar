"""Serie N: reanálisis NCEP/NCAR R1 (NOAA PSL, dominio público), promedios diarios desde 1981, rejilla de 2,5°.

Uso: python3 scripts/serie_n.py AÑO salida.nc
Baja los archivos diarios del año, recorta una caja del Pacífico ecuatorial oriental (10° N–10° S, 95°–70° O) y guarda
un netCDF pequeño. Aparte, la presión al nivel del mar en dos puntos lejanos (anticiclón e isla de Pascua).
Sin cuenta ni cola. Corre en GitHub Actions (repo público, sin costo de minutos)."""
import os, subprocess, sys, tempfile, time

import numpy as np
import xarray as xr

# Dos rutas al mismo archivo; el servidor de descargas rechaza (403) clientes sin "User-Agent" de navegador.
BASES = ["https://downloads.psl.noaa.gov/Datasets/ncep.reanalysis/Dailies/",
         "https://psl.noaa.gov/thredds/fileServer/Datasets/ncep.reanalysis/Dailies/"]
UA = "Mozilla/5.0 (X11; Linux x86_64) DataLabEc-investigacion"
NIVEL = {"omega": [850, 700, 500, 200], "uwnd": [850, 500, 200], "vwnd": [850, 500, 200], "rhum": [850, 700, 500], "air": [850, 500]}
SUP = {"pr_wtr": "surface/pr_wtr.eatm.{a}.nc", "lftx": "surface/lftx.sfc.{a}.nc", "slp": "surface/slp.{a}.nc"}
CAJA = dict(lat=slice(10, -10), lon=slice(265, 290))
LEJOS = {"x_anticiclon": (-30.0, 270.0), "x_pascua": (-27.5, 250.0)}


def bajar(ruta):
    f = tempfile.mktemp(suffix=".nc")
    for i in range(4):
        for base in BASES:
            r = subprocess.run(["curl", "-sfL", "--http1.1", "--retry", "3", "-A", UA, "-o", f, base + ruta], capture_output=True, text=True)
            if r.returncode == 0 and os.path.getsize(f) > 10000:
                return f
            print("  ", base.split("/")[2], ruta, "intento", i + 1, "curl", r.returncode, r.stderr.strip()[:200], flush=True)
        time.sleep(20 * (i + 1))
    raise RuntimeError("no se pudo bajar " + ruta)


def main():
    a, salida = int(sys.argv[1]), sys.argv[2]
    partes = {}
    for v, niv in NIVEL.items():
        f = bajar(f"pressure/{v}.{a}.nc")
        ds = xr.open_dataset(f)
        for n in niv:
            partes[f"{v}{n}"] = ds[v].sel(level=n, **CAJA).drop_vars("level").load().astype("float32")
        ds.close(); os.remove(f)
    for v, ruta in SUP.items():
        f = bajar(ruta.format(a=a))
        ds = xr.open_dataset(f)
        nombre = [x for x in ds.data_vars if x not in ("time_bnds",)][0]
        da = ds[nombre]
        if "level" in da.dims: da = da.isel(level=0, drop=True)
        partes[v] = da.sel(**CAJA).load().astype("float32")
        if v == "slp":
            for k, (la, lo) in LEJOS.items():
                partes[f"slp_{k}"] = da.sel(lat=la, lon=lo, method="nearest").drop_vars(["lat", "lon"]).load().astype("float32")
        ds.close(); os.remove(f)
    out = xr.Dataset(partes)
    out.attrs = {"fuente": "NCEP/NCAR Reanalysis 1, NOAA PSL (promedios diarios UTC, 2,5°)", "anio": a}
    enc = {k: {"zlib": True, "complevel": 9} for k in out.data_vars}
    out.to_netcdf(salida, encoding=enc)
    print(a, "listo:", dict(out.sizes), f"{os.path.getsize(salida) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
