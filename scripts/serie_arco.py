"""Rejilla de la Serie R desde ARCO-ERA5 (copia pública de ERA5 en Google Cloud, sin cola ni cuenta).
Mismo resultado que los pedazos r/g_AAAA_{s,p}N del CDS (serie_r.py): por punto, celda más cercana, mismas horas.
ARCO no trae humedad relativa ni divergencia en niveles: la HR se calcula de q y T (fórmula de ECMWF, agua/hielo mezclados)
y la divergencia con diferencias centradas de u y v en la malla de 0,25°. Termina ~5 meses atrás (valid_time_stop): lo más
reciente sigue viniendo del CDS.
Uso: python3 scripts/serie_arco.py s 1982 1 [--dias N] [--salida f.json]   (un pedazo, para probar)\n     python3 scripts/serie_arco.py lote p 3 20 300   (tarea 3 de 20, hasta 300 min; guarda en la rama serie-r)"""
import argparse, json, math, os, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import numcodecs
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from serie_r import AREA, DATOS, LATS_81, NIVELES, PUNTOS, RHO, existentes, fin_datos, guardar, pedazos   # noqa: E402
AREA_N, AREA_O, AREA_S, AREA_E = AREA

BASE = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
T0 = datetime(1900, 1, 1)
NIV37 = None
BLOSC = numcodecs.Blosc()
SUP = {"cape": "convective_available_potential_energy", "cin": "convective_inhibition", "tcwv": "total_column_water_vapour",
       "lcc": "low_cloud_cover", "swvl1": "volumetric_soil_water_layer_1"}
PRES = {"u": "u_component_of_wind", "v": "v_component_of_wind", "t": "temperature", "w": "vertical_velocity",
        "q": "specific_humidity"}


def bajar(url, intentos=5):
    for i in range(intentos):
        try:
            with urllib.request.urlopen(url, timeout=120) as r: return r.read()
        except Exception:
            if i == intentos - 1: raise
            time.sleep(2 * (i + 1))


def niveles():
    global NIV37
    if NIV37 is None:
        z = json.loads(bajar(BASE + "/.zmetadata"))["metadata"]
        NIV37 = [int(x) for x in np.frombuffer(BLOSC.decode(bajar(BASE + "/level/0")), dtype="<i8")]
        assert z["level/.zarray"]["shape"] == [37]
    return NIV37


def celda(la, lo):
    return int(round((90 - la) / 0.25)), int(round((lo % 360) / 0.25)) % 1440


CELDAS = {k: celda(*v) for k, v in PUNTOS.items()}
CELDAS81 = {la: celda(la, -81.0) for la in LATS_81}
I0, J0 = celda(AREA_N, 0)[0] - 1, celda(0, AREA_O)[1] - 1          # recuadro de Ecuador (+1 celda de margen)
I1, J1 = celda(AREA_S, 0)[0] + 2, celda(0, AREA_E)[1] + 2
assert all(I0 < i < I1 - 1 and J0 < j < J1 - 1 for i, j in list(CELDAS.values()) + list(CELDAS81.values()))


