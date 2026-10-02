(function () {
  "use strict";
  const { api, el, minutosDesde, aviso, bip, somLiberado, liberarSom } = window.C;
  const $ = (id) => document.getElementById(id);

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
      await api("POST", `/api/pedidos/${p.id}/status`, { status });
      if (status === "pronto") {
        recentes = [p, ...recentes.filter((r) => r.id !== p.id)].slice(0, 5);
        aviso("Pedido " + p.codigo + " pronto — o caixa foi avisado", "ok");
      }
      monitor.forcar();
    } catch (err) {
      aviso(err.message, "erro");
    }
  }

  function render() {
    // Só pedidos com algo para preparar, e só os itens de preparo
    // (bebida em lata, chips etc. ficam com o caixa/garçom).
    const fila = pedidos.filter((p) => p.vai_cozinha && (p.status === "novo" || p.status === "preparando"));
    $("n-fila").textContent = fila.filter((p) => p.status === "novo").length + " na fila";
    $("n-preparo").textContent = fila.filter((p) => p.status === "preparando").length + " em preparo";
    if (!fila.length) {
      $("pedidos").replaceChildren(el("div", { class: "vazio-cozinha" }, "Nenhum pedido para preparar 👌"));
    } else {
      $("pedidos").replaceChildren(...fila.map((p) => {
        const min = minutosDesde(p.criado_em);
        const classe = "ticket " + p.status + (min >= 20 ? " muito-atrasado" : min >= 10 ? " atrasado" : "");
        const origem = [{ qrcode: "QR code", garcom: "Garçom " + (p.usuario_nome || "") }[p.origem] || "Caixa",
          p.mesa ? "Mesa " + p.mesa : null, p.cliente || null].filter(Boolean).join(" · ");
        const outros = p.itens.filter((i) => !i.vai_cozinha);
        return el("article", { class: classe },
          el("div", { class: "cabeca" },
            el("span", { class: "numero" }, "#" + p.codigo),
            el("span", { class: "origem" }, origem),
            el("span", { class: "tempo" }, tempo(p))),
          el("ul", {}, p.itens.filter((i) => i.vai_cozinha).map((i) => el("li", {},
            el("span", { class: "qtd" }, i.quantidade + "×"), i.nome,
            i.observacao ? el("span", { class: "obs" }, "» " + i.observacao) : null))),
          p.observacao ? el("div", { class: "obs-geral" }, "⚠ " + p.observacao) : null,
          outros.length ? el("div", { class: "outros-itens" }, "Sai pelo caixa: " + outros.map((i) => i.quantidade + "× " + i.nome).join(", ")) : null,
          el("div", { class: "acoes" },
            p.status === "novo" ? el("button", { class: "amarelo", onclick: () => mudar(p, "preparando") }, "Iniciar preparo") : null,
            el("button", { class: "verde", onclick: () => mudar(p, "pronto") }, "✓ Pronto")));
      }));
    }
    const ativos = new Set(pedidos.map((p) => p.id + ":" + p.status));
    recentes = recentes.filter((r) => ativos.has(r.id + ":pronto"));
    $("prontos-recentes").replaceChildren(...(recentes.length ? [
      "Marcou pronto por engano? ",
      ...recentes.map((r) => el("button", { onclick: () => mudar(r, "preparando") }, "↩ Voltar #" + r.codigo + " para a fila")),
    ] : []));
  }

  function aplicar(dados) {
    pedidos = dados.pedidos;
    const ids = new Set(pedidos.filter((p) => p.vai_cozinha && p.status === "novo").map((p) => p.id));
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
