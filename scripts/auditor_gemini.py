"""Segundo auditor: Gemini propone un candidato nuevo para el laboratorio de Mazar (días alternos; Claude audita a diario).
Lee el manual del ciclo (laboratorio/GEMINI.md), las ideas de Luis (IDEAS.md), el marcador, el código del laboratorio y
del robot, y propone UNA función candidata. El script la valida (sin importaciones ni acceso a archivos/red, solo
cálculo sobre copias de P/ctx), la prueba con los datos de hoy y, si pasa, la deja lista en el repo para que el
workflow la suba a una rama candidato/gemini-<fecha>-<id>. Claude (auditor de las 14:36) la revisa con un Claude
independiente y la integra solo si los dos están de acuerdo. Nunca cambia el titular.
Salida: laboratorio/propuestas/AAAA-MM-DD.json (propuesta, validación y prueba) y, si pasa, el cambio en laboratorio.py."""
import ast, json, os, re, sys
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))
EC = timezone(timedelta(hours=-5))
MODELOS = ["gemini-4-argon", "gemini-3.8-flash"]
PERMITIDOS = {"min", "max", "abs", "round", "len", "range", "list", "dict", "float", "int", "sum", "enumerate", "zip", "sorted", "math", "None", "True", "False", "isinstance"}


def leer(p, n=60000):
    try:
        t = open(os.path.join(RAIZ, p), encoding="utf-8").read()
        return t if len(t) <= n else t[:n] + "\n…(recortado)"
    except Exception as e:
        return f"(no se pudo leer {p}: {e})"


