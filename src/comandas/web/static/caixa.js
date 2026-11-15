(function () {
  "use strict";
  const { api, moeda, el, minutosDesde, hora, aviso, bip, centavos, reais, campoDinheiro, dialogo, mascaraTelefone } = window.C;
  const $ = (id) => document.getElementById(id);
  const pode = {
    pedidos: document.body.dataset.podePedidos === "1",
    receber: document.body.dataset.podeReceber === "1",
    caixa: document.body.dataset.podeCaixa === "1",
    cancelar: document.body.dataset.podeCancelar === "1",
    estornar: document.body.dataset.podeEstornar === "1",
  };

  let estado = { pedidos: [], contas: [], recebimentos: [], formas: {}, chamados_garcom: [] };
  let produtos = [];
  let categoriaAtiva = null;
  let carrinho = []; // {produto, quantidade, observacao}
  let delivery = false; // venda de delivery (endereço de entrega no lugar de mesa/comanda)
  let prontosVistos = null;
  let chamadosVistos = null;

  async function acao(metodo, url, corpo, msgOk) {
    try {
      const r = await api(metodo, url, corpo || {});
      if (msgOk) aviso(msgOk, "ok");
      monitor.forcar();
      return r;
    } catch (err) {
      aviso(err.message, "erro");
      return null;
    }
  }

  // --- Abas -------------------------------------------------------------------

  document.querySelectorAll(".abas-caixa button").forEach((b) => b.addEventListener("click", () => abrirAba(b.dataset.aba)));
  function abrirAba(nome) {
    document.querySelectorAll(".abas-caixa button").forEach((b) => b.classList.toggle("ativa", b.dataset.aba === nome));
    document.querySelectorAll(".aba-caixa").forEach((a) => (a.hidden = a.id !== "aba-" + nome));
  }
  abrirAba(pode.pedidos ? "pedidos" : "contas");

  // --- Montagem do pedido ------------------------------------------------

  function renderCategorias() {
    const cats = [...new Set(produtos.map((p) => p.categoria))];
    if (categoriaAtiva && !cats.includes(categoriaAtiva)) categoriaAtiva = null;
    const chip = (rotulo, valor) => el("button", {
      class: categoriaAtiva === valor ? "ativo" : "",
      onclick: () => { categoriaAtiva = valor; renderCategorias(); renderProdutos(); },
    }, rotulo);
    $("categorias").replaceChildren(chip("Todos", null), ...cats.map((c) => chip(c, c)));
  }

  function renderProdutos() {
    const busca = $("busca").value.trim().toLowerCase();
    if (!produtos.length) {
      $("produtos").replaceChildren(el("div", { class: "vazio" }, "Nenhum produto cadastrado. ", el("a", { href: "/admin" }, "Cadastrar cardápio")));
      return;
    }
    const lista = produtos.filter((p) =>
      (categoriaAtiva === null || p.categoria === categoriaAtiva) && (!busca || p.nome.toLowerCase().includes(busca)));
    $("produtos").replaceChildren(...lista.map((p) =>
      el("button", { class: "produto-btn", onclick: () => adicionar(p) },
        p.foto ? el("img", { src: "/foto/" + p.foto, alt: "", loading: "lazy" }) : null,
        el("span", { class: "info" }, el("span", { class: "nome" }, p.nome), el("span", { class: "preco" }, moeda(p.preco_centavos))))));
  }

  function adicionar(produto) {
    const existente = carrinho.find((i) => i.produto.id === produto.id && !i.observacao);
    if (existente) existente.quantidade++;
    else carrinho.push({ produto, quantidade: 1, observacao: "" });
    renderCarrinho();
  }

  function taxaEntrega() {
    return delivery ? centavos($("dl-taxa").value) || 0 : 0;
  }

  function renderCarrinho() {
    const total = carrinho.reduce((s, i) => s + i.produto.preco_centavos * i.quantidade, 0) + taxaEntrega();
    $("total").textContent = moeda(total);
    $("linha-taxa-entrega").hidden = !taxaEntrega();
    $("valor-taxa-entrega").textContent = moeda(taxaEntrega());
    $("qtd-itens").textContent = carrinho.reduce((s, i) => s + i.quantidade, 0);
    // Sem caixa aberto não entra pedido.
    $("enviar").disabled = !carrinho.length || !estado.caixa_aberto;
    $("aviso-caixa-fechado").hidden = !!estado.caixa_aberto;
    if ($("enviar-receber")) $("enviar-receber").disabled = !carrinho.length || !estado.caixa_aberto;
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
        el("span", {}, moeda(item.produto.preco_centavos * item.quantidade)))));
  }

  function renderComandas() {
    const sel = $("comanda");
    $("linha-comanda").hidden = !estado.modo_comandas || delivery;
    if (!estado.modo_comandas) return;
    const atual = sel.value;
    sel.replaceChildren(el("option", { value: "" }, estado.comandas.length ? "— sem comanda (balcão/mesa) —" : "Nenhuma comanda aberta"),
      ...estado.comandas.map((k) => el("option", { value: k.id }, `${k.numero} · ${k.cliente_nome}`)));
    if ([...sel.options].some((o) => o.value === atual)) sel.value = atual;
  }

  // --- Abrir comanda sem sair do caixa -------------------------------------
  // Mesmo fluxo da tela de Comandas: busca o cliente (ou cadastra um novo),
  // abre a comanda e já deixa ela escolhida no pedido.

  function dialogoAbrirComanda() {
    const busca = el("input", { type: "search", placeholder: "Buscar cliente por nome, telefone ou CPF", autocomplete: "off" });
    const resultados = el("div", { class: "busca-cliente-resultados" });
    const numero = el("input", { maxlength: 20, placeholder: "Deixe vazio para usar o próximo livre", inputmode: "numeric" });
    const areaNovo = el("div", { hidden: true });
    let escolhido = null, form = null, criado = null; // criado: cadastro feito, não cadastra de novo se a abertura falhar
    const botaoNovo = el("button", { type: "button", class: "primario", onclick: () => {
      form = window.C.formCliente({ nome: /\d/.test(busca.value) ? "" : busca.value });
      areaNovo.replaceChildren(el("h3", {}, "Cliente novo"), form.elemento);
      areaNovo.hidden = false;
      escolhido = null;
      resultados.replaceChildren();
    } }, "+ Cliente novo");

    let temporizador = null;
    busca.addEventListener("input", () => {
      clearTimeout(temporizador);
      temporizador = setTimeout(buscar, 250);
    });
    async function buscar() {
      const q = busca.value.trim();
      if (q.length < 2) { resultados.replaceChildren(); return; }
      const { clientes } = await api("GET", "/api/clientes/busca?q=" + encodeURIComponent(q));
      const abertaPor = new Map(estado.comandas.map((k) => [k.cliente_id, k]));
      resultados.replaceChildren(...(clientes.length ? clientes.map((c) => {
        const aberta = abertaPor.get(c.id);
        const linha = el("div", { class: "resultado" + (escolhido && escolhido.id === c.id ? " escolhido" : "") },
          el("div", { class: "info" }, el("strong", {}, c.nome), c.aniversario_hoje ? " 🎂" : "",
            el("small", {}, c.telefone_formatado + (c.cpf_formatado ? " · CPF " + c.cpf_formatado : ""))),
          aberta ? el("button", { type: "button", onclick: () => { usarComanda(aberta.id); janela.fechar(); } }, "Usar comanda " + aberta.numero + " (já aberta)")
            : el("button", { type: "button", class: "verde", onclick: () => {
              escolhido = c;
              form = null;
              areaNovo.hidden = true;
              areaNovo.replaceChildren(); // sem os campos obrigatórios do cadastro escondidos
              resultados.querySelectorAll(".resultado").forEach((r) => r.classList.remove("escolhido"));
              linha.classList.add("escolhido");
              numero.focus();
            } }, "Escolher"));
        return linha;
      }) : [el("div", { class: "vazio" }, "Nenhum cliente encontrado. Use \"+ Cliente novo\".")]));
    }

    const janela = dialogo({
      titulo: "Abrir comanda",
      largo: true,
      corpo: el("div", {},
        el("div", { class: "linha-comanda" }, busca, botaoNovo), resultados, areaNovo,
        el("label", {}, "Número da comanda / cartão"), numero),
      confirmar: "Abrir comanda",
      aoConfirmar: async () => {
        let cliente = escolhido;
        if (form) {
          if (!criado) criado = (await api("POST", "/api/clientes", form.valores())).cliente;
          cliente = criado;
        }
        if (!cliente) throw new Error("Busque e escolha o cliente, ou cadastre um cliente novo.");
        const r = await api("POST", "/api/comandas", { cliente_id: cliente.id, numero: numero.value });
        const k = r.comanda;
        aviso(`Comanda ${k.numero} aberta para ${k.cliente_nome}` + (k.aniversario_hoje ? " — 🎂 aniversariante do dia!" : ""), "ok");
        estado.comandas = [...estado.comandas, k];
        renderComandas();
        usarComanda(k.id);
        monitor.forcar();
      },
    });
  }

  function usarComanda(id) {
    $("comanda").value = String(id);
  }

  if ($("abrir-comanda")) $("abrir-comanda").addEventListener("click", dialogoAbrirComanda);

  // --- Delivery --------------------------------------------------------------

  const ultimaTaxa = () => { try { return localStorage.getItem("taxa_entrega") || ""; } catch (e) { return ""; } };

  function usarDelivery(ligar) {
    delivery = ligar;
    $("venda-local").classList.toggle("ativo", !ligar);
    $("venda-delivery").classList.toggle("ativo", ligar);
    $("campos-delivery").hidden = !ligar;
    $("campos-local").hidden = ligar;
    if (ligar && !$("dl-taxa").value) $("dl-taxa").value = ultimaTaxa();
    renderComandas();
    renderCarrinho();
    if (ligar) $("dl-telefone").focus();
  }

  function limparDelivery() {
    for (const id of ["dl-telefone", "dl-nome", "dl-endereco", "dl-bairro", "dl-referencia", "dl-troco"]) $(id).value = "";
    $("dl-pagamento").value = "";
    $("linha-troco").hidden = true;
    $("dl-achado").hidden = true;
    $("dl-taxa").value = ultimaTaxa();
  }

  // Cliente que já pediu antes: o endereço do último delivery vem preenchido.
  async function buscarEnderecoAnterior() {
    const tel = $("dl-telefone").value.replace(/\D/g, "");
    if (tel.length < 10) return;
    try {
      const { entrega } = await api("GET", "/api/delivery/ultimo?telefone=" + encodeURIComponent(tel));
      if (!entrega) { $("dl-achado").hidden = true; return; }
      const campos = { "dl-nome": entrega.cliente, "dl-endereco": entrega.endereco, "dl-bairro": entrega.bairro, "dl-referencia": entrega.referencia };
      let preencheu = false;
      for (const [id, valor] of Object.entries(campos)) {
        if (!$(id).value.trim() && valor) { $(id).value = valor; preencheu = true; }
      }
      if (preencheu) {
        $("dl-achado").textContent = "✔ Cliente já pediu antes — nome e endereço preenchidos. Confira se ainda é o mesmo endereço.";
        $("dl-achado").hidden = false;
      }
    } catch (e) { /* sem endereço anterior: digita normalmente */ }
  }

  function dadosDelivery() {
    const nome = $("dl-nome").value.trim();
    if ($("dl-telefone").value.replace(/\D/g, "").length < 10) throw new Error("Informe o telefone do cliente com DDD.");
    if (!nome) throw new Error("Informe o nome do cliente do delivery.");
    if (!$("dl-endereco").value.trim()) throw new Error("Informe o endereço de entrega (rua e número).");
    const taxa = centavos($("dl-taxa").value), troco = centavos($("dl-troco").value);
    if (Number.isNaN(taxa) || Number.isNaN(troco)) throw new Error("Valor inválido na taxa ou no troco. Use por exemplo 5,00");
    return {
      cliente: nome,
      entrega: {
        telefone: $("dl-telefone").value, endereco: $("dl-endereco").value, bairro: $("dl-bairro").value,
        referencia: $("dl-referencia").value, taxa, pagamento: $("dl-pagamento").value, troco,
      },
    };
  }

  function imprimirEtiqueta(p) {
    if (estado.impressora_caixa_ativa) {
      acao("POST", `/api/pedidos/${p.id}/etiqueta`, {}, "Etiqueta do entregador enviada para a impressora");
    } else {
      window.open("/etiqueta/" + p.id, "_blank", "width=480,height=760");
    }
  }

  if (pode.pedidos) {
    $("venda-local").addEventListener("click", () => usarDelivery(false));
    $("venda-delivery").addEventListener("click", () => usarDelivery(true));
    $("dl-pagamento").addEventListener("change", () => {
      $("linha-troco").hidden = $("dl-pagamento").value !== "dinheiro";
      if (!$("linha-troco").hidden) $("dl-troco").focus();
    });
    $("dl-telefone").addEventListener("input", () => { $("dl-telefone").value = mascaraTelefone($("dl-telefone").value); });
    $("dl-telefone").addEventListener("change", buscarEnderecoAnterior);
    $("dl-taxa").addEventListener("input", renderCarrinho);
  }

  function limparCarrinho() {
    carrinho = [];
    $("comanda").value = "";
    $("cliente").value = $("mesa").value = $("obs").value = "";
    limparDelivery();
    renderCarrinho();
  }

  async function enviarPedido(receberDepois) {
    $("enviar").disabled = true;
    try {
      const corpo = {
        itens: carrinho.map((i) => ({ produto_id: i.produto.id, quantidade: i.quantidade, observacao: i.observacao })),
        cliente: $("cliente").value, mesa: $("mesa").value, observacao: $("obs").value,
        comanda_id: $("comanda").value || null,
      };
      if (delivery) {
        Object.assign(corpo, dadosDelivery(), { mesa: "", comanda_id: null });
        try { localStorage.setItem("taxa_entrega", $("dl-taxa").value.trim()); } catch (e) { /* sem memória da taxa */ }
      }
      const r = await api("POST", "/api/pedidos", corpo);
      aviso((r.pedido.entrega ? "🛵 Delivery nº " : "Pedido nº ") + r.pedido.codigo + (r.pedido.setores.length ? " enviado para: " + r.pedido.setores.map((s) => (estado.ambientes || {})[s] || s).join(" e ") : " registrado (sem preparo, já está pronto)"), "ok");
      limparCarrinho();
      monitor.forcar();
      if (receberDepois) dialogoPagamento([r.pedido], r.pedido.comanda_numero ? "Comanda " + r.pedido.comanda_numero
        : (r.pedido.entrega ? "Delivery nº " : "Pedido nº ") + r.pedido.codigo);
    } catch (err) {
      aviso(err.message, "erro");
      renderCarrinho();
    }
  }

  if (pode.pedidos) {
    $("busca").addEventListener("input", renderProdutos);
    $("limpar").addEventListener("click", limparCarrinho);
    $("enviar").addEventListener("click", () => enviarPedido(false));
    if ($("enviar-receber")) $("enviar-receber").addEventListener("click", () => enviarPedido(true));
    renderCarrinho();
  }

  // --- Lista de pedidos --------------------------------------------------

  // Editar pedido: tirar itens (todas ou algumas unidades) ou cancelar o
  // pedido inteiro — sempre com o motivo, que fica no histórico.
  function dialogoEditar(p) {
    const tirar = new Map(); // item_id -> quantas unidades cancelar
    const motivo = el("input", { maxlength: 200, placeholder: "Ex.: cliente desistiu, lançado errado" });
    const linhas = el("div", { class: "editar-itens" });
    const resumo = el("div", { class: "linha-valor destaque" });
    function render() {
      linhas.replaceChildren(...p.itens.map((i) => {
        const livre = i.quantidade - (i.pago_qtd || 0);
        const n = tirar.get(i.id) || 0;
        const mudar = (d) => { tirar.set(i.id, Math.min(livre, Math.max(0, n + d))); render(); };
        return el("div", { class: "editar-item" + (n ? " marcado" : "") },
          el("div", { class: "nome" }, el("strong", {}, i.quantidade + "× " + i.nome),
            i.observacao ? el("small", {}, " (" + i.observacao + ")") : null,
            i.pago_qtd ? el("small", { class: "positivo" }, ` · ${i.pago_qtd} já pago`) : null,
            el("small", {}, " · " + moeda(i.preco_centavos) + " cada")),
          livre ? el("div", { class: "qtd-cancelar" },
            el("span", {}, "Cancelar"),
            el("button", { type: "button", onclick: () => mudar(-1) }, "−"),
            el("strong", {}, String(n)),
            el("button", { type: "button", onclick: () => mudar(1) }, "+"),
            el("button", { type: "button", class: "discreto", onclick: () => { tirar.set(i.id, n === livre ? 0 : livre); render(); } }, n === livre ? "nenhum" : "todos"))
            : el("small", {}, "já pago — não dá para cancelar"));
      }));
      const valor = p.itens.reduce((t, i) => t + (tirar.get(i.id) || 0) * i.preco_centavos, 0);
      resumo.replaceChildren(el("span", {}, valor ? "O pedido fica com" : "Total do pedido"), el("span", {}, moeda(p.total_centavos - valor)));
      const ok = janela && janela.elemento.querySelector("button[type=submit]");
      if (ok) {
        const qtd = [...tirar.values()].reduce((a, b) => a + b, 0);
        ok.disabled = !qtd;
        ok.textContent = qtd ? `Cancelar ${qtd} ${qtd > 1 ? "itens" : "item"} (${moeda(valor)})` : "Escolha os itens a cancelar";
      }
    }
    const inteiro = el("button", { type: "button", class: "perigo", onclick: async () => {
      if (!motivo.value.trim()) { motivo.focus(); aviso("Escreva o motivo do cancelamento.", "erro"); return; }
      if (!confirm(`Cancelar o pedido nº ${p.codigo} inteiro (${moeda(p.total_centavos)})?`)) return;
      try {
        await api("POST", `/api/pedidos/${p.id}/status`, { status: "cancelado", motivo: motivo.value });
        aviso("Pedido cancelado", "ok");
        janela.fechar();
        monitor.forcar();
      } catch (err) { aviso(err.message, "erro"); }
    } }, "❌ Cancelar o pedido inteiro");
    const janela = dialogo({
      titulo: `Editar pedido nº ${p.codigo}` + (p.mesa ? " · mesa " + p.mesa : "") + (p.cliente ? " · " + p.cliente : ""),
      largo: true,
      corpo: el("div", {},
        el("p", { class: "dica" }, "Toque em + para escolher o que cancelar. O que já foi pago não pode ser cancelado."),
        linhas, resumo,
        el("label", {}, "Motivo do cancelamento (obrigatório, fica registrado)"), motivo,
        el("div", { class: "cancelar-inteiro" }, inteiro)),
      confirmar: "Escolha os itens a cancelar", cancelar: "Voltar", perigo: true,
      aoConfirmar: async () => {
        if (!motivo.value.trim()) throw new Error("Escreva o motivo do cancelamento.");
        const itens = [...tirar.entries()].filter(([, q]) => q).map(([item_id, quantidade]) => ({ item_id, quantidade }));
        const r = await api("POST", `/api/pedidos/${p.id}/cancelar-itens`, { itens, motivo: motivo.value });
        aviso(r.pedido_cancelado ? "Todos os itens saíram: pedido cancelado" : "Itens cancelados. O pedido ficou com " + moeda(r.pedido.total_centavos), "ok");
        monitor.forcar();
      },
    });
    render();
  }

  function cartaoPedido(p) {
    const botoes = [];
    const chamar = (rotulo, classe) => el("button", { class: classe || "", onclick: () => acao("POST", `/api/pedidos/${p.id}/chamar`, {}, `Pedido ${p.codigo} chamado no painel`) }, rotulo);
    if (pode.pedidos) {
      if (p.entrega) {
        // Delivery não vai para o painel: imprime a etiqueta e despacha.
        if (p.status === "pronto" || p.status === "chamado") {
          botoes.push(el("button", { class: "verde", onclick: () => imprimirEtiqueta(p) }, "🏷️ Etiqueta do entregador"));
          botoes.push(el("button", { onclick: () => acao("POST", `/api/pedidos/${p.id}/status`, { status: "entregue" }, `Delivery ${p.codigo} saiu para entrega`) }, "🛵 Saiu para entrega"));
        } else {
          botoes.push(el("button", { onclick: () => acao("POST", `/api/pedidos/${p.id}/status`, { status: "pronto" }) }, "Marcar pronto"));
          botoes.push(el("button", { class: "discreto", title: "Imprimir a etiqueta do entregador agora", onclick: () => imprimirEtiqueta(p) }, "🏷️"));
        }
      } else if (p.status === "pronto") {
        botoes.push(chamar("📢 Chamar no painel", "verde"));
      } else if (p.status === "chamado") {
        botoes.push(chamar("🔁 Chamar de novo"));
        botoes.push(el("button", { class: "verde", onclick: () => acao("POST", `/api/pedidos/${p.id}/status`, { status: "entregue" }) }, "✓ Entregue"));
      } else {
        botoes.push(el("button", { onclick: () => acao("POST", `/api/pedidos/${p.id}/status`, { status: "pronto" }) }, "Marcar pronto"));
        botoes.push(chamar("📢 Chamar"));
      }
      const ondeImprime = (p.setores || []).filter((s) => estado["impressora_" + s + "_ativa"]);
      if (ondeImprime.length) {
        botoes.push(el("button", { class: "discreto", title: "Reimprimir no(a) " + ondeImprime.join(" e "), onclick: () => acao("POST", `/api/pedidos/${p.id}/imprimir`, {}, "Enviado para a impressora") }, "🖨️"));
      }
    }
    if (pode.receber && !p.pago) {
      botoes.push(el("button", { class: "discreto", title: "Receber este pedido", onclick: () => dialogoPagamento([p], "Pedido nº " + p.codigo) }, "💲"));
    }
    if (pode.cancelar && !p.pago) {
      botoes.push(el("button", { class: "discreto", title: "Editar pedido: cancelar itens ou o pedido inteiro", onclick: () => dialogoEditar(p) }, "✏️ Editar"));
    }
    const quem = [p.origem === "qrcode" ? el("span", { class: "etiqueta qrcode" }, "QR code") : null,
      p.origem === "garcom" ? el("span", { class: "etiqueta qrcode" }, "Garçom " + (p.usuario_nome || "")) : null,
      p.comanda_numero ? el("span", { class: "etiqueta chamado" }, "Comanda " + p.comanda_numero) : null,
      p.entrega ? el("span", { class: "etiqueta delivery" }, "🛵 Delivery") : null,
      p.mesa ? "Mesa " + p.mesa : null, p.cliente || null].filter(Boolean);
    return el("div", { class: "pedido " + p.status },
      el("div", { class: "cabeca" },
        el("span", { class: "numero" }, "#" + p.codigo),
        el("span", { class: "etiqueta " + p.status }, window.C.STATUS_NOME[p.status]),
        el("span", { class: "etiqueta " + (p.pago ? "pago" : "a-receber") }, p.pago ? "pago" : "a receber"),
        p.impressao && p.impressao.startsWith("erro") ? el("span", { class: "etiqueta erro", title: p.impressao }, "falha na impressão") : null,
        el("span", { class: "quem" }, ...quem.flatMap((x, i) => (i ? [" · ", x] : [x]))),
        el("span", { class: "espaco" }),
        el("span", { class: "quem" }, minutosDesde(p.criado_em) + " min"),
        el("strong", {}, moeda(p.total_centavos))),
      el("div", { class: "itens" }, p.itens.map((i) => `${i.quantidade}× ${i.nome}${i.observacao ? " (" + i.observacao + ")" : ""}`).join(" · ")),
      p.observacao ? el("div", { class: "itens", style: "color: var(--amarelo)" }, "Obs: " + p.observacao) : null,
      p.entrega ? linhaEndereco(p) : null,
      el("div", { class: "acoes" }, botoes));
  }

  function descreverItens(p) {
    return p.itens.map((i) => i.quantidade + "× " + i.nome + (!p.pago && i.pago_qtd ? ` (${i.pago_qtd} pago)` : "")).join(", ")
      + (p.entrega_taxa ? " + entrega " + moeda(p.entrega_taxa) : "");
  }

  function linhaEndereco(p) {
    return el("div", { class: "endereco-entrega" }, "📍 " + p.entrega_endereco + (p.entrega_bairro ? " — " + p.entrega_bairro : "")
      + (p.entrega_referencia ? " (" + p.entrega_referencia + ")" : "") + " · 📞 " + p.entrega_telefone_formatado);
  }

  function preencherLista(id, contadorId, pedidos, textoVazio) {
    $(contadorId).textContent = pedidos.length;
    $(id).replaceChildren(...(pedidos.length ? pedidos.map(cartaoPedido) : [el("div", { class: "vazio" }, textoVazio)]));
  }

  // --- Contas a receber e pagamento ---------------------------------------

  function renderContas() {
    $("n-contas").textContent = estado.contas.length;
    if (!estado.contas.length) {
      $("aba-contas").replaceChildren(el("div", { class: "vazio" }, "Nenhuma conta em aberto. 🎉"));
      return;
    }
    $("aba-contas").replaceChildren(...estado.contas.map((c) => el("div", { class: "conta" },
      el("div", { class: "cabeca" }, el("h3", {}, c.titulo), el("span", { class: "espaco" }),
        el("strong", {}, moeda(c.abatido ? c.falta : c.total))),
      c.abatido ? el("div", { class: "ja-pago" }, `Conta ${moeda(c.total)} · já pago ${moeda(c.ja_pago)} · falta ${moeda(c.falta)}`) : null,
      el("ul", {}, c.pedidos.map((p) => el("li", {},
        `Pedido ${p.codigo} (${hora(p.criado_em)}): ` + descreverItens(p) + " — " + moeda(p.total_centavos)))),
      c.pedidos.length === 1 && c.pedidos[0].entrega ? linhaEndereco(c.pedidos[0]) : null,
      c.abatimentos && c.abatimentos.length ? el("ul", { class: "abatimentos" }, c.abatimentos.map((a) => el("li", {},
        `✔ Abatido ${moeda(a.total)} às ${hora(a.criado_em)} (` + a.formas.map((f) => estado.formas[f.forma]).join(" + ") + ")"
        + (a.itens ? " — " + a.itens : "")))) : null,
      el("div", { class: "acoes" },
        pode.pedidos && c.pedidos.length === 1 && c.pedidos[0].entrega ? el("button", { onclick: () => imprimirEtiqueta(c.pedidos[0]) }, "🏷️ Etiqueta do entregador") : null,
        estado.impressora_caixa_ativa ? el("button", { onclick: () => acao("POST", "/api/contas/imprimir", { pedido_ids: c.pedidos.map((p) => p.id), titulo: c.titulo }, "Conta enviada para a impressora") }, "🖨️ Imprimir conta") : null,
        pode.receber ? el("button", { class: "verde", disabled: !estado.caixa_aberto, title: estado.caixa_aberto ? "" : "Abra o caixa para receber",
          onclick: () => dialogoPagamento(c.pedidos, c.titulo) }, "💲 Receber") : null))));
  }

  // Valores já abatidos (partes da conta pagas antes) ligados a esses pedidos.
  function abatidoDe(pedidos) {
    const ids = new Set(pedidos.map((p) => p.id));
    const vistos = new Map();
    for (const c of estado.contas) {
      for (const a of c.abatimentos || []) {
        if (a.pedido_ids.some((i) => ids.has(i))) vistos.set(a.id, a);
      }
    }
    const lista = [...vistos.values()];
    return { subtotal: lista.reduce((s, a) => s + a.subtotal, 0), pago: lista.reduce((s, a) => s + a.total, 0) };
  }

  const ICONE_FORMA = { dinheiro: "💵", pix: "⚡", debito: "💳", credito: "💳", vale: "🍽️", outro: "🧾" };

  // Janela de pagamento: um valor só, a pessoa toca na forma de pagamento.
  // Desconto, taxa, dividir e "outro valor" (abater só uma parte) ficam em
  // botões, escondidos até serem usados. `seguir` vem preenchido quando a
  // conta está sendo dividida e a janela reabre para a próxima pessoa.
  function dialogoPagamento(pedidos, titulo, seguir) {
    if (!estado.caixa_aberto) {
      aviso("O caixa está fechado. Abra o caixa para receber.", "erro");
      return;
    }
    const s = seguir || {};
    const conta = pedidos.reduce((t, p) => t + p.total_centavos, 0);
    const ab = s.abatido !== undefined ? { subtotal: s.abatido, pago: s.jaPago } : abatidoDe(pedidos);
    const falta = conta - ab.subtotal;          // parte da conta que ainda não foi paga
    const taxaPct = estado.taxa_servico_percentual || 0;
    const st = {
      desconto: 0, taxa: false, pessoas: s.pessoas || 0, pessoa: s.pessoa || 1, totalPessoas: s.totalPessoas || 0,
      outroValor: null, forma: null,
      itens: null, // pagamento por item: Map item_id -> quantidade
    };

    // Itens que ainda não foram pagos (para o pagamento por item).
    const itensAbertos = pedidos.flatMap((p) => p.itens.map((i) => ({ ...i, pedido: p.codigo, livre: i.quantidade - (i.pago_qtd || 0) })))
      .filter((i) => i.livre > 0);
    const somaItens = () => (st.itens ? itensAbertos.reduce((t, i) => t + (st.itens.get(i.id) || 0) * i.preco_centavos, 0) : 0);
    const acrescimo = () => (st.taxa ? Math.round((st.itens ? somaItens() : falta) * taxaPct / 100) : 0);
    const maximo = () => Math.max(0, falta - st.desconto + acrescimo());
    function aPagar() {
      if (st.itens) return somaItens() - st.desconto + acrescimo();
      if (st.outroValor !== null) return st.outroValor;
      if (st.pessoas > 1) return Math.ceil(maximo() / st.pessoas);
      return maximo();
    }

    // --- resumo da conta
    const itens = el("details", { class: "itens-conta" }, el("summary", {}, `Ver itens (${pedidos.length} pedido${pedidos.length > 1 ? "s" : ""})`),
      el("ul", {}, pedidos.map((p) => el("li", {}, `Pedido ${p.codigo}: ` + descreverItens(p) + " — " + moeda(p.total_centavos)))));
    const linhasResumo = el("div", {});

    // --- ajustes (escondidos até tocar)
    const campoDesconto = campoDinheiro({ oninput: () => { st.desconto = centavos(campoDesconto.value) || 0; atualizar(); } });
    const caixaDesconto = el("div", { class: "ajuste-aberto", hidden: true }, el("label", {}, "Desconto (R$)"), campoDesconto);
    // Quantas partes: o caixa digita o número (ou usa − e +), de 2 a 50.
    // (sem min/max no campo: um número fora da faixa escondido travaria o
    // envio da janela sem mostrar aviso — a faixa é conferida aqui no código)
    const nPessoas = el("input", { class: "n-pessoas", type: "number", step: 1, inputmode: "numeric",
      "aria-label": "Dividir em quantas partes", oninput: () => {
        const n = parseInt(nPessoas.value, 10);
        if (n >= 2 && n <= 50) { st.pessoas = n; atualizar(false); }
      }, onblur: () => { nPessoas.value = st.pessoas; } });
    const mudarPessoas = (d) => { st.pessoas = Math.min(50, Math.max(2, st.pessoas + d)); atualizar(); };
    const caixaDividir = el("div", { class: "ajuste-aberto dividir", hidden: true },
      el("span", {}, s.totalPessoas ? "Dividir o que falta em" : "Dividir em"),
      el("button", { type: "button", title: "Uma parte a menos", onclick: () => mudarPessoas(-1) }, "−"),
      nPessoas,
      el("button", { type: "button", title: "Uma parte a mais", onclick: () => mudarPessoas(1) }, "+"),
      el("span", {}, "partes"),
      el("span", { class: "atalhos" }, [2, 3, 4, 5, 6].map((n) =>
        el("button", { type: "button", class: "atalho", onclick: () => { st.pessoas = n; atualizar(); } }, String(n)))));
    const campoOutro = campoDinheiro({ oninput: () => { st.outroValor = campoOutro.value.trim() ? centavos(campoOutro.value) : null; atualizar(); } });
    const caixaOutro = el("div", { class: "ajuste-aberto", hidden: true },
      el("label", {}, "Valor a pagar agora (R$) — o resto continua em aberto na conta"), campoOutro);

    // Pagamento por item: o cliente escolhe o que consumiu e paga só isso.
    const caixaItens = el("div", { class: "ajuste-aberto por-item", hidden: true });
    function renderItens() {
      caixaItens.replaceChildren(el("div", { class: "dica" }, "Toque em + nos itens que o cliente vai pagar agora:"),
        ...itensAbertos.map((i) => {
          const n = st.itens ? st.itens.get(i.id) || 0 : 0;
          const mudar = (q) => { st.itens.set(i.id, Math.min(i.livre, Math.max(0, q))); renderItens(); atualizar(); };
          return el("div", { class: "item-pagar" + (n ? " marcado" : "") },
            el("div", { class: "nome" }, el("strong", {}, i.nome),
              el("small", {}, ` ${moeda(i.preco_centavos)} cada · falta pagar ${i.livre}` + (i.pago_qtd ? ` (${i.pago_qtd} já pago)` : "")
                + (pedidos.length > 1 ? ` · pedido ${i.pedido}` : ""))),
            el("div", { class: "qtd-cancelar" },
              el("button", { type: "button", onclick: () => mudar(n - 1) }, "−"),
              el("strong", {}, String(n)),
              el("button", { type: "button", onclick: () => mudar(n + 1) }, "+"),
              el("button", { type: "button", class: "discreto", onclick: () => mudar(n === i.livre ? 0 : i.livre) }, n === i.livre ? "nenhum" : "todos")));
        }));
    }

    function alternar(botao, caixa, ligar, desligar) {
      const aberto = !caixa.hidden;
      caixa.hidden = aberto;
      botao.classList.toggle("ligado", !aberto);
      (aberto ? desligar : ligar)();
      atualizar();
      if (!aberto) { const i = caixa.querySelector("input"); if (i) i.focus(); }
    }
    const bDesconto = el("button", { type: "button", class: "ajuste" }, "➖ Desconto");
    bDesconto.onclick = () => alternar(bDesconto, caixaDesconto, () => {}, () => { campoDesconto.value = ""; st.desconto = 0; });
    const bTaxa = taxaPct ? el("button", { type: "button", class: "ajuste" }, `➕ Taxa ${taxaPct}%`) : null;
    if (bTaxa) bTaxa.onclick = () => { st.taxa = !st.taxa; bTaxa.classList.toggle("ligado", st.taxa); atualizar(); };
    const bDividir = el("button", { type: "button", class: "ajuste" }, "➗ Dividir conta");
    bDividir.onclick = () => {
      alternar(bDividir, caixaDividir,
        () => { st.pessoas = 2; st.pessoa = 1; st.totalPessoas = 0; fecharOutro(); fecharItens(); },
        () => { st.pessoas = 0; st.totalPessoas = 0; });
      if (!caixaDividir.hidden) nPessoas.select();
    };
    const bOutro = el("button", { type: "button", class: "ajuste" }, "✏️ Pagar só uma parte");
    function fecharOutro() { caixaOutro.hidden = true; bOutro.classList.remove("ligado"); campoOutro.value = ""; st.outroValor = null; }
    bOutro.onclick = () => alternar(bOutro, caixaOutro, () => {
      if (!caixaDividir.hidden) { caixaDividir.hidden = true; bDividir.classList.remove("ligado"); st.pessoas = 0; }
      fecharItens();
    }, () => { campoOutro.value = ""; st.outroValor = null; });
    const bItens = itensAbertos.length ? el("button", { type: "button", class: "ajuste" }, "🧾 Pagar por item") : null;
    function fecharItens() { if (!bItens) return; caixaItens.hidden = true; bItens.classList.remove("ligado"); st.itens = null; }
    if (bItens) bItens.onclick = () => alternar(bItens, caixaItens, () => {
      if (!caixaDividir.hidden) { caixaDividir.hidden = true; bDividir.classList.remove("ligado"); st.pessoas = 0; st.totalPessoas = 0; }
      fecharOutro();
      st.itens = new Map();
      renderItens();
    }, () => { st.itens = null; });
    if (st.pessoas > 1) { caixaDividir.hidden = false; bDividir.classList.add("ligado"); }

    // --- valor a pagar agora
    const valorGrande = el("div", { class: "valor-agora" });

    // --- forma de pagamento: um toque
    const botoesForma = {};
    const campoEntregue = campoDinheiro({ oninput: atualizar });
    const troco = el("strong", {});
    const caixaDinheiro = el("div", { class: "caixa-dinheiro", hidden: true },
      el("label", {}, "Quanto o cliente entregou? (para calcular o troco — pode deixar em branco)"), campoEntregue,
      el("div", { class: "linha-troco" }, el("span", {}, "Troco"), troco));
    const grade = el("div", { class: "botoes-forma" }, Object.entries(estado.formas).map(([forma, nome]) => {
      botoesForma[forma] = el("button", { type: "button", class: "botao-forma", onclick: () => {
        st.forma = forma;
        caixaDinheiro.hidden = forma !== "dinheiro";
        atualizar();
        if (forma === "dinheiro") campoEntregue.focus(); else botaoOk().focus();
      } }, el("span", { class: "icone" }, ICONE_FORMA[forma] || "💲"), nome);
      return botoesForma[forma];
    }));

    function botaoOk() { return janela.elemento.querySelector("button[type=submit]"); }

    function atualizar(mexerNoCampo = true) {
      if (mexerNoCampo && st.pessoas >= 2) nPessoas.value = st.pessoas;
      caixaDividir.querySelectorAll(".atalho").forEach((b) => b.classList.toggle("ligado", Number(b.textContent) === st.pessoas));
      const linhas = [el("div", { class: "linha-valor" }, el("span", {}, "Total da conta"), el("span", {}, moeda(conta)))];
      // taxa (ou desconto) que já entrou num pagamento anterior desta conta
      const ajusteAntes = ab.pago - ab.subtotal;
      if (ajusteAntes > 0) linhas.push(el("div", { class: "linha-valor" }, el("span", {}, "Taxa de serviço (já cobrada)"), el("span", {}, "+ " + moeda(ajusteAntes))));
      if (ajusteAntes < 0) linhas.push(el("div", { class: "linha-valor" }, el("span", {}, "Desconto (já dado)"), el("span", {}, "− " + moeda(-ajusteAntes))));
      if (ab.subtotal) linhas.push(el("div", { class: "linha-valor positivo" }, el("span", {}, "Já pago antes (abatido)"), el("span", {}, "− " + moeda(ab.pago))));
      const ajustes = [
        st.desconto ? el("div", { class: "linha-valor" }, el("span", {}, "Desconto"), el("span", {}, "− " + moeda(st.desconto))) : null,
        acrescimo() ? el("div", { class: "linha-valor" }, el("span", {}, `Taxa de serviço (${taxaPct}%)` + (st.itens ? " sobre os itens" : "")),
          el("span", {}, "+ " + moeda(acrescimo()))) : null].filter(Boolean);
      if (st.itens) {
        // por item: o que falta da conta, depois os itens escolhidos e a taxa/desconto deles
        linhas.push(el("div", { class: "linha-valor destaque" }, el("span", {}, "Falta pagar da conta"), el("span", {}, moeda(falta))));
        linhas.push(el("div", { class: "linha-valor" }, el("span", {}, "Itens escolhidos"), el("span", {}, moeda(somaItens()))), ...ajustes);
      } else linhas.push(...ajustes);
      if (!st.itens && (ab.subtotal || st.desconto || acrescimo())) linhas.push(el("div", { class: "linha-valor destaque" }, el("span", {}, "Falta pagar"), el("span", {}, moeda(maximo()))));
      linhasResumo.replaceChildren(...linhas);

      const valor = aPagar();
      const valido = !Number.isNaN(valor) && valor >= 0 && valor <= maximo() && (!st.itens || somaItens() > 0)
        && (!st.itens || st.desconto <= somaItens());
      const rotulo = st.itens ? "Pagar os itens escolhidos"
        : st.pessoas > 1 || st.totalPessoas
        ? `Parte ${st.pessoa} de ${st.totalPessoas || st.pessoas}`
        : st.outroValor !== null ? "Pagar agora (parte)" : "A pagar";
      valorGrande.replaceChildren(el("span", {}, rotulo), el("strong", { class: valido ? "" : "negativo" },
        valido ? moeda(valor) : st.itens && !somaItens() ? "escolha os itens" : "valor inválido"));
      if (valido && valor < maximo()) valorGrande.append(el("small", {}, `Depois deste pagamento a conta continua aberta com ${moeda(maximo() - valor)}.`));
      if (st.outroValor !== null && valor > maximo()) valorGrande.append(el("small", { class: "negativo" }, `Passa do que falta (${moeda(maximo())}).`));

      for (const [f, b] of Object.entries(botoesForma)) b.classList.toggle("escolhida", st.forma === f);
      const entregue = centavos(campoEntregue.value) || 0;
      troco.textContent = entregue > valor ? moeda(entregue - valor) : entregue && entregue < valor ? "falta " + moeda(valor - entregue) : "—";
      troco.className = entregue && entregue < valor ? "negativo" : "positivo";

      const ok = botaoOk();
      if (ok) {
        ok.disabled = !valido || !st.forma;
        ok.textContent = !st.forma ? "Escolha como o cliente vai pagar"
          : valor < maximo() ? `Abater ${moeda(valor)} no ${estado.formas[st.forma]}`
          : `Receber ${moeda(valor)} no ${estado.formas[st.forma]}`;
      }
    }

    const corpo = el("div", { class: "pagamento" },
      el("div", { class: "pagamento-resumo" }, linhasResumo, itens),
      el("div", { class: "ajustes" }, bDesconto, bTaxa, bItens, bDividir, bOutro),
      caixaDesconto, caixaItens, caixaDividir, caixaOutro,
      valorGrande,
      el("label", {}, "Como o cliente vai pagar?"),
      grade,
      caixaDinheiro,
      el("p", { class: "dica" }, "Pagou com duas formas (ex.: parte no Pix e parte no cartão)? Toque em \"Pagar só uma parte\", receba a primeira e depois o resto."));

    const janela = dialogo({
      titulo: "Receber — " + titulo + (st.totalPessoas ? ` (parte ${st.pessoa} de ${st.totalPessoas})` : ""),
      corpo, largo: true, confirmar: "Receber",
      aoConfirmar: async () => {
        const valor = aPagar();
        if (Number.isNaN(valor) || Number.isNaN(st.desconto) || Number.isNaN(centavos(campoEntregue.value))) {
          throw new Error("Há um valor inválido. Use por exemplo 12,50");
        }
        if (!st.forma) throw new Error("Toque em como o cliente vai pagar.");
        const entregue = centavos(campoEntregue.value) || 0;
        const pago = st.forma === "dinheiro" && entregue > valor ? entregue : valor;
        const r = await api("POST", "/api/recebimentos", {
          pedido_ids: pedidos.map((p) => p.id),
          desconto: st.desconto, acrescimo: acrescimo(), valor,
          formas: pago ? [{ forma: st.forma, valor: pago }] : [],
          itens: st.itens ? [...st.itens.entries()].filter(([, q]) => q).map(([item_id, quantidade]) => ({ item_id, quantidade })) : null,
        });
        const rec = r.recebimento;
        const trocoTxt = rec.troco ? " — troco " + moeda(rec.troco) : "";
        if (rec.parcial) {
          const restante = maximo() - valor;
          aviso(`Abatido ${moeda(rec.total)}${trocoTxt}. A conta continua aberta com ${moeda(restante)}.`, "ok");
          monitor.forcar();
          // Conta dividida: já abre o pagamento da próxima pessoa.
          if (st.pessoas > 1) {
            setTimeout(() => dialogoPagamento(pedidos, titulo, {
              abatido: ab.subtotal + rec.subtotal, jaPago: ab.pago + rec.total,
              pessoas: st.pessoas - 1, pessoa: st.pessoa + 1, totalPessoas: st.totalPessoas || st.pessoas,
            }), 0);
          }
          return;
        }
        aviso("Pagamento de " + moeda(rec.total) + " registrado" + trocoTxt, "ok");
        monitor.forcar();
      },
    });
    atualizar();
  }

  function renderRecebidos() {
    if (!$("aba-recebidos")) return;
    const lista = estado.recebimentos || [];
    $("n-recebidos").textContent = lista.filter((r) => !r.estornado_em).length;
    if (!estado.caixa_aberto) {
      $("aba-recebidos").replaceChildren(el("div", { class: "vazio" }, "O caixa está fechado."));
      return;
    }
    if (!lista.length) {
      $("aba-recebidos").replaceChildren(el("div", { class: "vazio" }, "Nenhum pagamento recebido neste caixa ainda."));
      return;
    }
    $("aba-recebidos").replaceChildren(...lista.map((r) => el("div", { class: "recebimento" + (r.estornado_em ? " estornado" : "") },
      el("span", {}, hora(r.criado_em)),
      el("div", {}, r.descricao, el("div", { class: "formas" },
        r.formas.map((f) => estado.formas[f.forma] + " " + moeda(f.valor)).join(" + ")
        + (r.troco ? ` (troco ${moeda(r.troco)})` : "") + ` · ${r.usuario_nome}`
        + (r.estornado_em ? ` · ESTORNADO por ${r.estornado_por_nome}: ${r.motivo_estorno}` : ""))),
      el("strong", {}, moeda(r.total)),
      r.estornado_em ? el("span", {}) : el("button", {
        class: "discreto",
        disabled: !pode.estornar,
        title: pode.estornar ? "Estornar este pagamento" : "Estorno liberado só para quem o administrador permitir",
        onclick: () => dialogoEstorno(r),
      }, "Estornar"))));
  }

  function dialogoEstorno(r) {
    const motivo = el("input", { maxlength: 200, required: true, placeholder: "Ex.: forma de pagamento lançada errada" });
    dialogo({
      titulo: "Estornar pagamento de " + moeda(r.total) + "?",
      corpo: el("div", {}, el("p", {}, r.descricao + ". Os pedidos voltam para \"A receber\"."), el("label", {}, "Motivo (fica registrado)"), motivo),
      confirmar: "Estornar", cancelar: "Voltar", perigo: true,
      aoConfirmar: async () => {
        await api("POST", `/api/recebimentos/${r.id}/estornar`, { motivo: motivo.value });
        aviso("Pagamento estornado", "ok");
        monitor.forcar();
      },
    });
  }

  // --- Abertura, movimentos e fechamento do caixa -------------------------

  function renderBarraCaixa() {
    if (!$("barra-caixa")) return;
    const s = estado.sessao;
    const status = $("status-caixa");
    if (estado.caixa_aberto && s) {
      status.replaceChildren(
        el("span", { class: "aberto" }, "● Caixa aberto"),
        ` desde ${hora(s.aberto_em)} (${s.aberto_por_nome}) · ${s.qtd_vendas} venda(s): `,
        el("strong", {}, moeda(s.total_vendas)));
    } else if (estado.caixa_aberto) {
      status.replaceChildren(el("span", { class: "aberto" }, "● Caixa aberto"));
    } else {
      status.replaceChildren(el("span", { class: "fechado" }, "● Caixa fechado"),
        pode.caixa ? " — abra o caixa para receber pagamentos." : " — peça para quem tem permissão abrir o caixa.");
    }
    if (pode.caixa) {
      $("abrir-caixa").hidden = estado.caixa_aberto;
      $("sangria").hidden = $("suprimento").hidden = $("fechar-caixa").hidden = !estado.caixa_aberto;
    }
  }

  if (pode.caixa) {
    $("abrir-caixa").addEventListener("click", () => {
      const valor = campoDinheiro({ required: true });
      dialogo({
        titulo: "Abrir caixa",
        corpo: el("div", {}, el("label", {}, "Fundo de troco: quanto em dinheiro tem na gaveta agora? (R$)"), valor),
        confirmar: "Abrir caixa",
        aoConfirmar: async () => {
          const c = centavos(valor.value);
          if (Number.isNaN(c)) throw new Error("Valor inválido.");
          await api("POST", "/api/caixa/abrir", { valor_abertura: c });
          aviso("Caixa aberto", "ok");
          monitor.forcar();
        },
      });
    });

    const movimento = (tipo) => () => {
      const valor = campoDinheiro({ required: true });
      const motivo = el("input", { maxlength: 200, required: true,
        placeholder: tipo === "sangria" ? "Ex.: depósito no banco, pagamento de fornecedor" : "Ex.: reforço de troco" });
      dialogo({
        titulo: tipo === "sangria" ? "Sangria (retirar dinheiro do caixa)" : "Suprimento (colocar dinheiro no caixa)",
        corpo: el("div", {}, el("label", {}, "Valor (R$)"), valor, el("label", {}, "Motivo"), motivo),
        confirmar: "Registrar",
        aoConfirmar: async () => {
          const c = centavos(valor.value);
          if (Number.isNaN(c) || c <= 0) throw new Error("Valor inválido.");
          await api("POST", "/api/caixa/movimento", { tipo, valor: c, motivo: motivo.value });
          aviso(tipo === "sangria" ? "Sangria registrada" : "Suprimento registrado", "ok");
          monitor.forcar();
        },
      });
    };
    $("sangria").addEventListener("click", movimento("sangria"));
    $("suprimento").addEventListener("click", movimento("suprimento"));

    $("fechar-caixa").addEventListener("click", () => {
      const s = estado.sessao;
      const contado = campoDinheiro({ required: true });
      const obs = el("input", { maxlength: 300, placeholder: "Opcional" });
      const pendentes = estado.contas.length;
      dialogo({
        titulo: "Fechar caixa",
        corpo: el("div", {},
          el("div", { class: "pagamento-resumo" },
            el("div", { class: "linha-valor" }, el("span", {}, `Vendas (${s.qtd_vendas})`), el("strong", {}, moeda(s.total_vendas))),
            ...Object.entries(estado.formas).filter(([f]) => s.por_forma[f]).map(([f, nome]) =>
              el("div", { class: "linha-valor" }, el("span", {}, "  " + nome), el("span", {}, moeda(s.por_forma[f]))))),
          pendentes ? el("p", { class: "negativo" }, `Atenção: ${pendentes} conta(s) ainda a receber. Elas continuam em aberto para o próximo caixa.`) : null,
          el("label", {}, "Conte o dinheiro da gaveta (incluindo o fundo de troco). Quanto tem? (R$)"), contado,
          el("label", {}, "Observação"), obs),
        confirmar: "Fechar caixa",
        aoConfirmar: async () => {
          const c = centavos(contado.value);
          if (Number.isNaN(c)) throw new Error("Valor inválido.");
          const r = await api("POST", "/api/caixa/fechar", { valor_contado: c, observacao: obs.value });
          monitor.forcar();
          mostrarFechamento(r.sessao, r.impresso);
        },
      });
    });
  }

  function mostrarFechamento(s, impresso) {
    const dif = s.diferenca || 0;
    const linha = (rotulo, valor, classe) => el("div", { class: "linha-valor " + (classe || "") }, el("span", {}, rotulo), el("span", {}, valor));
    dialogo({
      titulo: "Caixa fechado",
      corpo: el("div", {},
        linha(`Vendas (${s.qtd_vendas})`, moeda(s.total_vendas)),
        ...Object.entries(estado.formas).filter(([f]) => s.por_forma[f]).map(([f, nome]) => linha("  " + nome, moeda(s.por_forma[f]))),
        el("hr"),
        linha("Fundo de troco", moeda(s.valor_abertura)),
        linha("+ Vendas em dinheiro", moeda(s.por_forma.dinheiro || 0)),
        linha("+ Suprimentos", moeda(s.suprimentos)),
        linha("− Sangrias", moeda(s.sangrias)),
        linha("Dinheiro esperado", moeda(s.esperado_dinheiro), "destaque"),
        linha("Dinheiro contado", moeda(s.valor_contado)),
        el("div", { class: "linha-valor destaque " + (dif === 0 ? "positivo" : "negativo") },
          el("span", {}, dif === 0 ? "Sem diferença ✓" : dif > 0 ? "SOBRA" : "FALTA"), el("span", {}, moeda(Math.abs(dif)))),
        impresso ? el("p", { class: "rotulo" }, "Comprovante enviado para a impressora do caixa.") : null),
      confirmar: "OK", cancelar: null,
    });
  }

  // --- Atualização periódica ---------------------------------------------

  function aplicarEstado(dados) {
    estado = dados;
    $("nome-loja").textContent = "— " + dados.loja;

    if (pode.pedidos) {
      const assinatura = JSON.stringify(dados.produtos.map((p) => [p.id, p.nome, p.preco_centavos, p.foto, p.categoria]));
      if (assinatura !== JSON.stringify(produtos.map((p) => [p.id, p.nome, p.preco_centavos, p.foto, p.categoria]))) {
        produtos = dados.produtos;
        carrinho = carrinho.filter((i) => produtos.some((p) => p.id === i.produto.id));
        renderCategorias();
        renderProdutos();
      }
      renderComandas();
      renderCarrinho();
      if ($("dl-pagamento").options.length <= 1) {
        $("dl-pagamento").replaceChildren(el("option", { value: "" }, "— não informado —"),
          ...Object.entries(dados.formas).map(([f, nome]) => el("option", { value: f }, nome)));
      }

      const prontos = dados.pedidos.filter((p) => p.status === "pronto");
      preencherLista("lista-prontos", "n-prontos", prontos, "Nenhum pedido pronto esperando chamada.");
      preencherLista("lista-cozinha", "n-cozinha", dados.pedidos.filter((p) => p.status === "novo" || p.status === "preparando"), "Nenhum pedido na cozinha.");
      preencherLista("lista-chamados", "n-chamados", dados.pedidos.filter((p) => p.status === "chamado").reverse(), "Ninguém aguardando retirada.");

      // Avisos sonoros: pedido que acabou de ficar pronto e chamado de garçom novo.
      const idsProntos = new Set(prontos.map((p) => p.id));
      if (prontosVistos && [...idsProntos].some((id) => !prontosVistos.has(id))) bip("novo");
      prontosVistos = idsProntos;
      const idsChamados = new Set(dados.chamados_garcom.map((c) => c.id));
      if (chamadosVistos && [...idsChamados].some((id) => !chamadosVistos.has(id))) bip("garcom");
      chamadosVistos = idsChamados;

      $("chamados-garcom").replaceChildren(...dados.chamados_garcom.map((c) =>
        el("div", { class: "alerta-garcom" },
          c.tipo === "conta" ? "🧾 Mesa " + c.mesa + " pediu a conta" : "🙋 Mesa " + c.mesa + " chamou o garçom",
          el("span", { style: "font-weight: 400; opacity: .8" }, "há " + minutosDesde(c.criado_em) + " min"),
          el("button", { onclick: () => acao("POST", `/api/garcom/${c.id}/atender`) }, "Atendido"))));
    }
    renderContas();
    renderRecebidos();
    renderBarraCaixa();
  }

  const monitor = C.acompanhar("/api/estado", aplicarEstado, 2000);
  // Atualiza os "há X min" mesmo sem nada mudar no servidor.
  setInterval(() => monitor.forcar(), 30000);
})();
