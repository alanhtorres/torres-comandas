(function () {
  "use strict";
  const { api, moeda, el, minutosDesde, aviso, bip } = window.C;
  const $ = (id) => document.getElementById(id);

  let produtos = [];
  let categoriaAtiva = null;
  let carrinho = []; // {produto, quantidade, observacao}
  let prontosVistos = null;
  let chamadosVistos = null;

  // O guichê fica gravado neste aparelho (cada caixa tem o seu).
  try { $("guiche").value = localStorage.getItem("guiche") || ""; } catch (e) { /* sem storage */ }
  $("guiche").addEventListener("change", () => {
    try { localStorage.setItem("guiche", $("guiche").value.trim()); } catch (e) { /* sem storage */ }
  });

  // --- Montagem do pedido ------------------------------------------------

  function renderCategorias() {
    const cats = [...new Set(produtos.map((p) => p.categoria))];
    if (categoriaAtiva && !cats.includes(categoriaAtiva)) categoriaAtiva = null;
    $("categorias").replaceChildren(
      el("button", { class: categoriaAtiva === null ? "ativo" : "", onclick: () => { categoriaAtiva = null; renderCategorias(); renderProdutos(); } }, "Todos"),
      ...cats.map((c) => el("button", {
        class: categoriaAtiva === c ? "ativo" : "",
        onclick: () => { categoriaAtiva = c; renderCategorias(); renderProdutos(); },
      }, c))
    );
  }

  function renderProdutos() {
    const busca = $("busca").value.trim().toLowerCase();
    const lista = produtos.filter((p) =>
      (categoriaAtiva === null || p.categoria === categoriaAtiva) &&
      (!busca || p.nome.toLowerCase().includes(busca)));
    if (!produtos.length) {
      $("produtos").replaceChildren(el("div", { class: "vazio" }, "Nenhum produto cadastrado. ", el("a", { href: "/admin" }, "Cadastrar cardápio")));
      return;
    }
    $("produtos").replaceChildren(...lista.map((p) =>
      el("button", { class: "produto-btn", onclick: () => adicionar(p) },
        p.foto ? el("img", { src: "/foto/" + p.foto, alt: "", loading: "lazy" }) : null,
        el("span", { class: "info" }, el("span", { class: "nome" }, p.nome), el("span", { class: "preco" }, moeda(p.preco_centavos))))
    ));
  }

  function adicionar(produto) {
    const existente = carrinho.find((i) => i.produto.id === produto.id && !i.observacao);
    if (existente) existente.quantidade++;
    else carrinho.push({ produto, quantidade: 1, observacao: "" });
    renderCarrinho();
  }

  function renderCarrinho() {
    const total = carrinho.reduce((s, i) => s + i.produto.preco_centavos * i.quantidade, 0);
    $("total").textContent = moeda(total);
    $("qtd-itens").textContent = carrinho.reduce((s, i) => s + i.quantidade, 0);
    $("enviar").disabled = !carrinho.length;
    if (!carrinho.length) {
      $("itens-carrinho").replaceChildren(el("div", { class: "vazio" }, "Toque nos produtos acima para adicionar."));
      return;
    }
    $("itens-carrinho").replaceChildren(...carrinho.map((item, idx) =>
      el("div", { class: "item-carrinho" },
        el("div", { class: "qtd" },
          el("button", { onclick: () => { item.quantidade--; if (item.quantidade < 1) carrinho.splice(idx, 1); renderCarrinho(); } }, "−"),
          el("span", {}, item.quantidade),
          el("button", { onclick: () => { item.quantidade++; renderCarrinho(); } }, "+")),
        el("div", {}, item.produto.nome, item.observacao ? el("div", { class: "obs-item" }, "» " + item.observacao) : null),
        el("button", { class: "discreto", title: "Observação do item", onclick: () => {
          const obs = prompt("Observação para " + item.produto.nome + " (ex.: sem cebola):", item.observacao);
          if (obs !== null) { item.observacao = obs.trim(); renderCarrinho(); }
        } }, "✏️"),
        el("span", {}, moeda(item.produto.preco_centavos * item.quantidade)))
    ));
  }

  $("busca").addEventListener("input", renderProdutos);
  $("limpar").addEventListener("click", () => {
    carrinho = [];
    $("cliente").value = $("mesa").value = $("obs").value = "";
    renderCarrinho();
  });

  $("enviar").addEventListener("click", async () => {
    $("enviar").disabled = true;
    try {
      const r = await api("POST", "/api/pedidos", {
        itens: carrinho.map((i) => ({ produto_id: i.produto.id, quantidade: i.quantidade, observacao: i.observacao })),
        cliente: $("cliente").value, mesa: $("mesa").value, observacao: $("obs").value,
      });
      aviso("Pedido nº " + r.pedido.codigo + " enviado para a cozinha", "ok");
      carrinho = [];
      $("cliente").value = $("mesa").value = $("obs").value = "";
      renderCarrinho();
      monitor.forcar();
    } catch (err) {
      aviso(err.message, "erro");
      $("enviar").disabled = false;
    }
  });

  // --- Ações sobre pedidos -------------------------------------------------

  async function acao(url, corpo, msgOk) {
    try {
      await api("POST", url, corpo || {});
      if (msgOk) aviso(msgOk, "ok");
      monitor.forcar();
    } catch (err) {
      aviso(err.message, "erro");
    }
  }

  function descricaoOrigem(p) {
    const partes = [];
    if (p.origem === "qrcode") partes.push(el("span", { class: "etiqueta qrcode" }, "QR code"));
    if (p.mesa) partes.push("Mesa " + p.mesa);
    if (p.cliente) partes.push(p.cliente);
    return partes;
  }

  function cartaoPedido(p) {
    const botoes = [];
    if (p.status === "pronto") {
      botoes.push(el("button", { class: "verde", onclick: () => acao(`/api/pedidos/${p.id}/chamar`, {}, `Pedido ${p.codigo} chamado no painel`) }, "📢 Chamar no painel"));
    } else if (p.status === "chamado") {
      botoes.push(el("button", { onclick: () => acao(`/api/pedidos/${p.id}/chamar`, {}, "Chamado de novo") }, "🔁 Chamar de novo"));
      botoes.push(el("button", { class: "verde", onclick: () => acao(`/api/pedidos/${p.id}/status`, { status: "entregue" }) }, "✓ Entregue"));
    } else {
      botoes.push(el("button", { onclick: () => acao(`/api/pedidos/${p.id}/status`, { status: "pronto" }) }, "Marcar pronto"));
      botoes.push(el("button", { onclick: () => acao(`/api/pedidos/${p.id}/chamar`, {}, `Pedido ${p.codigo} chamado no painel`) }, "📢 Chamar"));
    }
    if (estado.impressora_cozinha_ativa) {
      botoes.push(el("button", { class: "discreto", title: "Reimprimir na cozinha", onclick: () => acao(`/api/pedidos/${p.id}/imprimir`, {}, "Enviado para a impressora") }, "🖨️"));
    }
    botoes.push(el("button", { class: "discreto", title: "Cancelar pedido", onclick: () => {
      if (confirm("Cancelar o pedido nº " + p.codigo + "?")) acao(`/api/pedidos/${p.id}/status`, { status: "cancelado" }, "Pedido cancelado");
    } }, "✕"));

    const impressao = p.impressao && p.impressao.startsWith("erro")
      ? el("span", { class: "etiqueta erro", title: p.impressao }, "falha na impressão") : null;

    return el("div", { class: "pedido " + p.status },
      el("div", { class: "cabeca" },
        el("span", { class: "numero" }, "#" + p.codigo),
        el("span", { class: "etiqueta " + p.status }, window.C.STATUS_NOME[p.status]),
        impressao,
        el("span", { class: "quem" }, ...descricaoOrigem(p).flatMap((x, i) => (i ? [" · ", x] : [x]))),
        el("span", { class: "espaco" }),
        el("span", { class: "quem" }, minutosDesde(p.criado_em) + " min"),
        el("strong", {}, moeda(p.total_centavos))),
      el("div", { class: "itens" }, p.itens.map((i) => `${i.quantidade}× ${i.nome}${i.observacao ? " (" + i.observacao + ")" : ""}`).join(" · ")),
      p.observacao ? el("div", { class: "itens", style: "color: var(--amarelo)" }, "Obs: " + p.observacao) : null,
      el("div", { class: "acoes" }, botoes));
  }

  function preencherLista(id, contadorId, pedidos, textoVazio) {
    $(contadorId).textContent = pedidos.length;
    $(id).replaceChildren(...(pedidos.length ? pedidos.map(cartaoPedido) : [el("div", { class: "vazio" }, textoVazio)]));
  }

  // --- Senhas ---------------------------------------------------------------

  async function emitir(prefixo) {
    try {
      const r = await api("POST", "/api/senhas", { prefixo });
      aviso("Senha " + r.senha.codigo + " emitida", "ok");
      monitor.forcar();
    } catch (err) {
      aviso(err.message, "erro");
    }
  }
  $("emitir-N").addEventListener("click", () => emitir("N"));
  $("emitir-P").addEventListener("click", () => emitir("P"));
  $("chamar-proxima").addEventListener("click", async () => {
    try {
      const r = await api("POST", "/api/senhas/chamar-proxima", { guiche: $("guiche").value.trim() });
      aviso("Chamando senha " + r.senha.codigo, "ok");
      monitor.forcar();
    } catch (err) {
      aviso(err.message, "erro");
    }
  });

  // --- Atualização periódica ---------------------------------------------

  let estado = {};

  function aplicarEstado(dados) {
    estado = dados;
    $("nome-loja").textContent = "— " + dados.loja;

    const idsProdutos = JSON.stringify(dados.produtos.map((p) => [p.id, p.nome, p.preco_centavos, p.foto, p.categoria]));
    if (idsProdutos !== JSON.stringify(produtos.map((p) => [p.id, p.nome, p.preco_centavos, p.foto, p.categoria]))) {
      produtos = dados.produtos;
      carrinho = carrinho.filter((i) => produtos.some((p) => p.id === i.produto.id));
      renderCategorias();
      renderProdutos();
      renderCarrinho();
    }

    const prontos = dados.pedidos.filter((p) => p.status === "pronto");
    const cozinha = dados.pedidos.filter((p) => p.status === "novo" || p.status === "preparando");
    const chamados = dados.pedidos.filter((p) => p.status === "chamado").reverse();
    preencherLista("lista-prontos", "n-prontos", prontos, "Nenhum pedido pronto esperando chamada.");
    preencherLista("lista-cozinha", "n-cozinha", cozinha, "Nenhum pedido na cozinha.");
    preencherLista("lista-chamados", "n-chamados", chamados, "Ninguém aguardando retirada.");

    // Avisos sonoros: pedido que acabou de ficar pronto e chamado de garçom novo.
    const idsProntos = new Set(prontos.map((p) => p.id));
    if (prontosVistos && [...idsProntos].some((id) => !prontosVistos.has(id))) bip("novo");
    prontosVistos = idsProntos;

    const idsChamados = new Set(dados.chamados_garcom.map((c) => c.id));
    if (chamadosVistos && [...idsChamados].some((id) => !chamadosVistos.has(id))) bip("garcom");
    chamadosVistos = idsChamados;

    $("chamados-garcom").replaceChildren(...dados.chamados_garcom.map((c) =>
      el("div", { class: "alerta-garcom" },
        (c.tipo === "conta" ? "🧾 Mesa " + c.mesa + " pediu a conta" : "🙋 Mesa " + c.mesa + " chamou o garçom"),
        el("span", { style: "font-weight: 400; opacity: .8" }, "há " + minutosDesde(c.criado_em) + " min"),
        el("button", { onclick: () => acao(`/api/garcom/${c.id}/atender`) }, "Atendido"))));

    $("fila-N").textContent = dados.senhas.aguardando.N || 0;
    $("fila-P").textContent = dados.senhas.aguardando.P || 0;
    $("chamar-proxima").disabled = !dados.senhas.total;
    $("senhas-chamadas").replaceChildren(...dados.senhas_chamadas.map((s) =>
      el("div", { class: "senha-chamada" },
        el("strong", {}, s.codigo),
        el("span", { class: "rotulo" }, s.guiche ? "Guichê " + s.guiche : "sem guichê"),
        el("span", { class: "espaco" }),
        el("button", { class: "discreto", onclick: () => acao(`/api/pedidos/${s.id}/chamar`, {}, "Chamada de novo") }, "🔁"),
        el("button", { class: "discreto", onclick: () => acao(`/api/pedidos/${s.id}/status`, { status: "entregue" }) }, "✓ Atendida"))));
  }

  renderCarrinho();
  const monitor = C.acompanhar("/api/estado", aplicarEstado, 2000);
  // Atualiza os "há X min" mesmo sem nada mudar no servidor.
  setInterval(() => monitor.forcar(), 30000);
})();
