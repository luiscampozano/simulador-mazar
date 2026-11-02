"""Completa historial/chirps_diario.json: vuelve a bajar los días que faltaron (CHIRPS v3 final 'rnl') y agrega los días
recientes que aún no tienen versión final con la versión PRELIMINAR (CHIRPS v3 prelim 'sat', reparto con IMERG; sale con ~1
semana de retraso). Cuando un día preliminar ya tiene versión final, se reemplaza. Luego rehace historial/clima_hist/.
Corre en GitHub Actions (semanal y a mano)."""
import json, os, re, subprocess, sys, time, urllib.request
from datetime import date, timedelta
import rasterio
AQUI = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(AQUI, "..")
F = os.path.join(R, "historial", "chirps_diario.json")
P = list(json.load(open(os.path.join(AQUI, "puntos_clima.json"))).items())
FIN = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/{y}/chirps-v3.0.rnl.{y}.{m:02d}.{d:02d}.tif"
PRE = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/prelim/sat/{y}/chirps-v3.0.prelim.{y}.{m:02d}.{d:02d}.tif"


def leer(url):
    f = "/tmp/c.tif"
    for i in range(4):
        try:
            urllib.request.urlretrieve(url, f)
            with rasterio.open(f) as r:
                return [(None if float(v[0]) < 0 else round(float(v[0]), 1)) for v in r.sample([(lo, la) for _, (la, lo) in P])]
        except Exception as e:
            if "404" in str(e): return None
            time.sleep(3 * (i + 1))
        finally:
            if os.path.exists(f): os.remove(f)
    return None


def poner(d, dia, vals):
    for (n, _), v in zip(P, vals): d["ciudades"].setdefault(n, {})[dia] = v


d = json.load(open(F)); pre = set(d.get("prelim", []))
ult = max(max(s) for s in d["ciudades"].values())
# 1) días que faltaron y días preliminares que ya pueden tener versión final
quedan = []
for dia in sorted(set(d.get("faltan", [])) | pre):
    y, m, dd = map(int, dia.split("-")); v = leer(FIN.format(y=y, m=m, d=dd))
    if v: poner(d, dia, v); pre.discard(dia); print("final", dia)
    elif dia in pre: pass
    else: quedan.append(dia)
# 2) días nuevos: primero final, si no, preliminar
x = date.fromisoformat(ult) + timedelta(days=1)
while x < date.today():
    dia = x.isoformat()
    if dia not in pre:
        v = leer(FIN.format(y=x.year, m=x.month, d=x.day))
        if v: poner(d, dia, v); print("final", dia)
        else:
            v = leer(PRE.format(y=x.year, m=x.month, d=x.day))
            if v: poner(d, dia, v); pre.add(dia); print("prelim", dia)
            else: break                                   # todavía no publicado: se intenta la próxima semana
    x += timedelta(days=1)
d["faltan"] = quedan; d["prelim"] = sorted(pre)
for c in d["ciudades"]: d["ciudades"][c] = dict(sorted(d["ciudades"][c].items()))
json.dump(d, open(F, "w"), separators=(",", ":"))
print("faltan", quedan, "prelim", len(pre), "hasta", max(max(s) for s in d["ciudades"].values()))
subprocess.run([sys.executable, os.path.join(AQUI, "clima_hist.py")], check=True)
