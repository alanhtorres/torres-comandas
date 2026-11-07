(function () {
  "use strict";
  const { api, moeda, el, minutosDesde, aviso, bip, somLiberado, liberarSom, dialogo } = window.C;
  const $ = (id) => document.getElementById(id);

  let estado = { pedidos: [], contas: [], chamados_garcom: [], mesas: [], produtos: [] };
  let produtos = [];
  let assinaturaProdutos = "";
  let categoriaAtiva = null;
  let mesa = "";
  let comandaId = null;
  const carrinho = new Map(); // produto_id -> {quantidade, observacao}
  let chamadosVistos = null;
  let entregasVistas = null;

  // --- Abas ------------------------------------------------------------------

  document.querySelectorAll(".abas-rodape button").forEach((b) => b.addEventListener("click", () => abrirAba(b.dataset.aba)));
  function abrirAba(nome) {
    document.querySelectorAll(".abas-rodape button").forEach((b) => b.classList.toggle("ativa", b.dataset.aba === nome));
    document.querySelectorAll(".aba-garcom").forEach((s) => (s.hidden = s.id !== "aba-" + nome));
    renderBarra();
    window.scrollTo({ top: 0 });
  }
  const abaAtual = () => document.querySelector(".abas-rodape button.ativa").dataset.aba;

  // --- Alertas (chamados do QR code e pedidos prontos) -----------------------

  function alertar(tipo) {
    bip(tipo);
    // O navegador só deixa vibrar depois que o garçom tocou na tela uma vez.
    const tocou = !navigator.userActivation || navigator.userActivation.hasBeenActive;
    if (navigator.vibrate && tocou) navigator.vibrate(tipo === "garcom" ? [400, 150, 400, 150, 400] : [250, 100, 250]);
  }

  function renderAlertas() {
    $("alertas").replaceChildren(...estado.chamados_garcom.map((c) => el("div", { class: "alerta" },
      el("span", {}, c.tipo === "conta" ? "🧾 Mesa " + c.mesa + " pediu a conta" : "🙋 Mesa " + c.mesa + " está chamando",
        el("small", {}, "há " + minutosDesde(c.criado_em) + " min")),
      el("span", { class: "espaco" }),
      c.tipo === "conta" && estado.impressora_caixa_ativa ? el("button", { onclick: () => imprimirConta(c.mesa) }, "🖨️ Conta") : null,
      el("button", { onclick: async () => {
        try { await api("POST", `/api/garcom/${c.id}/atender`); monitor.forcar(); } catch (e) { aviso(e.message, "erro"); }
      } }, "✓ Atendi"))));
  }

  // --- Novo pedido ---------------------------------------------------------

  function renderMesas() {
    const comConta = new Set(estado.contas.filter((c) => c.chave.startsWith("mesa:")).map((c) => c.chave.slice(5)));
    if (!estado.mesas.length) {
      $("mesas").replaceChildren(el("span", { class: "dica" }, "Nenhuma mesa cadastrada — digite abaixo."));
      return;
    }
    $("mesas").replaceChildren(...estado.mesas.map((m) => el("button", {
      class: (m === mesa ? "ativa " : "") + (comConta.has(m) ? "com-conta" : ""),
      title: comConta.has(m) ? "Mesa com conta aberta" : "",
      onclick: () => { mesa = m; $("mesa-outra").value = ""; renderMesas(); renderBarra(); },
    }, m)));
  }
  $("mesa-outra").addEventListener("input", () => { mesa = $("mesa-outra").value.trim(); renderMesas(); renderBarra(); });

  function comandaSelecionada() {
    return estado.comandas.find((k) => k.id === comandaId) || null;
  }

  function renderComandasGarcom() {
    $("secao-comandas").hidden = !estado.modo_comandas;
    if (!estado.modo_comandas) return;
    if (comandaId && !comandaSelecionada()) comandaId = null; // fechou enquanto o garçom anotava
    const filtro = $("busca-comanda").value.trim().toLowerCase();
    const lista = estado.comandas.filter((k) => !filtro || k.numero.toLowerCase() === filtro || k.cliente_nome.toLowerCase().includes(filtro));
    $("comandas").replaceChildren(...(lista.length ? lista.map((k) => el("button", {
      class: k.id === comandaId ? "ativa" : "",
      onclick: () => { comandaId = k.id === comandaId ? null : k.id; renderComandasGarcom(); renderBarra(); },
    }, el("strong", {}, k.numero), el("small", {}, k.cliente_nome + (k.aniversario_hoje ? " 🎂" : ""))))
      : [el("span", { class: "dica" }, estado.comandas.length ? "Nenhuma comanda com esse filtro." : "Nenhuma comanda aberta.")]));
  }
  $("busca-comanda").addEventListener("input", renderComandasGarcom);

  function destino() {
    const k = comandaSelecionada();
    return [k ? "Comanda " + k.numero : null, mesa ? "Mesa " + mesa : null].filter(Boolean).join(" · ");
  }

  function renderCategorias() {
    const cats = [...new Set(produtos.map((p) => p.categoria))];
    if (categoriaAtiva && !cats.includes(categoriaAtiva)) categoriaAtiva = null;
    const chip = (rotulo, valor) => el("button", {
      class: categoriaAtiva === valor ? "ativo" : "",
      onclick: () => { categoriaAtiva = valor; renderCategorias(); renderProdutos(); },
    }, rotulo);
    $("categorias").replaceChildren(chip("Todos", null), ...cats.map((c) => chip(c, c)));
  }

  function linhaProduto(p) {
    const q = (carrinho.get(p.id) || {}).quantidade || 0;
    return el("div", { class: "produto", id: "produto-" + p.id },
      p.foto ? el("img", { src: "/foto/" + p.foto, alt: "", loading: "lazy" }) : null,
      el("div", { class: "info" }, el("div", { class: "nome" }, p.nome), el("div", { class: "preco" }, moeda(p.preco_centavos))),
      el("div", { class: "qtd" },
        q ? el("button", { "aria-label": "Remover um", onclick: () => mudar(p, -1) }, "−") : null,
        q ? el("span", {}, q) : null,
        el("button", { class: "mais", "aria-label": "Adicionar", onclick: () => mudar(p, 1) }, "+")));
  }

  function renderProdutos() {
    const busca = $("busca").value.trim().toLowerCase();
    const lista = produtos.filter((p) =>
      (categoriaAtiva === null || p.categoria === categoriaAtiva) && (!busca || p.nome.toLowerCase().includes(busca)));
    $("produtos").replaceChildren(...(lista.length ? lista.map(linhaProduto) : [el("div", { class: "vazio" }, "Nenhum produto.")]));
  }
  $("busca").addEventListener("input", renderProdutos);

  function mudar(p, delta) {
    const atual = carrinho.get(p.id) || { quantidade: 0, observacao: "" };
    atual.quantidade += delta;
    if (atual.quantidade <= 0) carrinho.delete(p.id);
    else carrinho.set(p.id, atual);
    const antigo = $("produto-" + p.id);
    if (antigo) antigo.replaceWith(linhaProduto(p));
    renderBarra();
  }

  function resumoCarrinho() {
    let total = 0, qtd = 0;
    for (const [id, item] of carrinho) {
      const p = produtos.find((x) => x.id === id);
      if (p) { total += p.preco_centavos * item.quantidade; qtd += item.quantidade; }
    }
    return { total, qtd };
  }

  function renderBarra() {
    const { total, qtd } = resumoCarrinho();
    const barra = $("barra-pedido");
    barra.hidden = !qtd || abaAtual() !== "novo";
    barra.textContent = (destino() || "Escolha a mesa ou comanda") + ` · ${qtd} ite${qtd === 1 ? "m" : "ns"} · ${moeda(total)} — revisar e enviar`;
  }

  $("barra-pedido").addEventListener("click", () => {
    if (!mesa && !comandaId) {
      aviso("Escolha a mesa ou a comanda primeiro", "erro");
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const cliente = el("input", { maxlength: 60, placeholder: "Opcional" });
    const obs = el("input", { maxlength: 300, placeholder: "Ex.: tudo junto, sem pressa" });
    const lista = el("div", {});
    function renderLista() {
      lista.replaceChildren(...[...carrinho].map(([id, item]) => {
        const p = produtos.find((x) => x.id === id);
        if (!p) return null;
        return el("div", { class: "item-revisao" },
          el("strong", {}, item.quantidade + "×"),
          el("div", {}, p.nome, item.observacao ? el("span", { class: "obs" }, "» " + item.observacao) : null,
            el("button", { type: "button", class: "editar", onclick: () => {
              const o = prompt("Observação para " + p.nome + " (ex.: sem cebola, bem passado):", item.observacao);
              if (o !== null) { item.observacao = o.trim(); renderLista(); }
            } }, item.observacao ? "editar observação" : "+ observação")),
          el("span", {}, moeda(p.preco_centavos * item.quantidade)));
      }).filter(Boolean));
    }
    renderLista();
    dialogo({
      titulo: "Pedido — " + destino(),
      corpo: el("div", {}, lista,
        el("div", { class: "linha-valor destaque" }, el("span", {}, "Total"), el("span", {}, moeda(resumoCarrinho().total))),
        el("label", {}, "Nome do cliente"), cliente, el("label", {}, "Observação para a cozinha"), obs),
      confirmar: "Enviar pedido",
      aoConfirmar: async () => {
        const r = await api("POST", "/api/pedidos", {
          origem: "garcom", mesa, comanda_id: comandaId,
          itens: [...carrinho].map(([id, i]) => ({ produto_id: id, quantidade: i.quantidade, observacao: i.observacao })),
          cliente: cliente.value, observacao: obs.value,
        });
        aviso(`Pedido nº ${r.pedido.codigo} (${destino()}) enviado` + (r.pedido.setores.length ? " para: " + r.pedido.setores.join(" e ") : " (já está pronto)"), "ok");
        carrinho.clear();
        mesa = "";
        comandaId = null;
        $("busca-comanda").value = "";
        renderComandasGarcom();
        $("mesa-outra").value = "";
        renderMesas();
        renderProdutos();
        renderBarra();
        monitor.forcar();
      },
    });
  });

  // --- Entregar e mesas ------------------------------------------------------

  function paraEntregar() {
    return estado.pedidos.filter((p) => (p.mesa || p.comanda_numero) && (p.status === "pronto" || p.status === "chamado"))
      .sort((a, b) => (a.pronto_em || 0) - (b.pronto_em || 0));
  }

  function renderEntregar() {
    const lista = paraEntregar();
    $("n-entregar").textContent = lista.length;
    $("n-entregar").className = lista.length ? "" : "zero";
    $("lista-entregar").replaceChildren(...(lista.length ? lista.map((p) => el("div", { class: "cartao-entrega" },
      el("div", { class: "topo-cartao" }, el("span", { class: "mesa" }, p.mesa ? "Mesa " + p.mesa : "Comanda " + p.comanda_numero),
        el("span", { class: "dica" }, "pedido " + p.codigo + (p.mesa && p.comanda_numero ? " · comanda " + p.comanda_numero : "") + (p.cliente ? " · " + p.cliente : "")),
        el("span", { class: "espaco" }), el("span", { class: "dica" }, "pronto há " + minutosDesde(p.pronto_em || p.criado_em) + " min")),
      el("ul", {}, p.itens.map((i) => el("li", {}, i.quantidade + "× " + i.nome + (i.observacao ? " (" + i.observacao + ")" : "")))),
      el("div", { class: "acoes" }, el("button", { class: "verde", onclick: async () => {
        try {
          await api("POST", `/api/pedidos/${p.id}/status`, { status: "entregue" });
          aviso(`Pedido ${p.codigo} entregue`, "ok");
          monitor.forcar();
        } catch (e) { aviso(e.message, "erro"); }
      } }, "✓ Entreguei na mesa"))))
      : [el("div", { class: "vazio" }, "Nada para entregar agora. 👍")]));
  }

  async function imprimirConta(numeroMesa) {
    const conta = estado.contas.find((c) => c.chave === "mesa:" + numeroMesa);
    if (!conta) { aviso("A mesa " + numeroMesa + " não tem conta aberta.", "erro"); return; }
    try {
      await api("POST", "/api/contas/imprimir", { pedido_ids: conta.pedidos.map((p) => p.id), titulo: conta.titulo });
      aviso("Conta da mesa " + numeroMesa + " enviada para a impressora do caixa", "ok");
    } catch (e) { aviso(e.message, "erro"); }
  }

  function renderContas() {
    const contas = estado.contas.filter((c) => c.chave.startsWith("mesa:"));
    $("n-mesas").textContent = contas.length;
    $("n-mesas").className = contas.length ? "" : "zero";
    $("lista-mesas").replaceChildren(...(contas.length ? contas.map((c) => {
      const numero = c.chave.slice(5);
      const itens = {};
      c.pedidos.forEach((p) => p.itens.forEach((i) => { itens[i.nome] = (itens[i.nome] || 0) + i.quantidade; }));
      return el("div", { class: "cartao-mesa" },
        el("div", { class: "topo-cartao" }, el("span", { class: "mesa" }, c.titulo), el("span", { class: "espaco" }), el("strong", {}, moeda(c.total))),
        el("ul", {}, Object.entries(itens).map(([nome, q]) => el("li", {}, q + "× " + nome))),
        el("div", { class: "acoes" },
          estado.impressora_caixa_ativa ? el("button", { onclick: () => imprimirConta(numero) }, "🖨️ Imprimir conta") : null,
          el("button", { class: "primario", onclick: () => { mesa = numero; renderMesas(); abrirAba("novo"); } }, "+ Pedir mais")));
    }) : [el("div", { class: "vazio" }, "Nenhuma mesa com conta aberta.")]));
  }

  // --- Atualização -----------------------------------------------------------

  function aplicar(dados) {
    estado = dados;
    const assinatura = JSON.stringify(dados.produtos);
    if (assinatura !== assinaturaProdutos) {
      produtos = dados.produtos;
      assinaturaProdutos = assinatura;
      for (const id of [...carrinho.keys()]) if (!produtos.some((p) => p.id === id)) carrinho.delete(id);
      renderCategorias();
      renderProdutos();
    }
    renderMesas();
    renderComandasGarcom();
    renderAlertas();
    renderEntregar();
    renderContas();
    renderBarra();

    const idsChamados = new Set(dados.chamados_garcom.map((c) => c.id));
    if (chamadosVistos && [...idsChamados].some((id) => !chamadosVistos.has(id))) alertar("garcom");
    chamadosVistos = idsChamados;
    const idsEntrega = new Set(paraEntregar().map((p) => p.id));
    if (entregasVistas && [...idsEntrega].some((id) => !entregasVistas.has(id))) alertar("novo");
    entregasVistas = idsEntrega;
  }

  function checarSom() { $("ativar-som").hidden = somLiberado(); }
  setTimeout(checarSom, 1500);
  setInterval(checarSom, 10000);
  $("ativar-som").addEventListener("click", () => { liberarSom(); alertar("novo"); $("ativar-som").hidden = true; });

  const monitor = C.acompanhar("/api/estado", aplicar, 2000);
  setInterval(() => monitor.forcar(), 30000);
})();
