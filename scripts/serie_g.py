"""Serie R · análisis por grupos G1 / G2 / G3 (1981–2026) contra la lluvia diaria CHIRPS de cada ciudad.

Datos: rama serie-r (r/g_*: rejilla por punto; r/s_*: series de superficie por punto; r/mjo.txt) y historial/chirps_diario.json.
Todo en ANOMALÍAS: cada variable menos su promedio de (ciudad, mes) en los años de entrenamiento, dividido por su desvío;
así el ciclo anual no se cuela como "importancia". La lluvia: "día fuerte" = ≥ percentil 90 de esa ciudad y mes (y ≥ 1 mm).
Validación: se aprende con 1981–2010 y se mide con 2011–2026 (fuera de muestra). Intervalos con bootstrap por AÑOS (las
ciudades del mismo día y los días del mismo año no son independientes). Comparaciones múltiples: Benjamini-Hochberg.
Ojo: ERA5 es reanálisis (lo que pasó ese día), no pronóstico: dice qué ingredientes acompañan a la lluvia, no cuánto se
puede anticipar. Lo que salga se congela y se prueba en sombra.
Uso: SERIE_DATOS=<checkout de serie-r> python3 scripts/serie_g.py [--salida r/analisis_g.json]"""
import gzip, json, math, os, subprocess, sys
from datetime import date, timedelta

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.environ.get("SERIE_DATOS") or os.path.join(AQUI, "..", "_serie_r")
RAIZ = os.path.join(AQUI, "..")

REGIONES = {
    "Costa": ["Guayaquil", "Durán", "Samborondón", "Daule/Nobol", "Esmeraldas", "Santo Domingo", "Quevedo", "Babahoyo", "Portoviejo",
              "Manta", "Santa Elena", "Machala", "Milagro", "Bahía de Caráquez", "Piñas"],
    "Sierra": ["Quito", "Ibarra", "Tulcán", "Ambato", "Latacunga", "Riobamba", "Guaranda", "Cuenca", "Paute/Mazar", "Gualaceo", "Azogues", "Loja"],
    "Amazonía": ["Macas", "Puyo", "Tena", "El Coca", "Nueva Loja", "Coca Codo/El Chaco", "Zamora"],
    "Galápagos": ["Puerto Ayora", "Puerto Baquerizo Moreno", "Puerto Villamil"],
}
# Grupos (nombres neutros). Variable: (origen, punto, clave/función). "c" = la propia ciudad.
G = {
    "G1": ["tcwv", "cape_max", "cin_min", "hr850", "hr700", "hr500", "suelo", "lcc", "td2", "t2_max", "sol_man", "lhf",
           "sst_golfo", "sst_golfo_menos_humboldt", "sst_galapagos", "tcwv_choco", "tcwv_amazonia", "tcwv_galapagos"],
    "G3": ["w500_t", "w500_d", "w700_t", "w850_t", "conv850_t", "blh_max", "zc81_max", "zc81_lat", "u850_81o", "u850_choco",
           "v850_choco", "u850_golfo"],
    "G2": ["div200_t", "div200_d", "viento200", "u200", "u200_galapagos", "u200_amazonia", "mjo_amp", "mjo_rmm1", "mjo_rmm2",
           "msl_anticiclon", "grad_anticiclon"],
}
ENTRENA = (1981, 2010)
PRUEBA = (2011, 2026)


def git_json(rel):
    try:
        b = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=DATOS, capture_output=True, check=True).stdout
    except Exception:
        b = open(os.path.join(DATOS, rel), "rb").read()
    return json.loads(gzip.decompress(b) if rel.endswith(".gz") else b)


def archivos():
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD", "r/"], cwd=DATOS, capture_output=True, text=True).stdout.split()
    return out or sorted("r/" + f for f in os.listdir(os.path.join(DATOS, "r")))


