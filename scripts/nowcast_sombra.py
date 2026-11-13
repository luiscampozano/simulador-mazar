"""DataLab Ec · nowcast en SOMBRA con pysteps (Luis, 13 nov). NO cambia los avisos ni la página.

Prueba del 12–13 nov (22 días de GOES-19, 281 momentos, revisada por otro Claude): el movimiento por bloques que usa hoy
el aviso "tormenta en camino" pierde contra la persistencia desde +60 min; el ensamble STEPS de pysteps (Lucas-Kanade +
cascada estocástica, 12 miembros) da mejor probabilidad de llegada (CSI 0,32 vs 0,29 con P ≥ 0,3, umbral elegido viendo
los resultados → hay que confirmarlo aquí, fuera de muestra). Este script corre dentro del bucle del satélite, en sombra:
  - toma las 3 últimas imágenes (10 min entre sí) de salida/lluvia3d.json,
  - campo I = max(0, 260 − T) (I ≥ 45 ⇔ cima ≤ 215 K, nube de tormenta),
  - STEPS a 2 h (12 pasos de 10 min) y, para cada punto PÚBLICO fijo de scripts/puntos_satelite.json (nunca ubicaciones
    de suscriptores: este repo es público), la probabilidad de que una nube ≤215 K pase a ≤7 km en las próximas 2 h y el
    minuto mediano de llegada entre los miembros que llegan.
Salida: salida/nowcast_sombra.json (última) y salida/nowcast_sombra_hist.json (48 h, para verificarlo después)."""
import base64, contextlib, io, json, os, sys, time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np

N, O, PASO, FILAS, COLS = 2.0, -82.0, 0.05, 150, 140
REF, UMBRAL = 260.0, 215.0
I_UMB = REF - UMBRAL
MIEMBROS, PASOS, KM = 12, 12, 7.0
LAT = N - (np.arange(FILAS) + 0.5) * PASO
LON = O + (np.arange(COLS) + 0.5) * PASO
AQUI = os.path.dirname(os.path.abspath(__file__))


def cargar_cuadros():
    L = json.load(open("salida/lluvia3d.json"))
    assert L.get("filas") == FILAS and L.get("cols") == COLS
    out = []
    for c in sorted(L["cuadros"], key=lambda c: c["t"])[-3:]:
        a = np.frombuffer(base64.b64decode(c["tb"]), np.uint8).reshape(FILAS, COLS)
        T = np.where(a == 255, np.nan, a.astype(np.float32) + 150)
        out.append((datetime.fromisoformat(c["t"]), T))
    return out


def cerca(M, la, lo, km=KM):
    i0, j0 = int((N - la) / PASO), int((lo - O) / PASO)
    r = 3
    sub = M[max(0, i0 - r):i0 + r + 1, max(0, j0 - r):j0 + r + 1]
    if not sub.any(): return False
    ii, jj = np.nonzero(sub)
    ii = ii + max(0, i0 - r); jj = jj + max(0, j0 - r)
    d = np.hypot((LON[jj] - lo) * 111.2 * np.cos(np.radians(la)), (LAT[ii] - la) * 111.2)
    return bool((d <= km).any())