def campo(var, hora, pres=False):
    """Un campo global (721×1440, o 37×721×1440 en niveles) para la hora (datetime UTC)."""
    i = int((hora - T0).total_seconds() // 3600)
    a = np.frombuffer(BLOSC.decode(bajar(f"{BASE}/{var}/{i}.0.0" + (".0" if pres else ""))), dtype="<f4")
    return a.reshape((37, 721, 1440) if pres else (721, 1440))


def dia_local(hora):   # misma regla que serie_r.por_dia: día = UTC − 5 h
    return (hora - timedelta(hours=5)).date().isoformat()


def hr(q, t, p):
    """Humedad relativa (%) como ECMWF (saturación sobre agua/hielo mezclada entre −23 °C y 0 °C)."""
    e = q * p / (0.622 + 0.378 * q)
    esw = 611.21 * np.exp(17.502 * (t - 273.16) / (t - 32.19))
    esi = 611.21 * np.exp(22.587 * (t - 273.16) / (t + 0.7))
    al = np.clip((t - 250.16) / (273.16 - 250.16), 0, 1) ** 2
    return 100 * e / (al * esw + (1 - al) * esi)


def div(u, v, i, j, i0=0):
    """Divergencia (1/s) en la celda (i, j) del recuadro (fila i0 de la malla global) con diferencias centradas (0,25°)."""
    R, d = 6.371e6, math.radians(0.25)
    phi = math.radians(90 - 0.25 * (i + i0)); c = math.cos(phi)
    dudx = (u[i, j + 1] - u[i, j - 1]) / (2 * d * R * c)
    cn, cs = math.cos(phi + d), math.cos(phi - d)       # i-1 está al norte
    dvdy = (v[i - 1, j] * cn - v[i + 1, j] * cs) / (2 * d * R * c)
    return float(dudx + dvdy)


def pedazo(tipo, anio, k, dias=None, hilos=16):
    grupos = ([1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]) if tipo == "s" else ([1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12])
    meses = grupos[k - 1]
    d0 = date(anio, meses[0], 1)
    d1 = date(anio + (meses[-1] == 12), meses[-1] % 12 + 1, 1)
    fechas = [d0 + timedelta(n) for n in range((d1 - d0).days)][:dias]
    horas_utc = [12, 15, 18, 21] if tipo == "s" else [18, 23]
    tareas = [(datetime(f.year, f.month, f.day, h), v) for f in fechas for h in horas_utc for v in (SUP if tipo == "s" else PRES)]
    out = {}

    def pon(d, kk, n, x, nd=2):
        if d.startswith(str(anio)) and x == x: out.setdefault(d, {}).setdefault(kk, {})[n] = round(float(x), nd)

    if tipo == "s":
        acum = {}   # (día, punto, var) -> valores

        def una(t):
            hora, v = t; f = campo(SUP[v], hora)
            return hora, v, {kk: float(f[i, j]) for kk, (i, j) in CELDAS.items()}
        with ThreadPoolExecutor(hilos) as ex:
            for hora, v, vals in ex.map(una, tareas):
                for kk, x in vals.items(): acum.setdefault((dia_local(hora), kk, v), []).append(x)
        for (d, kk, v), xs in acum.items():
            xs = np.array(xs); xs = xs[~np.isnan(xs)]
            if not len(xs): continue
            n, fn = {"cape": ("cape_max", np.max), "cin": ("cin_min", np.min), "tcwv": ("tcwv", np.mean),
                     "lcc": ("lcc", np.mean), "swvl1": ("suelo", np.mean)}[v]
            pon(d, kk, n, fn(xs), 3 if n == "suelo" else 2)
    else:
        L = niveles(); il = {n: L.index(int(n)) for n in NIVELES}; lv = [il[n] for n in NIVELES]
        horas = sorted({h for h, _ in tareas})

        def una(t):   # un campo de 37 niveles → solo los 4 niveles y el recuadro de Ecuador (poca memoria)
            hora, v = t
            return hora, v, campo(PRES[v], hora, True)[lv, I0:I1, J0:J1].copy()
        F = {}
        with ThreadPoolExecutor(hilos) as ex:
            for hora, v, a in ex.map(una, [(h, v) for h in horas for v in PRES]): F.setdefault(hora, {})[v] = a
        for hora in horas:
            d, suf, G = dia_local(hora), ("_d" if hora.hour == 18 else "_t"), F.pop(hora)
            for kk, (i, j) in CELDAS.items():
                i, j = i - I0, j - J0
                for a, n in enumerate(NIVELES):
                    p = int(n) * 100.0
                    u, v_, t, w, q = (G[x][a] for x in ("u", "v", "t", "w", "q"))
                    if n != "200": pon(d, kk, f"hr{n}{suf}", hr(q[i, j], t[i, j], p))
                    pon(d, kk, f"u{n}{suf}", u[i, j]); pon(d, kk, f"v{n}{suf}", v_[i, j])
                    if n in ("850", "500"): pon(d, kk, f"t{n}{suf}", t[i, j] - 273.15)
                    if n in RHO: pon(d, kk, f"w{n}{suf}", -w[i, j] / (RHO[n] * 9.81), 3)
                    if n in ("200", "850"): pon(d, kk, f"div{n}{suf}", div(u, v_, i, j, I0) * 1e5)
            a = NIVELES.index("850")
            for la, (i, j) in CELDAS81.items():   # convergencia 850 a 81° O, promedio de 18 y 23 UTC
                out.setdefault("_c81", {}).setdefault((d, la), []).append(-div(G["u"][a], G["v"][a], i - I0, j - J0, I0) * 1e5)
        for (d, la), xs in out.pop("_c81", {}).items(): pon(d, "x_z81", f"c{la:+.1f}", sum(xs) / len(xs))
    return {"anio": anio, "pedazo": f"{tipo}{k}", "meses": meses,
            "fuente": "ERA5 vía ARCO-ERA5 (Google Cloud; Copernicus C3S, CC-BY 4.0), celda más cercana",
            "horas": "s: 12-21 UTC; p: 18 UTC (_d, 13 h) y 23 UTC (_t, 18 h)", "dias": dict(sorted(out.items()))}


def fin_arco():
    z = json.loads(bajar(BASE + "/.zmetadata"))["metadata"]
    return date.fromisoformat(z[".zattrs"]["valid_time_stop"][:10])


def lote(tipo, n, de, minutos, hilos):
    """Pedazos de la rejilla que faltan en la rama serie-r y que ARCO ya cubre, repartidos entre `de` tareas (esta es la n).
    Cada pedazo se guarda apenas termina; al pasar `minutos` no se empieza otro (la próxima corrida retoma)."""
    t0, fin, hay = time.time(), fin_arco(), existentes()
    todos = [(a, t, m) for a, t, m in pedazos(tipo)
             if f"r/g_{a}_{t}.json.gz" not in hay and date(a + (m[-1] == 12), m[-1] % 12 + 1, 1) <= fin + timedelta(1)]
    mios = todos[n::de]
    print(f"{tipo}: faltan {len(todos)} pedazos cubiertos por ARCO (hasta {fin}); esta tarea {n}/{de}: {len(mios)}", flush=True)
    for a, t, m in mios:
        if time.time() - t0 > minutos * 60: print("  se acabó el tiempo; sigue la próxima corrida", flush=True); break
        rel = f"r/g_{a}_{t}.json.gz"
        subprocess.run(["git", "fetch", "-q", "origin", "serie-r"], cwd=DATOS, capture_output=True)
        if rel in existentes(): continue          # lo bajó otra tarea (o el CDS, que trae r y d reales) mientras tanto
        t1 = time.time()
        try:
            r = pedazo(tipo, a, int(t[1:]), hilos=hilos)
            if not r["dias"]: print("  sin datos", rel, flush=True); continue
            guardar(rel, r); print(f"  {rel}: {len(r['dias'])} días en {(time.time() - t1) / 60:.1f} min", flush=True)
        except Exception as e:
            print("  FALLÓ", rel, str(e)[:250], flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "lote":    # lote <s|p> <n> <de> <minutos>
        lote(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]), int(os.environ.get("ARCO_HILOS", "16")))
        sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("tipo", choices=["s", "p"]); ap.add_argument("anio", type=int); ap.add_argument("k", type=int)
    ap.add_argument("--dias", type=int); ap.add_argument("--hilos", type=int, default=16); ap.add_argument("--salida")
    a = ap.parse_args(); t0 = time.time()
    r = pedazo(a.tipo, a.anio, a.k, a.dias, a.hilos)
    print(f"{a.tipo}{a.k} {a.anio}: {len(r['dias'])} días en {(time.time() - t0) / 60:.1f} min", flush=True)
    if a.salida: json.dump(r, open(a.salida, "w"), ensure_ascii=False, separators=(",", ":"))
