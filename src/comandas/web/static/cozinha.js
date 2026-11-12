(function () {
  "use strict";
  const { api, el, minutosDesde, aviso, bip, somLiberado, liberarSom } = window.C;
  const $ = (id) => document.getElementById(id);
  // A mesma tela serve para a cozinha e para o bar (cada um com o seu "pronto").
  const SETOR = document.body.dataset.setor || "cozinha";
  const OUTROS = { cozinha: "Sai na cozinha: ", bar: "Sai no bar: " };
  const naFila = (p) => ["novo", "preparando"].includes((p.preparo || {})[SETOR]);

  let pedidos = [];
  let vistos = null;
  // Pedido marcado como pronto por engano pode voltar pra fila por um tempo.
  let recentes = [];

  function tempo(p) {
    const min = minutosDesde(p.criado_em);
    return min < 1 ? "agora" : min + " min";
  }

  async function mudar(p, status) {
    try {
      await api("POST", `/api/pedidos/${p.id}/status`, { status, setor: SETOR });
      if (status === "pronto") {
        recentes = [p, ...recentes.filter((r) => r.id !== p.id)].slice(0, 5);
        aviso("Pedido " + p.codigo + " pronto" + (SETOR === "bar" ? " no bar" : "") + " — o caixa foi avisado", "ok");
      }
      monitor.forcar();
    } catch (err) {
      aviso(err.message, "erro");
    }
  }

  function render() {
    // Só pedidos com algo para preparar, e só os itens de preparo
    // (bebida em lata, chips etc. ficam com o caixa/garçom).
    const fila = pedidos.filter(naFila);
    const situacao = (p) => p.preparo[SETOR];
    $("n-fila").textContent = fila.filter((p) => situacao(p) === "novo").length + " na fila";
    $("n-preparo").textContent = fila.filter((p) => situacao(p) === "preparando").length + " em preparo";
    if (!fila.length) {
      $("pedidos").replaceChildren(el("div", { class: "vazio-cozinha" }, "Nenhum pedido para preparar 👌"));
    } else {
      $("pedidos").replaceChildren(...fila.map((p) => {
        const min = minutosDesde(p.criado_em);
        const classe = "ticket " + situacao(p) + (min >= 20 ? " muito-atrasado" : min >= 10 ? " atrasado" : "");
        const origem = [{ qrcode: "QR code", garcom: "Garçom " + (p.usuario_nome || "") }[p.origem] || "Caixa",
          p.entrega ? "🛵 DELIVERY" : null, p.mesa ? "Mesa " + p.mesa : null, p.cliente || null].filter(Boolean).join(" · ");
        const lista = (itens) => itens.map((i) => i.quantidade + "× " + i.nome).join(", ");
        const outroSetor = SETOR === "bar" ? "cozinha" : "bar";
        const doOutro = p.itens.filter((i) => i.setor === outroSetor);
        const prontos = p.itens.filter((i) => i.setor === "nenhum");
        return el("article", { class: classe },
          el("div", { class: "cabeca" },
            el("span", { class: "numero" }, "#" + p.codigo),
            el("span", { class: "origem" }, origem),
            el("span", { class: "tempo" }, tempo(p))),
          el("ul", {}, p.itens.filter((i) => i.setor === SETOR).map((i) => el("li", {},
            el("span", { class: "qtd" }, i.quantidade + "×"), i.nome,
            i.observacao ? el("span", { class: "obs" }, "» " + i.observacao) : null))),
          p.observacao ? el("div", { class: "obs-geral" }, "⚠ " + p.observacao) : null,
          doOutro.length ? el("div", { class: "outros-itens" }, OUTROS[outroSetor] + lista(doOutro)) : null,
          prontos.length ? el("div", { class: "outros-itens" }, "Sai pelo caixa: " + lista(prontos)) : null,
          el("div", { class: "acoes" },
            situacao(p) === "novo" ? el("button", { class: "amarelo", onclick: () => mudar(p, "preparando") }, "Iniciar preparo") : null,
            el("button", { class: "verde", onclick: () => mudar(p, "pronto") }, "✓ Pronto")));
      }));
    }
    // "voltar para a fila" enquanto o pedido ainda não foi chamado no painel
    const prontosAqui = new Set(pedidos.filter((p) => (p.preparo || {})[SETOR] === "pronto"
      && ["preparando", "pronto"].includes(p.status)).map((p) => p.id));
    recentes = recentes.filter((r) => prontosAqui.has(r.id));
    $("prontos-recentes").replaceChildren(...(recentes.length ? [
      "Marcou pronto por engano? ",
      ...recentes.map((r) => el("button", { onclick: () => mudar(r, "preparando") }, "↩ Voltar #" + r.codigo + " para a fila")),
    ] : []));
  }

  function aplicar(dados) {
    pedidos = dados.pedidos;
    const ids = new Set(pedidos.filter((p) => (p.preparo || {})[SETOR] === "novo").map((p) => p.id));
    if (vistos && [...ids].some((id) => !vistos.has(id))) bip("novo");
    vistos = ids;
    render();
  }

  function relogio() {
    $("relogio").textContent = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  relogio();
  setInterval(() => { relogio(); render(); $("ativar-som").hidden = somLiberado(); }, 15000);
  setTimeout(() => ($("ativar-som").hidden = somLiberado()), 1500);
  $("ativar-som").addEventListener("click", () => { liberarSom(); bip("novo"); $("ativar-som").hidden = true; });

  const monitor = C.acompanhar("/api/estado", aplicar, 2000);
})();