def main():
    t_ini = time.time()
    C = cargar_cuadros()
    if len(C) < 3: print("nowcast sombra: faltan imágenes"); return
    dt = [(C[i + 1][0] - C[i][0]).total_seconds() / 60 for i in range(2)]
    if any(abs(x - 10) > 2 for x in dt): print("nowcast sombra: imágenes no consecutivas", dt); return
    Is = [np.nan_to_num(np.where(np.isfinite(T), np.clip(REF - T, 0, None), np.nan), nan=0.0) for _, T in C]
    from pysteps import motion, nowcasts
    V = motion.get_method("LK")(np.stack(Is))
    t0 = C[-1][0]
    if (datetime.now(timezone.utc) - t0).total_seconds() > 25 * 60:     # lluvia3d.json no se actualizó: no publicar algo viejo
        print("nowcast sombra: la última imagen es vieja", t0.isoformat()); return
    with contextlib.redirect_stdout(io.StringIO()):
        R = nowcasts.get_method("steps")(np.stack(Is), V, PASOS, n_ens_members=MIEMBROS, n_cascade_levels=6, precip_thr=1.0,
                                        kmperpixel=5.5, timestep=10, noise_method="nonparametric", vel_pert_method="bps",
                                        mask_method="incremental", probmatching_method="cdf", seed=int(t0.timestamp()) % 100000,
                                        num_workers=1)
    Rc = np.nan_to_num(R, nan=0.0) >= I_UMB                      # (miembros, pasos, F, C)
    frio0 = np.nan_to_num(C[-1][1], nan=999) <= UMBRAL
    P = json.load(open(os.path.join(AQUI, "puntos_satelite.json")))
    puntos = {}
    for ciudad, lista in P.items():
        filas = []
        for nombre, la, lo in lista:
            if cerca(frio0, la, lo, 6.0):
                filas.append([nombre, None, 0, "encima"]); continue
            llegadas = []
            for e in range(MIEMBROS):
                k = next((k for k in range(PASOS) if cerca(Rc[e, k], la, lo)), None)
                if k is not None: llegadas.append(10 * (k + 1))
            p = len(llegadas) / MIEMBROS
            filas.append([nombre, round(p, 2), int(np.median(llegadas)) if llegadas else None, None])
        puntos[ciudad] = filas
    out = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "imagen": t0.isoformat(),
           "metodo": "pysteps STEPS (LK + cascada, 12 miembros), I = max(0, 260 − T), nube de tormenta ≤215 K a ≤7 km en ≤2 h",
           "estado": "SOMBRA: no se usa en avisos ni en la página",
           "campos_punto": ["nombre", "probabilidad_llegada_2h", "minuto_mediano_de_llegada", "encima"],
           "segundos": round(time.time() - t_ini, 1), "puntos": puntos}
    json.dump(out, open("salida/nowcast_sombra.json.tmp", "w"), ensure_ascii=False, separators=(",", ":"))
    os.replace("salida/nowcast_sombra.json.tmp", "salida/nowcast_sombra.json")
    # historial de 48 h (solo puntos con algo) para verificar contra las imágenes siguientes
    F = "salida/nowcast_sombra_hist.json"
    try:
        H = json.load(open(F)) if os.path.exists(F) else json.load(io.StringIO(__import__("requests").get(
            "https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/nowcast_sombra_hist.json", timeout=30).text))
    except Exception:
        H = {"registros": []}
    lim = (t0 - timedelta(hours=48)).isoformat()
    reg = [r for r in H.get("registros", []) if r[0] >= lim and r[0] != t0.isoformat()]
    reg += [[t0.isoformat(), c, f[0], f[1], f[2], f[3]] for c, fs in puntos.items() for f in fs if f[1] or f[3]]
    imgs = sorted({i for i in H.get("imagenes_procesadas", []) if i >= lim} | {t0.isoformat()})   # distingue "P = 0" de "no corrió"
    json.dump({"campos": ["imagen", "ciudad", "punto", "p", "min", "encima"], "imagenes_procesadas": imgs, "registros": reg},
              open(F + ".tmp", "w"), ensure_ascii=False, separators=(",", ":"))
    os.replace(F + ".tmp", F)        # escritura atómica: un timeout no deja el historial a medias
    print(f"nowcast sombra {t0:%H:%M} UTC: {sum(1 for fs in puntos.values() for f in fs if (f[1] or 0) >= 0.3)} puntos con P ≥ 0,3; "
          f"{out['segundos']} s")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:      # en sombra: nunca tumba al robot del satélite
        print("nowcast sombra falló:", repr(e)[:200])
