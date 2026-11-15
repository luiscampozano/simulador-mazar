// DataLab Ec · video diario "Lluvia del día 3D" (Luis, 15 nov): la vista pública /3d/acumulada/ en modo video (#video),
// cuadro por cuadro: la lluvia crece hora a hora mientras la cámara gira. Salida: <dir>/lluvia3d_<día>.mp4 (vertical 9:16).
// Uso: node video_3d.js <carpeta_salida> [url]
const { chromium } = require(process.env.PLAYWRIGHT || "playwright");
const { execFileSync } = require("child_process"); const fs = require("fs"); const path = require("path");
const OUT = process.argv[2] || "salida_videos", URL = process.argv[3] || "https://datalabecuador.com/3d/acumulada/#video";
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
  const plan = [];
  for (let i = 0; i < FPS * 1; i++) plan.push([0, 0, 1]);                                            // inicio
  for (let i = 0; i < FPS * 12; i++) { const t = i / (FPS * 12); plan.push([24 * t, -50 * suave(t), 1]); }   // el día crece
  for (let i = 0; i < FPS * 5; i++) { const t = suave(i / (FPS * 5)); plan.push([24, -50 + 90 * t, 1 - 0.2 * t]); }   // gira alrededor
  for (let i = 0; i < FPS * 1.5; i++) plan.push([24, 40, 0.8]);                                      // final
  let n = 0;
  for (const [h, g, a] of plan) {
    await p.evaluate(([h, g, a]) => window.__video.fijar(h, g, a), [h, g, a]);
    await p.screenshot({ path: path.join(tmp, `c${String(n++).padStart(4, "0")}.jpg`), type: "jpeg", quality: 92 });
  }
  await b.close();
  const f = path.join(OUT, `lluvia3d_${dia}.mp4`), parcial = f.replace(/\.mp4$/, ".tmp.mp4");
  execFileSync("ffmpeg", ["-v", "error", "-y", "-framerate", String(FPS), "-i", path.join(tmp, "c%04d.jpg"), "-vf", "scale=1080:1920:flags=lanczos,format=yuv420p",
    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart", parcial]);
  fs.renameSync(parcial, f); fs.rmSync(tmp, { recursive: true, force: true });
  console.log("video 3D:", f, n, "cuadros");
})().catch(e => { console.error(e); process.exit(1); });
