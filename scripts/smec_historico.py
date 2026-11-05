"""Historial diario del balance energético del Cenace (SMEC), para las pestañas de demanda por año, mes y día.

Luis (5 nov 2026) autorizó leer el SMEC con la misma función del robot (generacion.smec_dia, certificado autofirmado),
con una condición: validar los datos. Por eso cada mes se compara con la serie mensual oficial de energía neta del
Cenace (registro/referencias, bajada por HTTPS normal): si la suma de los días del SMEC se aparta más de TOLERANCIA,
el mes completo queda marcado "no_valido" y la página no lo usa. La verificación desactivada aplica SOLO a
smec.cenace.gob.ec; no se envía ninguna clave ni dato.

Uso: python scripts/smec_historico.py AAAA [AAAA2]   → historial/smec/<año>.json (un archivo por año)
     python scripts/smec_historico.py --validar        → marca cada mes como válido o no
"""
import json, os, re, sys, time, urllib.request
from datetime import date, timedelta

DIR = os.path.join("historial", "smec")
SMEC = "https://smec.cenace.gob.ec/SMEC/ResultadoInforme1.do?fecha="
REF = "https://raw.githubusercontent.com/jp1309/cenace-operacion/main/data/mensual_tecnologia.csv"   # serie mensual oficial del Cenace
TOLERANCIA = 0.03
UA = {"User-Agent": "Mozilla/5.0 (simulador-mazar-robot)"}
_CLAVES_DOC = {"Generación Hidráulica": "hidro", "Generación Vapor Bunker": "vapor", "Generación Turbinas a Gas": "gas",
          "Generación Turbinas a Diesel": "diesel", "Generación Motores Bunker": "motores", "Generación de Otros Tipos": "otros",
          "Total Generación": "total", "Importación de Colombia": "imp_col", "Exportación a Colombia": "exp_col",
          "Importación de Perú": "imp_peru", "Exportación a Perú": "exp_peru"}


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generacion import smec_dia   # misma lectura del SMEC que usa el robot cada día (cifrado y certificado incluidos)


def dia(d):
    """Balance del día en MW medios (como registro/balance_diario.json) más la demanda = generación + importación − exportación."""
    out = smec_dia(d)
    if not out:
        return None
    out["demanda"] = round(out["total"] + out.get("imp_col", 0) + out.get("imp_peru", 0) - out.get("exp_col", 0) - out.get("exp_peru", 0), 1)
    return out


def bajar(anio1, anio2):
    os.makedirs(DIR, exist_ok=True)
    for a in range(anio1, anio2 + 1):
        p = os.path.join(DIR, f"{a}.json")
        res = json.load(open(p)) if os.path.exists(p) else {"anio": a, "dias": {}, "fallas": []}
        d, fin = date(a, 1, 1), min(date(a, 12, 31), date.today() - timedelta(days=1))
        while d <= fin:
            k = d.isoformat()
            if k not in res["dias"]:
                for intento in range(3):
                    try:
                        x = dia(d)
                        if x: res["dias"][k] = x
                        else: res["fallas"].append(k)
                        break
                    except Exception:
                        time.sleep(5 * (intento + 1))
                else:
                    res["fallas"].append(k)
                time.sleep(0.3)
            d += timedelta(days=1)
        res["fallas"] = sorted(set(res["fallas"]) - set(res["dias"]))
        json.dump(res, open(p, "w"), separators=(",", ":"))
        print(f"{a}: {len(res['dias'])} días, {len(res['fallas'])} sin dato")


def validar():
    """Compara la generación total de cada mes del SMEC con la serie mensual oficial (energía neta, GWh)."""
    ref = {}
    with urllib.request.urlopen(urllib.request.Request(REF, headers=UA), timeout=60) as r:   # HTTPS verificado
        for l in r.read().decode("utf-8-sig").splitlines()[1:]:
            p = l.split(",")
            try: ref[f"{int(p[0])}-{int(p[1]):02d}"] = float(p[-1])
            except (ValueError, IndexError): pass
    resumen = {}
    for f in sorted(os.listdir(DIR)):
        if not re.fullmatch(r"\d{4}\.json", f): continue
        res = json.load(open(os.path.join(DIR, f)))
        meses = {}
        for k, v in res["dias"].items():
            meses.setdefault(k[:7], []).append(v["total"] * 24 / 1000.0)   # MW medios → GWh del día
        val = {}
        for m, xs in sorted(meses.items()):
            dias_mes = (date(int(m[:4]) + int(m[5:]) // 12, int(m[5:]) % 12 + 1, 1) - timedelta(days=1)).day
            gwh = sum(xs)
            r_ = ref.get(m)
            if len(xs) < dias_mes:
                estado = "incompleto"
            elif r_ is None:
                estado = "sin_referencia"
            else:
                estado = "valido" if abs(gwh - r_) / r_ <= TOLERANCIA else "no_valido"
            val[m] = {"dias": len(xs), "smec_gwh": round(gwh, 1), "oficial_gwh": round(r_, 1) if r_ else None,
                      "dif": round((gwh - r_) / r_, 4) if r_ else None, "estado": estado}
        res["validacion"] = val
        json.dump(res, open(os.path.join(DIR, f), "w"), separators=(",", ":"))
        resumen.update(val)
    from collections import Counter
    print("Validación:", dict(Counter(v["estado"] for v in resumen.values())))
    malos = {m: v for m, v in resumen.items() if v["estado"] == "no_valido"}
    for m, v in list(malos.items())[:30]: print("  no válido", m, v)


if __name__ == "__main__":
    if "--validar" in sys.argv: validar()
    else: bajar(int(sys.argv[1]), int(sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]))
