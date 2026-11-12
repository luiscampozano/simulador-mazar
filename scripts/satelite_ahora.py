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
    def ij(lat, lon):   # píxel (fila, columna) dentro de `a` para una lista de puntos
        LA_, LO_ = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
        pc = np.arctan((rpol ** 2 / req ** 2) * np.tan(LA_)); r_ = rpol / np.sqrt(1 - e2 * np.cos(pc) ** 2)
        ax = H - r_ * np.cos(pc) * np.cos(LO_ - l0); ay = -r_ * np.cos(pc) * np.sin(LO_ - l0); az = r_ * np.sin(pc)
        xx = np.arcsin(-ay / np.sqrt(ax * ax + ay * ay + az * az)); yy = np.arctan(az / ax)
        return np.rint((yy - y[0]) / (y[1] - y[0])).astype(int) - i0, np.rint((xx - x[0]) / (x[1] - x[0])).astype(int) - j0
    I -= i0; J -= j0
    acc = np.zeros(I.shape, np.float32); n = np.zeros(I.shape, np.float32)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            w = a[I + di, J + dj]; ok = np.isfinite(w)
            acc[ok] += w[ok]; n[ok] += 1
    def puntos(lats, lons, r=1):
        """Por punto: temperatura mínima, % de píxeles ≤ 235 K y ≤ 215 K, y media (5×5 píxeles de ~2 km ≈ 3 km de radio)."""
        pi, pj = ij(lats, lons); out = []
        for i, j in zip(pi, pj):
            w = a[max(0, i - 2):i + 3, max(0, j - 2):j + 3]
            w = w[np.isfinite(w)]
            out.append(None if not w.size else (float(w.min()), float((w <= 235).mean()), float((w <= 215).mean()), float(w.mean())))
        return out
    T = np.where(n > 0, acc / np.maximum(n, 1), np.nan)
    return T, inicio(clave), puntos


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
    C = np.zeros((FILAS, COLS), np.int32); todos = []
    with ThreadPoolExecutor(16) as ex:
        for r in ex.map(uno, ks):
            if r is None: continue
            todos.append(r)
            i = np.floor((N - r[:, 0]) / PASO).astype(int); j = np.floor((r[:, 1] - O) / PASO).astype(int)
            m = (i >= 0) & (i < FILAS) & (j >= 0) & (j < COLS)
            np.add.at(C, (i[m], j[m]), 1)
    return C, len(ks), (np.concatenate(todos) if todos else np.zeros((0, 2)))


