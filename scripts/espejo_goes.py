"""DataLab Ec · ESPEJO de imágenes GOES-19 recortadas a Ecuador (Luis, 15 nov: ahorrar minutos del repo privado sin
cambiar la frecuencia ni la calidad).

Qué hace: cada vuelta (10 min) busca las imágenes de las últimas 2 h de la NOAA (GOES-19, AWS, dominio público, sin
clave) que todavía no estén en el espejo y guarda, para cada una, el RECORTE CRUDO de Ecuador continental y su mar
(lat 2 a −5,5; lon −82 a −75): la variable del archivo tal cual (enteros, sin convertir) + su escala, desplazamiento,
valor de relleno y la geometría de la proyección. No calcula nada: quien lo lee obtiene exactamente los mismos
números que si bajara el archivo de la NOAA.
Productos: banda 13 (ABI-L2-CMIPF, C13, "CMI") y nubes (ACHAF "HT", ACTPF "Phase", CODF "COD", CPSF "CPS").
Dónde: assets de la versión (release) "espejo-goes" de este repo, "<nombre del archivo NOAA>.<variable>.npz"; se
borran los de más de HORAS_GUARDA horas. Corre en espejo-goes.yml (bucle aparte: no toca el robot del satélite)."""
import io, json, math, os, re, sys, time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

BUCKET = "https://noaa-goes19.s3.amazonaws.com"
CAJA = (2.0, -82.0, -5.5, -75.0)        # lat_norte, lon_oeste, lat_sur, lon_este
PRODUCTOS = {"CMIPF": "CMI", "ACHAF": "HT", "ACTPF": "Phase", "CODF": "COD", "CPSF": "CPS"}
HORAS_GUARDA = 10
REPO = os.environ.get("GITHUB_REPOSITORY", "luiscampozano/simulador-mazar")
TAG = "espejo-goes"
API = f"https://api.github.com/repos/{REPO}"
GH = requests.Session()
GH.headers.update({"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"})
S = requests.Session(); S.headers["User-Agent"] = "DataLab Ec (espejo GOES)"


def claves(prod, t):
    r = S.get(f"{BUCKET}/?list-type=2&prefix=ABI-L2-{prod}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/", timeout=40)
    ks = re.findall(r"<Key>([^<]+)</Key>", r.text)
    return sorted(k for k in ks if k.endswith(".nc") and (prod != "CMIPF" or "-M6C13_G19_" in k))


def inicio(k):
    m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})", k)
    return datetime(int(m.group(1)), 1, 1, tzinfo=timezone.utc) + timedelta(days=int(m.group(2)) - 1, hours=int(m.group(3)), minutes=int(m.group(4)))


def escaneo(P, lat, lon):
    req, rpol = P["semi_major_axis"], P["semi_minor_axis"]
    H, l0 = P["perspective_point_height"] + req, math.radians(P["longitude_of_projection_origin"])
    phi, lam = math.radians(lat), math.radians(lon)
    e2 = (req ** 2 - rpol ** 2) / req ** 2
    phic = math.atan((rpol ** 2 / req ** 2) * math.tan(phi))
    rc = rpol / math.sqrt(1 - e2 * math.cos(phic) ** 2)
    sx = H - rc * math.cos(phic) * math.cos(lam - l0); sy = -rc * math.cos(phic) * math.sin(lam - l0); sz = rc * math.sin(phic)
    return math.asin(-sy / math.sqrt(sx * sx + sy * sy + sz * sz)), math.atan(sz / sx)


