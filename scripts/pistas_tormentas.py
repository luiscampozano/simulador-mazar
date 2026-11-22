"""Pistas de tormentas cada 10 min (GOES-19 banda 13, datos públicos de NOAA).
Para un "día de tormenta" (06:00 → 06:00 hora de Ecuador) baja las imágenes de la banda 13 y sigue cada nube fría con
tobac (umbrales 235–195 K, ≥ 4 píxeles, enlace trackpy, ≥ 30 min de vida) en el recorte de la Costa y el golfo.
Guarda solo posiciones: [lat, lon, 'dd HH:MM' hora de Ecuador, tope más frío en K, área km²] de cada celda.
Uso: python3 scripts/pistas_tormentas.py AAAA-MM-DD  → salida/pistas/<día>.json"""
import json, os, sys, time, warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import satelite_ahora as S  # noqa: E402

N0, O0, PASO, FILAS, COLS = 2.0, -82.0, 0.05, 150, 140
I0, I1, J0, J1 = 0, 130, 0, 72          # lat 2,0 → −4,5; lon −82,0 → −78,4
DXY = 5550.0
UMBRALES = [235, 225, 215, 205, 195]
LAT = N0 - (np.arange(FILAS) + 0.5) * PASO
LON = O0 + (np.arange(COLS) + 0.5) * PASO


def bajar(dia):
    ini = datetime.fromisoformat(dia).replace(hour=11, tzinfo=timezone.utc)
    ks = []
    for h in range(24):
        try: ks += [k for k in S.listar("ABI-L2-CMIPF", ini + timedelta(hours=h)) if "M6C13" in k]
        except Exception as e: print("listado", h, str(e)[:80])

    def una(k):
        for _ in range(3):
            try:
                T, t, _ = S.escena(k)
                return t, np.where(np.isfinite(T), np.clip(np.rint(T - 150), 0, 254), 255).astype(np.uint8)
            except Exception:
                time.sleep(2)
        return None
    with ThreadPoolExecutor(6) as ex:
        r = sorted([x for x in ex.map(una, ks) if x], key=lambda x: x[0])
    return np.stack([x[1] for x in r]), [x[0] for x in r]


def seguir(tb8, ts):
    import pandas as pd, xarray as xr, tobac, trackpy, logging
    from scipy import ndimage
    trackpy.quiet(); logging.disable(logging.INFO)
    tb = tb8[:, I0:I1, J0:J1].astype(np.float32) + 150.0
    tb[tb >= 405] = np.nan
    t = pd.to_datetime([x.replace(tzinfo=None) for x in ts])
    da = xr.DataArray(np.where(np.isfinite(tb), tb, 300.0), dims=("time", "y", "x"),
                      coords={"time": t.values, "latitude": ("y", LAT[I0:I1]), "longitude": ("x", LON[J0:J1])}, name="tb")
    feats = tobac.feature_detection_multithreshold(da, DXY, threshold=UMBRALES, target="minimum", n_min_threshold=4,
                                                   position_threshold="weighted_diff", sigma_threshold=0.5, min_distance=0)
    if feats is None or len(feats) == 0:
        return []
    seg, feats = tobac.segmentation_2D(feats, da, DXY, threshold=235, target="minimum")
    tr = tobac.linking_trackpy(feats, da, dt=600, dxy=DXY, v_max=40, memory=2, stubs=3, adaptive_step=0.9, adaptive_stop=5,
                               method_linking="predict", time_cell_min=1800)
    tr = tr[tr["cell"] > 0].copy()
    mk = seg.values if hasattr(seg, "values") else seg.core_data()
    tmin = {}
    for f in np.unique(tr["frame"]):
        sub = tr.loc[tr["frame"] == f]
        v = ndimage.minimum(np.nan_to_num(tb[f], nan=300.0), labels=mk[f], index=sub["feature"].values)
        for (_, row), a, b in zip(sub.iterrows(), sub["feature"].values, v):
            if not (row.get("ncells", 0) > 0):
                i, j = int(round(row["hdim_1"])), int(round(row["hdim_2"]))
                b = np.nanmin(tb[f, max(i - 1, 0):i + 2, max(j - 1, 0):j + 2])
            tmin[a] = float(b)
    tr["tb_min"] = tr["feature"].map(tmin)
    tr["ncells"] = np.where(tr["ncells"].fillna(0) > 0, tr["ncells"].fillna(0), tr["num"])
    tr["area"] = tr["ncells"] * (DXY / 1000) ** 2
    tr["local"] = pd.to_datetime(tr["time"]) - pd.Timedelta(hours=5)
    out = []
    for c, g in tr.groupby("cell"):
        g = g.sort_values("time")
        out.append({"id": int(c), "tb_min_K": round(float(g["tb_min"].min()), 0), "area_max_km2": int(round(float(g["area"].max()), -1)),
                    "pista": [[round(float(r.latitude), 3), round(float(r.longitude), 3), r.local.strftime("%d %H:%M"),
                               (round(float(r.tb_min), 1) if np.isfinite(r.tb_min) else None), int(round(float(r.area)))] for r in g.itertuples()]})
    return out


def main():
    dia = sys.argv[1]
    t0 = time.time(); tb8, ts = bajar(dia)
    print(f"{dia}: {len(ts)} imágenes ({time.time() - t0:.0f} s)")
    if len(ts) < 100:
        raise SystemExit(f"pocas imágenes ({len(ts)} de 144)")
    celdas = seguir(tb8, ts)
    os.makedirs("salida/pistas", exist_ok=True)
    json.dump({"dia": dia, "imagenes": len(ts), "nota": "cada pista: [lat, lon, 'dd HH:MM' hora Ecuador, tope K, área km²] cada 10 min",
               "celdas": celdas}, open(f"salida/pistas/{dia}.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{dia}: {len(celdas)} celdas ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
