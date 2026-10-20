"""Calibración diaria del modelo de Mazar con todo el historial de Celec Sur (desde 2023).

Corre una vez al día desde el robot de GitHub. Hace cuatro cosas:
1. Completa historial/celec_diario.json con los días que falten (cota, caudal de entrada, energía de
   Mazar, Molino y Sopladora, y cota de Amaluza).
2. Ajusta con ese historial la física del embalse:
   - curva de Mazar: millones de m³ por metro de cota, a partir del balance diario de agua;
   - cuánta agua debe soltar Mazar por cada MW de Paute, separando lo que aporta la cuenca entre
     Mazar y Amaluza (crece con la lluvia) y lo que se saca de Amaluza;
   - modelo lluvia–caudal del Paute (época seca) con la lluvia histórica de Open-Meteo;
   - variación de la generación de Paute según el día de la semana.
3. Prueba retrospectiva: simula el modelo desde decenas de fechas pasadas y mide cuánto se alejó la
   realidad. Con eso calcula el rango probable que muestra la página.
4. Evalúa las predicciones que el robot guardó en registro/predicciones.json.
Escribe parametros_modelo.json. Requiere numpy.
"""
import json, os, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone
import numpy as np

EC = timezone(timedelta(hours=-5))
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F_HIST = os.path.join(RAIZ, "historial", "celec_diario.json")
F_CLIM = os.path.join(RAIZ, "historial", "clima_lluvia_paute.json")
F_PAR = os.path.join(RAIZ, "parametros_modelo.json")
F_REG = os.path.join(RAIZ, "registro", "predicciones.json")
ORDS = "https://generacioncsr.celec.gob.ec:8443/ords/csr/"
PISO_AMALUZA = 1971.3          # nivel más bajo usado por la operación (abr 2024 y oct 2026)
AREA_AMALUZA = (0.0844, 0.1203)  # hm³/m = a + b·(cota − 1971), ajustado con 2023–2026


def _items(url, intentos=3):
    for k in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (simulador-mazar)"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r).get("items", [])
        except Exception:
            time.sleep(1 + k)
    return None


def _puntos(mrid, d):
    ini = datetime(d.year, d.month, d.day, 1, tzinfo=EC).astimezone(timezone.utc)
    fin = ini + timedelta(hours=23)
    it = _items(f"{ORDS}sardomcsr/pointValues?mrid={mrid}&fechaInicio={ini:%Y-%m-%dT%H:%M:%S.000Z}"
                f"&fechaFin={fin:%Y-%m-%dT%H:%M:%S.000Z}&fecha={d:%d/%m/%Y}%2001:00:00")
    if it is None:
        return None
    return sorted((i["loctimestamp"], float(i["valueedit"])) for i in it if i.get("valueedit") is not None)


def _energia(ep, d):
    it = _items(f"{ORDS}{ep}?fecha={d:%d/%m/%Y}%2000:00:00")
    if it is None:
        return None
    v = [float(i["valueedit"]) for i in it if i.get("valueedit") is not None]
    return sum(v) if len(v) >= 20 else None


def dia_celec(d):
    c, q, am = _puntos(30031, d), _puntos(30538, d), _puntos(24019, d)
    e = [_energia(ep, d) for ep in ("sardommaz/mazEnerDia", "sardommol/molEnerDia", "sardomsop/sopEnerDia")]
    if not c or len(c) < 20 or not q or len(q) < 20 or not am or None in e:
        return None
    return {"c": round(c[-1][1], 3), "q": round(sum(v for _, v in q) / len(q), 2),
            "maz": round(e[0], 1), "mol": round(e[1], 1), "sop": round(e[2], 1), "am": round(am[-1][1], 3)}


def completar_historial(H, hasta, max_dias=20):
    d = date.fromisoformat(max(H)) + timedelta(days=1)
    nuevos = 0
    while d <= hasta and nuevos < max_dias:
        r = dia_celec(d)
        if r is None:
            print(f"Historial: {d} incompleto en Celec; se reintenta luego")
            break
        H[d.isoformat()] = r
        nuevos += 1
        d += timedelta(days=1)
    return nuevos


