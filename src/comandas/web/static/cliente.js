(function () {
  "use strict";
  const { api, moeda, el, aviso } = window.C;
  const $ = (id) => document.getElementById(id);
  const token = document.body.dataset.token;
  const base = "/api/cliente/" + encodeURIComponent(token);

  let produtos = [];
  let assinaturaProdutos = "";
  let pedidosAtivos = true;
  // produto_id -> {quantidade, observacao}
  const carrinho = new Map();

  try {
    $("nome-cliente").value = localStorage.getItem("nome-cliente") || "";
  } catch (e) { /* sem storage */ }

  function renderCardapio() {
    const categorias = [...new Set(produtos.map((p) => p.categoria))];
    $("categorias").replaceChildren(...categorias.map((c, i) =>
      el("a", { href: "#cat-" + i, class: i === 0 ? "ativo" : "" }, c)));
    if (!produtos.length) {
      $("cardapio").replaceChildren(el("div", { class: "vazio" }, "Cardápio indisponível no momento."));
      return;
    }
    $("cardapio").replaceChildren(...categorias.flatMap((c, i) => [
      el("h2", { id: "cat-" + i }, c),
      ...produtos.filter((p) => p.categoria === c).map(cartaoProduto),
    ]));
  }

  function cartaoProduto(p) {
    const q = (carrinho.get(p.id) || {}).quantidade || 0;
    return el("div", { class: "produto", id: "produto-" + p.id },
      p.foto ? el("img", { src: "/foto/" + p.foto, alt: "", loading: "lazy" }) : null,
      el("div", { class: "info" },
        el("span", { class: "nome" }, p.nome),
        p.descricao ? el("span", { class: "desc" }, p.descricao) : null,
        el("div", { class: "rodape" },
          el("span", { class: "preco" }, moeda(p.preco_centavos)),
          pedidosAtivos ? el("div", { class: "qtd" },
            q ? el("button", { class: "menos", "aria-label": "Remover um", onclick: () => mudar(p, -1) }, "−") : null,
            q ? el("span", {}, q) : null,
            el("button", { "aria-label": "Adicionar", onclick: () => mudar(p, 1) }, "+")) : null)));
  }

  function mudar(p, delta) {
    const atual = carrinho.get(p.id) || { quantidade: 0, observacao: "" };
    atual.quantidade += delta;
    if (atual.quantidade <= 0) carrinho.delete(p.id);
    else carrinho.set(p.id, atual);
    const antigo = $("produto-" + p.id);
    if (antigo) antigo.replaceWith(cartaoProduto(p));
    renderCarrinho();
  }

  function totalCarrinho() {
    let total = 0, qtd = 0;
    for (const [id, item] of carrinho) {
      const p = produtos.find((x) => x.id === id);
      if (p) { total += p.preco_centavos * item.quantidade; qtd += item.quantidade; }
    }
    return { total, qtd };
  }

  function renderCarrinho() {
    const { total, qtd } = totalCarrinho();
    $("barra-carrinho").hidden = !qtd || !pedidosAtivos;
    $("barra-qtd").textContent = qtd;
    $("barra-total").textContent = moeda(total);
    $("total-folha").textContent = moeda(total);
    if (!qtd) { $("folha").hidden = true; }
    $("itens-folha").replaceChildren(...[...carrinho].map(([id, item]) => {
      const p = produtos.find((x) => x.id === id);
      if (!p) return null;
      return el("div", { class: "item-folha" },
        el("div", { class: "qtd" },
          el("button", { class: "menos", onclick: () => mudar(p, -1) }, "−"),
          el("span", {}, item.quantidade),
          el("button", { onclick: () => mudar(p, 1) }, "+")),
        el("div", { class: "nome" }, p.nome,
          item.observacao ? el("span", { class: "obs-item" }, "» " + item.observacao) : null,
          el("button", { class: "editar", onclick: () => {
            const obs = prompt("Observação para " + p.nome + ":", item.observacao);
            if (obs !== null) { item.observacao = obs.trim(); renderCarrinho(); }
          } }, item.observacao ? "editar observação" : "+ observação")),
        el("strong", {}, moeda(p.preco_centavos * item.quantidade)));
    }).filter(Boolean));
  }

  function renderPedidos(pedidos) {
    $("meus-pedidos").hidden = !pedidos.length;
    const nomes = { novo: "Recebido", preparando: "Preparando", pronto: "Pronto!", chamado: "Pronto! Pode retirar", entregue: "Entregue" };
    $("lista-pedidos").replaceChildren(...pedidos.slice().reverse().map((p) =>
      el("div", { class: "meu-pedido" },
        el("div", { class: "linha" },
          el("span", { class: "num" }, "Pedido nº " + p.codigo + (p.cliente ? " · " + p.cliente : "")),
          el("span", { class: "status " + p.status }, nomes[p.status] || p.status)),
        el("div", { class: "itens" }, p.itens.map((i) => i.quantidade + "× " + i.nome).join(", ") + " — " + moeda(p.total_centavos)))));
  }

  function aplicar(dados) {
    document.title = dados.loja + " — Cardápio";
    $("loja").textContent = dados.loja;
    $("mesa").textContent = "Mesa " + dados.mesa;
    const mudouAtivo = pedidosAtivos !== dados.pedidos_ativos;
    pedidosAtivos = dados.pedidos_ativos;
    $("aviso-desativado").hidden = pedidosAtivos;
    const assinatura = JSON.stringify(dados.produtos);
    if (assinatura !== assinaturaProdutos || mudouAtivo) {
      produtos = dados.produtos;
      assinaturaProdutos = assinatura;
      for (const id of [...carrinho.keys()]) if (!produtos.some((p) => p.id === id)) carrinho.delete(id);
      renderCardapio();
      renderCarrinho();
    }
    renderPedidos(dados.pedidos);
    $("chamar-garcom").classList.toggle("enviado", dados.chamados.includes("garcom"));
    $("pedir-conta").classList.toggle("enviado", dados.chamados.includes("conta"));
    $("chamar-garcom").textContent = dados.chamados.includes("garcom") ? "✓ Garçom a caminho" : "🙋 Chamar garçom";
    $("pedir-conta").textContent = dados.chamados.includes("conta") ? "✓ Conta solicitada" : "🧾 Pedir a conta";
  }

  async function atualizar() {
    try {
      const res = await fetch(base, { cache: "no-store" });
      if (res.status === 404) {
        document.body.replaceChildren(el("div", { class: "vazio" }, "Este QR code não é mais válido. Chame um atendente."));
        return;
      }
      aplicar(await res.json());
    } catch (e) { /* sem rede: tenta de novo no próximo ciclo */ }
    setTimeout(atualizar, 4000);
  }

  async function chamar(tipo) {
    try {
      await api("POST", base + "/chamar", { tipo });
      aviso(tipo === "conta" ? "Pronto! Já vamos trazer a conta." : "Pronto! Um garçom já vem até sua mesa.", "ok");
      const res = await fetch(base, { cache: "no-store" });
      aplicar(await res.json());
    } catch (err) {
      aviso(err.message, "erro");
    }
  }
  $("chamar-garcom").addEventListener("click", () => chamar("garcom"));
  $("pedir-conta").addEventListener("click", () => chamar("conta"));

  $("barra-carrinho").addEventListener("click", () => { renderCarrinho(); $("folha").hidden = false; });
  $("fechar-folha").addEventListener("click", () => ($("folha").hidden = true));
  $("folha").addEventListener("click", (e) => { if (e.target === $("folha")) $("folha").hidden = true; });

  $("confirmar").addEventListener("click", async () => {
    $("confirmar").disabled = true;
    const nome = $("nome-cliente").value.trim();
    try { localStorage.setItem("nome-cliente", nome); } catch (e) { /* sem storage */ }
    try {
      const r = await api("POST", base + "/pedido", {
        itens: [...carrinho].map(([id, i]) => ({ produto_id: id, quantidade: i.quantidade, observacao: i.observacao })),
        cliente: nome,
        observacao: $("obs-pedido").value,
      });
      carrinho.clear();
      $("obs-pedido").value = "";
      $("folha").hidden = true;
      renderCardapio();
      renderCarrinho();
      aviso("Pedido nº " + r.pedido.codigo + " enviado! Acompanhe o status aqui.", "ok");
      window.scrollTo({ top: 0, behavior: "smooth" });
      const res = await fetch(base, { cache: "no-store" });
      aplicar(await res.json());
    } catch (err) {
      aviso(err.message, "erro");
    } finally {
      $("confirmar").disabled = false;
    }
  });

  // destaca a categoria visível enquanto rola a página
  document.addEventListener("scroll", () => {
    const titulos = [...document.querySelectorAll("main h2")];
    let ativo = titulos[0];
    for (const t of titulos) if (t.getBoundingClientRect().top < 90) ativo = t;
    document.querySelectorAll(".categorias a").forEach((a) =>
      a.classList.toggle("ativo", ativo && a.getAttribute("href") === "#" + ativo.id));
  }, { passive: true });

  atualizar();
})();