def cargar():
    chirps = json.load(open(os.path.join(RAIZ, "historial", "chirps_diario.json"), encoding="utf-8"))["ciudades"]
    ciudades = [c for v in REGIONES.values() for c in v if c in chirps]
    d0, d1 = date(1981, 1, 1), date(2026, 10, 31)
    dias = [d0 + timedelta(n) for n in range((d1 - d0).days + 1)]
    di = {d.isoformat(): i for i, d in enumerate(dias)}
    nombres = [v for g in G.values() for v in g]
    vi = {v: i for i, v in enumerate(nombres)}
    X = np.full((len(ciudades), len(dias), len(nombres)), np.nan, dtype=np.float32)
    Y = np.full((len(ciudades), len(dias)), np.nan, dtype=np.float32)
    for a, c in enumerate(ciudades):
        for k, v in chirps[c].items():
            if k in di and v is not None: Y[a, di[k]] = v
    # rejilla por punto (s: superficie; p: niveles), puntos x_* comunes a todas las ciudades
    comun = {}   # (var, i_dia) -> valor
    lista = archivos()
    for rel in [f for f in lista if f.startswith("r/g_")]:
        d = git_json(rel)["dias"]
        for k, pts in d.items():
            i = di.get(k)
            if i is None: continue
            xc, xa, xg, xo, xg2 = (pts.get(n) or {} for n in ("x_choco", "x_amazonia", "x_galapagos", "x_81o", "x_golfo"))
            z = pts.get("x_z81") or {}
            for nom, val in (("tcwv_choco", xc.get("tcwv")), ("tcwv_amazonia", xa.get("tcwv")), ("tcwv_galapagos", xg.get("tcwv")),
                             ("u850_81o", _m(xo, "u850")), ("u850_choco", _m(xc, "u850")), ("v850_choco", _m(xc, "v850")),
                             ("u850_golfo", _m(xg2, "u850")), ("u200_galapagos", _m(xg, "u200")), ("u200_amazonia", _m(xa, "u200"))):
                if val is not None: comun[(nom, i)] = val
            if z:
                sur = {float(kk[1:]): vv for kk, vv in z.items() if -4.0 <= float(kk[1:]) <= -0.5 and vv is not None}
                if sur:
                    la = max(sur, key=sur.get); comun[("zc81_max", i)] = sur[la]; comun[("zc81_lat", i)] = la
            for a, c in enumerate(ciudades):
                p = pts.get(c)
                if not p: continue
                for k2, v2 in p.items():
                    if k2 in vi and v2 is not None: X[a, i, vi[k2]] = v2
                for nom, val in (("hr850", _m(p, "hr850")), ("hr700", _m(p, "hr700")), ("hr500", _m(p, "hr500")),
                                 ("u200", _m(p, "u200"))):
                    if val is not None: X[a, i, vi[nom]] = val
                for k2 in ("w500_t", "w500_d", "w700_t", "w850_t", "div200_t", "div200_d"):
                    if p.get(k2) is not None: X[a, i, vi[k2]] = p[k2]
                if p.get("div850_t") is not None: X[a, i, vi["conv850_t"]] = -p["div850_t"]
                if p.get("u200_t") is not None and p.get("v200_t") is not None:
                    X[a, i, vi["viento200"]] = math.hypot(p["u200_t"], p["v200_t"])
    # series de superficie por punto
    def serie(pto):
        rel = "r/s_" + pto.replace("/", "-").replace(" ", "_") + ".json.gz"
        return git_json(rel)["dias"] if rel in lista else {}
    S = {p: serie(p) for p in ("x_golfo", "x_humboldt", "x_galapagos", "x_anticiclon")}
    for k, i in di.items():
        g_, h_, ga, an = (S[p].get(k) or {} for p in ("x_golfo", "x_humboldt", "x_galapagos", "x_anticiclon"))
        if g_.get("sst") is not None:
            comun[("sst_golfo", i)] = g_["sst"]
            if h_.get("sst") is not None: comun[("sst_golfo_menos_humboldt", i)] = g_["sst"] - h_["sst"]
        if ga.get("sst") is not None: comun[("sst_galapagos", i)] = ga["sst"]
        if an.get("msl") is not None: comun[("msl_anticiclon", i)] = an["msl"]
    for a, c in enumerate(ciudades):
        sc = serie(c)
        for k, v in sc.items():
            i = di.get(k)
            if i is None: continue
            for k2 in ("td2", "t2_max", "sol_man", "lhf", "blh_max"):
                if v.get(k2) is not None: X[a, i, vi[k2]] = v[k2]
            if v.get("msl") is not None and ("msl_anticiclon", i) in comun:
                X[a, i, vi["grad_anticiclon"]] = comun[("msl_anticiclon", i)] - v["msl"]
    # MJO
    try:
        for ln in subprocess.run(["git", "show", "HEAD:r/mjo.txt"], cwd=DATOS, capture_output=True, text=True).stdout.splitlines()[2:]:
            p = ln.split()
            if len(p) < 7: continue
            k = f"{int(p[0]):04d}-{int(p[1]):02d}-{int(p[2]):02d}"
            if k in di and float(p[6]) < 100:
                comun[("mjo_amp", di[k])] = float(p[6]); comun[("mjo_rmm1", di[k])] = float(p[3]); comun[("mjo_rmm2", di[k])] = float(p[4])
    except Exception: pass
    for (nom, i), val in comun.items(): X[:, i, vi[nom]] = val
    return ciudades, dias, nombres, X, Y


