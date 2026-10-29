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

  // Converte o que foi digitado ("12,50", "12.50", "1.234,50", "R$ 3") em centavos.
  function centavos(texto) {
    const limpo = String(texto || "").replace(/[^\d,.-]/g, "");
    if (!limpo) return 0;
    const normalizado = limpo.includes(",") ? limpo.replace(/\./g, "").replace(",", ".") : limpo;
    const valor = Number(normalizado);
    return Number.isFinite(valor) ? Math.round(valor * 100) : NaN;
  }

  function reais(c) {
    return (Number(c || 0) / 100).toFixed(2).replace(".", ",");
  }

  function campoDinheiro(props) {
    return el("input", Object.assign({ type: "text", inputmode: "decimal", placeholder: "0,00", autocomplete: "off" }, props || {}));
  }

  // Janela de diálogo. `aoConfirmar` pode ser assíncrona; se der erro, a
  // mensagem aparece na própria janela (que continua aberta).
  function dialogo(opcoes) {
    const o = Object.assign({ confirmar: "Confirmar", cancelar: "Cancelar" }, opcoes);
    const d = el("dialog", { class: "dialogo" + (o.largo ? " largo" : "") });
    const erro = el("p", { class: "erro-dialogo", hidden: true });
    const btnOk = o.confirmar ? el("button", { class: (o.perigo ? "perigo" : "primario") + " grande", type: "submit" }, o.confirmar) : null;
    const form = el("form", { method: "dialog" },
      el("h2", {}, o.titulo),
      o.corpo,
      erro,
      el("div", { class: "acoes-dialogo" },
        o.cancelar ? el("button", { type: "button", class: "discreto", onclick: () => fechar() }, o.cancelar) : null,
        btnOk));
    function fechar() {
      if (d.open) d.close();
      d.remove();
    }
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!o.aoConfirmar) return fechar();
      btnOk.disabled = true;
      erro.hidden = true;
      try {
        const r = await o.aoConfirmar();
        if (r !== false) fechar();
      } catch (err) {
        erro.textContent = err.message;
        erro.hidden = false;
      } finally {
        btnOk.disabled = false;
      }
    });
    d.addEventListener("close", () => d.remove());
    d.append(form);
    document.body.append(d);
    d.showModal();
    const primeiro = d.querySelector("input:not([type=checkbox]), select, textarea");
    if (primeiro) primeiro.focus();
    return { fechar, elemento: d };
  }

  function dataHora(ts) {
    return new Date(ts * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function hojeISO(deslocamentoDias) {
    const d = new Date();
    d.setDate(d.getDate() + (deslocamentoDias || 0));
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  // --- Clientes e WhatsApp -------------------------------------------------

  function mascaraTelefone(valor) {
    const d = String(valor || "").replace(/\D/g, "").slice(0, 11);
    if (d.length <= 2) return d;
    if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
    if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
    return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  }

  function mascaraCpf(valor) {
    const d = String(valor || "").replace(/\D/g, "").slice(0, 11);
    return d.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
  }

  // Formulário de cadastro de cliente (nome e telefone obrigatórios).
  function formCliente(c) {
    c = c || {};
    const campo = (props) => el("input", props);
    const nome = campo({ maxlength: 80, required: true, value: c.nome || "", autocomplete: "off" });
    const tel = campo({ inputmode: "tel", required: true, placeholder: "(11) 98765-4321", value: mascaraTelefone(c.telefone || "") });
    const cpf = campo({ inputmode: "numeric", placeholder: "Opcional", value: c.cpf ? mascaraCpf(c.cpf) : "" });
    const nasc = campo({ type: "date", value: c.nascimento || "" });
    const aceita = el("input", { type: "checkbox", checked: !!c.aceita_mensagens });
    const obs = campo({ maxlength: 300, placeholder: "Opcional", value: c.observacao || "" });
    tel.addEventListener("input", () => (tel.value = mascaraTelefone(tel.value)));
    cpf.addEventListener("input", () => (cpf.value = mascaraCpf(cpf.value)));
    const elemento = el("div", { class: "form-cliente" },
      el("label", {}, "Nome completo *"), nome,
      el("div", { class: "campos-duplos" },
        el("div", {}, el("label", {}, "Telefone (WhatsApp) *"), tel),
        el("div", {}, el("label", {}, "CPF"), cpf)),
      el("div", { class: "campos-duplos" },
        el("div", {}, el("label", {}, "Data de nascimento"), nasc),
        el("div", {}, el("label", {}, "Observação"), obs)),
      el("label", { class: "inline consentimento" }, aceita,
        "O cliente autoriza receber mensagens de promoções, eventos e aniversário pelo WhatsApp"));
    return {
      elemento,
      valores: () => ({ nome: nome.value, telefone: tel.value, cpf: cpf.value, nascimento: nasc.value,
        aceita_mensagens: aceita.checked, observacao: obs.value }),
    };
  }

  // Troca {nome} (primeiro nome), {nome_completo} e {loja} na mensagem.
  function preencherMensagem(modelo, cliente, loja) {
    const primeiro = String(cliente.nome || "").trim().split(/\s+/)[0] || "";
    return String(modelo || "").replaceAll("{nome}", primeiro).replaceAll("{nome_completo}", cliente.nome || "")
      .replaceAll("{loja}", loja || "");
  }

  // Abre a conversa com a mensagem já escrita — só falta apertar "enviar".
  function abrirWhatsapp(telefone, texto, modo) {
    const numero = "55" + String(telefone).replace(/\D/g, "");
    const t = encodeURIComponent(texto);
    if (modo === "app") {
      location.href = `whatsapp://send?phone=${numero}&text=${t}`;
    } else if (modo === "link") {
      window.open(`https://wa.me/${numero}?text=${t}`, "_blank");
    } else {
      // Sempre na mesma aba do WhatsApp Web, para não abrir uma aba por cliente.
      window.open(`https://web.whatsapp.com/send?phone=${numero}&text=${t}`, "whatsapp_envio");
    }
  }

  const STATUS_NOME = {
    novo: "Na fila",
    preparando: "Preparando",
    pronto: "Pronto",
    chamado: "Chamado no painel",
    entregue: "Entregue",
    cancelado: "Cancelado",
  };

  window.C = { api, moeda, el, minutosDesde, hora, dataHora, hojeISO, aviso, bip, falar, somLiberado, liberarSom, acompanhar,
    centavos, reais, campoDinheiro, dialogo, STATUS_NOME, mascaraTelefone, mascaraCpf, formCliente,
    preencherMensagem, abrirWhatsapp };
})();
