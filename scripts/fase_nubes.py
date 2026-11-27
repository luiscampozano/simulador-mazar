"""Registro de la fase de la cima de las nubes (GOES-19) sobre nuestros puntos públicos — Luis, 27 nov 2026.

Solo DATOS CRUDOS de la NOAA (sin reglas): para cada imagen de 10 min y cada punto de scripts/puntos_satelite.json (más
Chongón/Cerecita) guarda cuántos píxeles de ~2 km hay de cada fase en una ventana de ~10 km, la altura de la cima y,
de día, el espesor óptico. Sirve para ver lluvia de nube baja que el infrarrojo no ve (nubes de agua líquida altas) y para
separar el núcleo de una tormenta (hielo grueso) de su yunque (hielo fino).

Productos (NOAA, dominio público, s3://noaa-goes19): ABI-L2-ACTPF (fase), ABI-L2-ACHAF (altura), ABI-L2-CODF (espesor).
Se leen solo los bloques sobre Ecuador (lecturas parciales por HTTP). Cada corrida completa las imágenes de las últimas
HORAS que falten, así los atrasos de GitHub no dejan huecos.

Salida: registro/fase_nubes/<día local>.json en la rama fase-nubes (no en main: cada push a main publica la página)
  {"fuente": ..., "campos": [...], "puntos": [...], "imagenes": {"HH:MM": [[despejado, liquida, sobreenfriada, mixta,
   hielo, desconocida, altura_km, espesor] por punto, en el orden de "puntos"]}}
Conteos de 25 píxeles (5×5; si suman menos, el resto es relleno sin dato); altura = cima en el píxel de 10 km (km);
espesor = espesor óptico medio 3×3 (de noche puede faltar). Un punto nuevo en puntos_satelite.json entra al día siguiente.
"""
import datetime as D, json, os, re, sys, urllib.request

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.environ.get("DIR_SALIDA") or os.path.join(RAIZ, "registro", "fase_nubes")   # en GitHub: la rama fase-nubes
S3 = "https://noaa-goes19.s3.amazonaws.com/"
HORAS = max(1, int(os.environ.get("HORAS") or "3"))   # ≥1: la carpeta de la hora actual está vacía los primeros ~10 min
EXTRA = {"Chongón/Cerecita": [["Cerecita", -2.305, -80.270], ["Chongón", -2.235, -80.075]]}
TODOS = {"Guayaquil", "Durán", "Samborondón", "Daule/Nobol", "Milagro", "Chongón/Cerecita"}
CONGELADO = "2026-11-27"   # ventana, productos y campos fijos desde este día
CAMPOS = ["despejado", "liquida", "sobreenfriada", "mixta", "hielo", "desconocida", "altura_km", "espesor"]
ESPERA_MIN = 60   # altura y espesor salen 2–4 min después de la fase: si faltan, se espera hasta 60 min antes de guardar sin ellos


def _leer(f):
    if not os.path.exists(f): return None
    with open(f, encoding="utf-8") as g: return json.load(g)


def puntos():
    p = json.load(open(os.path.join(RAIZ, "scripts", "puntos_satelite.json"), encoding="utf-8"))
    p.update(EXTRA)
    # todos los puntos de Guayaquil y alrededores; en el resto del país, uno por ciudad (para no inflar el repo)
    return {f"{c} · {x[0]}": (x[1], x[2]) for c, xs in p.items() for x in (xs if c in TODOS else xs[:1])}


def listar(prod, t):
    u = f"{S3}?list-type=2&prefix=ABI-L2-{prod}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/"
    with urllib.request.urlopen(u, timeout=60) as r:
        return re.findall(r"<Key>([^<]+)</Key>", r.read().decode())


def inicio(k):   # hora de inicio del escaneo (UTC) en el nombre: _sAAAADDDHHMMSSs
    m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})", k)
    return D.datetime(int(m[1]), 1, 1, int(m[3]), int(m[4]), tzinfo=D.timezone.utc) + D.timedelta(days=int(m[2]) - 1)


class Malla:
    """Proyección fija del GOES: (lat, lon) → (fila, columna), leyendo solo los ejes x/y del archivo."""
    def __init__(self, d):
        p = d["goes_imager_projection"].attrs
        self.H = float(p["perspective_point_height"]) + float(p["semi_major_axis"])
        self.a, self.b = float(p["semi_major_axis"]), float(p["semi_minor_axis"])
        self.l0 = np.radians(float(p["longitude_of_projection_origin"]))
        self.x, self.y = d["x"][:] * 1.0, d["y"][:] * 1.0
        if "scale_factor" in d["x"].attrs:   # h5netcdf no aplica la escala sola
            self.x = d["x"][:] * float(d["x"].attrs["scale_factor"]) + float(d["x"].attrs["add_offset"])
            self.y = d["y"][:] * float(d["y"].attrs["scale_factor"]) + float(d["y"].attrs["add_offset"])

    def idx(self, lat, lon):
        la, lo = np.radians(lat), np.radians(lon)
        lc = np.arctan((self.b ** 2) / (self.a ** 2) * np.tan(la)); e2 = 1 - self.b ** 2 / self.a ** 2
        rc = self.b / np.sqrt(1 - e2 * np.cos(lc) ** 2)
        sx = self.H - rc * np.cos(lc) * np.cos(lo - self.l0); sy = -rc * np.cos(lc) * np.sin(lo - self.l0); sz = rc * np.sin(lc)
        y = np.arctan(sz / sx); x = np.arcsin(-sy / np.sqrt(sx * sx + sy * sy + sz * sz))
        return int(np.argmin(abs(self.y - y))), int(np.argmin(abs(self.x - x)))


