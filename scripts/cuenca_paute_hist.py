"""Luis 19 nov: promedio diario histórico del caudal de la cuenca del Paute (Celec Sur, punto 24812, el de la página de
gráficas de Celec) para tener "lo normal del mes". Baja, para cada año desde 2010, los días del mes pedido (por defecto
el actual) y guarda el promedio de cada día en historial/paute_cuenca_diario.json. Los días que ya están no se piden."""
import json, os, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone
EC = timezone(timedelta(hours=-5)); F = os.path.join("historial", "paute_cuenca_diario.json"); MRID = 24812
def dia(d):
    ini = datetime(d.year, d.month, d.day, 1, tzinfo=EC).astimezone(timezone.utc); fin = ini + timedelta(hours=23)
    u = (f"https://generacioncsr.celec.gob.ec:8443/ords/csr/sardomcsr/pointValues?mrid={MRID}&fechaInicio={ini:%Y-%m-%dT%H:%M:%S.000Z}"
         f"&fechaFin={fin:%Y-%m-%dT%H:%M:%S.000Z}&fecha={d:%d/%m/%Y}%2001:00:00")
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 DataLabEc"}), timeout=40) as r:
                v = [float(i["valueedit"]) for i in json.loads(r.read()).get("items", []) if i.get("valueedit") is not None and 0 <= float(i["valueedit"]) < 5000]
            return round(sum(v) / len(v), 1) if len(v) >= 12 else None
        except Exception as e:
            print(d, "intento", k + 1, e, flush=True); time.sleep(5)
H = json.load(open(F)) if os.path.exists(F) else {}
mes = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(EC).month
hoy = datetime.now(EC).date()
for a in range(2010, hoy.year + 1):
    for d0 in range(1, 32):
        try: d = date(a, mes, d0)
        except ValueError: break
        if d >= hoy or d.isoformat() in H: continue
        v = dia(d)
        if v is not None: H[d.isoformat()] = v
        time.sleep(0.3)
    print(a, sum(1 for k in H if k.startswith(f"{a}-{mes:02d}")), "días", flush=True)
json.dump(dict(sorted(H.items())), open(F, "w"), separators=(",", ":"))
print("total", len(H))
