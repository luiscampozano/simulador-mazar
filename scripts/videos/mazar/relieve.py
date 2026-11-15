"""Relieve del embalse Mazar para el video diario 3D (Luis, 15 nov). Se corre UNA vez (el resultado se guarda en el repo).
Fuente: mosaico público de elevación de AWS (Terrain Tiles, "terrarium", zoom 13, ~19 m; en esta zona viene del SRTM de
2000, antes de llenar Mazar: por eso se ve el fondo del cañón). Presa: −2,5921, −78,6177 (cresta 2.166 m; nivel máximo
normal 2.153 m). El agua de cada día = el cañón lleno desde la presa hasta la cota (la página lo calcula).
Salida: relieve.json {filas, cols, paso_m, h_b64 (uint16, m − 2000), bar_b64 (uint8: 1 = presa), semilla, presa}."""
import base64, io, json, math, os, sys
import numpy as np, requests
from PIL import Image

Z = 13; PRESA = (-2.5921417, -78.6176611)
N_, O_, S_, E_ = -2.45, -78.85, -2.75, -78.45


def tile(lat, lon):
    n = 2 ** Z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def main(salida):
    x0, y0 = tile(N_, O_); x1, y1 = tile(S_, E_)
    filas = []
    for ty in range(int(y0), int(y1) + 1):
        f = []
        for tx in range(int(x0), int(x1) + 1):
            b = requests.get(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{tx}/{ty}.png", timeout=60).content
            a = np.asarray(Image.open(io.BytesIO(b)).convert("RGB")).astype(float)
            f.append(a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768)
        filas.append(np.hstack(f))
    H = np.vstack(filas); X0, Y0 = int(x0), int(y0)
    px = lambda la, lo: (int(round((tile(la, lo)[1] - Y0) * 256)), int(round((tile(la, lo)[0] - X0) * 256)))
    di, dj = px(*PRESA)
    B = np.zeros(H.shape, bool); yy, xx = np.ogrid[:H.shape[0], :H.shape[1]]; B[(yy - di) ** 2 + (xx - dj) ** 2 <= 400] = True
    from scipy import ndimage
    lab, _ = ndimage.label((H < 2153) & ~B); M = lab == lab[px(-2.62, -78.62)]
    s = np.unravel_index(np.where(M, H, 1e9).argmin(), H.shape)
    ii, jj = np.nonzero(M); g = 200   # margen (~3,8 km) para que el giro de cámara no vea el borde
    i0, i1, j0, j1 = max(0, ii.min() - g), min(H.shape[0], ii.max() + g), max(0, jj.min() - g), min(H.shape[1], jj.max() + g)
    f = 2; C = H[i0:i1:f, j0:j1:f]; Bc = B[i0:i1:f, j0:j1:f]
    print(f"embalse a 2.153 m: {M.sum() * 19.1 ** 2 / 1e6:.2f} km² · malla {C.shape}")
    json.dump({"filas": int(C.shape[0]), "cols": int(C.shape[1]), "paso_m": 19.1 * f,
               "h_b64": base64.b64encode(np.clip(np.rint(C - 2000), 0, 65535).astype("<u2").tobytes()).decode(),
               "bar_b64": base64.b64encode(Bc.astype(np.uint8).tobytes()).decode(),
               "semilla": [int((s[0] - i0) // f), int((s[1] - j0) // f)], "presa": [int((di - i0) // f), int((dj - j0) // f)],
               "fuente": "AWS Terrain Tiles (SRTM), zoom 13"}, open(salida, "w"), separators=(",", ":"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "relieve.json"))