def lluvia_paute(desde, hasta):
    """Lluvia diaria media de dos puntos de la cuenca del Paute (Open-Meteo)."""
    out = {}
    fin_archivo = min(hasta, date.today() - timedelta(days=6))
    url = ("https://archive-api.open-meteo.com/v1/archive?latitude=-2.75,-2.55&longitude=-78.85,-78.60"
           f"&start_date={desde}&end_date={fin_archivo}&daily=precipitation_sum&timezone=America%2FGuayaquil")
    for loc in json.load(urllib.request.urlopen(url, timeout=180)):
        for t, v in zip(loc["daily"]["time"], loc["daily"]["precipitation_sum"]):
            if v is not None:
                out.setdefault(t, []).append(v)
    url = ("https://api.open-meteo.com/v1/forecast?latitude=-2.75,-2.55&longitude=-78.85,-78.60"
           "&daily=precipitation_sum&past_days=14&forecast_days=1&timezone=America%2FGuayaquil")
    for loc in json.load(urllib.request.urlopen(url, timeout=60)):
        for t, v in zip(loc["daily"]["time"], loc["daily"]["precipitation_sum"]):
            if v is not None and t > fin_archivo.isoformat():
                out.setdefault(t, []).append(v)
    return {t: sum(v) / len(v) for t, v in out.items()}


# ------------------------------------------------------------------ física (debe coincidir con modelo.js)
def vol_mazar(x, a, b):
    return a * x + b * x * x / 2


def x_mazar(v, a, b):
    if v <= 0:
        return v / a
    return (-a + (a * a + 2 * b * v) ** 0.5) / b


def vol_amaluza(h):
    a, b = AREA_AMALUZA
    if h <= PISO_AMALUZA:
        return 0.0
    return a * (h - PISO_AMALUZA) + b * ((h - 1971) ** 2 - (PISO_AMALUZA - 1971) ** 2) / 2


def paso_caudal(coef, q_prev, q30, p0, p1, p2, p36, p730):
    """Modelo lluvia–caudal con memoria de 30 días (distingue un año seco de uno normal)."""
    return float(np.exp(coef[0] + coef[1] * np.log(max(q_prev, 1.0)) + coef[2] * np.log(max(q30, 1.0))
                        + coef[3] * p0 + coef[4] * p1 + coef[5] * p2 + coef[6] * p36 + coef[7] * p730))