def _m(p, base):
    a, b = p.get(base + "_d"), p.get(base + "_t")
    return a if b is None else (b if a is None else (a + b) / 2)


def anomalias(X, Y, dias):
    """Anomalía estandarizada por (ciudad, mes) con la climatología de los años de entrenamiento; 'día fuerte' por (ciudad, mes)."""
    mes = np.array([d.month for d in dias]); anio = np.array([d.year for d in dias])
    tr = (anio >= ENTRENA[0]) & (anio <= ENTRENA[1])
    Z = np.full_like(X, np.nan); F = np.zeros(Y.shape, dtype=bool); V = np.isfinite(Y)
    for m in range(1, 13):
        sel = mes == m; st = sel & tr
        mu = np.nanmean(X[:, st, :], axis=1, keepdims=True); sd = np.nanstd(X[:, st, :], axis=1, keepdims=True)
        sd[~np.isfinite(sd) | (sd == 0)] = np.nan
        Z[:, sel, :] = (X[:, sel, :] - mu) / sd
        p90 = np.nanpercentile(Y[:, st], 90, axis=1, keepdims=True)
        F[:, sel] = (Y[:, sel] >= np.maximum(p90, 1.0))
    return Z, F, V, anio, mes


def auc(s, y):
    ok = np.isfinite(s); s, y = s[ok], y[ok]
    n1, n0 = y.sum(), (~y).sum()
    if n1 == 0 or n0 == 0: return float("nan")
    r = np.argsort(np.argsort(s)) + 1.0
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def logit(Xm, y, l2=1.0, it=25):
    """Logística con regularización L2 (IRLS). Xm sin NaN, con columna de 1."""
    w = np.zeros(Xm.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(Xm @ w, -30, 30)))
        g = Xm.T @ (p - y) + l2 * np.r_[0, w[1:]]
        H = (Xm * (p * (1 - p))[:, None]).T @ Xm + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)])
        try: w -= np.linalg.solve(H, g)
        except np.linalg.LinAlgError: break
    return w


def bh(ps):
    ps = np.asarray(ps, float); n = np.isfinite(ps).sum(); o = np.argsort(ps); q = np.full_like(ps, np.nan); prev = 1.0
    for rank, i in reversed(list(enumerate(o, 1))):
        if not np.isfinite(ps[i]): continue
        prev = min(prev, ps[i] * n / rank); q[i] = prev
    return q


