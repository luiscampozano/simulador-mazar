"""Mapa de la fase de las nubes sobre Guayaquil y alrededores (GOES-19) para la pestaña Tormentas — EN PRUEBA (Luis 27 nov 2026).

Toma la última imagen de 10 min que ya tenga fase (ACTP), altura (ACHA) y espesor (COD) y dibuja 6 clases:
despejado · agua líquida baja · agua líquida con cima ≥ 4 km · sobreenfriada/mixta · hielo fino · hielo grueso (espesor ≥ 20);
de noche (sol con ángulo cenital > 85°, o crepúsculo con espesor tope ≤ 16,5) el espesor no sirve y todo el hielo va a una sola clase "hielo_noche".
Los nombres "núcleo"/"yunque" y el umbral de 20 son hipótesis hasta cruzarlos con el Inamhi (registro en sombra fase_nubes).
Salida (carpeta dada, en GitHub la rama fase-nubes): fase_gye.png y fase_gye.json (hora y lectura por zona)."""
import datetime as D, json, os, re, sys, urllib.request
import numpy as np

S3 = "https://noaa-goes19.s3.amazonaws.com/"
N, S, O, E = -1.45, -3.05, -80.75, -79.25
UMBRAL_COD = 20
CLASES = ["despejado", "liquida_baja", "liquida_alta", "mixta", "hielo_fino", "hielo_grueso", "hielo_noche"]
COLORES = ["#1b2229", "#6fb7c9", "#29e0d0", "#7a7cff", "#c9cfd6", "#ff4d3d", "#e9a8ff"]
ZENIT_NOCHE = 85   # de noche el espesor de NOAA no pasa de ~16 (revisor, 27 nov): no se separa núcleo de yunque. A 76° todavía llega a 158
# zonas públicas (radio ~8 km) para la lectura en palabras
ZONAS = [("Guayaquil", -2.17, -79.92, 0.09), ("Durán", -2.15, -79.81, 0.05), ("Samborondón", -2.03, -79.86, 0.06),
         ("Daule", -1.87, -79.98, 0.07), ("Chongón y Cerecita", -2.27, -80.17, 0.10), ("Milagro", -2.13, -79.59, 0.07),
         ("Playas", -2.63, -80.39, 0.07)]


def listar(p, t):
    u = f"{S3}?list-type=2&prefix=ABI-L2-{p}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/"
    with urllib.request.urlopen(u, timeout=60) as r:
        return re.findall(r"<Key>([^<]+)</Key>", r.read().decode())


def leer(k, var):
    import fsspec, h5netcdf
    with fsspec.filesystem("https").open(S3 + k, block_size=2 ** 18) as f, h5netcdf.File(f, "r") as d:
        p = d["goes_imager_projection"].attrs
        a, b = float(p["semi_major_axis"]), float(p["semi_minor_axis"]); H = float(p["perspective_point_height"]) + a
        l0 = np.radians(float(p["longitude_of_projection_origin"]))
        sc = lambda v: d[v][:] * float(d[v].attrs["scale_factor"]) + float(d[v].attrs["add_offset"])
        X, Y = sc("x"), sc("y")

        def ij(la, lo):
            la, lo = np.radians(la), np.radians(lo); lc = np.arctan(b * b / (a * a) * np.tan(la)); e2 = 1 - b * b / (a * a)
            rc = b / np.sqrt(1 - e2 * np.cos(lc) ** 2)
            sx = H - rc * np.cos(lc) * np.cos(lo - l0); sy = -rc * np.cos(lc) * np.sin(lo - l0); sz = rc * np.sin(lc)
            return int(np.argmin(abs(Y - np.arctan(sz / sx)))), int(np.argmin(abs(X - np.arcsin(-sy / np.sqrt(sx * sx + sy * sy + sz * sz)))))
        i0, j0 = ij(N, O); i1, j1 = ij(S, E)
        v = d[var]; A = np.asarray(v[i0:i1 + 1, j0:j1 + 1]).astype(float); fv = v.attrs.get("_FillValue")
        if fv is not None: A[A == float(np.asarray(fv).ravel()[0])] = np.nan
        if var != "Phase": A = A * float(v.attrs.get("scale_factor", 1)) + float(v.attrs.get("add_offset", 0))
        xx, yy = np.meshgrid(X[j0:j1 + 1], Y[i0:i1 + 1])   # inversa de la proyección fija: lat/lon de cada píxel
        aa = np.sin(xx) ** 2 + np.cos(xx) ** 2 * (np.cos(yy) ** 2 + a * a / (b * b) * np.sin(yy) ** 2)
        bb = -2 * H * np.cos(xx) * np.cos(yy); cc = H * H - a * a
        rs = (-bb - np.sqrt(bb * bb - 4 * aa * cc)) / (2 * aa)
        sx = rs * np.cos(xx) * np.cos(yy); sy = -rs * np.sin(xx); sz = rs * np.cos(xx) * np.sin(yy)
        lat = np.degrees(np.arctan(a * a / (b * b) * sz / np.sqrt((H - sx) ** 2 + sy * sy))); lon = np.degrees(l0 - np.arctan(sy / (H - sx)))
        return A, lat, lon