def gemini(texto):
    import urllib.request, urllib.error, time
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key: return None, None
    cuerpo = json.dumps({"contents": [{"role": "user", "parts": [{"text": texto}]}],
                         "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4000}}).encode()
    for m in MODELOS:
        for i in range(3):
            if i: time.sleep(20 * i)
            try:
                req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", data=cuerpo,
                                             headers={"Content-Type": "application/json", "x-goog-api-key": key})
                with urllib.request.urlopen(req, timeout=240) as r:
                    d = json.load(r)
                return m, "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
            except urllib.error.HTTPError as e:
                print(m, "HTTP", e.code, file=sys.stderr)
                if e.code not in (500, 503): break
            except Exception as e:
                print(m, e, file=sys.stderr)
    return None, None


def validar(cid, codigo):
    """Solo se acepta una función pura: sin import, sin open/exec/eval, sin atributos especiales, sin red ni archivos."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", cid or ""): return "id inválido"
    arbol = ast.parse(codigo)
    if len(arbol.body) != 1 or not isinstance(arbol.body[0], ast.FunctionDef) or arbol.body[0].name != f"c_{cid}":
        return f"debe ser una sola función llamada c_{cid}"
    args = [a.arg for a in arbol.body[0].args.args]
    if args != ["P", "ctx", "mod"]: return "la firma debe ser (P, ctx, mod)"
    for n in ast.walk(arbol):
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.Lambda, ast.ClassDef, ast.AsyncFunctionDef, ast.With, ast.Try)):
            return f"no se permite {type(n).__name__}"
        if isinstance(n, ast.Attribute) and (n.attr.startswith("_") or n.attr in ("system", "popen", "remove", "write")):
            return f"atributo no permitido: {n.attr}"
        if isinstance(n, ast.Name) and n.id in ("open", "exec", "eval", "compile", "__import__", "globals", "locals", "getattr", "setattr", "os", "sys", "subprocess", "json"):
            return f"nombre no permitido: {n.id}"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id not in PERMITIDOS and n.func.id != f"c_{cid}":
            return f"función no permitida: {n.func.id}"
    return None


def probar(cid, codigo):
    import math, robot, laboratorio as L
    entorno = {"math": math, "__builtins__": {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
                                               for k in ("min", "max", "abs", "round", "len", "range", "list", "dict", "float", "int", "sum", "enumerate", "zip", "sorted", "isinstance")}}
    exec(compile(codigo, "candidato", "exec"), entorno)
    f = entorno[f"c_{cid}"]
    d = json.load(open(os.path.join(RAIZ, "datos.json"), encoding="utf-8")); m = d["modelo"]; hoy = d["hoy"]
    P = {"qMazar": hoy["qMazar"], "qCoca": hoy["qCoca"], "wPaute": "auto", "wCoca": "auto", "demanda": hoy["dBase"] + 50 * (hoy["tCosta"] - 32),
         "cut": hoy["cut"], "imp": hoy["imp"], "therm": hoy["therm"], "other": hoy["other"]}
    ctx = {"cota": d["cota"], "diaSemana0": m["diaSemana0"], "amaluzaCota": m["amaluzaCota"], "amaluzaRitmo": m["amaluzaRitmo"],
           "deltaDia": m["deltaDia"], "cutDias": m["cutDias"], "cutPlan": m.get("cutPlan"), "serieMazar": m["serieMazar"], "serieCoca": m["serieCoca"],
           "ccsFactor": m.get("ccsFactor"), "otrasRios": m.get("otrasRios"), "ajuste": m.get("ajuste"), "memoria": m.get("memoria")}
    P0, c0 = L._copia(P), L._copia(ctx)
    r = f(L._copia(P), L._copia(ctx), L._copia(m))
    if r is None: return {"ok": True, "nota": "devuelve None con los datos de hoy (no aplica hoy)"}
    if not (isinstance(r, tuple) and len(r) == 3 and isinstance(r[2], dict)): return {"ok": False, "nota": "debe devolver (P, ctx, cambios_mod) o None"}
    dt, _ = robot.simular_py(P0, c0, m, horizonte=14)
    dc, _ = robot.simular_py(r[0], r[1], m, horizonte=14)
    v = [round(x["cota"], 2) for x in dc]
    if not all(2090 <= x <= 2160 for x in v): return {"ok": False, "nota": f"cotas fuera de rango: {v}"}
    return {"ok": True, "titular_1_7_14": [round(dt[h]["cota"], 2) for h in (1, 7, 14)], "candidato_1_7_14": [v[1], v[7], v[14]],
            "cambios_mod": sorted(r[2].keys())}


def main():
    hoy = datetime.now(EC).date().isoformat()
    import laboratorio as L
    existentes = sorted(L.CANDIDATOS)
    texto = (leer("laboratorio/GEMINI.md") + "\n\n# TU PAPEL HOY: SEGUNDO AUDITOR (PROPONES, NO REVISAS)\n"
             "Propón UN candidato nuevo para el laboratorio de Mazar que pueda acercar el error típico a 1 día a 5 cm (meta de Luis) "
             "sin empeorar a 7 y 14 días. Básate en el marcador (dónde y cuándo falla el titular, importancia_1d), en las ideas de "
             "Luis (IDEAS.md) y en cómo el robot arma P y ctx. No repitas candidatos existentes: " + ", ".join(existentes) + ".\n"
             "Reglas del código: una sola función `def c_<id>(P, ctx, mod):` que modifica SOLO sus argumentos (ya son copias) y "
             "devuelve (P, ctx, cambios_mod) o None si hoy no aplica; cambios_mod = campos de datos.json que la página necesitaría "
             "para hacer el mismo cálculo (normalmente los mismos que cambias en ctx). Sin import, sin archivos, sin red; solo "
             "aritmética, min/max/abs/round/len/range/list/dict/sum/sorted/enumerate/zip/isinstance y math. Nada de datos del futuro.\n"
             "Responde SOLO con JSON: {\"id\": \"snake_case\", \"hipotesis\": \"una frase medible\", \"promocion\": \"auto|luis\", "
             "\"por_que\": \"2-4 frases con los datos que te llevaron a esta idea\", \"codigo\": \"def c_<id>(P, ctx, mod): ...\"} "
             "o {\"id\": null, \"por_que\": \"...\"} si hoy no hay una idea que valga la pena.\n\n"
             "# IDEAS.md\n" + leer("laboratorio/IDEAS.md", 8000) + "\n\n# marcador.json\n" + leer("laboratorio/marcador.json", 25000)
             + "\n\n# scripts/laboratorio.py\n```python\n" + leer("scripts/laboratorio.py", 40000) + "\n```\n\n# scripts/robot.py (cómo se arman P y ctx)\n```python\n"
             + leer("scripts/robot.py", 90000) + "\n```")
    modelo, resp = gemini(texto)
    reg = {"fecha": hoy, "modelo": modelo}
    os.makedirs(os.path.join(RAIZ, "laboratorio", "propuestas"), exist_ok=True)
    out = os.path.join(RAIZ, "laboratorio", "propuestas", hoy + ".json")
    if not resp:
        reg["estado"] = "gemini no respondió"; json.dump(reg, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print(reg); return
    try:
        p = json.loads(re.search(r"\{.*\}", resp, re.S).group(0))
    except Exception as e:
        reg.update({"estado": "respuesta sin JSON", "crudo": resp[:3000]}); json.dump(reg, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print(reg); return
    reg["propuesta"] = p
    cid = p.get("id")
    if not cid:
        reg["estado"] = "sin propuesta hoy"
    elif cid in L.CANDIDATOS:
        reg["estado"] = "ya existe"
    else:
        err = validar(cid, p.get("codigo", ""))
        if err:
            reg["estado"] = "rechazada por validación: " + err
        else:
            try:
                prueba = probar(cid, p["codigo"])
            except Exception as e:
                prueba = {"ok": False, "nota": f"error al probar: {e}"}
            reg["prueba"] = prueba
            if not prueba.get("ok"):
                reg["estado"] = "rechazada en la prueba"
            else:
                reg["estado"] = "lista para revisión de Claude"
                s = open(os.path.join(RAIZ, "scripts", "laboratorio.py"), encoding="utf-8").read()
                cand = (p["codigo"].rstrip() + "\n\n\n")
                ent = (f'CANDIDATOS["{cid}"] = {{"f": c_{cid}, "promocion": {json.dumps("luis" if p.get("promocion") == "luis" else "auto")}, '
                       f'"origen": "Gemini {hoy}", "hipotesis": {json.dumps(p.get("hipotesis", ""), ensure_ascii=False)}}}\n\n\n')
                s = s.replace("\ndef aplicar_titular(", "\n" + cand + ent + "def aplicar_titular(", 1)
                open(os.path.join(RAIZ, "scripts", "laboratorio.py"), "w", encoding="utf-8").write(s)
                reg["rama"] = f"candidato/gemini-{hoy}-{cid}"
    json.dump(reg, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(reg, ensure_ascii=False, indent=1)[:4000])
    if reg.get("rama"):
        open(os.path.join(RAIZ, ".rama_candidato"), "w").write(reg["rama"])


if __name__ == "__main__":
    main()
