"""Señal de "riesgo de corte esta noche" EN SOMBRA (Luis 25 nov 2026, tras el apagón del lunes 23 nov 20:34).

Lección del 23 nov: el apagón no fue por falta de agua en Mazar, sino porque centrales que gastan su reserva del día
(Coca Codo con su embalse compensador, Molino con Amaluza bajo su mínimo) no aguantaron el pico de la noche y Colombia
no estaba vendiendo. Esta señal mira, una vez al día entre las 16:00 y las 18:00 (antes del pico de 19–21 h), cuatro cosas:

  S1 Coca Codo sin río para el pico: con el caudal de ahora el río solo da < 800 MW (el pico pide ~950 MW) o en las
     últimas 3 h generó más de 100 MW por encima de lo que da su río (está gastando el compensador).
  S2 Amaluza bajo su mínimo operativo (1.971,3 m): Molino no tiene reserva.
  S3 Demanda alta: el pico de anoche (18–22 h) fue ≥ 5.100 MW.
  S4 Sin Colombia: no está entrando energía de Colombia (0 MW en la última hora).

Nivel: 0–1 señales = bajo, 2 = medio, 3–4 = alto. Umbrales CONGELADOS el 2026-11-25; no se ajustan solos.
No se muestra en la página ni avisa a nadie: se guarda en registro/riesgo_noche.json y al día siguiente se verifica con
la demanda del Cenace si hubo alivio de carga (una caída ≥ 350 MW en media hora entre 19:00 y 23:30 y, a las 21:30,
≥ 400 MW menos que la noche anterior a la misma hora; se verifica cuando ya está el dato de las 23:30, hasta 3 días
después). Se evalúa con ≥ 20 noches (contar NOCHES).
"""
import json, os, statistics
from datetime import datetime, timedelta, timezone

EC = timezone(timedelta(hours=-5))
CONGELADO = "2026-11-25"
U = {"rio_mw_min": 800, "exceso_mw": 100, "amaluza_min": 1971.3, "pico_mw": 5100,
     "caida_30min": 350, "caida_vs_ayer_2130": 400}
F = os.path.join("registro", "riesgo_noche.json")


def leer(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def rio_mw(q):   # lo que puede dar el río Coca (misma fórmula que la página: ~5,25 MW por m³/s sobre el caudal ecológico)
    return max(0.0, min(1200.0, 5.25 * (q - 21)))


def puntos_demanda():
    G = leer(os.path.join("registro", "generacion.json"), {}) or {}
    out = {}
    for p in G.get("puntos") or []:
        if len(p) >= 7 and p[6] is not None:
            out[p[0]] = (p[6], p[4])   # clave "AAAA-MM-DDTHH:MM" (hora Ecuador): (demanda, importación)
    return out


def predecir(ahora):
    rio = leer(os.path.join("registro", "coca_rio.json"), {}) or {}
    tur = leer(os.path.join("registro", "ccs_turbinado.json"), {}) or {}
    ks = [k for k in sorted(rio) if k <= ahora.strftime("%Y-%m-%dT%H")][-3:]
    q = rio[ks[-1]] if ks else None
    exceso = [tur[k] * 8 * 5.25 - rio_mw(rio[k]) for k in ks if k in tur and rio.get(k) is not None]
    ex = round(sum(exceso) / len(exceso)) if exceso else None
    amal = ((leer("datos.json", {}) or {}).get("modelo") or {}).get("amaluzaCota")
    P = puntos_demanda()
    ayer = (ahora.date() - timedelta(days=1)).isoformat()
    pico = max([v[0] for k, v in P.items() if k.startswith(ayer) and "18:00" <= k[11:16] <= "22:00"], default=None)
    ult = [P[k][1] for k in sorted(P) if k <= ahora.strftime("%Y-%m-%dT%H:%M")][-2:]
    s = {"S1_coca": None if q is None else bool(rio_mw(q) < U["rio_mw_min"] or (ex is not None and ex > U["exceso_mw"])),
         "S2_amaluza": None if amal is None else bool(amal < U["amaluza_min"]),
         "S3_demanda": None if pico is None else bool(pico >= U["pico_mw"]),
         "S4_sin_colombia": None if not ult else bool(all((x or 0) <= 0 for x in ult))}
    n = sum(1 for v in s.values() if v)
    return {"hecha": ahora.isoformat(timespec="minutes"), "antes_del_evento": ahora.hour < 19, "congelado": CONGELADO,
            "senales": s, "n": n, "nivel": "alto" if n >= 3 else "medio" if n == 2 else "bajo",
            "datos_de": {"coca": ks[-1] if ks else None, "cenace": max([k for k in P if k <= ahora.strftime("%Y-%m-%dT%H:%M")], default=None)},
            "valores": {"rio_coca_m3s": q, "rio_da_mw": None if q is None else round(rio_mw(q)), "exceso_coca_3h_mw": ex,
                        "amaluza_m": amal, "pico_anoche_mw": pico, "colombia_ultima_hora_mw": ult}}


def verificar(dia, P):
    """¿Hubo alivio de carga esa noche? Necesita la demanda de esa noche y de la anterior (generacion.json guarda ~3 días)."""
    serie = sorted((k[11:16], v[0]) for k, v in P.items() if k.startswith(dia) and "19:00" <= k[11:16] <= "23:30")
    if not serie or serie[-1][0] != "23:30":   # revisor: esperar a tener la noche completa
        return None
    mins = lambda h: int(h[:2]) * 60 + int(h[3:])
    previo = (datetime.fromisoformat(dia) - timedelta(days=1)).date().isoformat()
    a2130, p2130 = P.get(dia + "T21:30"), P.get(previo + "T21:30")
    if len(serie) < 8 or not a2130 or not p2130:
        return None
    caida = max((a[1] - b[1] for a, b in zip(serie, serie[1:]) if mins(b[0]) - mins(a[0]) == 30), default=0)   # solo pares a 30 min
    vs_ayer = p2130[0] - a2130[0]
    return {"caida_max_30min_mw": round(caida), "menos_que_ayer_2130_mw": round(vs_ayer),
            "alivio_de_carga": bool(caida >= U["caida_30min"] and vs_ayer >= U["caida_vs_ayer_2130"])}


def main(ahora=None):
    ahora = ahora or datetime.now(EC)
    R = leer(F, {}) or {}
    if not isinstance(R, dict): R = {}   # revisor: un archivo dañado no debe apagar la señal para siempre
    hoy = ahora.date().isoformat()
    if hoy not in R and 16 <= ahora.hour < 18:
        R[hoy] = {"prediccion": predecir(ahora)}
        print("riesgo de corte esta noche (sombra):", R[hoy]["prediccion"]["nivel"], R[hoy]["prediccion"]["senales"])
    P = puntos_demanda()
    for dia, r in R.items():
        if dia < hoy and "verificacion" not in r:
            v = verificar(dia, P)
            if v:
                cd = ((leer("datos.json", {}) or {}).get("manual") or {})
                v["corte_programado_mw"] = ((cd.get("cortes_registro") or {}).get(dia, (cd.get("cortes_plan") or {}).get(dia)))   # para separar racionamientos
                r["verificacion"] = v
    os.makedirs("registro", exist_ok=True)
    try:
        with open(F + ".tmp", "w", encoding="utf-8") as fo:
            json.dump(dict(sorted(R.items())[-400:]), fo, ensure_ascii=False, indent=1)
        os.replace(F + ".tmp", F)
    finally:
        if os.path.exists(F + ".tmp"): os.remove(F + ".tmp")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # nunca tumba al robot
        print("riesgo_noche:", e)
