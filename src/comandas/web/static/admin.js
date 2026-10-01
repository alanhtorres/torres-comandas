(function () {
  "use strict";
  const { api, moeda, el, aviso, dialogo, dataHora, hojeISO } = window.C;
  const $ = (id) => document.getElementById(id);

  // --- Abas -------------------------------------------------------------------

  const carregadores = {};
  function abrirAba() {
    const disponiveis = [...document.querySelectorAll(".abas a")].map((a) => a.dataset.aba);
    const nome = location.hash.slice(1);
    const aba = disponiveis.includes(nome) ? nome : disponiveis[0];
    document.querySelectorAll(".aba").forEach((s) => (s.hidden = s.id !== "aba-" + aba));
    document.querySelectorAll(".abas a").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === aba));
    if (carregadores[aba]) carregadores[aba]();
  }
  window.addEventListener("hashchange", abrirAba);

  // --- Produtos ---------------------------------------------------------------

  if ($("aba-produtos")) {
    let produtos = [];

    const precoParaCentavos = window.C.centavos;

    function limparFormProduto() {
      $("form-produto").reset();
      $("produto-id").value = "";
      $("produto-ativo").checked = true;
      $("titulo-form-produto").textContent = "Novo produto";
      $("cancelar-edicao").hidden = true;
    }

    function editarProduto(p) {
      $("produto-id").value = p.id;
      $("produto-nome").value = p.nome;
      $("produto-categoria").value = p.categoria;
      $("produto-preco").value = (p.preco_centavos / 100).toFixed(2).replace(".", ",");
      $("produto-descricao").value = p.descricao;
      $("produto-ativo").checked = p.ativo;
      $("produto-foto").value = "";
      $("titulo-form-produto").textContent = "Editando: " + p.nome;
      $("cancelar-edicao").hidden = false;
      $("form-produto").scrollIntoView({ behavior: "smooth" });
      $("produto-nome").focus();
    }

    async function enviarFoto(produtoId, arquivo) {
      const dados = new FormData();
      dados.append("arquivo", arquivo);
      await api("POST", `/api/produtos/${produtoId}/foto`, dados);
    }

    $("form-produto").addEventListener("submit", async (e) => {
      e.preventDefault();
      const centavos = precoParaCentavos($("produto-preco").value);
      if (Number.isNaN(centavos) || centavos < 0) {
        aviso("Preço inválido. Use por exemplo 12,50", "erro");
        return;
      }
      const corpo = {
        nome: $("produto-nome").value,
        categoria: $("produto-categoria").value,
        preco_centavos: centavos,
        descricao: $("produto-descricao").value,
        ativo: $("produto-ativo").checked,
      };
      try {
        const id = $("produto-id").value;
        const r = id ? await api("PUT", "/api/produtos/" + id, corpo) : await api("POST", "/api/produtos", corpo);
        const arquivo = $("produto-foto").files[0];
        if (arquivo) await enviarFoto(r.produto.id, arquivo);
        aviso("Produto salvo", "ok");
        limparFormProduto();
        carregarProdutos();
      } catch (err) {
        aviso(err.message, "erro");
      }
    });
    $("cancelar-edicao").addEventListener("click", limparFormProduto);

    async function carregarProdutos() {
      produtos = (await api("GET", "/api/produtos")).produtos;
      const categorias = [...new Set(produtos.map((p) => p.categoria))];
      $("lista-categorias").replaceChildren(...categorias.map((c) => el("option", { value: c })));
      if (!produtos.length) {
        $("lista-produtos").replaceChildren(el("div", { class: "vazio" }, "Nenhum produto ainda. Cadastre o primeiro acima."));
        return;
      }
      const linhas = [];
      for (const cat of categorias) {
        linhas.push(el("tr", { class: "grupo-categoria" }, el("td", { colspan: 5 }, cat)));
        for (const p of produtos.filter((x) => x.categoria === cat)) {
          const inputFoto = el("input", { type: "file", accept: "image/*", hidden: true, onchange: async (e) => {
            try { await enviarFoto(p.id, e.target.files[0]); aviso("Foto atualizada", "ok"); carregarProdutos(); }
            catch (err) { aviso(err.message, "erro"); }
          } });
          linhas.push(el("tr", { class: p.ativo ? "" : "inativo" },
            el("td", {}, p.foto ? el("img", { class: "miniatura", src: "/foto/" + p.foto, alt: "" }) : el("div", { class: "sem-foto" }, "📷")),
            el("td", {}, el("strong", {}, p.nome), p.descricao ? el("div", { class: "dica" }, p.descricao) : null),
            el("td", {}, moeda(p.preco_centavos)),
            el("td", {}, p.ativo ? "" : el("span", { class: "etiqueta" }, "indisponível")),
            el("td", { class: "acoes" },
              inputFoto,
              el("button", { title: "Trocar foto", onclick: () => inputFoto.click() }, "📷"),
              el("button", { title: p.ativo ? "Marcar como indisponível" : "Marcar como disponível", onclick: async () => {
                await api("PUT", "/api/produtos/" + p.id, { ativo: !p.ativo }); carregarProdutos();
              } }, p.ativo ? "Pausar" : "Ativar"),
              el("button", { onclick: () => editarProduto(p) }, "Editar"),
              el("button", { class: "perigo", onclick: async () => {
                if (!confirm("Excluir " + p.nome + "?")) return;
                await api("DELETE", "/api/produtos/" + p.id); carregarProdutos();
              } }, "Excluir"))));
        }
      }
      $("lista-produtos").replaceChildren(el("table", { class: "tabela" }, el("tbody", {}, linhas)));
    }
    carregadores.produtos = () => carregarProdutos().catch((e) => aviso(e.message, "erro"));
  }

  // --- Mesas ------------------------------------------------------------------

  if ($("aba-mesas")) {
    async function carregarMesas() {
      const r = await api("GET", "/api/mesas");
      $("url-base").textContent = r.url_base;
      if (!r.mesas.length) {
        $("lista-mesas").replaceChildren(el("div", { class: "vazio" }, "Nenhuma mesa cadastrada."));
        return;
      }
      $("lista-mesas").replaceChildren(...r.mesas.map((m) => el("div", { class: "mesa" },
        el("img", { src: `/qrcode/mesa/${m.id}.svg?t=${m.token}`, alt: "QR code" }),
        el("strong", {}, "Mesa " + m.numero),
        el("div", { class: "botoes" },
          el("a", { href: m.link, target: "_blank" }, el("button", {}, "Abrir")),
          el("button", { title: "Gera um QR code novo e invalida o antigo", onclick: async () => {
            if (!confirm("Gerar um QR code novo para a mesa " + m.numero + "? O QR code impresso atual deixa de funcionar.")) return;
            await api("POST", `/api/mesas/${m.id}/novo-qrcode`); carregarMesas();
          } }, "Novo QR"),
          el("button", { class: "perigo", onclick: async () => {
            if (!confirm("Excluir a mesa " + m.numero + "?")) return;
            await api("DELETE", "/api/mesas/" + m.id); carregarMesas();
          } }, "Excluir")))));
    }
    carregadores.mesas = () => carregarMesas().catch((e) => aviso(e.message, "erro"));

    $("criar-lote").addEventListener("click", async () => {
      try {
        const r = await api("POST", "/api/mesas", { de: $("mesa-de").value, ate: $("mesa-ate").value });
        aviso(r.criadas + " mesa(s) criada(s)", "ok");
        carregarMesas();
      } catch (err) { aviso(err.message, "erro"); }
    });
    $("criar-mesa").addEventListener("click", async () => {
      try {
        await api("POST", "/api/mesas", { numero: $("mesa-nome").value });
        $("mesa-nome").value = "";
        carregarMesas();
      } catch (err) { aviso(err.message, "erro"); }
    });
  }

  // --- Mídias do painel -----------------------------------------------------

  if ($("aba-midias")) {
    async function carregarMidias() {
      const { midias } = await api("GET", "/api/midias");
      if (!midias.length) {
        $("lista-midias").replaceChildren(el("div", { class: "vazio" }, "Nenhuma mídia enviada — o painel está mostrando as fotos dos produtos."));
        return;
      }
      $("lista-midias").replaceChildren(el("table", { class: "tabela" }, el("tbody", {}, midias.map((m, i) =>
        el("tr", { class: m.ativo ? "" : "inativo" },
          el("td", {}, m.tipo === "foto"
            ? el("img", { class: "miniatura", src: "/midia/" + m.arquivo, alt: "" })
            : el("video", { class: "miniatura", src: "/midia/" + m.arquivo + "#t=1", muted: true, preload: "metadata" })),
          el("td", {}, m.nome_original || m.arquivo, el("div", { class: "dica" }, m.tipo === "foto" ? "Foto" : "Vídeo (toca até o fim)")),
          el("td", {}, m.tipo === "foto" ? el("label", { class: "inline", style: "font-size: .85rem" },
            el("input", { type: "number", min: 2, max: 300, value: m.duracao || "", placeholder: "padrão", onchange: async (e) => {
              await api("PUT", "/api/midias/" + m.id, { duracao: e.target.value || null }); aviso("Duração salva", "ok");
            } }), "seg") : null),
          el("td", { class: "acoes" },
            el("button", { disabled: i === 0, onclick: async () => { await api("PUT", "/api/midias/" + m.id, { mover: -1 }); carregarMidias(); } }, "↑"),
            el("button", { disabled: i === midias.length - 1, onclick: async () => { await api("PUT", "/api/midias/" + m.id, { mover: 1 }); carregarMidias(); } }, "↓"),
            el("button", { onclick: async () => { await api("PUT", "/api/midias/" + m.id, { ativo: !m.ativo }); carregarMidias(); } }, m.ativo ? "Pausar" : "Ativar"),
            el("button", { class: "perigo", onclick: async () => {
              if (!confirm("Remover esta mídia do painel?")) return;
              await api("DELETE", "/api/midias/" + m.id); carregarMidias();
            } }, "Excluir")))))));
    }
    carregadores.midias = () => carregarMidias().catch((e) => aviso(e.message, "erro"));

    $("enviar-midia").addEventListener("click", () => {
      const arquivos = $("arquivos-midia").files;
      if (!arquivos.length) { aviso("Escolha um ou mais arquivos", "erro"); return; }
      const dados = new FormData();
      for (const a of arquivos) dados.append("arquivos", a);
      // XHR (e não fetch) para mostrar o progresso de vídeos grandes.
      const xhr = new XMLHttpRequest();
      const barra = $("progresso-midia");
      barra.hidden = false;
      barra.value = 0;
      $("enviar-midia").disabled = true;
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) barra.value = (e.loaded / e.total) * 100; };
      xhr.onloadend = () => {
        barra.hidden = true;
        $("enviar-midia").disabled = false;
        let r = {};
        try { r = JSON.parse(xhr.responseText); } catch (e) { /* resposta inválida */ }
        if (xhr.status === 200 && r.ok) {
          let msg = r.adicionadas + " arquivo(s) adicionado(s)";
          if (r.recusados.length) msg += ". Não aceitos: " + r.recusados.join(", ");
          aviso(msg, r.recusados.length ? "erro" : "ok");
          $("arquivos-midia").value = "";
          carregarMidias();
        } else {
          aviso(r.erro || (xhr.status === 413 ? "Arquivo grande demais (máx. 500 MB)." : "Falha no envio."), "erro");
        }
      };
      xhr.open("POST", "/api/midias");
      xhr.send(dados);
    });
  }

  // --- Configurações ----------------------------------------------------------

  if ($("aba-config")) {
    async function carregarConfig() {
      const { config, url_base_detectada } = await api("GET", "/api/config");
      const form = $("form-config");
      for (const campo of form.querySelectorAll("[name]")) {
        const valor = config[campo.name];
        if (campo.type === "checkbox") campo.checked = !!valor;
        else campo.value = valor === undefined || valor === null ? "" : valor;
      }
      $("cfg-url_base").placeholder = url_base_detectada ? "Detectado: " + url_base_detectada : "http://192.168.0.10:8090";
      }
    carregadores.config = () => carregarConfig().catch((e) => aviso(e.message, "erro"));

    async function salvarConfig() {
      const corpo = {};
      for (const campo of $("form-config").querySelectorAll("[name]")) {
        corpo[campo.name] = campo.type === "checkbox" ? campo.checked : campo.value;
      }
      await api("PUT", "/api/config", corpo);
      await carregarConfig();
    }

    $("form-config").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await salvarConfig();
        aviso("Configurações salvas", "ok");
      } catch (err) {
        aviso(err.message, "erro");
      }
    });

    document.querySelectorAll("[data-teste]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        // salva antes, pra testar exatamente o IP/porta que estão na tela
        await salvarConfig();
        await api("POST", "/api/impressora/teste", { qual: b.dataset.teste });
        aviso("Teste enviado para a impressora", "ok");
      } catch (err) {
        aviso(err.message, "erro");
      } finally {
        b.disabled = false;
      }
    }));
  }

  // --- Usuários e permissões -------------------------------------------------

  if ($("aba-usuarios")) {
    let catalogo = { permissoes: {}, modelos: {} };

    async function carregarUsuarios() {
      const r = await api("GET", "/api/usuarios");
      catalogo = r;
      $("lista-usuarios").replaceChildren(el("table", { class: "tabela" },
        el("thead", {}, el("tr", {}, el("th", {}, "Nome"), el("th", {}, "Usuário"), el("th", {}, "Pode acessar"), el("th", {}, ""))),
        el("tbody", {}, r.usuarios.map((u) => el("tr", { class: u.ativo ? "" : "inativo" },
          el("td", {}, el("strong", {}, u.nome), u.ativo ? null : el("div", { class: "dica" }, "desativado")),
          el("td", {}, u.login),
          el("td", {}, u.permissoes.length === Object.keys(r.permissoes).length
            ? el("span", { class: "etiqueta pronto" }, "Tudo (administrador)")
            : u.permissoes.length ? el("div", { class: "lista-permissoes" }, u.permissoes.map((p) => el("span", { class: "etiqueta" }, rotuloCurto(p))))
              : el("span", { class: "dica" }, "nenhuma permissão")),
          el("td", { class: "acoes" }, el("button", { onclick: () => dialogoUsuario(u) }, "Editar")))))));
    }

    const CURTOS = { pedidos: "Caixa/pedidos", cozinha: "Cozinha", receber: "Receber", caixa: "Abrir/fechar caixa",
      cancelar: "Cancelar/estornar", cardapio: "Cardápio", mesas: "Mesas", midias: "Mídias", configuracoes: "Configurações",
      relatorios: "Relatórios", historico: "Histórico", usuarios: "Usuários" };
    const rotuloCurto = (p) => CURTOS[p] || p;

    function dialogoUsuario(u) {
      const novo = !u;
      const nome = el("input", { maxlength: 60, required: true, value: u ? u.nome : "" });
      const login = el("input", { maxlength: 30, required: novo, value: u ? u.login : "", disabled: !novo, autocapitalize: "none", pattern: "\\S+" });
      const senha = el("input", { type: "password", minlength: 4, required: novo, autocomplete: "new-password",
        placeholder: novo ? "" : "Deixe em branco para manter a atual" });
      const ativo = el("input", { type: "checkbox", checked: u ? u.ativo : true });
      const caixas = {};
      const lista = el("div", { class: "lista-checks" }, Object.entries(catalogo.permissoes).map(([p, descricao]) => {
        caixas[p] = el("input", { type: "checkbox", checked: u ? u.permissoes.includes(p) : false });
        return el("label", { class: "inline" }, caixas[p], descricao);
      }));
      const modelos = el("div", { class: "linha" }, el("span", { class: "dica" }, "Modelos prontos:"),
        Object.values(catalogo.modelos).map((m) => el("button", { type: "button", onclick: () => {
          for (const [p, c] of Object.entries(caixas)) c.checked = m.permissoes.includes(p);
        } }, m.nome)));
      dialogo({
        titulo: novo ? "Novo usuário" : "Editar usuário — " + u.nome,
        largo: true,
        corpo: el("div", {},
          el("div", { class: "grade-form" },
            el("div", {}, el("label", {}, "Nome"), nome),
            el("div", {}, el("label", {}, "Usuário (login, sem espaços)"), login),
            el("div", {}, el("label", {}, novo ? "Senha (mínimo 4 caracteres)" : "Nova senha"), senha)),
          el("h3", { class: "subtitulo" }, "O que este usuário pode acessar"),
          modelos, lista,
          novo ? null : el("label", { class: "inline", style: "margin-top: 12px" }, ativo, "Usuário ativo (desmarque para bloquear o acesso)")),
        confirmar: novo ? "Criar usuário" : "Salvar",
        aoConfirmar: async () => {
          const permissoes = Object.entries(caixas).filter(([, c]) => c.checked).map(([p]) => p);
          if (novo) {
            await api("POST", "/api/usuarios", { nome: nome.value, login: login.value, senha: senha.value, permissoes });
          } else {
            const dados = { nome: nome.value, permissoes, ativo: ativo.checked };
            if (senha.value) dados.senha = senha.value;
            await api("PUT", "/api/usuarios/" + u.id, dados);
          }
          aviso("Usuário salvo", "ok");
          carregarUsuarios();
        },
      });
    }

    $("novo-usuario").addEventListener("click", () => dialogoUsuario(null));
    carregadores.usuarios = () => carregarUsuarios().catch((e) => aviso(e.message, "erro"));
  }

  // --- Relatórios ----------------------------------------------------------

  if ($("aba-relatorios")) {
    $("rel-de").value = $("rel-ate").value = hojeISO();

    function definirPeriodo(p) {
      if (p === "mes") {
        const hoje = hojeISO();
        $("rel-de").value = hoje.slice(0, 8) + "01";
        $("rel-ate").value = hoje;
      } else if (p === "1") {
        $("rel-de").value = $("rel-ate").value = hojeISO(-1);
      } else {
        $("rel-de").value = hojeISO(-(Number(p) ? Number(p) - 1 : 0));
        $("rel-ate").value = hojeISO();
      }
      carregarRelatorio();
    }
    document.querySelectorAll("[data-periodo]").forEach((b) => b.addEventListener("click", () => definirPeriodo(b.dataset.periodo)));
    $("rel-de").addEventListener("change", carregarRelatorio);
    $("rel-ate").addEventListener("change", carregarRelatorio);

    const cartaoNumero = (rotulo, valor, dica) => el("div", { class: "cartao numero" }, el("span", { class: "dica" }, rotulo), el("strong", {}, valor), dica ? el("span", { class: "dica" }, dica) : null);
    const barra = (valor, maximo) => el("div", { class: "barra" }, el("div", { style: `width: ${maximo ? Math.max(2, (valor / maximo) * 100) : 0}%` }));
    const secao = (titulo, conteudo) => el("div", { class: "cartao" }, el("h2", {}, titulo), conteudo);
    const tabela = (cabecalho, linhas, vazio) => linhas.length
      ? el("table", { class: "tabela" }, el("thead", {}, el("tr", {}, cabecalho.map((c) => el("th", {}, c)))), el("tbody", {}, linhas))
      : el("div", { class: "vazio" }, vazio || "Nada no período.");

    async function carregarRelatorio() {
      const de = $("rel-de").value, ate = $("rel-ate").value;
      $("rel-csv").href = `/api/relatorios/vendas.csv?de=${de}&ate=${ate}`;
      let r, formas;
      try {
        ({ relatorio: r, formas } = await api("GET", `/api/relatorios?de=${de}&ate=${ate}`));
      } catch (e) {
        aviso(e.message, "erro");
        return;
      }
      const maxForma = Math.max(0, ...Object.values(r.por_forma));
      const maxProduto = Math.max(0, ...r.por_produto.map((p) => p.valor));
      const maxDia = Math.max(0, ...r.por_dia.map((d) => d.valor));
      const dif = (d) => el("span", { class: d === 0 ? "positivo" : "negativo" }, d === 0 ? "ok" : (d > 0 ? "sobra " : "falta ") + moeda(Math.abs(d)));
      // (seções que não se aplicam ao período vêm como null e são puladas)
      $("relatorio").replaceChildren(...[
        el("div", { class: "numeros" },
          cartaoNumero("Total vendido", moeda(r.total_vendas), r.descontos ? `descontos: ${moeda(r.descontos)}` : null),
          cartaoNumero("Vendas", r.qtd_vendas),
          cartaoNumero("Ticket médio", moeda(r.ticket_medio)),
          cartaoNumero("A receber agora", moeda(r.a_receber.total), `${r.a_receber.quantidade} pedido(s) sem pagamento`)),
        el("div", { class: "duas-colunas" },
          secao("Por forma de pagamento", tabela(["Forma", "", "Valor"],
            Object.entries(formas).filter(([f]) => r.por_forma[f]).map(([f, nome]) =>
              el("tr", {}, el("td", {}, nome), el("td", { class: "col-barra" }, barra(r.por_forma[f], maxForma)), el("td", {}, moeda(r.por_forma[f])))))),
          secao("Por atendente (quem recebeu)", tabela(["Usuário", "Vendas", "Valor"],
            r.por_usuario.map((u) => el("tr", {}, el("td", {}, u.nome), el("td", {}, u.quantidade), el("td", {}, moeda(u.valor))))))),
        r.por_dia.length > 1 ? secao("Vendas por dia", tabela(["Dia", "", "Valor"], r.por_dia.map((d) =>
          el("tr", {}, el("td", {}, d.dia.split("-").reverse().join("/")), el("td", { class: "col-barra" }, barra(d.valor, maxDia)), el("td", {}, moeda(d.valor)))))) : null,
        secao("Produtos vendidos", tabela(["Produto", "Qtd.", "", "Valor (sem descontos)"], r.por_produto.map((p) =>
          el("tr", {}, el("td", {}, p.nome), el("td", {}, p.quantidade), el("td", { class: "col-barra" }, barra(p.valor, maxProduto)), el("td", {}, moeda(p.valor)))))),
        secao("Caixas (abertura e fechamento)", tabela(["Abertura", "Fechamento", "Vendas", "Dinheiro esperado", "Contado", "Diferença", ""],
          r.sessoes.map((s) => el("tr", {},
            el("td", {}, dataHora(s.aberto_em), el("div", { class: "dica" }, s.aberto_por_nome + " · fundo " + moeda(s.valor_abertura))),
            el("td", {}, s.fechado_em ? [dataHora(s.fechado_em), el("div", { class: "dica" }, s.fechado_por_nome)] : el("span", { class: "etiqueta pronto" }, "aberto")),
            el("td", {}, moeda(s.total_vendas), el("div", { class: "dica" }, s.qtd_vendas + " venda(s)")),
            el("td", {}, moeda(s.esperado_dinheiro || 0)),
            el("td", {}, s.valor_contado == null ? "—" : moeda(s.valor_contado)),
            el("td", {}, s.fechado_em ? dif(s.diferenca || 0) : "—", s.observacao ? el("div", { class: "dica" }, s.observacao) : null),
            el("td", { class: "acoes" }, el("button", { title: "Imprimir na impressora do caixa", onclick: async () => {
              try { await api("POST", `/api/caixa/sessoes/${s.id}/imprimir`); aviso("Enviado para a impressora", "ok"); } catch (e) { aviso(e.message, "erro"); }
            } }, "🖨️"))))), "Nenhum caixa aberto no período."),
        el("div", { class: "duas-colunas" },
          secao("Pagamentos estornados", tabela(["Quando", "O quê", "Valor", "Quem estornou / motivo"], r.estornos.map((e) =>
            el("tr", {}, el("td", {}, dataHora(e.estornado_em)), el("td", {}, e.descricao), el("td", {}, moeda(e.total)),
              el("td", {}, e.estornado_por_nome, el("div", { class: "dica" }, e.motivo_estorno)))))),
          secao("Pedidos cancelados", tabela(["Quando", "Pedido", "Valor", "Quem cancelou / motivo"], r.cancelados.map((c) =>
            el("tr", {}, el("td", {}, dataHora(c.atualizado_em)), el("td", {}, "Nº " + c.codigo + (c.mesa ? " · mesa " + c.mesa : "")),
              el("td", {}, moeda(c.total_centavos)), el("td", {}, c.cancelado_por_nome, el("div", { class: "dica" }, c.motivo_cancelamento)))))))].filter(Boolean));
    }
    carregadores.relatorios = carregarRelatorio;
  }

  // --- Histórico de ações ----------------------------------------------------

  if ($("aba-historico")) {
    $("hist-de").value = hojeISO(-6);
    $("hist-ate").value = hojeISO();
    let usuariosCarregados = false;

    async function carregarHistorico() {
      const params = new URLSearchParams({ de: $("hist-de").value, ate: $("hist-ate").value,
        usuario_id: $("hist-usuario").value, busca: $("hist-busca").value });
      let r;
      try {
        r = await api("GET", "/api/auditoria?" + params);
      } catch (e) {
        aviso(e.message, "erro");
        return;
      }
      if (!usuariosCarregados) {
        $("hist-usuario").append(...r.usuarios.map((u) => el("option", { value: u.id }, u.nome)));
        usuariosCarregados = true;
      }
      $("lista-historico").replaceChildren(r.registros.length
        ? el("table", { class: "tabela" },
          el("thead", {}, el("tr", {}, el("th", {}, "Quando"), el("th", {}, "Quem"), el("th", {}, "Ação"), el("th", {}, "Detalhes"))),
          el("tbody", {}, r.registros.map((a) => el("tr", {},
            el("td", { style: "white-space: nowrap" }, dataHora(a.criado_em)),
            el("td", {}, a.usuario_nome),
            el("td", {}, el("strong", {}, a.acao)),
            el("td", {}, a.detalhes)))))
        : el("div", { class: "vazio" }, "Nenhuma ação encontrada com esses filtros."));
    }
    $("hist-filtrar").addEventListener("click", carregarHistorico);
    $("hist-busca").addEventListener("keydown", (e) => { if (e.key === "Enter") carregarHistorico(); });
    carregadores.historico = carregarHistorico;
  }

  abrirAba();
})();