def analizar(ciudades, dias, nombres, X, Y, rnd=np.random.default_rng(7), nboot=100):
    Z, F, V, anio, mes = anomalias(X, Y, dias)
    vi = {v: i for i, v in enumerate(nombres)}
    anios = np.arange(1981, 2027)
    out = {"definiciones": {"grupos": G, "regiones": REGIONES, "entrena": ENTRENA, "prueba": PRUEBA,
                            "dia_fuerte": "≥ percentil 90 de la ciudad y el mes (1981–2010) y ≥ 1 mm"}, "regiones": {}}
    for reg, lista in REGIONES.items():
        ci = [ciudades.index(c) for c in lista if c in ciudades]
        for temporada, meses in (("todo", range(1, 13)), ("ene-may", range(1, 6)), ("jun-dic", range(6, 13))):
            sm = np.isin(mes, list(meses))
            filas = [(a, i) for a in ci for i in np.where(sm)[0]]
            A = np.array([a for a, _ in filas]); I = np.array([i for _, i in filas])
            y = F[A, I]; ok = V[A, I]; Zr = Z[A, I, :]; yr = anio[I]
            tr = ok & (yr <= ENTRENA[1]); te = ok & (yr >= PRUEBA[0])
            R = {"filas": int(ok.sum()), "dias": int(len(set(I[ok]))), "tasa_dia_fuerte": round(float(y[ok].mean()), 3), "variables": {}, "grupos": {}}
            # 1) cada variable: AUC fuera de muestra (signo aprendido en entrenamiento), IC90 por años, p por permutación de años
            ps = []
            for v in nombres:
                j = vi[v]; s = Zr[:, j]
                a_tr = auc(s[tr], y[tr])
                if not np.isfinite(a_tr): ps.append(np.nan); continue
                sg = 1 if a_tr >= 0.5 else -1
                a_te = auc(sg * s[te], y[te])
                yt = yr[te]; ss = sg * s[te]; yy = y[te]; bo = []
                uy = np.unique(yt); idx = {u: np.where(yt == u)[0] for u in uy}
                for _ in range(nboot):
                    k = np.concatenate([idx[u] for u in rnd.choice(uy, len(uy))]); bo.append(auc(ss[k], yy[k]))
                bo = np.array([b for b in bo if np.isfinite(b)])
                # p: proporción de remuestreos con AUC ≤ 0,5 (unilateral, por años)
                p = float(((bo <= 0.5).sum() + 1) / (len(bo) + 1))
                ps.append(p)
                R["variables"][v] = {"grupo": next(g for g, l in G.items() if v in l), "signo": sg, "auc_entrena": round(max(a_tr, 1 - a_tr), 3),
                                     "auc_prueba": round(a_te, 3), "ic90": [round(float(np.percentile(bo, 5)), 3), round(float(np.percentile(bo, 95)), 3)],
                                     "p": round(p, 4)}
            q = bh(ps)
            for v, qq in zip(nombres, q):
                if v in R["variables"]: R["variables"][v]["q_bh"] = None if not np.isfinite(qq) else round(float(qq), 4)
            # 2) cada grupo: logística con sus variables (entrena 1981–2010) → AUC 2011–2026; quitar-una para ver qué pesa
            def ajuste(cols, devolver=False):
                Xm = Zr[:, cols]; okc = np.all(np.isfinite(Xm), axis=1)
                a, b = tr & okc, te & okc
                if a.sum() < 500 or b.sum() < 200: return None
                w = logit(np.c_[np.ones(a.sum()), Xm[a]], y[a].astype(float))
                s = np.c_[np.ones(b.sum()), Xm[b]] @ w
                r = auc(s, y[b])
                return (r, w, b, s) if devolver else r
            for g, vs in G.items():
                cols = [vi[v] for v in vs if v in R["variables"] and R["variables"][v]["auc_entrena"] >= 0.52]
                if not cols: continue
                res = ajuste(cols, True)
                if not res: continue
                base, w, b, s = res
                quita = {}
                for c in cols:
                    r2 = ajuste([x for x in cols if x != c])
                    if r2 is not None: quita[nombres[c]] = round(base - r2, 4)
                R["grupos"][g] = {"auc_prueba": round(base, 3), "variables_usadas": [nombres[c] for c in cols],
                                  "peso_al_quitar": dict(sorted(quita.items(), key=lambda kv: -kv[1])),
                                  "coef": {nombres[c]: round(float(x), 3) for c, x in zip(cols, w[1:])}}
            # 3) los tres juntos y su interacción: puntaje de cada grupo en tercios → tasa de días fuertes por combinación
            pun = {}
            for g in G:
                if g not in R["grupos"]: continue
                cols = [vi[v] for v in R["grupos"][g]["variables_usadas"]]; Xm = Zr[:, cols]; okc = np.all(np.isfinite(Xm), axis=1)
                a = tr & okc
                w = logit(np.c_[np.ones(a.sum()), Xm[a]], y[a].astype(float))
                sc = np.full(len(y), np.nan); sc[okc] = np.c_[np.ones(okc.sum()), Xm[okc]] @ w
                pun[g] = sc
            if len(pun) == 3:
                todo = np.all([np.isfinite(pun[g]) for g in pun], axis=0)
                cols3 = np.c_[[pun[g] for g in ("G1", "G2", "G3")]].T
                a, b = tr & todo, te & todo
                w3 = logit(np.c_[np.ones(a.sum()), cols3[a]], y[a].astype(float))
                inter = np.c_[cols3, cols3[:, 0] * cols3[:, 1], cols3[:, 0] * cols3[:, 2], cols3[:, 1] * cols3[:, 2], cols3.prod(axis=1)]
                w4 = logit(np.c_[np.ones(a.sum()), inter[a]], y[a].astype(float))
                R["juntos"] = {"auc_suma": round(auc(np.c_[np.ones(b.sum()), cols3[b]] @ w3, y[b]), 3),
                               "auc_con_interaccion": round(auc(np.c_[np.ones(b.sum()), inter[b]] @ w4, y[b]), 3),
                               "coef_suma": dict(zip(("G1", "G2", "G3"), [round(float(x), 3) for x in w3[1:]]))}
                cortes = {g: np.nanpercentile(pun[g][a], [33.3, 66.7]) for g in pun}
                nivel = {g: np.digitize(pun[g], cortes[g]) for g in pun}   # 0 bajo, 1 medio, 2 alto
                tabla = {}
                for k1 in (0, 2):
                    for k2 in (0, 2):
                        for k3 in (0, 2):
                            m = te & todo & (nivel["G1"] == k1) & (nivel["G2"] == k2) & (nivel["G3"] == k3)
                            if m.sum() >= 50:
                                tabla[f"G1{'+' if k1 else '-'} G2{'+' if k2 else '-'} G3{'+' if k3 else '-'}"] = {"tasa": round(float(y[m].mean()), 3), "n": int(m.sum())}
                R["juntos"]["tercios_prueba"] = tabla
            # 4) veto: con ≥ 60 % de las otras variables del grupo del lado favorable, ¿cuánto baja la tasa si esta está en su tercio bajo?
            veto = {}
            for g, vs in G.items():
                usadas = [v for v in vs if v in R["variables"] and R["variables"][v]["auc_entrena"] >= 0.55]
                if len(usadas) < 3: continue
                S = np.c_[[R["variables"][v]["signo"] * Zr[:, vi[v]] for v in usadas]].T
                for k, v in enumerate(usadas):
                    otras = np.delete(S, k, axis=1)
                    fav = (np.nansum(otras > 0, axis=1) >= 0.6 * otras.shape[1]) & ok
                    lo, hi = fav & (S[:, k] < -0.43), fav & (S[:, k] > 0.43)
                    if lo.sum() < 200 or hi.sum() < 200: continue
                    t_lo, t_hi = float(y[lo].mean()), float(y[hi].mean())
                    bo = []
                    uy = np.unique(yr); idl = {u: np.where(lo & (yr == u))[0] for u in uy}; idh = {u: np.where(hi & (yr == u))[0] for u in uy}
                    for _ in range(200):
                        ss = rnd.choice(uy, len(uy)); kl = np.concatenate([idl[u] for u in ss]); kh = np.concatenate([idh[u] for u in ss])
                        if len(kl) and len(kh) and y[kh].mean() > 0: bo.append(1 - y[kl].mean() / y[kh].mean())
                    veto[v] = {"grupo": g, "tasa_tercio_bajo": round(t_lo, 3), "tasa_tercio_alto": round(t_hi, 3),
                               "baja_relativa": round(1 - t_lo / t_hi, 3) if t_hi > 0 else None,
                               "ic90": [round(float(np.percentile(bo, 5)), 3), round(float(np.percentile(bo, 95)), 3)] if bo else None,
                               "n_bajo": int(lo.sum()), "n_alto": int(hi.sum())}
            R["veto"] = dict(sorted(veto.items(), key=lambda kv: -(kv[1]["baja_relativa"] or 0)))
            out["regiones"].setdefault(reg, {})[temporada] = R
            print(f"{reg} {temporada}: {R['filas']} filas; grupos " + ", ".join(f"{g} {x['auc_prueba']}" for g, x in R["grupos"].items())
                  + (f"; juntos {R['juntos']['auc_suma']} / con interacción {R['juntos']['auc_con_interaccion']}" if "juntos" in R else ""), flush=True)
    return out


if __name__ == "__main__":
    sal = sys.argv[sys.argv.index("--salida") + 1] if "--salida" in sys.argv else None
    c, d, n, X, Y = cargar()
    print(f"cargado: {len(c)} ciudades × {len(d)} días × {len(n)} variables; con dato {np.isfinite(X).mean():.0%}", flush=True)
    for v in n:
        f = np.isfinite(X[:, :, n.index(v)]).mean()
        if f < 0.5: print(f"  ojo: {v} con dato en {f:.0%}", flush=True)
    r = analizar(c, d, n, X, Y)
    if sal:
        os.makedirs(os.path.dirname(sal) or ".", exist_ok=True)
        json.dump(r, open(sal, "w"), ensure_ascii=False, indent=1)