def historia(t1, pun1, pun0, flashes):
    """Puntos satélite por ciudad (Guayaquil 10, las demás 5) con las últimas 13 h, para la tabla de estaciones."""
    P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "puntos_satelite.json"), encoding="utf-8"))
    ids, lats, lons = [], [], []
    for c, ps in P.items():
        for nom, la, lo in ps: ids.append(f"{c}|{nom}"); lats.append(la); lons.append(lo)
    v1, v0 = pun1(lats, lons), pun0(lats, lons)
    reg = {}
    for k, idp in enumerate(ids):
        if v1[k] is None: continue
        tmin, fl, ft, tm = v1[k]
        ry = 0
        if len(flashes):
            dk = np.hypot((flashes[:, 0] - lats[k]) * 111.2, (flashes[:, 1] - lons[k]) * 111.2 * math.cos(math.radians(lats[k])))
            ry = int((dk <= 8).sum())
        d10 = round(tm - v0[k][3], 1) if v0[k] is not None else None
        reg[idp] = [round(tmin), round(fl * 100), round(ft * 100), ry, d10]
    try:   # en el bucle del workflow la historia de la vuelta anterior está en disco (raw.githubusercontent tarda en refrescar)
        H = json.load(open("salida/historia.json")) if os.path.exists("salida/historia.json") else \
            SES.get("https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/historia.json", timeout=30).json()
        assert isinstance(H.get("serie"), list)
    except Exception:
        H = {"serie": []}
    lim = (t1 - timedelta(hours=13)).isoformat()
    serie = [e for e in H["serie"] if e.get("t", "") >= lim and e.get("t") != t1.isoformat()] + [{"t": t1.isoformat(), "p": reg}]
    H = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "puntos": P,
         "campos": ["temp_min_K", "pct_nubes_lluvia_le235K", "pct_nubes_tormenta_le215K", "rayos_8km_15min", "cambio_10min_K"],
         "nota": "radio ~3 km por punto (5×5 píxeles de ~2 km); rayos a ≤ 8 km en 15 min; señales, no milímetros",
         "serie": sorted(serie, key=lambda e: e["t"])}
    json.dump(H, open("salida/historia.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"Historia: {len(H['serie'])} imágenes · {len(reg)} puntos")


def movimiento(T0, T1, minutos, bloque=16, paso=8, busca=6, min_frio=8, min_corr=0.5):
    """Luis 11 nov ("llega a tu barrio en ~40 min"): hacia dónde y a qué velocidad se mueven las nubes frías.
    Correlación por bloques de 16×16 celdas (~88 km, cada ~44 km) entre la imagen de hace ~30 min y la actual, buscando
    desplazamientos de hasta ±6 celdas (~33 km en 30 min) con ajuste parabólico fino. Solo bloques con ≥ 8 celdas ≤ 235 K y
    correlación ≥ 0,5. Devuelve [lat, lon del centro del bloque, u (km/h hacia el este), v (km/h hacia el norte), correlación].
    Es una extrapolación: sirve para la próxima hora o dos; las tormentas también nacen y mueren en el camino."""
    I0 = np.nan_to_num(np.clip(255 - T0, 0, 40)); I1 = np.nan_to_num(np.clip(255 - T1, 0, 40))
    F, Cc = I1.shape; out = []
    for bi in range(0, F - bloque + 1, paso):
        for bj in range(0, Cc - bloque + 1, paso):
            b1 = I1[bi:bi + bloque, bj:bj + bloque]
            if (b1 >= 20).sum() < min_frio: continue          # ≤ 235 K
            best = None; sc = {}
            for di in range(-busca, busca + 1):
                for dj in range(-busca, busca + 1):
                    i0, j0 = bi - di, bj - dj
                    if i0 < 0 or j0 < 0 or i0 + bloque > F or j0 + bloque > Cc: continue
                    b0 = I0[i0:i0 + bloque, j0:j0 + bloque]
                    a, b = b1 - b1.mean(), b0 - b0.mean()
                    den = math.sqrt((a * a).sum() * (b * b).sum())
                    if den <= 0: continue
                    r = float((a * b).sum() / den); sc[(di, dj)] = r
                    if best is None or r > best[0]: best = (r, di, dj)
            if not best or best[0] < min_corr: continue
            r, di, dj = best
            def sub(c, m, p):   # ajuste parabólico
                d = m - 2 * c + p
                return 0.0 if d >= 0 else 0.5 * (m - p) / d
            fi = di + (sub(r, sc.get((di - 1, dj), r), sc.get((di + 1, dj), r)) if (di - 1, dj) in sc and (di + 1, dj) in sc else 0)
            fj = dj + (sub(r, sc.get((di, dj - 1), r), sc.get((di, dj + 1), r)) if (di, dj - 1) in sc and (di, dj + 1) in sc else 0)
            lat = N - PASO * (bi + bloque / 2); lon = O + PASO * (bj + bloque / 2)
            h = minutos / 60
            u = fj * PASO * 111.2 * math.cos(math.radians(lat)) / h; v = -fi * PASO * 111.2 / h
            if abs(di) == busca or abs(dj) == busca: continue   # en el borde de la búsqueda: no confiable
            out.append([round(lat, 2), round(lon, 2), round(u, 1), round(v, 1), round(r, 2)])
    return out


def lluvia3d(t1, tb, n=9):
    """Últimas n imágenes (~1 h 20 min) de la temperatura de la cima en la malla de 0,05°, para la vista "Nubes 3D" de
    la página (Luis, 11 nov): las columnas de lluvia se dibujan donde la cima está a ≤ 245 K."""
    F = "salida/lluvia3d.json"
    try:
        L = json.load(open(F)) if os.path.exists(F) else \
            SES.get("https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/lluvia3d.json", timeout=30).json()
        assert isinstance(L.get("cuadros"), list) and L.get("filas") == FILAS and L.get("cols") == COLS
    except Exception:
        L = {"cuadros": []}
    cuadros = [c for c in L["cuadros"] if c.get("t") != t1.isoformat()] + [{"t": t1.isoformat(), "tb": b64(tb)}]
    cuadros = sorted(cuadros, key=lambda c: c["t"])[-n:]
    json.dump({"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "n": N, "s": S_, "o": O, "e": E, "paso": PASO,
               "filas": FILAS, "cols": COLS, "campos": "tb = temperatura de la cima − 150 K (u8, 255 = sin dato)", "cuadros": cuadros},
              open(F, "w"), separators=(",", ":"))


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
    T1, t1, pun1 = escena(ks[-1]); T0, t0, pun0 = escena(ks[-2])
    rayos, nglm, flashes = glm(t1 - timedelta(minutes=10), t1 + timedelta(minutes=5))
    mov = None
    try:   # imagen de hace ~30 min (3 escenas antes) para el movimiento de las tormentas
        if len(ks) >= 4:
            Tm, tm, _ = escena(ks[-4]); mins = (t1 - tm).total_seconds() / 60
            if 15 <= mins <= 45:
                mov = {"desde": tm.isoformat(), "minutos": round(mins, 1), "campos": ["lat", "lon", "u_kmh_este", "v_kmh_norte", "correlacion"],
                       "vectores": movimiento(Tm, T1, mins)}
    except Exception as e:
        print("movimiento:", str(e)[:120])
    tb = np.where(np.isfinite(T1), np.clip(np.rint(T1) - 150, 0, 254), 255).astype(np.uint8)          # 255 = sin dato
    d = np.where(np.isfinite(T1) & np.isfinite(T0), np.clip(np.rint(T1 - T0), -127, 127), -128).astype(np.int8)
    out = {"generado": ahora.isoformat(timespec="seconds"), "imagen": t1.isoformat(), "imagen_previa": t0.isoformat(),
           "rayos_desde": (t1 - timedelta(minutes=10)).isoformat(), "rayos_hasta": (t1 + timedelta(minutes=5)).isoformat(),
           "archivos_glm": nglm, "norte": N, "oeste": O, "paso": PASO, "filas": FILAS, "cols": COLS,
           "fuente": "NOAA GOES-19 (ABI banda 13 y GLM), datos públicos",
           "tb_menos_150_u8": b64(tb), "cambio_10min_i8": b64(d), "rayos_u8": b64(np.clip(rayos, 0, 255).astype(np.uint8))}
    if mov: out["movimiento"] = mov
    os.makedirs("salida", exist_ok=True)
    json.dump(out, open("salida/ahora.json", "w"), separators=(",", ":"))
    historia(t1, pun1, pun0, flashes)
    try:
        lluvia3d(t1, tb)
    except Exception as e:
        print("lluvia3d:", str(e)[:120])
    try:   # laboratorio de los avisos de tormenta: cada variante avisa y se califica sola con las imágenes siguientes (Luis, 11 nov)
        import avisos_lab
        avisos_lab.actualizar(T1, t1, (mov or {}).get("vectores") or [], N, O, PASO, SES)
    except Exception as e:
        print("avisos_lab:", str(e)[:160])
    frio = int((T1 < 215).sum()); print(f"Satélite {t1:%H:%M} UTC: celdas < 215 K: {frio} · rayos: {int(rayos.sum())} ({nglm} archivos GLM) · vectores de movimiento: {len((mov or {}).get('vectores') or [])}")


if __name__ == "__main__":
    main()
