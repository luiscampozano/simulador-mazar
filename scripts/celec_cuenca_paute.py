"""Luis 19 nov: ubicar en la página pública de gráficas de Celec Sur (la que él indicó) el punto del
"Caudal de la cuenca del Paute". Solo lee esa página y los archivos JavaScript que ella misma carga; no prueba códigos."""
import re, urllib.request
BASE = "https://generacioncsr.celec.gob.ec/graficasproduccion/"
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 DataLabEc"}), timeout=40) as r:
        return r.read().decode("utf-8", "ignore")
h = get(BASE + "index.html")
print("index.html", len(h))
fuentes = [("index.html", h)]
for src in sorted(set(re.findall(r'<script[^>]+src="([^"]+)"', h))):
    u = src if src.startswith("http") else BASE + src.lstrip("./")
    if "generacioncsr.celec.gob.ec" not in u: continue
    try: fuentes.append((src, get(u)))
    except Exception as e: print("no se pudo leer", src, e)
for nom, t in fuentes:
    for m in re.finditer(r"(?i)cuenca|paute|mazar|mrid|pointValues|caudal", t):
        print(f"{nom}: …{t[max(0, m.start() - 120):m.end() + 160]!r}")
