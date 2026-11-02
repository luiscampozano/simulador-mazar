"""Parte el historial diario CHIRPS (historial/chirps_diario.json) en un archivo chico por ciudad para la página del clima
(paneles Año / Mes / Día): historial/clima_hist/<slug>.json = {"c": ciudad, "desde": "1981-01-01", "v": [décimas de mm por día]}.
Se excluyen las ciudades donde CHIRPS no es confiable (Galápagos, costa árida de Santa Elena y Manta, valles de Riobamba y Ambato)."""
import json, os, re, unicodedata
from datetime import date, timedelta
AQUI = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(AQUI, "..")
FUERA = {"Puerto Ayora", "Puerto Baquerizo Moreno", "Puerto Villamil", "Santa Elena", "Manta", "Riobamba", "Ambato"}
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
d = json.load(open(os.path.join(R, "historial", "chirps_diario.json")))
os.makedirs(os.path.join(R, "historial", "clima_hist"), exist_ok=True)
idx = {}
for c, s in d["ciudades"].items():
    if c in FUERA: continue
    ks = sorted(s); d0, d1 = date.fromisoformat(ks[0]), date.fromisoformat(ks[-1])
    v, x = [], d0
    while x <= d1:
        y = s.get(x.isoformat()); v.append(None if y is None else round(y * 10)); x += timedelta(days=1)
    pre = sorted(x for x in d.get("prelim", []) if x in s)
    json.dump({"c": c, "desde": ks[0], "hasta": ks[-1], "prelim_desde": pre[0] if pre else None, "v": v}, open(os.path.join(R, "historial", "clima_hist", slug(c) + ".json"), "w"), separators=(",", ":"))
    idx[c] = slug(c)
json.dump({"fuente": "CHIRPS v3.0 diario (rnl): total de 5 días del Climate Hazards Center (UCSB) repartido por día con ERA5",
           "ciudades": idx}, open(os.path.join(R, "historial", "clima_hist", "indice.json"), "w"), ensure_ascii=False, separators=(",", ":"))
print(len(idx), "ciudades")
