"""Lluvia diaria CHIRPS v3 (rnl: total de 5 días repartido con ERA5; 1981 en adelante) en los puntos de las ciudades del
clima de DataLab Ec. Corre en GitHub Actions (repo público): baja cada archivo diario global (~16 MB), lee los puntos y lo
borra. Uso: python3 scripts/chirps_diario.py AÑO_DESDE AÑO_HASTA salida.json"""
import json, os, sys, time, urllib.request
from datetime import date, timedelta
import rasterio
AQUI = os.path.dirname(os.path.abspath(__file__))
P = list(json.load(open(os.path.join(AQUI, "puntos_clima.json"))).items())
U = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/{y}/chirps-v3.0.rnl.{y}.{m:02d}.{d:02d}.tif"
y0, y1, sal = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
out = {n: {} for n, _ in P}; faltan = []
d = date(y0, 1, 1)
while d <= min(date(y1, 12, 31), date.today() - timedelta(days=30)):
    f = f"/tmp/c_{d}.tif"; ok = False
    for i in range(4):
        try:
            urllib.request.urlretrieve(U.format(y=d.year, m=d.month, d=d.day), f)
            with rasterio.open(f) as r:
                for (n, _), v in zip(P, r.sample([(lo, la) for _, (la, lo) in P])):
                    x = float(v[0]); out[n][d.isoformat()] = round(x, 1) if x >= 0 else None
            ok = True; break
        except Exception as e:
            if "404" in str(e): break
            time.sleep(3 * (i + 1))
        finally:
            if os.path.exists(f): os.remove(f)
    if not ok: faltan.append(d.isoformat())
    d += timedelta(days=1)
json.dump({"desde": y0, "hasta": y1, "faltan": faltan, "ciudades": out}, open(sal, "w"), separators=(",", ":"))
print(y0, y1, "días:", len(out[P[0][0]]), "faltan:", len(faltan), faltan[:5])
