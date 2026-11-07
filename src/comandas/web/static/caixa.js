(function () {
  "use strict";
  const { api, moeda, el, minutosDesde, hora, aviso, bip, centavos, reais, campoDinheiro, dialogo } = window.C;
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

  function renderCarrinho() {
    const total = carrinho.reduce((s, i) => s + i.produto.preco_centavos * i.quantidade, 0);
    $("total").textContent = moeda(total);
    $("qtd-itens").textContent = carrinho.reduce((s, i) => s + i.quantidade, 0);
    $("enviar").disabled = !carrinho.length;
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
    $("linha-comanda").hidden = !estado.modo_comandas;
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

  function limparCarrinho() {
    carrinho = [];
    $("comanda").value = "";
    $("cliente").value = $("mesa").value = $("obs").value = "";
    renderCarrinho();
  }

  async function enviarPedido(receberDepois) {
    $("enviar").disabled = true;
    try {
      const r = await api("POST", "/api/pedidos", {
        itens: carrinho.map((i) => ({ produto_id: i.produto.id, quantidade: i.quantidade, observacao: i.observacao })),
        cliente: $("cliente").value, mesa: $("mesa").value, observacao: $("obs").value,
        comanda_id: $("comanda").value || null,
      });
      aviso("Pedido nº " + r.pedido.codigo + (r.pedido.setores.length ? " enviado para: " + r.pedido.setores.join(" e ") : " registrado (sem preparo, já está pronto)"), "ok");
      limparCarrinho();
      monitor.forcar();
      if (receberDepois) dialogoPagamento([r.pedido], r.pedido.comanda_numero ? "Comanda " + r.pedido.comanda_numero : "Pedido nº " + r.pedido.codigo);
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

  function dialogoCancelar(p) {
    const motivo = el("input", { maxlength: 200, required: true, placeholder: "Ex.: cliente desistiu, lançado errado" });
    dialogo({
      titulo: "Cancelar o pedido nº " + p.codigo + "?",
      corpo: el("div", {}, el("p", {}, p.itens.map((i) => i.quantidade + "× " + i.nome).join(", ") + " — " + moeda(p.total_centavos)),
        el("label", {}, "Motivo do cancelamento (fica registrado)"), motivo),
      confirmar: "Cancelar pedido", cancelar: "Voltar", perigo: true,
      aoConfirmar: async () => {
        await api("POST", `/api/pedidos/${p.id}/status`, { status: "cancelado", motivo: motivo.value });
        aviso("Pedido cancelado", "ok");
        monitor.forcar();
      },
    });
  }

  function cartaoPedido(p) {
    const botoes = [];
    const chamar = (rotulo, classe) => el("button", { class: classe || "", onclick: () => acao("POST", `/api/pedidos/${p.id}/chamar`, {}, `Pedido ${p.codigo} chamado no painel`) }, rotulo);
    if (pode.pedidos) {
      if (p.status === "pronto") {
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
      botoes.push(el("button", { class: "discreto", title: "Cancelar pedido", onclick: () => dialogoCancelar(p) }, "✕"));
    }
    const quem = [p.origem === "qrcode" ? el("span", { class: "etiqueta qrcode" }, "QR code") : null,
      p.origem === "garcom" ? el("span", { class: "etiqueta qrcode" }, "Garçom " + (p.usuario_nome || "")) : null,
      p.comanda_numero ? el("span", { class: "etiqueta chamado" }, "Comanda " + p.comanda_numero) : null,
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
      el("div", { class: "acoes" }, botoes));
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
      el("div", { class: "cabeca" }, el("h3", {}, c.titulo), el("span", { class: "espaco" }), el("strong", {}, moeda(c.total))),
      el("ul", {}, c.pedidos.map((p) => el("li", {},
        `Pedido ${p.codigo} (${hora(p.criado_em)}): ` + p.itens.map((i) => i.quantidade + "× " + i.nome).join(", ") + " — " + moeda(p.total_centavos)))),
      el("div", { class: "acoes" },
        estado.impressora_caixa_ativa ? el("button", { onclick: () => acao("POST", "/api/contas/imprimir", { pedido_ids: c.pedidos.map((p) => p.id), titulo: c.titulo }, "Conta enviada para a impressora") }, "🖨️ Imprimir conta") : null,
        pode.receber ? el("button", { class: "verde", disabled: !estado.caixa_aberto, title: estado.caixa_aberto ? "" : "Abra o caixa para receber",
          onclick: () => dialogoPagamento(c.pedidos, c.titulo) }, "💲 Receber") : null))));
  }

  function dialogoPagamento(pedidos, titulo) {
    if (!estado.caixa_aberto) {
      aviso("O caixa está fechado. Abra o caixa para receber.", "erro");
      return;
    }
    const subtotal = pedidos.reduce((s, p) => s + p.total_centavos, 0);
    const desconto = campoDinheiro();
    const acrescimo = campoDinheiro();
    const taxa = estado.taxa_servico_percentual || 0;
    const campos = {};
    const saldo = el("div", { class: "saldo-pagamento" });
    const totalEl = el("strong", {});

    function total() {
      return subtotal - (centavos(desconto.value) || 0) + (centavos(acrescimo.value) || 0);
    }
    function recebido() {
      return Object.values(campos).reduce((s, c) => s + (centavos(c.value) || 0), 0);
    }
    function atualizar() {
      totalEl.textContent = moeda(total());
      const dif = recebido() - total();
      saldo.replaceChildren(
        el("span", {}, dif < 0 ? "Falta receber" : dif > 0 ? "Troco" : "Tudo certo"),
        el("span", { class: dif < 0 ? "negativo" : "positivo" }, moeda(Math.abs(dif))));
    }

    const grade = el("div", { class: "grade-formas" }, Object.entries(estado.formas).map(([forma, nome]) => {
      campos[forma] = campoDinheiro({ oninput: atualizar });
      return el("label", { class: "forma" },
        el("span", {}, nome, el("button", { type: "button", title: "Preencher com o que falta", onclick: () => {
          campos[forma].value = "";
          const falta = total() - recebido();
          if (falta > 0) campos[forma].value = reais(falta);
          atualizar();
        } }, "restante")),
        campos[forma]);
    }));
    desconto.addEventListener("input", atualizar);
    acrescimo.addEventListener("input", atualizar);

    const corpo = el("div", {},
      el("div", { class: "pagamento-resumo" },
        el("ul", {}, pedidos.map((p) => el("li", {}, `Pedido ${p.codigo}: ` + p.itens.map((i) => i.quantidade + "× " + i.nome).join(", ") + " — " + moeda(p.total_centavos)))),
        el("div", { class: "linha-valor" }, el("span", {}, "Subtotal"), el("span", {}, moeda(subtotal)))),
      el("div", { class: "campos-duplos" },
        el("div", {}, el("label", {}, "Desconto (R$)"), desconto),
        el("div", {}, el("label", {}, "Acréscimo / taxa de serviço (R$)",
          taxa ? el("button", { type: "button", class: "discreto", onclick: () => { acrescimo.value = reais(Math.round(subtotal * taxa / 100)); atualizar(); } }, `+${taxa}%`) : null), acrescimo)),
      el("div", { class: "linha-valor destaque" }, el("span", {}, "Total a pagar"), totalEl),
      el("label", {}, "Como o cliente vai pagar? (pode dividir entre várias formas; em dinheiro, digite o valor entregue para calcular o troco)"),
      grade,
      saldo);
    atualizar();
    dialogo({
      titulo: "Receber — " + titulo,
      corpo, largo: true, confirmar: "Confirmar pagamento",
      aoConfirmar: async () => {
        for (const c of [desconto, acrescimo, ...Object.values(campos)]) {
          if (Number.isNaN(centavos(c.value))) throw new Error("Há um valor inválido. Use por exemplo 12,50");
        }
        const r = await api("POST", "/api/recebimentos", {
          pedido_ids: pedidos.map((p) => p.id),
          desconto: centavos(desconto.value), acrescimo: centavos(acrescimo.value),
          formas: Object.entries(campos).map(([forma, c]) => ({ forma, valor: centavos(c.value) })).filter((f) => f.valor > 0),
        });
        aviso("Pagamento de " + moeda(r.recebimento.total) + " registrado" + (r.recebimento.troco ? " — troco " + moeda(r.recebimento.troco) : ""), "ok");
        monitor.forcar();
      },
    });
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