def main():
    hoy = datetime.now(EC).date()
    par_prev = json.load(open(F_PAR, encoding="utf-8")) if os.path.exists(F_PAR) else {}
    forzar = "--forzar" in sys.argv
    if par_prev.get("calibrado") == hoy.isoformat() and not forzar:
        print("Calibración de hoy ya hecha.")
        return 0
    H = json.load(open(F_HIST, encoding="utf-8"))
    n_nuevos = completar_historial(H, hoy - timedelta(days=1))
    with open(F_HIST, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(H.items())), f, separators=(",", ":"))
    print(f"Historial: {len(H)} días ({n_nuevos} nuevos), hasta {max(H)}")

    ds = sorted(H)
    n = len(ds)
    c = np.array([H[d]["c"] for d in ds]); q = np.array([H[d]["q"] for d in ds])
    emaz = np.array([H[d]["maz"] for d in ds]); ems = np.array([H[d]["mol"] + H[d]["sop"] for d in ds])
    am = np.array([H[d]["am"] for d in ds])
    Pmz = emaz / 24; Pms = ems / 24; Ptot = Pmz + Pms

    # 1) Curva de Mazar y eficiencia de Mazar (balance diario de agua, días sin vertido)
    dc = c[1:] - c[:-1]; cm = (c[1:] + c[:-1]) / 2; Hd = cm - am[1:]
    m = (c[1:] < 2152.5) & (c[:-1] < 2152.5) & (np.abs(dc) < 3) & (Hd > 50)
    mejor = None
    for eta in np.arange(0.70, 0.98, 0.005):
        Qmz = Pmz[1:] / (0.00981 * eta * Hd)
        y = (q[1:] - Qmz)[m] * 86400 / 1e6
        X = np.c_[dc[m], dc[m] * (cm[m] - 2115)]
        co, *_ = np.linalg.lstsq(X, y, rcond=None)
        err = float(np.mean((X @ co - y) ** 2))
        if mejor is None or err < mejor[0]:
            mejor = (err, float(eta), float(co[0]), float(co[1]))
    _, eta, a, b = mejor
    print(f"Curva Mazar: {a:.3f} + {b:.4f}·x hm³/m; eficiencia {eta:.3f}")

    # 2) Agua de Mazar por MW de Paute (semanas de estiaje)
    Qmaz = Pmz / (0.00981 * eta * (c - am))
    filas = []
    for i in range(1, n - 7, 7):
        sl = slice(i, i + 7)
        if q[sl].mean() < 70 and c[sl].mean() < 2150:
            filas.append((Pms[sl].mean(), Qmaz[sl].mean(), q[sl].mean(), am[i + 6] - am[i - 1]))
    R = np.array(filas)
    co, *_ = np.linalg.lstsq(R[:, 1:4], R[:, 0], rcond=None)
    k_ms, beta = float(co[0]), float(co[1] / co[0])
    print(f"Molino+Sopladora: {k_ms:.2f} MW por m³/s; aporte de la cuenca intermedia = {beta:.3f} × caudal de Mazar")

    # 3) Modelo lluvia–caudal (época seca)
    lluvia = lluvia_paute(date.fromisoformat(ds[0]) - timedelta(days=10), hoy - timedelta(days=1))
    p = np.array([lluvia.get(d, np.nan) for d in ds])
    p = np.where(np.isnan(p), np.nanmean(p), p)
    mes = np.array([int(d[5:7]) for d in ds])
    Xl, yl = [], []
    for i in range(31, n):
        if mes[i] in (8, 9, 10, 11, 12, 1):
            Xl.append([1.0, np.log(max(q[i - 1], 1)), np.log(max(q[i - 30:i].mean(), 1)), p[i], p[i - 1], p[i - 2],
                       np.mean(p[i - 6:i - 2]), np.mean(p[i - 30:i - 6])])
            yl.append(np.log(max(q[i], 1)))
    coef_q = [float(x) for x in np.linalg.lstsq(np.array(Xl), np.array(yl), rcond=None)[0]]

    # 3b) Sesgo del pronóstico de lluvia (ECMWF) frente a la lluvia de referencia, meses secos
    sesgo = par_prev.get("sesgo_lluvia_pronostico", 0.72)
    try:
        url = ("https://historical-forecast-api.open-meteo.com/v1/forecast?latitude=-2.75,-2.55"
               f"&longitude=-78.85,-78.60&start_date=2024-01-01&end_date={hoy - timedelta(days=7)}"
               "&daily=precipitation_sum&models=ecmwf_ifs025&timezone=America%2FGuayaquil")
        pr = {}
        for loc in json.load(urllib.request.urlopen(url, timeout=180)):
            for t, v in zip(loc["daily"]["time"], loc["daily"]["precipitation_sum"]):
                if v is not None:
                    pr.setdefault(t, []).append(v)
        pares = [(sum(v) / len(v), lluvia[t]) for t, v in pr.items()
                 if t in lluvia and int(t[5:7]) in (8, 9, 10, 11, 12, 1)]
        if len(pares) > 100:
            sesgo = sum(x[1] for x in pares) / sum(x[0] for x in pares)
        print(f"Pronóstico ECMWF: la lluvia real es {sesgo:.2f} × la pronosticada ({len(pares)} días secos)")
    except Exception as e:
        print(f"Sesgo del pronóstico: {e}; se conserva {sesgo}")

    # 4) Paute según el día de la semana (últimas 26 semanas; lunes = 0)
    P7c = np.convolve(Ptot, np.ones(7) / 7, mode="same")
    wd = np.array([date.fromisoformat(d).weekday() for d in ds])
    rel = Ptot / np.where(P7c > 0, P7c, np.nan)
    rec = np.arange(n) > n - 182
    fd = np.array([np.nanmedian(rel[(wd == k) & rec]) for k in range(7)])
    fd = fd / fd.mean()

    # 5) Prueba retrospectiva con el despacho real conocido → rango de incertidumbre (caudal + física)
    clim = json.load(open(F_CLIM))
    doy = np.array([date.fromisoformat(d).timetuple().tm_yday for d in ds])

    def retro(i0, Hh=30):
        V = vol_mazar(c[i0 - 1] - 2115, a, b)
        pp = p.copy()
        for j in range(i0, min(n, i0 + Hh)):
            pp[j] = clim[doy[j] - 1]
        qq = q[i0 - 1]; out = []; hq = list(q[i0 - 30:i0])
        for j in range(i0, min(n, i0 + Hh)):
            qq = paso_caudal(coef_q, qq, np.mean(hq[-30:]), pp[j], pp[j - 1], pp[j - 2], np.mean(pp[j - 6:j - 2]),
                             np.mean(pp[j - 30:j - 6]))
            hq.append(qq)
            cc = 2115 + x_mazar(V, a, b)
            Qam = -(vol_amaluza(am[j]) - vol_amaluza(am[j - 1])) / 0.0864
            Qm = max(0.0, (Ptot[j] - k_ms * (beta * qq + Qam)) / (0.00981 * eta * (cc - am[j]) + k_ms))
            V += (qq - Qm) * 0.0864
            out.append(2115 + x_mazar(V, a, b))
        return out

    inicios = [i for i in range(40, n - 31, 2)
               if 2116 < c[i - 1] < 2150 and q[i - 1] < 60 and mes[i] in (7, 8, 9, 10, 11, 12, 1)]
    def medir(lista):
        cuant, metr, perc = {}, {}, {}
        for h in (7, 14, 21, 30):
            ratios, errs = [], []
            for i0 in lista:
                pr = retro(i0)
                if len(pr) < h:
                    continue
                real = c[i0 - 1 + h]
                errs.append(pr[h - 1] - real)
                caida_pred = c[i0 - 1] - pr[h - 1]
                if caida_pred > 1.0:
                    ratios.append((c[i0 - 1] - real) / caida_pred)
            if len(ratios) < 8:
                continue
            r25, r50, r75 = np.percentile(ratios, [25, 50, 75])
            cuant[str(h)] = [round(float(r25), 3), round(float(r75), 3)]
            # distribución completa (percentiles 5, 10, …, 95) para calcular probabilidades
            perc[str(h)] = [round(float(x), 3) for x in np.percentile(ratios, list(range(5, 100, 5)))]
            metr[str(h)] = {"error_medio_m": round(float(np.mean(np.abs(errs))), 2),
                            "sesgo_m": round(float(np.mean(errs)), 2), "mediana_real_vs_pred": round(float(r50), 2),
                            "casos": len(ratios)}
        return cuant, metr, perc
    cuant, metr, perc = medir(inicios)
    # Mismo análisis solo con fechas de caudal bajo (< 35 m³/s), como en las sequías de 2023 y 2024
    cuant_seco, metr_seco, perc_seco = medir([i for i in inicios if q[i - 1] < 35])
    print("Prueba retrospectiva (caudal bajo):", metr_seco)
    print("Prueba retrospectiva:", metr)

    # 6) Evaluación de las predicciones del robot: registro/verificacion.json compara cada predicción con la
    #    cota real de Celec Sur a la misma hora (lo llena el robot en cada corrida)
    aciertos = {}
    f_ver = os.path.join(RAIZ, "registro", "verificacion.json")
    if os.path.exists(f_ver):
        ver = json.load(open(f_ver, encoding="utf-8"))
        for h in sorted({v["h"] for v in ver}):
            errs = [v["err"] for v in ver if v["h"] == h]
            aciertos[str(h)] = {"n": len(errs), "dias": len({v["pred_ts"][:10] for v in ver if v["h"] == h}),
                                "error_medio_m": round(float(np.mean(np.abs(errs))), 2),
                                "sesgo_m": round(float(np.mean(errs)), 2)}
    par = {
        "calibrado": hoy.isoformat(),
        "historial": {"desde": ds[0], "hasta": ds[-1], "dias": n},
        "curva_mazar": {"a": round(a, 4), "b": round(b, 5)},
        "eficiencia_mazar": round(eta, 4),
        "k_molino_sopladora": round(k_ms, 3),
        "beta_cuenca_intermedia": round(beta, 4),
        "amaluza": {"piso": PISO_AMALUZA, "area": list(AREA_AMALUZA)},
        "caudal_coef": [round(x, 5) for x in coef_q],
        "sesgo_lluvia_pronostico": round(float(sesgo), 3),
        "factor_dia_semana_lun_dom": [round(float(x), 4) for x in fd],
        "rango_cuantiles": cuant,
        "retrospectiva": metr,
        "rango_cuantiles_caudal_bajo": cuant_seco,
        "ratios_percentiles": perc,
        "ratios_percentiles_caudal_bajo": perc_seco,
        "retrospectiva_caudal_bajo": metr_seco,
        "aciertos_registro": aciertos,
    }
    with open(F_PAR, "w", encoding="utf-8") as f:
        json.dump(par, f, ensure_ascii=False, indent=2)
    print("parametros_modelo.json actualizado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
