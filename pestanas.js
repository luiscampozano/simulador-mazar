/* Pestañas "2026 vs. 2024" y "Región de proyección" del simulador "Mazar y generación".
   Solo leen datos (datos.json e historial/celec_diario.json) y usan el mismo modelo (modelo.js);
   no cambian nada de la pestaña principal. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const f = (n, d = 0) => n.toLocaleString("es-EC", { minimumFractionDigits: d, maximumFractionDigits: d });
  const MON = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const DOW = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
  const MESL = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  const iso = d => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const sgn = (v, d = 1) => (v >= 0 ? "+" : "−") + f(Math.abs(v), d);
  const CORTES24 = ["2024-09-23", "2024-12-20"];   // cortes de luz nacionales de 2024
  const ZC = 2116, PARADA = 2115;

  let D = null, HISTD = null, listo = { comp: false, region: false };

  /* ---------- pestañas ---------- */
  function mostrar(tab) {
    if (tab !== "sim" && !document.getElementById("tab-" + tab)) tab = "sim";
    const wrap = document.querySelector(".wrap");
    [...wrap.children].forEach(n => {
      if (n.tagName === "HEADER" || n.tagName === "FOOTER" || n.classList.contains("tabs")) return;
      const esPanel = !!n.id && n.id.startsWith("tab-");
      n.classList.toggle("fuera", tab === "sim" ? esPanel : n.id !== "tab-" + tab);
    });
    document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false"));
    dibujar(tab);
  }
  function dibujar(tab) {
    if (tab === "comp" && D && HISTD) comparacion();
    if (tab === "region" && D) region();
    if (window.GEN) window.GEN.dibujar(tab);   // pestañas de generación y clima (generacion.js)
  }
  function actual() { return (location.hash || "").replace("#", "") || "sim"; }

  function medidas(id) {
    const svg = $(id), W = Math.max(300, Math.round(svg.parentNode.clientWidth || 760));
    const H = W < 500 ? 300 : 360;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    return { W, H, L: W < 500 ? 46 : 56, R: 14, T: 18, B: 36 };
  }

  /* ---------- 2026 vs. 2024 ---------- */
  function serieAnio(y, desde, hasta) {
    const out = [];
    for (let d = new Date(y, desde[0], desde[1]); d <= new Date(y, hasta[0], hasta[1]); d.setDate(d.getDate() + 1)) {
      const k = iso(d), v = HISTD[k];
      if (v && v.c) out.push([new Date(d), v.c]);
    }
    return out;
  }
  function comparacion() {
    const hoy = new Date(D.fecha), cota = D.cota;
    const y0 = hoy.getFullYear();
    const mismo24 = new Date(2024, hoy.getMonth(), hoy.getDate());
    const c = k => HISTD[k] && HISTD[k].c;
    const c24 = c(iso(mismo24));
    const hace = (d, n) => { const x = new Date(d); x.setDate(x.getDate() - n); return iso(x); };
    const c26_30 = c(hace(hoy, 30)), c24_30 = c(hace(mismo24, 30));
    const c26_7 = c(hace(hoy, 7)), c24_7 = c(hace(mismo24, 7));
    // fecha de 2024 en que la cota bajó por primera vez al nivel de hoy (desde el 1 de julio)
    let igual = null;
    for (const [d, v] of serieAnio(2024, [6, 1], [11, 31])) if (v <= cota) { igual = d; break; }
    const ventaja = igual ? Math.round((mismo24 - igual) / 86400000) : null;
    // mínimo de 2024 en la época seca y días bajo 2.115
    const s24 = serieAnio(2024, [6, 1], [11, 31]);
    const min24 = s24.reduce((a, b) => b[1] < a[1] ? b : a);
    const bajo = s24.filter(p => p[1] < PARADA).length;

    let txt = `Hoy Mazar está <b>${f(Math.abs(cota - c24), 1)} m ${cota >= c24 ? "más arriba" : "más abajo"}</b> que el mismo día de 2024. `;
    if (igual && ventaja > 0) txt += `La cota de hoy es la que tenía el <b>${igual.getDate()} de ${MESL[igual.getMonth()]} de 2024</b>: llevamos unos <b>${ventaja} días de ventaja</b> (unas ${Math.round(ventaja / 7)} semanas).`;
    else if (igual && ventaja < 0) txt += `En 2024 Mazar llegó a la cota de hoy recién el <b>${igual.getDate()} de ${MESL[igual.getMonth()]}</b>: este año vamos <b>${-ventaja} días adelantados</b> hacia el mínimo.`;
    $("cmpTxt").innerHTML = txt;

    const filas = [
      ["Cota (msnm)", f(cota, 2), f(c24, 2)],
      ["Sobre la parada de Mazar (2.115)", sgn(cota - PARADA, 2) + " m", sgn(c24 - PARADA, 2) + " m"],
      ["Cambio en 7 días", c26_7 ? sgn(cota - c26_7) + " m" : "–", c24_7 ? sgn(c24 - c24_7) + " m" : "–"],
      ["Cambio en 30 días", c26_30 ? sgn(cota - c26_30) + " m" : "–", c24_30 ? sgn(c24 - c24_30) + " m" : "–"],
    ];
    $("cmpTbl").innerHTML = `<tr><th></th><th style="text-align:right">Hoy</th><th style="text-align:right">Mismo día 2024</th></tr>` +
      filas.map(r => `<tr><td>${r[0]}</td><td class="n"><b>${r[1]}</b></td><td class="n">${r[2]}</td></tr>`).join("");
    $("cmpNota").innerHTML = `En 2024 la cota llegó a <b>${f(min24[1], 2)} m el ${min24[0].getDate()} de ${MESL[min24[0].getMonth()]}</b> y pasó <b>${bajo} días</b> por debajo de 2.115 entre julio y diciembre. Los cortes de luz nacionales fueron del 23 de septiembre al 20 de diciembre de 2024. Cotas diarias de Celec Sur; la de hoy es la lectura de las ${String(hoy.getHours()).padStart(2, "0")}:00.`;

    // gráfico: 1 jul → 31 dic, eje por día del año
    const { W, H, L, R, T, B } = medidas("cmpChart");
    const ini = m => new Date(2000, m[0], m[1]);
    const x0 = ini([6, 1]), x1 = ini([11, 31]);
    const doy = d => new Date(2000, d.getMonth(), d.getDate());
    const X = d => L + (doy(d) - x0) / (x1 - x0) * (W - L - R);
    const s26 = serieAnio(y0, [6, 1], [11, 31]).filter(p => iso(p[0]) < iso(hoy));
    s26.push([hoy, cota]);
    const todos = s24.map(p => p[1]).concat(s26.map(p => p[1]));
    const cMin = Math.floor(Math.min(...todos, PARADA) - 5), cMax = Math.ceil(Math.max(...todos) + 1);
    const Y = v => T + (cMax - v) / (cMax - cMin) * (H - T - B);
    const ink = css("--ink"), muted = css("--muted"), line = css("--line"), water = css("--water"), crit = css("--crit"), warn = css("--warn");
    const F = 'font-family="IBM Plex Sans, sans-serif"', FM = 'font-family="IBM Plex Mono, monospace"';
    let s = "";
    const xa = X(new Date(CORTES24[0] + "T00:00")), xb = X(new Date(CORTES24[1] + "T00:00"));
    s += `<rect x="${xa}" y="${T}" width="${xb - xa}" height="${H - T - B}" fill="${crit}" opacity=".08"/>`;
    s += `<text x="${xa + 6}" y="${T + 14}" ${F} font-size="11" font-weight="600" fill="${crit}">cortes de luz 2024</text>`;
    const paso = (cMax - cMin) > 30 ? 10 : 5;
    for (let v = Math.ceil(cMin / paso) * paso; v <= cMax; v += paso) {
      s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${line}"/>`;
      s += `<text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end" ${FM} font-size="11" fill="${muted}">${f(v)}</text>`;
    }
    for (let m = 6; m <= 11; m++) {
      const d = new Date(2000, m, 1);
      s += `<line x1="${X(d)}" x2="${X(d)}" y1="${H - B}" y2="${H - B + 5}" stroke="${muted}"/>`;
      s += `<text x="${X(d) + 4}" y="${H - B + 19}" ${FM} font-size="11" fill="${muted}">${MON[m]}</text>`;
    }
    s += `<line x1="${L}" x2="${W - R}" y1="${Y(PARADA)}" y2="${Y(PARADA)}" stroke="${crit}" stroke-width="1.5" stroke-dasharray="6 4"/>`;
    s += `<text x="${L + 6}" y="${Y(PARADA) - 6}" ${F} font-size="11" font-weight="600" fill="${crit}">parada de Mazar 2.115</text>`;
    const pl = (pts, col, w, extra = "") => `<polyline points="${pts.map(p => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ")}" fill="none" stroke="${col}" stroke-width="${w}" stroke-linejoin="round" ${extra}/>`;
    s += pl(s24, warn, 2.2);
    s += pl(s26, water, 2.8);
    // proyección del simulador (desde hoy)
    const Rb = base();
    if (Rb) {
      const pj = Rb.daily.filter(r => r.t <= 45).map(r => [new Date(hoy.getTime() + r.t * 86400000), r.cota]).filter(p => doy(p[0]) <= x1 && p[0].getFullYear() === y0);
      s += pl(pj, water, 2, 'stroke-dasharray="4 4" opacity=".8"');
    }
    s += `<circle cx="${X(min24[0])}" cy="${Y(min24[1])}" r="5" fill="${warn}" stroke="${css("--panel")}" stroke-width="2"/>`;
    s += `<text x="${X(min24[0])}" y="${Y(min24[1]) + 22}" text-anchor="middle" ${F} font-size="11" font-weight="600" fill="${warn}">2024: mín. ${f(min24[1], 1)}</text>`;
    s += `<circle cx="${X(hoy)}" cy="${Y(cota)}" r="5.5" fill="${water}" stroke="${css("--panel")}" stroke-width="2"/>`;
    s += `<text x="${X(hoy) - 10}" y="${Y(cota) - 10}" text-anchor="end" ${F} font-size="12" font-weight="700" fill="${water}">hoy ${f(cota, 1)}</text>`;
    if (igual && ventaja > 0) {
      s += `<circle cx="${X(igual)}" cy="${Y(HISTD[iso(igual)].c)}" r="4" fill="none" stroke="${warn}" stroke-width="2"/>`;
      s += `<line x1="${X(igual)}" x2="${X(hoy)}" y1="${Y(cota)}" y2="${Y(cota)}" stroke="${ink}" stroke-width="1" stroke-dasharray="2 3" opacity=".5"/>`;
    }
    $("cmpChart").innerHTML = s;
    listo.comp = true;
  }

  /* ---------- Región de proyección ---------- */
  function ctxBase(extra) {
    const m = D.modelo || {};
    return Object.assign({ cota: D.cota, inicio: new Date(D.fecha), diaSemana0: m.diaSemana0, amaluzaCota: m.amaluzaCota, amaluzaRitmo: m.amaluzaRitmo,
      deltaDia: m.deltaDia, cutDias: m.cutDias, cutPlan: m.cutPlan, ajuste: m.ajuste, serieMazar: m.serieMazar, serieCoca: m.serieCoca, memoria: m.memoria, horizonte: 60 }, extra || {});
  }
  function correr(qCoca, wCoca, extra) {
    const h = D.hoy;
    return ModeloMazar.simular({ qMazar: h.qMazar, qCoca, wPaute: h.wPaute, wCoca, demanda: h.dBase + 50 * (h.tCosta - 32), cut: h.cut, imp: h.imp, therm: h.therm, other: h.other }, ctxBase(extra));
  }
  function base() { if (!D || !window.ModeloMazar) return null; ModeloMazar.configurar(D.modelo); return correr(D.hoy.qCoca, D.hoy.wCoca); }
  function escenarios() {
    const m = D.modelo || {}, q = D.hoy.qCoca, q15 = Math.round(q * 0.85), uno = new Array(61).fill(1);
    const coca = [
      { id: "pron", txt: "sube como pronostica GloFAS", q, w: D.hoy.wCoca, ex: {} },
      { id: "const", txt: `se queda en ${q} m³/s (hoy)`, q, w: "auto", ex: { serieCoca: uno } },
      { id: "baja", txt: `baja 15 % (${q15} m³/s)`, q: q15, w: "auto", ex: { serieCoca: uno } },
    ];
    const paute = [{ id: "lluvia", txt: "lluvia pronosticada", ex: {} }];
    if (m.serieMazarSeca) paute.push({ id: "seca", txt: "semana seca como la anterior", ex: { serieMazar: m.serieMazarSeca } });
    ModeloMazar.configurar(D.modelo);
    const out = [];
    for (const c of coca) for (const p of paute) {
      const R = correr(c.q, c.w, Object.assign({}, c.ex, p.ex));
      out.push({ coca: c, paute: p, R, Z: ModeloMazar.zonaCritica(R, D.cota), principal: c.id === "pron" && p.id === "lluvia" });
    }
    return out;
  }
  function region() {
    const E = escenarios(), hoy = new Date(D.fecha), cota = D.cota;
    const fecha = t => { const d = new Date(hoy.getTime() + t * 86400000); return `${DOW[d.getDay()]} ${d.getDate()} ${MON[d.getMonth()]}`; };
    const conE = E.filter(e => e.Z.entrada !== null).sort((a, b) => a.Z.entrada - b.Z.entrada);
    const pr = E.find(e => e.principal);
    const temprano = conE[0], tarde = E.some(e => e.Z.entrada === null) ? null : conE[conE.length - 1];
    $("regTemprano").textContent = temprano ? fecha(temprano.Z.entrada) : "no entra";
    $("regTempranoTxt").textContent = temprano ? `Coca ${temprano.coca.txt.replace(/ \(hoy\)/, "")} y ${temprano.paute.txt}` : "en ningún escenario en 60 días";
    const mismo = tarde && tarde === pr;
    $("regTardeBox").classList.toggle("fuera", !!mismo);
    $("regPrinTxt").textContent = "Coca según GloFAS y lluvia pronosticada en el Paute" + (mismo ? ". Hoy es también el escenario más favorable." : "");
    $("regTarde").textContent = tarde ? fecha(tarde.Z.entrada) : "más de 60 días";
    $("regTardeTxt").textContent = tarde ? `Coca ${tarde.coca.txt} y ${tarde.paute.txt}` : "algún escenario no llega a 2.116 en 60 días";
    const NUM = (D.modelo.prediccion || {}).numero;   // mismo número grande que la pestaña principal
    $("regPrin").textContent = NUM ? (NUM.critica.dias >= 59 ? "más de 60 días" : fecha(NUM.critica.dias)) : (pr.Z.entrada !== null ? fecha(pr.Z.entrada) : "no entra");
    if (NUM) { $("regPrinTxt").textContent = "Igual que el número grande: promedio ponderado de las corridas de las últimas 48 h"; $("regTardeBox").classList.remove("fuera"); }

    // tabla
    $("regTbl").innerHTML = `<tr><th>Escenario</th><th style="text-align:right">Entra a 2.116</th><th style="text-align:right">Llega a 2.115</th></tr>` +
      E.map(e => {
        const z = e.Z, mn = z.minimo;
        const para = e.R.crossDay !== null && z.paradaEnVentana ? fecha(e.R.crossDay) : (mn ? "no (mín. " + f(mn.cota, 1) + ")" : "no");
        return `<tr${e.principal ? ' style="font-weight:600"' : ""}><td>Coca ${e.coca.txt}<br><span style="color:var(--muted)">Paute: ${e.paute.txt}</span>${e.principal ? "<br><span style='color:var(--water)'>proyección del simulador</span>" : ""}</td><td class="n">${z.entrada === null ? "más de 60 días" : fecha(z.entrada)}</td><td class="n">${para}</td></tr>`;
      }).join("");

    // gráfico
    const HZ = 45, { W, H, L, R, T, B } = medidas("regChart");
    const hist = (D.historico || []).map(([k, v]) => [Math.round((new Date(k + "T00:00:00") - new Date(D.fecha.slice(0, 10) + "T00:00:00")) / 86400000), v]).filter(p => p[0] >= -20 && p[0] < 0);
    hist.push([0, cota]);
    const tMin = Math.min(-20, ...hist.map(p => p[0]));
    const X = t => L + (t - tMin) / (HZ - tMin) * (W - L - R);
    const serie = e => e.R.daily.filter(r => r.t <= HZ).map(r => [r.t, r.cota]);
    const todos = E.flatMap(e => serie(e).map(p => p[1])).concat(hist.map(p => p[1]));
    const cMin = Math.min(2113, Math.floor(Math.min(...todos)) - 1), cMax = Math.ceil(Math.max(...todos)) + 1;
    const Y = v => T + (cMax - v) / (cMax - cMin) * (H - T - B);
    const ink = css("--ink"), muted = css("--muted"), line = css("--line"), water = css("--water"), crit = css("--crit"), warn = css("--warn");
    const F = 'font-family="IBM Plex Sans, sans-serif"', FM = 'font-family="IBM Plex Mono, monospace"';
    let s = "";
    s += `<rect x="${L}" y="${Y(ZC)}" width="${W - L - R}" height="${Y(PARADA) - Y(ZC)}" fill="${warn}" opacity=".12"/>`;
    s += `<rect x="${L}" y="${Y(PARADA)}" width="${W - L - R}" height="${Y(cMin) - Y(PARADA)}" fill="${crit}" opacity=".08"/>`;
    for (let v = Math.ceil(cMin / 2) * 2; v <= cMax; v += 2) {
      s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${line}"/>`;
      s += `<text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end" ${FM} font-size="11" fill="${muted}">${f(v)}</text>`;
    }
    const pasoT = W < 500 ? 20 : 10;
    for (let t = Math.ceil(tMin / pasoT) * pasoT; t <= HZ; t += pasoT) {
      const d = new Date(hoy.getTime() + t * 86400000);
      s += `<line x1="${X(t)}" x2="${X(t)}" y1="${H - B}" y2="${H - B + 5}" stroke="${muted}"/>`;
      s += `<text x="${X(t)}" y="${H - B + 19}" text-anchor="middle" ${FM} font-size="11" fill="${muted}">${d.getDate()} ${MON[d.getMonth()]}</text>`;
    }
    // región: mínimo y máximo de todos los escenarios, día por día
    const n = Math.min(...E.map(e => serie(e).length));
    const sup = [], inf = [];
    for (let i = 0; i < n; i++) { const vs = E.map(e => serie(e)[i][1]); sup.push([E[0].R.daily[i].t, Math.max(...vs)]); inf.push([E[0].R.daily[i].t, Math.min(...vs)]); }
    const P = pts => pts.map(p => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1));
    s += `<path d="M${P(sup).join(" L")} L${P(inf.slice().reverse()).join(" L")} Z" fill="${water}" opacity=".18"/>`;
    s += `<polyline points="${P(sup).join(" ")}" fill="none" stroke="${water}" stroke-width="1" opacity=".55"/>`;
    s += `<polyline points="${P(inf).join(" ")}" fill="none" stroke="${water}" stroke-width="1" opacity=".55"/>`;
    s += `<line x1="${L}" x2="${W - R}" y1="${Y(ZC)}" y2="${Y(ZC)}" stroke="${warn}" stroke-width="1.5" stroke-dasharray="6 4"/>`;
    s += `<text x="${L + 6}" y="${Y(ZC) - 6}" ${F} font-size="11" font-weight="600" fill="${warn}">zona crítica 2.116</text>`;
    s += `<line x1="${L}" x2="${W - R}" y1="${Y(PARADA)}" y2="${Y(PARADA)}" stroke="${crit}" stroke-width="2"/>`;
    s += `<text x="${L + 6}" y="${Y(PARADA) + 16}" ${F} font-size="11" font-weight="600" fill="${crit}">parada de Mazar 2.115</text>`;
    E.filter(e => !e.principal).forEach(e => { s += `<polyline points="${P(serie(e)).join(" ")}" fill="none" stroke="${ink}" stroke-width="1" stroke-dasharray="2 4" opacity=".35"/>`; });
    s += `<polyline points="${P(serie(pr)).join(" ")}" fill="none" stroke="${water}" stroke-width="2.6"/>`;
    s += `<polyline points="${P(hist).join(" ")}" fill="none" stroke="${ink}" stroke-width="1.5" opacity=".5"/>`;
    hist.forEach(p => { s += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="3" fill="${ink}"/>`; });
    s += `<line x1="${X(0)}" x2="${X(0)}" y1="${T}" y2="${H - B}" stroke="${muted}" stroke-dasharray="3 3"/>`;
    s += `<text x="${X(0) + 5}" y="${T + 12}" ${F} font-size="11" fill="${muted}">hoy</text>`;
    $("regChart").innerHTML = s;
    listo.region = true;
  }

  /* ---------- arranque ---------- */
  function iniciar() {
    document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => {
      const t = b.dataset.tab;
      history.replaceState(null, "", t === "sim" ? location.pathname + location.search : "#" + t);
      mostrar(t);
      window.scrollTo({ top: document.querySelector(".tabs").offsetTop - 8 });
    }));
    window.addEventListener("hashchange", () => mostrar(actual()));
    const redibujar = () => dibujar(actual());
    let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(redibujar, 150); });
    try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redibujar); } catch (e) { }
    new MutationObserver(redibujar).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    mostrar(actual());
    fetch("datos.json", { cache: "no-store" }).then(r => r.ok ? r.json() : null).then(j => { if (j && j.cota) { D = j; redibujar(); } }).catch(() => { });
    fetch("historial/celec_diario.json", { cache: "no-store" }).then(r => r.ok ? r.json() : null).then(j => { if (j) { HISTD = j; redibujar(); } }).catch(() => { });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();
})();
