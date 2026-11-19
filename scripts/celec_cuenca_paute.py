"""Luis 19 nov: comprobar el punto de la cuenca del Paute que usa la página de gráficas de Celec Sur (24812, y 24811
de la misma página) con los mismos pedidos que hace esa página. De una vez."""
import json, urllib.request
from datetime import datetime, timedelta, timezone
EC = timezone(timedelta(hours=-5)); hoy = datetime.now(EC).date()
ini = datetime(hoy.year, hoy.month, hoy.day, 1, tzinfo=EC).astimezone(timezone.utc); fin = ini + timedelta(hours=23)
for m in (24812, 24811, 30538):
    u = (f"https://generacioncsr.celec.gob.ec:8443/ords/csr/sardomcsr/pointValues?mrid={m}&fechaInicio={ini:%Y-%m-%dT%H:%M:%S.000Z}"
         f"&fechaFin={fin:%Y-%m-%dT%H:%M:%S.000Z}&fecha={hoy:%d/%m/%Y}%2001:00:00")
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 DataLabEc"}), timeout=40) as r:
            it = json.loads(r.read()).get("items", [])
        print(m, [(i["loctimestamp"][11:16], i.get("valueedit")) for i in it])
    except Exception as e: print(m, "error", e)