def zenit(t, lat, lon):
    """Ángulo cenital del sol (grados), fórmula aproximada de la NOAA."""
    n = t.timetuple().tm_yday; h = t.hour + t.minute / 60
    g = 2 * np.pi / 365 * (n - 1 + (h - 12) / 24)
    dec = 0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g) + 0.000907 * np.sin(2 * g)
    eq = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g) - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    ha = np.radians((h * 60 + eq + 4 * lon) / 4 - 180)
    la = np.radians(lat)
    return float(np.degrees(np.arccos(np.sin(la) * np.sin(dec) + np.cos(la) * np.cos(dec) * np.cos(ha))))


def cercano(la_o, lo_o, v, la, lo):
    """Valor de la malla gruesa (ACHA/COD) en cada píxel de la malla fina (fase), por vecino más cercano."""
    from scipy.spatial import cKDTree
    _, i = cKDTree(np.c_[la_o.ravel(), lo_o.ravel()]).query(np.c_[la.ravel(), lo.ravel()])
    return v.ravel()[i].reshape(la.shape)


def main():
    sal = sys.argv[1] if len(sys.argv) > 1 else "."
    ahora = D.datetime.now(D.timezone.utc); K = {}
    for p in ("ACTPF", "ACHAF", "CODF"):
        ks = []
        for h in (2, 1, 0):
            try: ks += listar(p, ahora - D.timedelta(hours=h))
            except Exception as e: print(p, e)
        K[p] = {re.search(r"_s(\d{11})", k)[1]: k for k in ks}
    comunes = sorted(set(K["ACTPF"]) & set(K["ACHAF"]) & set(K["CODF"]))
    if not comunes: sys.exit("ERROR: no hay una imagen reciente con fase, altura y espesor")
    s = comunes[-1]; t = D.datetime.strptime(s, "%Y%j%H%M").replace(tzinfo=D.timezone.utc)
    ph, la, lo = leer(K["ACTPF"][s], "Phase"); ht, la2, lo2 = leer(K["ACHAF"][s], "HT"); cod, la3, lo3 = leer(K["CODF"][s], "COD")
    htp, codp = cercano(la2, lo2, ht, la, lo), cercano(la3, lo3, cod, la, lo)
    C = np.full(ph.shape, np.nan)
    C[ph == 0] = 0; C[ph == 1] = 1; C[(ph == 1) & (htp >= 4000)] = 2; C[(ph == 2) | (ph == 3)] = 3
    zz = zenit(t, -2.2, -79.9)
    noche = zz > ZENIT_NOCHE or (zz > 70 and np.nanmax(cod) <= 16.5)   # 2.º caso: el producto ya pasó a su algoritmo nocturno
    if noche: C[ph == 4] = 6
    else: C[ph == 4] = 4; C[(ph == 4) & (codp >= UMBRAL_COD)] = 5

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt, matplotlib.patheffects as pe
    from matplotlib.colors import ListedColormap
    fig = plt.figure(figsize=(8, 8.5), dpi=110); ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off(); fig.patch.set_facecolor("#0d1217")
    ax.pcolormesh(lo, la, C, cmap=ListedColormap(COLORES), vmin=-.5, vmax=6.5, shading="nearest")
    B = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fase_mapa_base.json"), encoding="utf-8"))
    for seg in B["costa"]:
        seg = np.array(seg); ax.plot(seg[:, 0], seg[:, 1], color="#ffd36b", lw=1.2, alpha=.9)
    for an in B["limites"]:
        an = np.array(an); ax.plot(an[:, 0], an[:, 1], color="#ffffff", lw=.6, alpha=.5)
    borde = [pe.withStroke(linewidth=3, foreground="k")]
    for n, y, x, dy in [("Guayaquil", -2.19, -79.89, -.06), ("Durán", -2.12, -79.80, .02), ("Samborondón", -2.0, -79.86, .02), ("Daule", -1.87, -79.98, .02),
                        ("Chongón", -2.235, -80.075, .02), ("Cerecita", -2.305, -80.27, .02), ("Milagro", -2.13, -79.59, .02), ("Playas", -2.63, -80.39, .02)]:
        ax.plot(x, y, "o", ms=5, color="#ffd36b", mec="k"); ax.text(x + .02, y + dy, n, color="w", fontsize=12, weight="bold", path_effects=borde)
    ax.set_xlim(O, E); ax.set_ylim(S, N); ax.set_aspect(1 / np.cos(np.radians(2.2)))
    loc = t - D.timedelta(hours=5)
    ax.text(.015, .985, f"{loc:%d/%m %H:%M} (Ecuador)", transform=ax.transAxes, va="top", color="w", fontsize=15, weight="bold", path_effects=borde)
    ax.text(.985, .012, "@DataLabEc · GOES-19 (NOAA)", transform=ax.transAxes, ha="right", color="#cfe0e6", fontsize=10, path_effects=borde)
    os.makedirs(sal, exist_ok=True)
    plt.savefig(os.path.join(sal, "fase_gye.tmp.png"), facecolor=fig.get_facecolor()); os.replace(os.path.join(sal, "fase_gye.tmp.png"), os.path.join(sal, "fase_gye.png"))

    zonas = []
    for n, y, x, r in ZONAS:
        m = ((la - y) ** 2 + (lo - x) ** 2 <= r * r) & np.isfinite(C)
        if not m.any(): continue
        cnt = np.bincount(C[m].astype(int), minlength=len(CLASES)) / m.sum()
        dom = int(np.argmax(cnt)); h = htp[m & (C == dom)]; h = h[np.isfinite(h)]   # cima de la clase que se muestra
        zonas.append({"zona": n, "fracciones": {c: round(float(f), 2) for c, f in zip(CLASES, cnt)},
                      "cima_km": round(float(np.percentile(h, 90)) / 1000, 1) if h.size else None})
    J = {"imagen_utc": t.isoformat(), "hora_local": loc.strftime("%Y-%m-%d %H:%M"), "umbral_espesor": UMBRAL_COD,
         "clases": CLASES, "colores": COLORES, "noche": bool(noche), "zonas": zonas, "estado": "en prueba"}
    with open(os.path.join(sal, "fase_gye.tmp.json"), "w", encoding="utf-8") as g: json.dump(J, g, ensure_ascii=False)
    os.replace(os.path.join(sal, "fase_gye.tmp.json"), os.path.join(sal, "fase_gye.json"))
    print("mapa", J["hora_local"], [(z["zona"], max(z["fracciones"], key=z["fracciones"].get)) for z in zonas])


if __name__ == "__main__":
    main()
