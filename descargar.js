/* DataLab Ec · botón ⬇ para descargar cada gráfico o sección como imagen PNG.
   Uso: <script src="descargar.js" data-sel=".panel"></script>  (data-sel = qué cajas llevan botón; data-excluir = cuáles no). */
(function () {
  var S = document.currentScript || {};
  var SEL = (S.dataset && S.dataset.sel) || ".panel";
  var EXCLUIR = (S.dataset && S.dataset.excluir) || "";
  var MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  var CREDITO = "Ing. Luis Campozano, MBA e Ing. Alfredo Campozano";
  var h2c = null;

  var css = document.createElement("style");
  css.textContent =
    ".dl-btn{position:absolute;top:8px;right:8px;z-index:5;width:28px;height:28px;border-radius:8px;border:1px solid rgba(125,211,252,.35);" +
    "background:rgba(7,26,34,.75);color:#7dd3fc;font:700 15px/1 Inter,system-ui,sans-serif;cursor:pointer;display:grid;place-items:center;opacity:.55;transition:opacity .2s,background .2s;padding:0}" +
    ".dl-btn:hover,.dl-btn:focus-visible{opacity:1;background:rgba(56,189,248,.18)}" +
    ".dl-btn[aria-busy=true]{opacity:1;cursor:progress}" +
    ".dl-con{position:relative}" +
    ".dl-btn.en-titulo{position:static;display:inline-grid;vertical-align:middle;margin-left:8px;width:26px;height:26px;font-size:13px;opacity:.6}";
  document.head.appendChild(css);

  function cargar() {
    if (window.html2canvas) return Promise.resolve(window.html2canvas);
    if (h2c) return h2c;
    h2c = new Promise(function (ok, mal) {
      var s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
      s.onload = function () { ok(window.html2canvas); };
      s.onerror = mal;
      document.head.appendChild(s);
    });
    return h2c;
  }

  var TIT = "h1,h2,h3,h4,.g-h3,.titulo,[class~=uppercase]";
  function cabeza(el) {
    var l = el.querySelectorAll(TIT);
    for (var i = 0; i < l.length; i++) {
      var n = l[i], t = (n.textContent || "").trim();
      if (n.closest("button,a,select,label") || !t || t.length > 90) continue;
      return n;
    }
    return null;
  }
  function titulo(el) {
    var t = cabeza(el);
    return ((t && t.textContent) || "datalab-ec").replace("⬇", "").trim().replace(/\s+/g, " ");
  }

  function nombre(el) {
    var d = new Date(), p = function (n) { return String(n).padStart(2, "0"); };
    var slug = titulo(el).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
    return "datalab-ec-" + (slug || "grafico") + "-" + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "-" + p(d.getHours()) + p(d.getMinutes()) + ".png";
  }

  function fondo(el) {
    var c = getComputedStyle(document.body).backgroundColor;
    return c && c !== "rgba(0, 0, 0, 0)" ? c : "#071a22";
  }

  function bajar(el, btn) {
    btn.setAttribute("aria-busy", "true"); btn.textContent = "…";
    cargar().then(function (html2canvas) {
      return html2canvas(el, {
        backgroundColor: fondo(el), scale: Math.min(2, Math.max(1.5, window.devicePixelRatio || 1)), useCORS: true, logging: false,
        ignoreElements: function (n) { return n.classList && n.classList.contains("dl-btn"); },
        onclone: function (doc, copia) {
          copia.style.height = "auto"; copia.style.minHeight = "0"; copia.style.alignSelf = "start";
          // controles que no sirven en una imagen (deslizadores, play)
          copia.querySelectorAll('input[type=range],.play,[data-dl-ocultar]').forEach(function (n) { n.style.visibility = "hidden"; });
          // tablas con barra de desplazamiento: se muestran completas en la imagen
          copia.querySelectorAll("*").forEach(function (n) {
            var st = doc.defaultView.getComputedStyle(n);
            if ((st.overflowY === "auto" || st.overflowY === "scroll") && n.scrollHeight > n.clientHeight + 4) { n.style.maxHeight = "none"; n.style.overflow = "visible"; }
          });
        }
      });
    }).then(function (cv) {
      var k = cv.width / el.offsetWidth, pie = Math.round(46 * k), pad = Math.round(16 * k);
      var out = document.createElement("canvas");
      out.width = cv.width + 2 * pad; out.height = cv.height + pie + 2 * pad;
      var x = out.getContext("2d");
      x.fillStyle = fondo(el); x.fillRect(0, 0, out.width, out.height);
      x.drawImage(cv, pad, pad);
      var y = pad + cv.height + pie * 0.62, d = new Date();
      x.textBaseline = "middle";
      x.font = "700 " + Math.round(15 * k) + "px Inter, system-ui, sans-serif"; x.fillStyle = "#7dd3fc"; x.textAlign = "left";
      x.fillText("@DataLabEc", pad, y);
      var ancho = x.measureText("@DataLabEc").width;
      x.font = Math.round(12 * k) + "px Inter, system-ui, sans-serif"; x.fillStyle = "#8fb3ba";
      x.fillText("  ·  " + d.getDate() + " " + MES[d.getMonth()] + " " + d.getFullYear() + ", " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"), pad + ancho, y);
      x.textAlign = "right"; x.fillText(CREDITO, out.width - pad, y);
      out.toBlob(function (b) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(b); a.download = nombre(el);
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
      }, "image/png");
    }).catch(function (e) {
      console.warn("descarga", e); alert("No se pudo crear la imagen. Intenta de nuevo cuando termine de cargar.");
    }).then(function () { btn.removeAttribute("aria-busy"); btn.textContent = "⬇"; });
  }

  function poner() {
    document.querySelectorAll(SEL).forEach(function (el) {
      if (el.querySelector(".dl-btn") || (EXCLUIR && el.matches(EXCLUIR))) return;
      if (el.querySelector(SEL)) return;                 // solo la caja más interna
      if (el.offsetParent === null && !el.closest("[hidden]")) return;
      el.dataset.dl = "1";
      if (getComputedStyle(el).position === "static") el.classList.add("dl-con");
      var b = document.createElement("button");
      b.type = "button"; b.className = "dl-btn"; b.textContent = "⬇";
      b.title = "Descargar como imagen"; b.setAttribute("aria-label", "Descargar «" + titulo(el) + "» como imagen");
      b.addEventListener("click", function (ev) { ev.preventDefault(); ev.stopPropagation(); bajar(el, b); });
      var h = cabeza(el);
      if (h) { b.classList.add("en-titulo"); h.appendChild(b); } else el.appendChild(b);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", poner); else poner();
  new MutationObserver(function () { clearTimeout(poner.t); poner.t = setTimeout(poner, 300); }).observe(document.body, { childList: true, subtree: true });
  window.DataLabDescargar = { poner: poner };
})();
