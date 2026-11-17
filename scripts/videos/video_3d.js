// DataLab Ec · video diario "Lluvia del día 3D" (Luis, 15 nov): la vista pública /3d/acumulada/ en modo video (#video),
// cuadro por cuadro: la lluvia crece hora a hora mientras la cámara gira. Salida: <dir>/lluvia3d_<día>.mp4 (vertical 9:16).
// Uso: node video_3d.js <carpeta_salida> [url]
const { chromium } = require(process.env.PLAYWRIGHT || "playwright");
const { execFileSync } = require("child_process"); const fs = require("fs"); const path = require("path");
const OUT = process.argv[2] || "salida_videos", URL = process.argv[3] || "https://datalabecuador.com/3d/acumulada/#video";
const GIRO_A = +Number(process.env.GIRO_A || 40), GIRO_B = +Number(process.env.GIRO_B || -10);
const FPS = 24, suave = t => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
(async () => {
  fs.mkdirSync(OUT, { recursive: true }); const tmp = fs.mkdtempSync(path.join(require("os").tmpdir(), "v3d-"));
  const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const p = await (await b.newContext({ viewport: { width: 540, height: 960 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true })).newPage();
  if (process.env.PAGINA_LOCAL) {   // pruebas: servir la página y los datos desde archivos
    await p.route("https://datalabecuador.com/3d/acumulada/", r => r.fulfill({ contentType: "text/html", body: fs.readFileSync(process.env.PAGINA_LOCAL, "utf8") }));
    if (process.env.DATOS_LOCAL) await p.route("https://datalabecuador.com/3d/d/acumulada.json", r => r.fulfill({ contentType: "application/json", body: fs.readFileSync(process.env.DATOS_LOCAL) }));
    if (process.env.RELIEVE_LOCAL) await p.route("https://datalabecuador.com/3d/d/ecuador.json", r => r.fulfill({ contentType: "application/json", body: fs.readFileSync(process.env.RELIEVE_LOCAL) }));
  }
  await p.goto(URL, { timeout: 120000 });
  await p.waitForFunction(() => window.__video && window.__video.listo, null, { timeout: 120000 });
  await p.waitForTimeout(2500);
  const dia = await p.evaluate(() => window.__video.dia);
  if (process.env.DIA && dia !== process.env.DIA) throw new Error(`la lluvia del día publicada es del ${dia}, no del ${process.env.DIA}`);
  // Luis (16 nov): cada día llueve en otro lado. Mientras el día crece, la cámara encuadra TODOS los focos importantes
  // (núcleos con ≥ la mitad de la lluvia del mayor): apunta al centro de todos y se aleja lo necesario para que
  // quepan. Al final recorre cada foco (los que estén a > 150 km de uno ya visitado) para verlos de cerca.
  const V = await p.evaluate(() => ({ nucleos: window.__video.nucleos || [], centro: window.__video.centro }));
  const km = (a, b) => Math.hypot((a.lon - b.lon) * 111.3 * Math.cos(a.lat * Math.PI / 180), (a.lat - b.lat) * 110.6);
  const mezcla = (a, b, t) => ({ lon: a.lon + (b.lon - a.lon) * t, lat: a.lat + (b.lat - a.lat) * t });
  const C = V.centro, N1 = V.nucleos[0];
  const F = N1 ? V.nucleos.filter(x => x.mm >= 0.5 * N1.mm) : [];
  // centro de la caja que contiene a todos los focos (no ponderado: el foco más débil también debe verse entero)
  const CF = F.length ? { lon: (Math.min(...F.map(x => x.lon)) + Math.max(...F.map(x => x.lon))) / 2, lat: (Math.min(...F.map(x => x.lat)) + Math.max(...F.map(x => x.lat))) / 2 } : C;
  const ext = F.length ? Math.max(0, ...F.map(x => km(x, CF))) * 2 : 0;          // tamaño del grupo de focos (km)
  const LEJOS = Math.max(0.65, Math.min(1.3, (ext + 200) / 460));                 // 1 = la vista general (~Esmeraldas–Machala)
  const gira = [];                                                                // recorrido final: focos separados > 150 km
  for (const x of F) if (!gira.some(y => km(x, y) <= 150)) gira.push(x);
  const CERCA = 0.7;
  const plan = [];
  for (let i = 0; i < FPS * 1; i++) plan.push([0, 0, 1, C]);                                                   // inicio: vista general
  for (let i = 0; i < FPS * 12; i++) { const t = i / (FPS * 12), u = suave(t);                                // el día crece: encuadre de todos los focos
    plan.push([24 * t, GIRO_A * u, 1 + (LEJOS - 1) * u, mezcla(C, CF, u)]); }
  let prev = { o: CF, a: LEJOS, g: GIRO_A };
  gira.forEach((x, k) => {                                                                                      // de cerca, foco por foco
    const g = gira.length === 1 ? GIRO_B : GIRO_A + (GIRO_B - GIRO_A) * (k + 1) / gira.length;
    for (let i = 0; i < FPS * 2.5; i++) { const u = suave(i / (FPS * 2.5)); plan.push([24, prev.g + (g - prev.g) * u, prev.a + (CERCA - prev.a) * u, mezcla(prev.o, x, u)]); }
    for (let i = 0; i < FPS * 1.2; i++) plan.push([24, g, CERCA, x]);
    prev = { o: x, a: CERCA, g };
  });
  if (!gira.length) for (let i = 0; i < FPS * 5; i++) { const u = suave(i / (FPS * 5)); plan.push([24, GIRO_A + (GIRO_B - GIRO_A) * u, 1, C]); }
  for (let i = 0; i < FPS * 1; i++) plan.push(plan[plan.length - 1]);                                         // final
  console.log("focos:", F.map(x => `${x.lugar} ${x.mm}`).join(", ") || "ninguno", "· recorrido:", gira.map(x => x.lugar).join(" → "), "· encuadre", LEJOS.toFixed(2));
  let n = 0;
  for (const [h, g, a, o] of plan) {
    await p.evaluate(([h, g, a, o]) => window.__video.fijar(h, g, a, o.lon, o.lat), [h, g, a, o]);
    await p.screenshot({ path: path.join(tmp, `c${String(n++).padStart(4, "0")}.jpg`), type: "jpeg", quality: 92 });
  }
  await b.close();
  const f = path.join(OUT, `lluvia3d_${dia}.mp4`), parcial = f.replace(/\.mp4$/, ".tmp.mp4");
  execFileSync("ffmpeg", ["-v", "error", "-y", "-framerate", String(FPS), "-i", path.join(tmp, "c%04d.jpg"), "-vf", "scale=1080:1920:flags=lanczos,format=yuv420p",
    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart", parcial]);
  fs.renameSync(parcial, f); fs.rmSync(tmp, { recursive: true, force: true });
  console.log("video 3D:", f, n, "cuadros");
})().catch(e => { console.error(e); process.exit(1); });
