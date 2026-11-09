"""DataLab Ec · señales del satélite cada 10 min para los puntos ciegos de la lluvia (Luis, 9 nov).

Para cada celda de 0,05° (~5,5 km) sobre Ecuador continental y su mar:
  - temperatura de la cima de las nubes (GOES-19 ABI banda 13, 10,3 µm, la imagen más reciente; ~10 min de retraso),
  - su cambio frente a la imagen de 10 min antes (− = la nube crece/se enfría = tormenta que se fortalece),
  - rayos vistos por el satélite (GOES-19 GLM) en los últimos 15 min.
NO son milímetros (el infrarrojo no distingue bien el núcleo que llueve del "yunque" frío que no llueve; la página lo
muestra como señales: nubes de lluvia, tormenta, rayos, creciendo/apagándose). Datos públicos de la NOAA en AWS.
Salida: salida/ahora.json (malla codificada en base64; la página la decodifica). Corre en satelite-ahora.yml."""
import base64, io, json, math, os, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import h5py
import numpy as np
import requests

B = "https://noaa-goes19.s3.amazonaws.com"
N, O, S_, E = 2.0, -82.0, -5.5, -75.0
PASO = 0.05
FILAS, COLS = int(round((N - S_) / PASO)), int(round((E - O) / PASO))
SES = requests.Session(); SES.headers["User-Agent"] = "DataLab Ec (satelite)"


def listar(prod, t):
    out, tok = [], None
    pref = f"{prod}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/"
    while True:
        u = f"{B}/?list-type=2&prefix={pref}" + (f"&continuation-token={requests.utils.quote(tok)}" if tok else "")
        x = SES.get(u, timeout=40).text
        out += re.findall(r"<Key>([^<]+\.nc)</Key>", x)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", x)
        if not m: return out
        tok = m.group(1)


def inicio(k):
    m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})", k)
    return datetime(int(m.group(1)), 1, 1, tzinfo=timezone.utc) + timedelta(days=int(m.group(2)) - 1, hours=int(m.group(3)),
                                                                            minutes=int(m.group(4)), seconds=int(m.group(5)))


def escena(clave):
    """Temperatura de brillo de cada celda de la malla (media de 3×3 píxeles de ~2 km alrededor del centro)."""
    b = SES.get(f"{B}/{clave}", timeout=120).content
    h = h5py.File(io.BytesIO(b), "r"); v = h["CMI"]
    esc = lambda n: h[n][:] * float(np.ravel(h[n].attrs["scale_factor"])[0]) + float(np.ravel(h[n].attrs["add_offset"])[0])
    x, y = esc("x"), esc("y")
    pa = h["goes_imager_projection"].attrs
    P = {k: float(np.ravel(pa[k])[0]) for k in ("semi_major_axis", "semi_minor_axis", "perspective_point_height", "longitude_of_projection_origin")}
    req, rpol = P["semi_major_axis"], P["semi_minor_axis"]
    H, l0 = P["perspective_point_height"] + req, math.radians(P["longitude_of_projection_origin"])
    e2 = (req ** 2 - rpol ** 2) / req ** 2
    lats = N - PASO / 2 - PASO * np.arange(FILAS); lons = O + PASO / 2 + PASO * np.arange(COLS)
    LA, LO = np.meshgrid(np.radians(lats), np.radians(lons), indexing="ij")
    phic = np.arctan((rpol ** 2 / req ** 2) * np.tan(LA))
    rc = rpol / np.sqrt(1 - e2 * np.cos(phic) ** 2)
    sx = H - rc * np.cos(phic) * np.cos(LO - l0); sy = -rc * np.cos(phic) * np.sin(LO - l0); sz = rc * np.sin(phic)
    xs = np.arcsin(-sy / np.sqrt(sx * sx + sy * sy + sz * sz)); ys = np.arctan(sz / sx)
    J = np.rint((xs - x[0]) / (x[1] - x[0])).astype(int); I = np.rint((ys - y[0]) / (y[1] - y[0])).astype(int)
    i0, i1, j0, j1 = I.min() - 2, I.max() + 3, J.min() - 2, J.max() + 3
    a = v[i0:i1, j0:j1].astype(np.float32)
    fv = float(np.ravel(v.attrs["_FillValue"])[0])
    a = np.where(a == fv, np.nan, a * float(np.ravel(v.attrs["scale_factor"])[0]) + float(np.ravel(v.attrs["add_offset"])[0]))
    I -= i0; J -= j0
    acc = np.zeros(I.shape, np.float32); n = np.zeros(I.shape, np.float32)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            w = a[I + di, J + dj]; ok = np.isfinite(w)
            acc[ok] += w[ok]; n[ok] += 1
    return np.where(n > 0, acc / np.maximum(n, 1), np.nan), inicio(clave)


