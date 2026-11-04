"""Revisor Gemini: le envía a Gemini (API) el manual de contexto, el código del laboratorio, el cambio propuesto y los
marcadores, y deja su veredicto como comentario en el commit. Uso en GitHub Actions (secreto GEMINI_API_KEY):
  python revisor_gemini.py --manual laboratorio/GEMINI.md --base origin/main --archivos a.py b.json ...
  python revisor_gemini.py --prueba      (solo comprueba que la llave y el modelo funcionan)
Modelos: primero gemini-4-argon; si falla, gemini-3.8-flash."""
import argparse, json, os, subprocess, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gasto_gemini as GG

MODELOS = ["gemini-4-argon", "gemini-3.8-flash"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
MAX_CHARS = 220000
MODELOS_SALTAR = set()   # cuota agotada o modelo no disponible: no reintentar   # tope de contexto por revisión (controla el costo)


def preguntar(texto):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("Falta el secreto GEMINI_API_KEY")
    cuerpo = json.dumps({"contents": [{"role": "user", "parts": [{"text": texto}]}],
                         "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2500}}).encode()
    ultimo = None
    lista = GG.modelos(MODELOS)
    if not lista:
        return None, "(Gemini no revisó: tope de gasto del mes alcanzado; decide el revisor Claude)", {}
    for m, intento in [(m, i) for m in lista for i in range(3)]:
        if m in MODELOS_SALTAR:
            continue
        if intento:
            time.sleep(20 * intento)   # 503 = mucha demanda: esperar y reintentar
        req = urllib.request.Request(URL.format(m=m), data=cuerpo,
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            partes = d["candidates"][0]["content"]["parts"]
            uso = d.get("usageMetadata", {})
            GG.anotar("revisor", m, uso)
            return m, "".join(p.get("text", "") for p in partes), uso
        except urllib.error.HTTPError as e:
            ultimo = f"{m}: HTTP {e.code} {e.read()[:300]!r}"
            if e.code not in (500, 503):
                print("Falló", ultimo, file=sys.stderr)
                MODELOS_SALTAR.add(m)
        except Exception as e:
            ultimo = f"{m}: {e}"
        print("Falló", ultimo, file=sys.stderr)
    sys.exit("Ningún modelo respondió: " + str(ultimo))


def leer(p, n=40000):
    try:
        with open(p, encoding="utf-8") as f:
            t = f.read()
        return t if len(t) <= n else t[:n] + f"\n…(recortado, {len(t)} caracteres)"
    except Exception as e:
        return f"(no se pudo leer {p}: {e})"


UMBRAL_MENOR = 40


def lineas_codigo(desde, hasta):
    """Líneas agregadas + quitadas en código (sin datos .json, site/ ni worker.js) entre dos commits."""
    out = subprocess.run(["git", "diff", "--numstat", desde, hasta, "--", ".", ":(exclude)*.json", ":(exclude)site/**",
                          ":(exclude)worker.js", ":(exclude)*.png"], capture_output=True, text=True).stdout
    n = 0
    for l in out.splitlines():
        a_, b_, *_ = l.split("\t")
        n += (int(a_) if a_.isdigit() else 0) + (int(b_) if b_.isdigit() else 0)
    return n


def revision_previa(base):
    """(sha, texto) del commit más nuevo de esta rama (sin contar HEAD) que ya tiene un comentario del Revisor Gemini
    con revisión real (no un "sin llamar a Gemini")."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo or not os.environ.get("GH_TOKEN"):
        return None
    shas = subprocess.run(["git", "rev-list", f"{base}..HEAD~1"], capture_output=True, text=True).stdout.split()
    for sha in shas[:15]:
        r = subprocess.run(["gh", "api", f"repos/{repo}/commits/{sha}/comments", "-q", ".[].body"], capture_output=True, text=True)
        if "**Revisor Gemini** (`" in r.stdout:
            return sha, r.stdout
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual"); ap.add_argument("--base", default="origin/main")
    ap.add_argument("--archivos", nargs="*", default=[]); ap.add_argument("--prueba", action="store_true")
    ap.add_argument("--salida", default="revision_gemini.md")
    a = ap.parse_args()
    if a.prueba:
        m, t, uso = preguntar("Responde solo: 'Revisor Gemini de DataLab Ec listo.'")
        print(f"Modelo: {m}\nRespuesta: {t.strip()}\nUso: {uso}")
        return
    # Luis (4 nov): ahorro. (1) Si ya hubo una revisión en esta rama y lo nuevo desde entonces es un cambio menor
    # (< UMBRAL_MENOR líneas de código), no se vuelve a revisar: se deja el aviso con el veredicto anterior.
    # (2) Se manda solo el cambio, con las funciones completas que toca (git diff -W), no los archivos enteros.
    previa = revision_previa(a.base)
    if previa:
        sha, cuerpo = previa
        n = lineas_codigo(sha, "HEAD")
        if n < UMBRAL_MENOR:
            ver = next((l for l in cuerpo.splitlines() if "VEREDICTO" in l.upper()), "").strip()
            sal = (f"**Revisor Gemini** (sin llamar a Gemini)\n\nCambio menor ({n} líneas de código) sobre la versión ya revisada "
                   f"({sha[:7]}): no se vuelve a revisar. Veredicto anterior: {ver or 'ver el comentario de ' + sha[:7]}.\n")
            open(a.salida, "w", encoding="utf-8").write(sal); print(sal); return
    excl = [":(exclude)*.json", ":(exclude)site/**", ":(exclude)worker.js", ":(exclude)*.png"]
    diff = subprocess.run(["git", "diff", "-W", a.base, "HEAD", "--", "."] + excl, capture_output=True, text=True).stdout
    stat = subprocess.run(["git", "diff", "--stat", a.base, "HEAD"], capture_output=True, text=True).stdout
    log = subprocess.run(["git", "log", "--format=%h %s%n%b", f"{a.base}..HEAD"], capture_output=True, text=True).stdout
    partes = [leer(a.manual, 30000), "\n\n# Commits del candidato\n" + log, "\n\n# Archivos tocados\n" + stat[-4000:],
              "\n\n# Cambio propuesto (git diff con las funciones completas que toca; sin archivos de datos)\n```diff\n" + diff[:60000] + "\n```"]
    for p in a.archivos:   # solo archivos chicos de configuración; el código va en el diff
        t = leer(p, 6000)
        if len(t) < 6000 and not p.endswith(".py"):
            partes.append(f"\n\n# Archivo: {p}\n```\n{t}\n```")
    partes.append("\n\nRevisa el cambio propuesto según el manual. Empieza con la línea de VEREDICTO.")
    texto = "".join(partes)[:MAX_CHARS]
    m, t, uso = preguntar(texto)
    sal = f"**Revisor Gemini** (`{m}`)\n\n{t.strip()}\n\n<sub>tokens: entrada {uso.get('promptTokenCount')}, salida {uso.get('candidatesTokenCount')}</sub>\n"
    with open(a.salida, "w", encoding="utf-8") as f:
        f.write(sal)
    print(sal)


if __name__ == "__main__":
    main()
