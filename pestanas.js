/* Pestañas "2026 vs. años anteriores" y "Región de proyección" del simulador "Mazar y generación".
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
  const ZC = 2116, PARADA = 2115;

  let D = null, HISTD = null, HISTV = null, listo = { comp: false, region: false };

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

  /* ---------- 2026 vs. años anteriores ---------- */
  // Cortes de luz nacionales (programados) por año
  const CORTES = {
    2023: [["2023-10-27", "2023-12-19"]],
    2024: [["2024-04-15", "2024-04-30"], ["2024-09-23", "2024-12-20"]],
  };
  const CORTES_TXT = {
    2023: "del 27 de octubre al 19 de diciembre de 2023",
    2024: "del 15 al 30 de abril y del 23 de septiembre al 20 de diciembre de 2024",
  };
  const ANIO0 = 2011;          // Mazar se llenó en 2010; desde 2011 opera con el embalse completo
  let cmpSel = "todos", cmpTodas = false;
  const hist = k => (HISTD && HISTD[k]) || (HISTV && HISTV[k]);
  function serieAnio(y, desde, hasta) {
    const out = [];
    for (let d = new Date(y, desde[0], desde[1]); d <= new Date(y, hasta[0], hasta[1]); d.setDate(d.getDate() + 1)) {
      const v = hist(iso(d));
      if (v && v.c) out.push([new Date(d), v.c]);
    }
    return out;
  }
  function aniosDisponibles(y0) {
    const out = [];
    for (let y = ANIO0; y < y0; y++) if (serieAnio(y, [6, 1], [6, 10]).length) out.push(y);
    return out;
  }
  function subpestanas(y0) {
    const anios = aniosDisponibles(y0);
    const fijos = [y0 - 1, y0 - 2, y0 - 3].filter(y => anios.includes(y));
    const otros = anios.filter(y => !fijos.includes(y)).reverse();
    const sel = String(cmpSel);
    let h = `<button type="button" role="tab" data-anio="todos" aria-selected="${sel === "todos"}">Todos los años</button>`;
    h += fijos.map(y => `<button type="button" role="tab" data-anio="${y}" aria-selected="${sel === String(y)}">${y}${CORTES[y] ? ' <span class="corte-pt" title="hubo cortes de luz"></span>' : ""}</button>`).join("");
    if (otros.length) {
      const enOtros = otros.map(String).includes(sel);
      h += `<select id="cmpOtro" aria-label="Otro año" class="${enOtros ? "on" : ""}"><option value="">${otros.length ? "Más años…" : ""}</option>` +
        otros.map(y => `<option value="${y}" ${sel === String(y) ? "selected" : ""}>${y}</option>`).join("") + `</select>`;
    }
    $("cmpSub").innerHTML = h;
    $("cmpSub").querySelectorAll("button").forEach(b => b.onclick = () => { cmpSel = b.dataset.anio; comparacion(); });
    const s = $("cmpOtro"); if (s) s.onchange = () => { if (s.value) { cmpSel = s.value; comparacion(); } };
    if (!HISTV) $("cmpSub").insertAdjacentHTML("beforeend", `<span class="cmp-carga">cargando 2011–2022…</span>`);
  }
  function comparacion() {
    const hoy = new Date(D.fecha), y0 = hoy.getFullYear();
    subpestanas(y0);
    if (cmpSel === "todos") return comparacionTodos(hoy, y0);
    return comparacionAnio(hoy, y0, +cmpSel);
  }

  // marco común del gráfico (1 jul → 31 dic, eje por día del año)
  function marco(todos, cortes) {
    const { W, H, L, R, T, B } = medidas("cmpChart");
    const x0 = new Date(2000, 6, 1), x1 = new Date(2000, 11, 31);
    const doy = d => new Date(2000, d.getMonth(), d.getDate());
    const X = d => L + (doy(d) - x0) / (x1 - x0) * (W - L - R);
    const cMin = Math.floor(Math.min(...todos, PARADA) - 5), cMax = Math.ceil(Math.max(...todos) + 1);
    const Y = v => T + (cMax - v) / (cMax - cMin) * (H - T - B);
    const c = { ink: css("--ink"), muted: css("--muted"), line: css("--line"), water: css("--water"), crit: css("--crit"), warn: css("--warn"), panel: css("--panel") };
    const F = 'font-family="IBM Plex Sans, sans-serif"', FM = 'font-family="IBM Plex Mono, monospace"';
    let s = "";
    (cortes || []).forEach(([a, b], i) => {
      const da = new Date(a + "T00:00"), db = new Date(b + "T00:00");
      if (db < new Date(da.getFullYear(), 6, 1)) return;           // fuera de jul–dic (abril 2024)
      const xa = X(da < new Date(da.getFullYear(), 6, 1) ? new Date(2000, 6, 1) : da), xb = X(db);
      s += `<rect x="${xa}" y="${T}" width="${xb - xa}" height="${H - T - B}" fill="${c.crit}" opacity=".08"/>`;
      s += `<text x="${xa + 6}" y="${T + 14}" ${F} font-size="11" font-weight="600" fill="${c.crit}">cortes de luz ${da.getFullYear()}</text>`;
    });
    const paso = (cMax - cMin) > 30 ? 10 : 5;
    for (let v = Math.ceil(cMin / paso) * paso; v <= cMax; v += paso) {
      s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${c.line}"/>`;
      s += `<text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end" ${FM} font-size="11" fill="${c.muted}">${f(v)}</text>`;
    }
    for (let m = 6; m <= 11; m++) {
      const d = new Date(2000, m, 1);
      s += `<line x1="${X(d)}" x2="${X(d)}" y1="${H - B}" y2="${H - B + 5}" stroke="${c.muted}"/>`;
      s += `<text x="${X(d) + 4}" y="${H - B + 19}" ${FM} font-size="11" fill="${c.muted}">${MON[m]}</text>`;
    }
    s += `<line x1="${L}" x2="${W - R}" y1="${Y(PARADA)}" y2="${Y(PARADA)}" stroke="${c.crit}" stroke-width="1.5" stroke-dasharray="6 4"/>`;
    s += `<text x="${L + 6}" y="${Y(PARADA) - 6}" ${F} font-size="11" font-weight="600" fill="${c.crit}">parada de Mazar 2.115</text>`;
    const pl = (pts, col, w, extra = "") => `<polyline points="${pts.map(p => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ")}" fill="none" stroke="${col}" stroke-width="${w}" stroke-linejoin="round" ${extra}/>`;
    return { s, X, Y, x1, doy, pl, c, F };
  }
  function serie26(hoy, y0) {
    const s26 = serieAnio(y0, [6, 1], [11, 31]).filter(p => iso(p[0]) < iso(hoy));
    s26.push([hoy, D.cota]);
    return s26;
  }
  function trazo26(g, hoy, y0, s26) {
    let s = g.pl(s26, g.c.water, 2.8);
    const Rb = base();
    if (Rb) {
      const pj = Rb.daily.filter(r => r.t <= 45).map(r => [new Date(hoy.getTime() + r.t * 86400000), r.cota]).filter(p => g.doy(p[0]) <= g.x1 && p[0].getFullYear() === y0);
      s += g.pl(pj, g.c.water, 2, 'stroke-dasharray="4 4" opacity=".8"');
    }
    s += `<circle cx="${g.X(hoy)}" cy="${g.Y(D.cota)}" r="5.5" fill="${g.c.water}" stroke="${g.c.panel}" stroke-width="2"/>`;
    s += `<text x="${g.X(hoy) - 10}" y="${g.Y(D.cota) - 10}" text-anchor="end" ${g.F} font-size="12" font-weight="700" fill="${g.c.water}">hoy ${f(D.cota, 1)}</text>`;
    return s;
  }
  const ley = (col, txt, tipo) => {
    const m = tipo === "dash" ? `width:14px;height:0;border-top:2px dashed ${col}` : tipo === "caja" ? `width:12px;height:12px;background:${col}` : `width:14px;height:3px;background:${col}`;
    return `<span><i style="display:inline-block;${m};vertical-align:middle;margin-right:6px"></i>${txt}</span>`;
  };
  const LEY_CORTE = "color-mix(in srgb,var(--crit) 15%,transparent)";

  function resumenAnio(y) {
    const s = serieAnio(y, [6, 1], [11, 31]);
    if (!s.length) return null;
    const min = s.reduce((a, b) => b[1] < a[1] ? b : a);
    return { s, min, bajo: s.filter(p => p[1] < PARADA).length };
  }

  /* --- un año --- */
  function comparacionAnio(hoy, y0, y) {
    $("cmpTbl").classList.remove("abierta");
    const cota = D.cota;
    const mismo = new Date(y, hoy.getMonth(), hoy.getDate());
    const c = k => { const v = hist(k); return v && v.c; };
    const cy = c(iso(mismo));
    const hace = (d, n) => { const x = new Date(d); x.setDate(x.getDate() - n); return iso(x); };
    const r = resumenAnio(y);
    let igual = null;
    for (const [d, v] of r.s) if (v <= cota) { igual = d; break; }
    const ventaja = igual ? Math.round((mismo - igual) / 86400000) : null;

    $("cmpTit").textContent = `2026 vs. ${y}` + (CORTES[y] ? ", un año con cortes" : "");
    let txt = `Hoy Mazar está <b>${f(Math.abs(cota - cy), 1)} m ${cota >= cy ? "más arriba" : "más abajo"}</b> que el mismo día de ${y}. `;
    if (igual && ventaja > 0) txt += `La cota de hoy es la que tenía el <b>${igual.getDate()} de ${MESL[igual.getMonth()]} de ${y}</b>: llevamos unos <b>${ventaja} días de ventaja</b>${ventaja >= 14 ? ` (unas ${Math.round(ventaja / 7)} semanas)` : ""}.`;
    else if (igual && ventaja < 0) txt += `En ${y} Mazar llegó a la cota de hoy recién el <b>${igual.getDate()} de ${MESL[igual.getMonth()]}</b>: este año vamos <b>${-ventaja} días adelantados</b> hacia el mínimo.`;
    else if (!igual) txt += `En ${y} Mazar <b>nunca bajó a la cota de hoy</b> entre julio y diciembre: su mínimo fue ${f(r.min[1], 1)} m.`;
    $("cmpTxt").innerHTML = txt;

    const filas = [
      ["Cota (msnm)", f(cota, 2), f(cy, 2)],
      ["Sobre la parada de Mazar (2.115)", sgn(cota - PARADA, 2) + " m", sgn(cy - PARADA, 2) + " m"],
      ["Cambio en 7 días", c(hace(hoy, 7)) ? sgn(cota - c(hace(hoy, 7))) + " m" : "–", c(hace(mismo, 7)) ? sgn(cy - c(hace(mismo, 7))) + " m" : "–"],
      ["Cambio en 30 días", c(hace(hoy, 30)) ? sgn(cota - c(hace(hoy, 30))) + " m" : "–", c(hace(mismo, 30)) ? sgn(cy - c(hace(mismo, 30))) + " m" : "–"],
    ];
    $("cmpTbl").innerHTML = `<tr><th></th><th style="text-align:right">Hoy</th><th style="text-align:right">Mismo día ${y}</th></tr>` +
      filas.map(r => `<tr><td>${r[0]}</td><td class="n"><b>${r[1]}</b></td><td class="n">${r[2]}</td></tr>`).join("");
    const cortesTxt = CORTES_TXT[y] ? ` Los cortes de luz nacionales fueron ${CORTES_TXT[y]}.` : ` En ${y} no hubo cortes de luz nacionales.`;
    $("cmpNota").innerHTML = `En ${y} la cota llegó a <b>${f(r.min[1], 2)} m el ${r.min[0].getDate()} de ${MESL[r.min[0].getMonth()]}</b>` +
      (r.bajo ? ` y pasó <b>${r.bajo} días</b> por debajo de 2.115 entre julio y diciembre.` : `; no bajó de 2.115 entre julio y diciembre.`) +
      cortesTxt + ` Cotas diarias de Celec Sur; la de hoy es la lectura de las ${String(hoy.getHours()).padStart(2, "0")}:00.`;

    $("cmpLey").innerHTML = ley("var(--water)", y0) + ley("var(--water)", "proyección del simulador", "dash") + ley("var(--warn)", y) + (CORTES[y] ? ley(LEY_CORTE, `cortes de luz ${y}`, "caja") : "");

    const s26 = serie26(hoy, y0);
    const g = marco(r.s.map(p => p[1]).concat(s26.map(p => p[1])), CORTES[y]);
    let s = g.s + g.pl(r.s, g.c.warn, 2.2) + trazo26(g, hoy, y0, s26);
    s += `<circle cx="${g.X(r.min[0])}" cy="${g.Y(r.min[1])}" r="5" fill="${g.c.warn}" stroke="${g.c.panel}" stroke-width="2"/>`;
    s += `<text x="${g.X(r.min[0])}" y="${g.Y(r.min[1]) + 22}" text-anchor="middle" ${g.F} font-size="11" font-weight="600" fill="${g.c.warn}">${y}: mín. ${f(r.min[1], 1)}</text>`;
    if (igual && ventaja > 0) {
      s += `<circle cx="${g.X(igual)}" cy="${g.Y(hist(iso(igual)).c)}" r="4" fill="none" stroke="${g.c.warn}" stroke-width="2"/>`;
      s += `<line x1="${g.X(igual)}" x2="${g.X(hoy)}" y1="${g.Y(cota)}" y2="${g.Y(cota)}" stroke="${g.c.ink}" stroke-width="1" stroke-dasharray="2 3" opacity=".5"/>`;
    }
    $("cmpChart").innerHTML = s;
    $("cmpChart").setAttribute("aria-label", `Cota de Mazar en ${y0} comparada con ${y}`);
    listo.comp = true;
  }

  /* --- todos los años --- */
  function comparacionTodos(hoy, y0) {
    const cota = D.cota;
    const anios = aniosDisponibles(y0);
    const R = {};
    anios.forEach(y => { R[y] = resumenAnio(y); });
    // franja: mínimo y máximo de cada día entre los años disponibles
    const banda = [];
    for (let d = new Date(2001, 6, 1); d <= new Date(2001, 11, 31); d.setDate(d.getDate() + 1)) {
      const vs = anios.map(y => { const v = hist(iso(new Date(y, d.getMonth(), d.getDate()))); return v && v.c; }).filter(Boolean);
      if (vs.length >= 3) { vs.sort((a, b) => a - b); banda.push([new Date(y0, d.getMonth(), d.getDate()), vs[0], vs[vs.length - 1], vs[Math.floor(vs.length / 2)]]); }
    }
    // ranking del mismo día
    const hoyD = anios.map(y => { const v = hist(iso(new Date(y, hoy.getMonth(), hoy.getDate()))); return [y, v && v.c]; }).filter(p => p[1]);
    const masBajos = hoyD.filter(p => p[1] < cota).sort((a, b) => a[1] - b[1]);
    const prom = hoyD.reduce((a, p) => a + p[1], 0) / hoyD.length;
    const n = hoyD.length + 1, pos = masBajos.length + 1;

    $("cmpTit").textContent = `2026 vs. ${anios[0]}–${anios[anios.length - 1]}`;
    let txt = `Para un ${hoy.getDate()} de ${MESL[hoy.getMonth()]}, Mazar está hoy <b>${f(Math.abs(cota - prom), 1)} m ${cota >= prom ? "por encima" : "por debajo"} del promedio</b> de ${hoyD.length} años (${f(prom, 1)} m). `;
    if (!masBajos.length) txt += `<b>Es la cota más baja</b> para esta fecha desde ${anios[0]}.`;
    else txt += `Es la <b>${pos}.ª más baja de ${n}</b> para esta fecha: solo ${masBajos.length === 1 ? "estuvo más abajo" : "estuvieron más abajo"} <b>${masBajos.map(p => p[0]).join(", ")}</b>.`;
    $("cmpTxt").innerHTML = txt;

    const orden = anios.slice().sort((a, b) => { const ca = hoyD.find(p => p[0] === a), cb = hoyD.find(p => p[0] === b); return (ca ? ca[1] : 1e9) - (cb ? cb[1] : 1e9); });
    const filas = orden.map((y, k) => {
      const r = R[y], hc = hoyD.find(p => p[0] === y);
      return `<tr class="${k >= 5 ? "extra" : ""}"><td>${y}${CORTES[y] ? ' <span class="corte-pt" title="hubo cortes de luz"></span>' : ""}</td><td class="n">${hc ? f(hc[1], 1) : "–"}</td><td class="n">${f(r.min[1], 1)} <span class="muted">(${r.min[0].getDate()} ${MON[r.min[0].getMonth()]})</span></td><td class="n">${r.bajo || "–"}</td></tr>`;
    });
    $("cmpTbl").innerHTML = `<tr><th>Año</th><th style="text-align:right">Cota el ${hoy.getDate()} ${MON[hoy.getMonth()]}</th><th style="text-align:right">Mínimo jul–dic</th><th style="text-align:right">Días bajo 2.115</th></tr>` +
      `<tr class="hoy"><td><b>${y0}</b></td><td class="n"><b>${f(cota, 1)}</b></td><td class="n">–</td><td class="n">–</td></tr>` + filas.join("") +
      `<tr class="vermas"><td colspan="4"><button type="button" id="cmpVer">Ver los ${anios.length} años</button></td></tr>`;
    $("cmpTbl").classList.toggle("abierta", cmpTodas);
    $("cmpVer").onclick = () => { cmpTodas = !cmpTodas; $("cmpTbl").classList.toggle("abierta", cmpTodas); $("cmpVer").textContent = cmpTodas ? "Ver solo los 5 más bajos" : `Ver los ${anios.length} años`; };
    if (cmpTodas) $("cmpVer").textContent = "Ver solo los 5 más bajos";
    $("cmpNota").innerHTML = `La tabla ordena los años de la cota más baja a la más alta para esta fecha. La franja gris va de la cota más baja a la más alta que tuvo Mazar cada día entre ${anios[0]} y ${anios[anios.length - 1]}; la línea gris es la mediana. Los años con <span class="corte-pt"></span> tuvieron cortes de luz nacionales: 2023 (27 oct–19 dic) y 2024 (15–30 abr y 23 sep–20 dic). 2010 no se incluye porque Mazar todavía se estaba llenando. Cotas diarias de Celec Sur.`;
    $("cmpLey").innerHTML = ley("var(--water)", y0) + ley("var(--water)", "proyección del simulador", "dash") + ley("color-mix(in srgb,var(--muted) 25%,transparent)", `rango ${anios[0]}–${anios[anios.length - 1]}`, "caja") + ley("var(--muted)", "mediana") + ley("var(--warn)", "2024") + ley("var(--crit)", "2023");

    const s26 = serie26(hoy, y0);
    const g = marco(banda.flatMap(b => [b[1], b[2]]).concat(s26.map(p => p[1])), []);
    let s = g.s;
    const arriba = banda.map(b => g.X(b[0]).toFixed(1) + "," + g.Y(b[2]).toFixed(1));
    const abajo = banda.slice().reverse().map(b => g.X(b[0]).toFixed(1) + "," + g.Y(b[1]).toFixed(1));
    s += `<polygon points="${arriba.concat(abajo).join(" ")}" fill="${g.c.muted}" opacity=".16"/>`;
    s += g.pl(banda.map(b => [b[0], b[3]]), g.c.muted, 1.6, 'opacity=".8"');
    if (R[2023]) s += g.pl(R[2023].s, g.c.crit, 1.6, 'opacity=".75"');
    if (R[2024]) s += g.pl(R[2024].s, g.c.warn, 1.6, 'opacity=".85"');
    s += trazo26(g, hoy, y0, s26);
    $("cmpChart").innerHTML = s;
    $("cmpChart").setAttribute("aria-label", `Cota de Mazar en ${y0} comparada con ${anios[0]}–${anios[anios.length - 1]}`);
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
      { id: "pron", txt: "sigue el pronóstico de GloFAS", q, w: D.hoy.wCoca, ex: {} },
      { id: "const", txt: `Coca Codo se queda como hoy (${q} m³/s equivalentes)`, q, w: "auto", ex: { serieCoca: uno } },
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
  // Escenarios para el panel de cortes (pesimista / optimista) de la pestaña principal
  function publicarEscenarios() {
    try { if (!D || !window.ModeloMazar) return; window.ESC_CORTES = escenarios().map(e => e.R); if (window.pintarCortes) window.pintarCortes(); } catch (e) { }
  }
  function region() {
    const E = escenarios(), hoy = new Date(D.fecha), cota = D.cota;
    if (D.modelo && D.modelo.serieCocaRio) {
      const q = D.hoy.qCoca;
      const R_som = correr(q, "auto", { serieCoca: D.modelo.serieCocaRio });
      E.push({
        coca: { id: "sombra", txt: "modelo en prueba desde el 28 oct: usa el caudal real del río Coca", q, w: "auto", ex: { serieCoca: D.modelo.serieCocaRio } },
        paute: { id: "lluvia", txt: "lluvia pronosticada", ex: {} },
        R: R_som,
        Z: ModeloMazar.zonaCritica(R_som, cota),
        principal: false,
        sombra: true
      });
    }
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

    const e_somb = E.find(e => e.sombra);
    const boxSomb = $("reg-sombra-box") || $("regSombraBox");
    if (boxSomb) {
      if (e_somb && e_somb.Z) {
        boxSomb.classList.remove("fuera");
        const elFecha = $("reg-sombra") || $("regSombra");
        if (elFecha) elFecha.textContent = e_somb.Z.entrada !== null ? fecha(e_somb.Z.entrada) : "más de 60 días";
        const elTxt = $("reg-sombra-txt") || $("regSombraTxt");
        if (elTxt) elTxt.textContent = "Caudal real del Coca con tope físico de 1.200 MW";
      } else {
        boxSomb.classList.add("fuera");
      }
    }
    const NUM = (D.modelo.prediccion || {}).numero;   // mismo número grande que la pestaña principal
    $("regPrin").textContent = NUM ? (NUM.critica.dias >= 59 ? "más de 60 días" : fecha(NUM.critica.dias)) : (pr.Z.entrada !== null ? fecha(pr.Z.entrada) : "no entra");
    if (NUM) { $("regPrinTxt").textContent = "Igual que el número grande: promedio ponderado de las corridas de las últimas 48 h"; $("regTardeBox").classList.remove("fuera"); }

    // tabla
    $("regTbl").innerHTML = `<tr><th>Escenario</th><th style="text-align:right">Entra a 2.116</th><th style="text-align:right">Llega a 2.115</th></tr>` +
      E.map(e => {
        const z = e.Z, mn = z.minimo;
        const para = e.R.crossDay !== null && z.paradaEnVentana ? fecha(e.R.crossDay) : (mn ? "no (mín. " + f(mn.cota, 1) + ")" : "no");
        const esSomb = e.sombra;
        const tit = esSomb ? `<b style="color:#c084fc">${e.coca.txt}</b>` : `Coca ${e.coca.txt}`;
        const sub = esSomb ? `<br><span style="color:#c084fc;opacity:.85">Paute: ${e.paute.txt} · Caudal real con tope 1.200 MW</span>` : `<br><span style="color:var(--muted)">Paute: ${e.paute.txt}</span>${e.principal ? "<br><span style='color:var(--water)'>proyección del simulador</span>" : ""}`;
        return `<tr${e.principal ? ' style="font-weight:600"' : (esSomb ? ' style="background:rgba(192,132,252,.08)"' : "")}><td>${tit}${sub}</td><td class="n"${esSomb ? ' style="color:#c084fc;font-weight:600"' : ""}>${z.entrada === null ? "más de 60 días" : fecha(z.entrada)}</td><td class="n"${esSomb ? ' style="color:#c084fc"' : ""}>${para}</td></tr>`;
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
    E.filter(e => !e.principal).forEach(e => { s += `<polyline points="${P(serie(e)).join(" ")}" fill="none" stroke="${e.sombra ? '#c084fc' : ink}" stroke-width="${e.sombra ? 2.2 : 1}" stroke-dasharray="${e.sombra ? '5 3' : '2 4'}" opacity="${e.sombra ? 0.95 : .35}"/>`; });
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
    fetch("datos.json", { cache: "no-store" }).then(r => r.ok ? r.json() : null).then(j => { if (j && j.cota) { D = j; redibujar(); publicarEscenarios(); } }).catch(() => { });
    fetch("historial/celec_diario.json", { cache: "no-store" }).then(r => r.ok ? r.json() : null).then(j => { if (j) { HISTD = j; redibujar(); } }).catch(() => { });
    fetch("historial/celec_2010_2022.json").then(r => r.ok ? r.json() : null).then(j => { if (j) { HISTV = j; redibujar(); } }).catch(() => { });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();
})();