def recorte(clave, var):
    """El mismo recorte que hace el lector del repo privado (filas i0..i1 y columnas j0..j1 de la CAJA), sin convertir."""
    import fsspec, h5py
    fs = fsspec.filesystem("http", client_kwargs={"trust_env": True})
    with fs.open(f"{BUCKET}/{clave}", block_size=2 ** 22, cache_type="bytes") as f:
        h = h5py.File(f, "r"); v = h[var]
        esc = lambda n: h[n][:] * float(np.ravel(h[n].attrs["scale_factor"])[0]) + float(np.ravel(h[n].attrs["add_offset"])[0])
        x, y = esc("x"), esc("y")
        pa = h["goes_imager_projection"].attrs
        P = {k: float(np.ravel(pa[k])[0]) for k in ("semi_major_axis", "semi_minor_axis", "perspective_point_height", "longitude_of_projection_origin")}
        x0, y0, dx, dy = float(x[0]), float(y[0]), float(x[1] - x[0]), float(y[1] - y[0])
        xa, ya = escaneo(P, CAJA[0], CAJA[1]); xb, yb = escaneo(P, CAJA[2], CAJA[3])
        j0, j1 = sorted([int((xa - x0) / dx), int((xb - x0) / dx)])
        i0, i1 = sorted([int((ya - y0) / dy), int((yb - y0) / dy)])
        a = v[i0:i1 + 1, j0:j1 + 1]
        sf = float(np.ravel(v.attrs["scale_factor"])[0]) if "scale_factor" in v.attrs else 1.0
        ao = float(np.ravel(v.attrs["add_offset"])[0]) if "add_offset" in v.attrs else 0.0
        fv = int(np.ravel(v.attrs["_FillValue"])[0])
    b = io.BytesIO()
    np.savez_compressed(b, a=a, geo=np.array([x0, y0, dx, dy, i0, j0, sf, ao, fv] + [P[k] for k in (
        "semi_major_axis", "semi_minor_axis", "perspective_point_height", "longitude_of_projection_origin")], dtype=np.float64))
    return b.getvalue()


def version():
    r = GH.get(f"{API}/releases/tags/{TAG}", timeout=30)
    if r.status_code == 200: return r.json()
    r = GH.post(f"{API}/releases", json={"tag_name": TAG, "name": "Espejo GOES-19 (Ecuador)", "prerelease": True,
              "body": "Recortes crudos de imágenes GOES-19 de la NOAA (dominio público) sobre Ecuador; se renuevan cada 10 min "
                      f"y se borran a las {HORAS_GUARDA} h. Uso interno de DataLab Ec (scripts/espejo_goes.py)."}, timeout=30)
    r.raise_for_status(); return r.json()


def assets(rel):
    out, p = [], 1
    while True:
        r = GH.get(f"{API}/releases/{rel['id']}/assets", params={"per_page": 100, "page": p}, timeout=30); r.raise_for_status()
        out += r.json()
        if len(r.json()) < 100: return out
        p += 1


def main():
    ahora = datetime.now(timezone.utc)
    rel = version(); A = assets(rel)
    for a in [x for x in A if x.get("state") != "uploaded"]:   # subida cortada a medias: se borra y se vuelve a subir
        GH.delete(f"{API}/releases/assets/{a['id']}", timeout=30); A.remove(a)
    hay = {a["name"] for a in A}
    subidos = borrados = fallas = 0
    for prod, var in PRODUCTOS.items():
        ks = []
        for h in (2, 1, 0):
            try: ks += claves(prod, ahora - timedelta(hours=h))
            except Exception as e: print(f"{prod}: listado falló ({str(e)[:80]})")
        for k in sorted(ks, key=inicio, reverse=True):          # lo más nuevo primero
            if not (ahora - timedelta(hours=2, minutes=20) <= inicio(k) <= ahora): continue
            nom = os.path.basename(k) + f".{var}.npz"
            if nom in hay: continue
            try:
                b = recorte(k, var)
                r = GH.post(rel["upload_url"].split("{")[0], params={"name": nom}, data=b,
                            headers={"Content-Type": "application/octet-stream"}, timeout=120)
                if r.status_code == 201: subidos += 1; hay.add(nom)
                else: fallas += 1; print(f"subir {nom}: {r.status_code} {r.text[:100]}")
            except Exception as e:
                fallas += 1; print(f"{prod} {inicio(k):%H:%M}: {str(e)[:100]}")
    for a in A:
        try: t = inicio(a["name"])
        except Exception: continue
        if t < ahora - timedelta(hours=HORAS_GUARDA):
            if GH.delete(f"{API}/releases/assets/{a['id']}", timeout=30).status_code == 204: borrados += 1
    print(f"Espejo GOES {ahora:%H:%M} UTC: {subidos} nuevos, {borrados} borrados, {fallas} fallas, {len(hay) - borrados} en el espejo")


if __name__ == "__main__":
    main()
