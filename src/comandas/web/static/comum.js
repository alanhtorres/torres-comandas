/* Utilitários compartilhados por todas as telas. */
(function () {
  "use strict";

  async function api(metodo, url, corpo) {
    const opcoes = { method: metodo, headers: {}, cache: "no-store" };
    if (corpo instanceof FormData) {
      opcoes.body = corpo;
    } else if (corpo !== undefined) {
      opcoes.headers["Content-Type"] = "application/json";
      opcoes.body = JSON.stringify(corpo);
    }
    const res = await fetch(url, opcoes);
    if (res.status === 401 && !url.startsWith("/api/cliente")) {
      location.href = "/login?proximo=" + encodeURIComponent(location.pathname);
      throw new Error("Sessão expirada.");
    }
    let dados = {};
    try {
      dados = await res.json();
    } catch (e) {
      if (!res.ok) throw new Error("Erro " + res.status + " no servidor.");
    }
    if (!res.ok || dados.ok === false) {
      throw new Error(dados.erro || "Erro " + res.status + " no servidor.");
    }
    return dados;
  }

  function moeda(centavos) {
    return (Number(centavos || 0) / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  // el("div", {class: "x", onclick: fn}, "texto", outroEl)
  function el(tag, props) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else if (v === true) node.setAttribute(k, "");
      else node.setAttribute(k, v);
    }
    for (let i = 2; i < arguments.length; i++) {
      const filho = arguments[i];
      if (filho === null || filho === undefined || filho === false) continue;
      if (Array.isArray(filho)) filho.forEach((f) => f && node.append(f));
      else node.append(filho instanceof Node ? filho : String(filho));
    }
    return node;
  }

  function minutosDesde(ts) {
    return Math.max(0, Math.floor((Date.now() / 1000 - ts) / 60));
  }

  function hora(ts) {
    return new Date(ts * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }

  let toastTimer = null;
  function aviso(msg, tipo) {
    let box = document.getElementById("aviso-flutuante");
    if (!box) {
      box = el("div", { id: "aviso-flutuante" });
      document.body.append(box);
    }
    box.textContent = msg;
    box.className = "visivel " + (tipo || "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (box.className = ""), 3500);
  }

  // --- Som (gerado na hora, sem arquivo de áudio) -------------------------
  // Navegadores só liberam som depois de um toque/clique na página; o
  // primeiro clique em qualquer lugar já destrava.
  let audioCtx = null;
  function contexto() {
    if (!audioCtx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      audioCtx = new Ctx();
    }
    return audioCtx;
  }
  function somLiberado() {
    const ctx = contexto();
    return !!ctx && ctx.state === "running";
  }
  function liberarSom() {
    const ctx = contexto();
    if (ctx && ctx.state !== "running") ctx.resume().catch(() => {});
  }
  document.addEventListener("click", liberarSom, true);
  document.addEventListener("keydown", liberarSom, true);
  document.addEventListener("touchstart", liberarSom, true);

  function bip(tipo) {
    const ctx = contexto();
    if (!ctx) return;
    if (ctx.state !== "running") ctx.resume().catch(() => {});
    const notas = {
      chamada: [[660, 0], [880, 0.28], [1100, 0.56]],
      novo: [[880, 0], [880, 0.2]],
      garcom: [[1000, 0], [750, 0.18], [1000, 0.36], [750, 0.54]],
    }[tipo || "novo"];
    const t0 = ctx.currentTime + 0.02;
    for (const [freq, atraso] of notas) {
      const osc = ctx.createOscillator();
      const ganho = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      ganho.gain.setValueAtTime(0.0001, t0 + atraso);
      ganho.gain.exponentialRampToValueAtTime(0.4, t0 + atraso + 0.02);
      ganho.gain.exponentialRampToValueAtTime(0.0001, t0 + atraso + 0.45);
      osc.connect(ganho).connect(ctx.destination);
      osc.start(t0 + atraso);
      osc.stop(t0 + atraso + 0.5);
    }
  }

  function falar(texto) {
    if (!("speechSynthesis" in window)) return;
    const fala = new SpeechSynthesisUtterance(texto);
    fala.lang = "pt-BR";
    fala.rate = 0.95;
    window.speechSynthesis.speak(fala);
  }

  // Consulta periódica com "versão": o servidor só devolve os dados quando
  // algo mudou, então dá pra consultar a cada 2 s sem pesar na rede.
  function acompanhar(url, aoMudar, intervaloMs) {
    let versao = null;
    let falhas = 0;
    let timer = null;
    let emAndamento = false;
    let repetir = false;
    const barra = document.getElementById("sem-conexao");
    async function rodada() {
      clearTimeout(timer);
      if (emAndamento) {
        repetir = true;
        return;
      }
      emAndamento = true;
      try {
        const sep = url.includes("?") ? "&" : "?";
        const res = await fetch(url + (versao ? sep + "v=" + versao : ""), { cache: "no-store" });
        if (res.status === 401) {
          location.href = "/login?proximo=" + encodeURIComponent(location.pathname);
          return;
        }
        if (!res.ok) throw new Error("HTTP " + res.status);
        const dados = await res.json();
        falhas = 0;
        if (barra) barra.hidden = true;
        if (dados.mudou !== false) {
          versao = dados.versao;
          aoMudar(dados);
        }
      } catch (err) {
        falhas++;
        if (barra && falhas >= 2) barra.hidden = false;
      } finally {
        emAndamento = false;
      }
      if (repetir) {
        repetir = false;
        rodada();
      } else {
        timer = setTimeout(rodada, intervaloMs || 2000);
      }
    }
    rodada();
    return {
      // Atualiza já (depois de um clique), sem esperar a próxima consulta.
      forcar() {
        versao = null;
        rodada();
      },
    };
  }

  const STATUS_NOME = {
    novo: "Na fila",
    preparando: "Preparando",
    pronto: "Pronto",
    chamado: "Chamado no painel",
    entregue: "Entregue",
    cancelado: "Cancelado",
  };

  window.C = { api, moeda, el, minutosDesde, hora, aviso, bip, falar, somLiberado, liberarSom, acompanhar, STATUS_NOME };
})();