def glm(desde, hasta):
    """Rayos (destellos) por celda entre desde y hasta (UTC)."""
    ks = []
    t = desde.replace(minute=0, second=0, microsecond=0)
    while t <= hasta:
        try: ks += [k for k in listar("GLM-L2-LCFA", t) if desde <= inicio(k) <= hasta]
        except Exception as e: print("GLM listado:", str(e)[:80])
        t += timedelta(hours=1)
    def uno(k):
        for _ in range(2):
            try:
                f = h5py.File(io.BytesIO(SES.get(f"{B}/{k}", timeout=60).content), "r")
                if "flash_lat" not in f or f["flash_lat"].shape[0] == 0: return None
                g = lambda n: f[n][:].astype(float) * float(np.ravel(f[n].attrs.get("scale_factor", [1]))[0]) + float(np.ravel(f[n].attrs.get("add_offset", [0]))[0])
                return np.stack([g("flash_lat"), g("flash_lon")], axis=1)
            except Exception:
                continue
        return None
    C = np.zeros((FILAS, COLS), np.int32)
    with ThreadPoolExecutor(16) as ex:
        for r in ex.map(uno, ks):
            if r is None: continue
            i = np.floor((N - r[:, 0]) / PASO).astype(int); j = np.floor((r[:, 1] - O) / PASO).astype(int)
            m = (i >= 0) & (i < FILAS) & (j >= 0) & (j < COLS)
            np.add.at(C, (i[m], j[m]), 1)
    return C, len(ks)


def b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def main():
    ahora = datetime.now(timezone.utc)
    ks = []
    for hh in (1, 0):
        try: ks += [k for k in listar("ABI-L2-CMIPF", ahora - timedelta(hours=hh)) if "-M6C13_G19_" in k]
        except Exception as e: print("ABI listado:", str(e)[:80])
    ks = sorted(ks, key=inicio)
    if len(ks) < 2: sys.exit("sin imágenes GOES recientes")
    T1, t1 = escena(ks[-1]); T0, t0 = escena(ks[-2])
    rayos, nglm = glm(t1 - timedelta(minutes=10), t1 + timedelta(minutes=5))
    tb = np.where(np.isfinite(T1), np.clip(np.rint(T1) - 150, 0, 254), 255).astype(np.uint8)          # 255 = sin dato
    d = np.where(np.isfinite(T1) & np.isfinite(T0), np.clip(np.rint(T1 - T0), -127, 127), -128).astype(np.int8)
    out = {"generado": ahora.isoformat(timespec="seconds"), "imagen": t1.isoformat(), "imagen_previa": t0.isoformat(),
           "rayos_desde": (t1 - timedelta(minutes=10)).isoformat(), "rayos_hasta": (t1 + timedelta(minutes=5)).isoformat(),
           "archivos_glm": nglm, "norte": N, "oeste": O, "paso": PASO, "filas": FILAS, "cols": COLS,
           "fuente": "NOAA GOES-19 (ABI banda 13 y GLM), datos públicos",
           "tb_menos_150_u8": b64(tb), "cambio_10min_i8": b64(d), "rayos_u8": b64(np.clip(rayos, 0, 255).astype(np.uint8))}
    os.makedirs("salida", exist_ok=True)
    json.dump(out, open("salida/ahora.json", "w"), separators=(",", ":"))
    frio = int((T1 < 215).sum()); print(f"Satélite {t1:%H:%M} UTC: celdas < 215 K: {frio} · rayos: {int(rayos.sum())} ({nglm} archivos GLM)")


if __name__ == "__main__":
    main()