def leer(k, var, P, ventana):
    """Devuelve {punto: arreglo de la ventana} leyendo solo el recuadro de Ecuador del archivo."""
    import fsspec, h5netcdf
    with fsspec.filesystem("https").open(S3 + k, block_size=2 ** 18) as f, h5netcdf.File(f, "r") as d:
        m = Malla(d); v = d[var]
        ij = {n: m.idx(la, lo) for n, (la, lo) in P.items()}
        i0 = min(i for i, _ in ij.values()) - ventana; i1 = max(i for i, _ in ij.values()) + ventana + 1
        j0 = min(j for _, j in ij.values()) - ventana; j1 = max(j for _, j in ij.values()) + ventana + 1
        a = np.asarray(v[i0:i1, j0:j1]).astype(float)
        fill = v.attrs.get("_FillValue")
        if fill is not None: a[a == float(np.asarray(fill).ravel()[0])] = np.nan
        sf = float(v.attrs.get("scale_factor", 1)); off = float(v.attrs.get("add_offset", 0))
        return {n: a[i - i0 - ventana:i - i0 + ventana + 1, j - j0 - ventana:j - j0 + ventana + 1] * (1 if var == "Phase" else sf) + (0 if var == "Phase" else off)
                for n, (i, j) in ij.items()}


def main():
    P = puntos()
    ahora = D.datetime.now(D.timezone.utc)
    horas = [ahora - D.timedelta(hours=h) for h in range(HORAS, -1, -1)]
    claves = {p: {} for p in ("ACTPF", "ACHAF", "CODF")}
    for p in claves:
        for t in horas:
            try:
                for k in listar(p, t): claves[p][inicio(k)] = k
            except Exception as e:
                print(p, t, str(e)[:80])
    nuevos, fallas = 0, 0
    if not claves["ACTPF"]:
        sys.exit("ERROR: no se pudo listar ninguna imagen de fase (ACTPF) en S3")
    for t0, k in sorted(claves["ACTPF"].items()):
        loc = t0 - D.timedelta(hours=5); dia, hh = loc.date().isoformat(), loc.strftime("%H:%M")
        f = os.path.join(DIR, dia + ".json")
        R = _leer(f) or {
            "fuente": "GOES-19 ABI L2 (NOAA, dominio público): ACTP fase (5×5 píxeles de 2 km), ACHA altura de la cima (1 píxel de 10 km), COD espesor óptico medio (3×3 de 4 km; de noche puede faltar). Sin filtro de calidad (DQF): datos crudos.",
            "congelado": CONGELADO, "campos": CAMPOS, "puntos": list(P), "imagenes": {}}
        if hh in R["imagenes"]: continue
        edad = (ahora - t0).total_seconds() / 60
        if (t0 not in claves["ACHAF"] or t0 not in claves["CODF"]) and edad < ESPERA_MIN:
            print(hh, "espera: aún no hay altura o espesor"); continue
        orden = R["puntos"]
        try:
            fa = leer(k, "Phase", P, 2)
            ha = leer(claves["ACHAF"][t0], "HT", P, 0) if t0 in claves["ACHAF"] else {}
            co = leer(claves["CODF"][t0], "COD", P, 1) if t0 in claves["CODF"] else {}
        except Exception as e:
            print(hh, "falló:", str(e)[:120]); fallas += 1; continue
        fila = []
        for n in orden:
            if n not in P: fila.append(None); continue
            w = fa[n].ravel(); w = w[np.isfinite(w)]
            cnt = [int((w == c).sum()) for c in range(6)]   # 5 = desconocida; el resto hasta 25 es relleno sin dato
            h = ha.get(n); h = None if h is None or not np.isfinite(h).any() else round(float(np.nanmax(h)) / 1000, 1)
            c = co.get(n); c = None if c is None or not np.isfinite(c).any() else round(float(np.nanmean(c)), 1)
            fila.append(cnt + [h, c])
        R["imagenes"][hh] = fila
        R["imagenes"] = dict(sorted(R["imagenes"].items()))
        os.makedirs(DIR, exist_ok=True)
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as g:
            json.dump(R, g, ensure_ascii=False, separators=(",", ":")); g.flush(); os.fsync(g.fileno())
        os.replace(tmp, f)
        nuevos += 1
        print(dia, hh, "ok")
    print("imágenes nuevas:", nuevos, "· fallas:", fallas)
    if fallas and not nuevos:
        sys.exit("ERROR: ninguna imagen se pudo leer")
    # la fábrica debe enterarse si el registro se quedó atrás (GOES tarda ~15 min en publicar)
    ult = max(claves["ACTPF"]); dia = (ult - D.timedelta(hours=5)).date().isoformat()
    hechas = (_leer(os.path.join(DIR, dia + ".json")) or {}).get("imagenes", {})
    if not hechas and (ahora - ult).total_seconds() > 2 * 3600:
        sys.exit("ERROR: el registro tiene más de 2 h de atraso")


if __name__ == "__main__":
    main()
