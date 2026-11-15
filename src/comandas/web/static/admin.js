(function () {
  "use strict";
  const { api, moeda, el, aviso, dialogo, dataHora, hojeISO, formCliente, preencherMensagem, abrirWhatsapp } = window.C;
  const $ = (id) => document.getElementById(id);
  // Ambientes de preparo (cozinha, bar e os criados pelo administrador).
  const AMBIENTES = JSON.parse(($("dados-ambientes") || {}).textContent || "[]");

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
      $("produto-destino").value = "cozinha";
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
      $("produto-destino").value = p.destino;
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
        destino: $("produto-destino").value,
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
    // Produto novo numa categoria que já existe: já vem com a impressora dela.
    $("produto-categoria").addEventListener("change", () => {
      if ($("produto-id").value) return;
      const destinos = new Set(produtos.filter((p) => p.categoria === $("produto-categoria").value.trim()).map((p) => p.destino));
      if (destinos.size === 1) $("produto-destino").value = [...destinos][0];
    });

    const DESTINOS = {};
    for (const a of AMBIENTES) DESTINOS[a.chave] = a.icone + " " + a.nome;
    DESTINOS.nenhum = "Nenhum lugar (já pronto)";
    const etiqueta = (destino) => destino === "nenhum"
      ? el("span", { class: "etiqueta" }, "só caixa")
      : el("span", { class: "etiqueta " + (destino === "cozinha" ? "preparando" : "pronto") }, DESTINOS[destino] || destino);

    function escolhaCategoria(cat, daCategoria) {
      const destinos = new Set(daCategoria.map((x) => x.destino));
      const sel = el("select", { class: "destino-categoria", title: "Para qual ambiente vão todos os produtos desta categoria" },
        destinos.size > 1 ? el("option", { value: "" }, "Misturado (cada produto o seu)") : null,
        ...Object.entries(DESTINOS).map(([valor, rotulo]) => el("option", { value: valor }, rotulo)));
      sel.value = destinos.size > 1 ? "" : [...destinos][0];
      sel.addEventListener("change", async () => {
        if (!sel.value) return;
        try {
          await api("POST", "/api/produtos/categoria-destino", { categoria: cat, destino: sel.value });
          aviso(`Todos os produtos de "${cat}" vão para: ${DESTINOS[sel.value]}`, "ok");
        } catch (e) { aviso(e.message, "erro"); }
        carregarProdutos();
      });
      return el("label", { class: "inline" }, "Vai para: ", sel);
    }

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
        const daCategoria = produtos.filter((x) => x.categoria === cat);
        linhas.push(el("tr", { class: "grupo-categoria" }, el("td", { colspan: 4 }, cat),
          el("td", { class: "acoes" }, escolhaCategoria(cat, daCategoria))));
        for (const p of produtos.filter((x) => x.categoria === cat)) {
          const inputFoto = el("input", { type: "file", accept: "image/*", hidden: true, onchange: async (e) => {
            try { await enviarFoto(p.id, e.target.files[0]); aviso("Foto atualizada", "ok"); carregarProdutos(); }
            catch (err) { aviso(err.message, "erro"); }
          } });
          linhas.push(el("tr", { class: p.ativo ? "" : "inativo" },
            el("td", {}, p.foto ? el("img", { class: "miniatura", src: "/foto/" + p.foto, alt: "" }) : el("div", { class: "sem-foto" }, "📷")),
            el("td", {}, el("strong", {}, p.nome), p.descricao ? el("div", { class: "dica" }, p.descricao) : null),
            el("td", {}, moeda(p.preco_centavos)),
            el("td", {}, p.ativo ? null : el("span", { class: "etiqueta" }, "indisponível"), " ",
              etiqueta(p.destino)),
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
    // Impressora USB: a lista vem das impressoras instaladas no Windows do PC
    // que roda o sistema. Uma escolhida antes que sumiu continua na lista.
    async function carregarImpressorasUsb(config) {
      let nomes = [], windows = true;
      try { ({ impressoras: nomes, windows } = await api("GET", "/api/impressoras/usb")); } catch (e) { /* segue sem lista */ }
      for (const sel of document.querySelectorAll("[data-lista-usb]")) {
        const escolhida = config[sel.name] || "";
        const opcoes = [el("option", { value: "" }, !windows ? "Só funciona com o sistema rodando no Windows"
          : nomes.length ? "— escolha a impressora —" : "Nenhuma impressora instalada neste PC")];
        for (const nome of nomes) opcoes.push(el("option", { value: nome }, nome));
        if (escolhida && !nomes.includes(escolhida)) opcoes.push(el("option", { value: escolhida }, escolhida + " (não encontrada)"));
        sel.replaceChildren(...opcoes);
      }
    }

    function mostrarTipoImpressora() {
      for (const sel of document.querySelectorAll("[data-tipo-impressora]")) {
        const qual = sel.dataset.tipoImpressora;
        document.querySelectorAll(`[data-so-rede="${qual}"]`).forEach((d) => (d.hidden = sel.value === "usb"));
        document.querySelectorAll(`[data-so-usb="${qual}"]`).forEach((d) => (d.hidden = sel.value !== "usb"));
      }
    }
    document.querySelectorAll("[data-tipo-impressora]").forEach((s) => s.addEventListener("change", mostrarTipoImpressora));

    // Logo do estabelecimento: enviada na hora (não precisa "Salvar configurações").
    if ($("enviar-logo")) {
      $("enviar-logo").addEventListener("click", () => $("arquivo-logo").click());
      $("arquivo-logo").addEventListener("change", async (e) => {
        const arquivo = e.target.files[0];
        if (!arquivo) return;
        const corpo = new FormData();
        corpo.append("arquivo", arquivo);
        try {
          const r = await fetch("/api/config/logo", { method: "POST", body: corpo });
          const dados = await r.json();
          if (!r.ok || !dados.ok) throw new Error(dados.erro || "Não foi possível enviar a logo.");
          $("previa-logo").replaceChildren(el("img", { src: dados.logo_url, alt: "Logo" }));
          $("remover-logo").hidden = false;
          aviso("Logo atualizada. As outras telas mostram a nova ao recarregar.", "ok");
        } catch (err) { aviso(err.message, "erro"); }
        e.target.value = "";
      });
      $("remover-logo").addEventListener("click", async () => {
        if (!confirm("Remover a logo? Fica só o nome do estabelecimento.")) return;
        try {
          await api("DELETE", "/api/config/logo");
          $("previa-logo").replaceChildren(el("span", {}, "Sem logo"));
          $("remover-logo").hidden = true;
          aviso("Logo removida", "ok");
        } catch (err) { aviso(err.message, "erro"); }
      });
    }

    // Cozinha ou bar sem tela e sem impressora: avisa (ninguém ficaria sabendo do pedido).
    function avisarSetores() {
      for (const aviso of document.querySelectorAll("[data-aviso-setor]")) {
        const setor = aviso.dataset.avisoSetor;
        const tela = document.querySelector(`[data-setor-tela="${setor}"]`);
        const impressora = document.querySelector(`[name="impressora_${setor}_ativa"]`);
        aviso.hidden = !tela || !impressora || tela.checked || impressora.checked;
      }
    }
    document.querySelectorAll("[data-setor-tela], [name$='_ativa']").forEach((c) => c.addEventListener("change", avisarSetores));

    // Ambientes novos (pizzaria, confeitaria...): o administrador cria, renomeia e exclui.
    const ICONES = ["🍕", "🍰", "🥩", "🍣", "🍔", "🥗", "🍜", "🍦", "☕", "🍺", "🥤", "🔥", "🍽️"];
    function formAmbiente(nome, icone) {
      const campoNome = el("input", { maxlength: 30, value: nome || "", placeholder: "Ex.: Pizzaria" });
      const campoIcone = el("select", {}, ...ICONES.map((i) => el("option", { value: i }, i)));
      campoIcone.value = ICONES.includes(icone) ? icone : "🍽️";
      return { campoNome, campoIcone, corpo: el("div", {}, el("label", {}, "Nome do ambiente"), campoNome,
        el("label", {}, "Ícone"), campoIcone,
        el("p", { class: "dica" }, "Depois escolha se ele tem tela e/ou impressora, e no Cardápio quais produtos vão para ele.")) };
    }
    async function salvarERecarregar(acao) {
      await salvarConfig();  // não perde o que já foi mudado nesta página
      await acao();
      location.reload();
    }
    const botaoNovo = $("novo-ambiente");
    if (botaoNovo) botaoNovo.addEventListener("click", () => {
      const f = formAmbiente("", "🍽️");
      dialogo({ titulo: "➕ Novo ambiente", corpo: f.corpo, confirmar: "Criar",
        aoConfirmar: () => salvarERecarregar(() => api("POST", "/api/ambientes", { nome: f.campoNome.value, icone: f.campoIcone.value })) });
      setTimeout(() => f.campoNome.focus(), 50);
    });
    document.querySelectorAll("[data-renomear-ambiente]").forEach((b) => b.addEventListener("click", () => {
      const f = formAmbiente(b.dataset.nome, b.dataset.icone);
      dialogo({ titulo: "✏️ Renomear ambiente", corpo: f.corpo, confirmar: "Salvar",
        aoConfirmar: () => salvarERecarregar(() => api("PUT", "/api/ambientes/" + b.dataset.renomearAmbiente,
          { nome: f.campoNome.value, icone: f.campoIcone.value })) });
    }));
    document.querySelectorAll("[data-excluir-ambiente]").forEach((b) => b.addEventListener("click", () => {
      if (!confirm(`Excluir o ambiente "${b.dataset.nome}"? A tela e a impressora dele deixam de existir.`)) return;
      salvarERecarregar(() => api("DELETE", "/api/ambientes/" + b.dataset.excluirAmbiente)).catch((e) => aviso(e.message, "erro"));
    }));

    async function carregarConfig() {
      const { config, url_base_detectada } = await api("GET", "/api/config");
      await carregarImpressorasUsb(config);
      const form = $("form-config");
      for (const campo of form.querySelectorAll("[name]")) {
        const valor = config[campo.name];
        if (campo.type === "checkbox") campo.checked = !!valor;
        else campo.value = valor === undefined || valor === null ? "" : valor;
      }
      mostrarTipoImpressora();
      avisarSetores();
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
        const temaAntes = document.documentElement.dataset.tema;
        await salvarConfig();
        aviso("Configurações salvas", "ok");
        // Novo tema padrão: já mostra aqui (se este aparelho não escolheu o seu no botão do topo).
        let temaDoAparelho = null;
        try { temaDoAparelho = localStorage.getItem("tema"); } catch (e) { /* sem armazenamento */ }
        if (!temaDoAparelho && $("cfg-tema_padrao").value !== temaAntes) setTimeout(() => location.reload(), 600);
      } catch (err) {
        aviso(err.message, "erro");
      }
    });

    document.querySelectorAll("[data-teste]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        // salva antes, pra testar exatamente a impressora que está na tela
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

  // --- Clientes e WhatsApp ------------------------------------------------

  if ($("aba-clientes")) {
    const dataBR = (iso) => (iso ? iso.split("-").reverse().join("/") : "");

    async function enviarWhatsapp(cliente, texto, campanha, modo) {
      abrirWhatsapp(cliente.telefone, texto, modo);
      try {
        await api("POST", "/api/mensagens", { cliente_id: cliente.id, campanha, texto });
      } catch (e) { aviso(e.message, "erro"); }
    }

    // Envio um por um: um botão só (ou Enter) abre a conversa do próximo
    // cliente com o texto pronto e já marca como enviado.
    let sequenciaAtiva = null;
    function iniciarSequencia(alvo, lista, { texto, campanha, modo, aoEnviar, aoFechar }) {
      const fila = lista.filter((c) => !c.enviado_em);
      let pos = 0;
      const pulados = [];
      const caixa = el("div", { class: "sequencia" });
      const fechar = () => { sequenciaAtiva = null; caixa.remove(); if (aoFechar) aoFechar(); };
      const dicaModo = modo === "web"
        ? "O WhatsApp Web recarrega a cada cliente (alguns segundos). Para ir mais rápido, escolha \"Aplicativo WhatsApp do PC\"."
        : modo === "app" ? "Na primeira vez o navegador pergunta se pode abrir o WhatsApp: marque \"sempre permitir\"." : "";
      function desenhar() {
        const enviados = lista.filter((c) => c.enviado_em).length;
        const status = el("div", { class: "seq-status" }, `${enviados} de ${lista.length} enviados`);
        const barra = el("progress", { max: String(lista.length || 1), value: String(enviados) });
        if (pos >= fila.length) {
          sequenciaAtiva = null;
          caixa.replaceChildren(barra, status,
            el("div", { class: "seq-fim" }, pulados.length ? `Fim da lista — ${pulados.length} pulado(s).` : "✓ Pronto! Todos receberam."),
            el("div", { class: "linha" },
              pulados.length ? el("button", { class: "botao-zap", onclick: () => { fila.splice(0, fila.length, ...pulados.splice(0)); pos = 0; desenhar(); } }, "Enviar para os pulados") : null,
              el("button", { onclick: fechar }, "Fechar")));
          return;
        }
        const c = fila[pos];
        const enviar = el("button", { class: "botao-zap", onclick: async () => {
          enviar.disabled = true;
          await enviarWhatsapp(c, texto(c), campanha, modo);
          c.enviado_em = Date.now() / 1000;
          if (aoEnviar) aoEnviar(c);
          pos += 1;
          desenhar();
        } }, `Abrir conversa com ${c.nome.split(" ")[0]} ⏎`);
        caixa.replaceChildren(barra, status,
          el("div", { class: "seq-proximo" }, "Próximo: ", el("strong", {}, c.nome), " · ", c.telefone_formatado),
          el("div", { class: "linha" }, enviar,
            el("button", { onclick: () => { pulados.push(c); pos += 1; desenhar(); } }, "Pular"),
            el("button", { onclick: fechar }, "Parar")),
          dicaModo ? el("p", { class: "dica" }, dicaModo) : null);
        sequenciaAtiva = enviar;
        enviar.focus();
      }
      alvo.replaceChildren(caixa);
      desenhar();
      caixa.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    // Enter manda para o próximo mesmo se o foco saiu do botão (ao voltar do WhatsApp)
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !sequenciaAtiva || sequenciaAtiva.disabled || document.querySelector("dialog[open]")) return;
      if (e.target.closest && e.target.closest("input, textarea, select, button")) return;
      e.preventDefault();
      sequenciaAtiva.click();
    });

    async function carregarAniversarios() {
      const r = await api("GET", "/api/aniversariantes?dias=7");
      const campanha = "aniversario-" + new Date().getFullYear();
      $("lista-aniversarios").replaceChildren(r.aniversariantes.length
        ? el("table", { class: "tabela" }, el("tbody", {}, r.aniversariantes.map((c) => el("tr", { class: c.parabens_enviado ? "enviado" : "" },
          el("td", {}, el("strong", {}, c.faltam_dias === 0 ? "🎂 Hoje" : c.faltam_dias === 1 ? "Amanhã" : dataBR(c.data_aniversario))),
          el("td", {}, c.nome, el("div", { class: "dica" }, `faz ${c.idade} anos · ${c.telefone_formatado}`)),
          el("td", { class: "acoes" }, c.parabens_enviado ? el("span", { class: "etiqueta pronto" }, "✓ parabéns enviado")
            : !c.aceita_mensagens ? el("span", { class: "dica" }, "não autorizou mensagens")
              : el("button", { class: "botao-zap", onclick: async () => {
                await enviarWhatsapp(c, preencherMensagem(r.mensagem, c, r.loja), campanha, r.whatsapp_abrir_em);
                carregarAniversarios();
              } }, "Enviar parabéns no WhatsApp"))))))
        : el("div", { class: "vazio" }, "Nenhum aniversariante nos próximos 7 dias."));
      const pendentesHoje = r.aniversariantes.filter((c) => c.faltam_dias === 0 && c.aceita_mensagens && !c.parabens_enviado);
      if (!$("seq-aniversario").querySelector(".sequencia")) {
        $("seq-aniversario").replaceChildren(pendentesHoje.length > 1
          ? el("button", { class: "botao-zap", onclick: () => iniciarSequencia($("seq-aniversario"), pendentesHoje, {
            texto: (c) => preencherMensagem(r.mensagem, c, r.loja), campanha, modo: r.whatsapp_abrir_em,
            aoEnviar: () => carregarAniversarios(), aoFechar: () => carregarAniversarios(),
          }) }, `🎂 Enviar parabéns para os ${pendentesHoje.length} aniversariantes de hoje, um após o outro`)
          : "");
      }
    }

    // Campanha
    let publicosCarregados = false;
    async function prepararCampanha() {
      if (publicosCarregados) return;
      const { publicos, whatsapp_abrir_em } = await api("GET", "/api/campanhas/publicos");
      $("camp-publico").replaceChildren(...Object.entries(publicos).map(([k, v]) => el("option", { value: k }, v)));
      $("camp-modo").value = whatsapp_abrir_em;
      publicosCarregados = true;
    }
    function atualizarPrevia() {
      const t = $("camp-texto").value;
      $("camp-previa").textContent = t ? "Prévia: " + preencherMensagem(t, { nome: "Maria Silva" }, "seu estabelecimento") : "";
    }
    $("camp-texto").addEventListener("input", atualizarPrevia);

    async function dadosCampanha() {
      if (!$("camp-nome").value.trim()) $("camp-nome").value = "Mensagem de " + new Date().toLocaleDateString("pt-BR");
      const campanha = $("camp-nome").value.trim();
      const r = await api("GET", `/api/campanhas/publico?publico=${$("camp-publico").value}&campanha=${encodeURIComponent(campanha)}`);
      return { campanha, ...r };
    }

    $("camp-montar").addEventListener("click", async () => {
      const texto = $("camp-texto").value.trim();
      if (!texto) { aviso("Escreva a mensagem", "erro"); $("camp-texto").focus(); return; }
      let r;
      try { r = await dadosCampanha(); } catch (e) { aviso(e.message, "erro"); return; }
      const { campanha, clientes: lista } = r;
      const modo = $("camp-modo").value;
      if (!lista.length) {
        $("camp-lista").replaceChildren(el("div", { class: "vazio" }, "Nenhum cliente desse público autorizou receber mensagens."));
        return;
      }
      const textoDe = (c) => preencherMensagem(texto, c, r.loja);
      const linhas = new Map();
      const tabela = el("table", { class: "tabela" }, el("tbody", {}, lista.map((c) => {
        const quando = el("td", {}, c.enviado_em ? "✓ enviado em " + dataHora(c.enviado_em) : "");
        const botao = el("button", { onclick: async () => {
          await enviarWhatsapp(c, textoDe(c), campanha, modo);
          c.enviado_em = Date.now() / 1000;
          marcar(c);
        } }, c.enviado_em ? "Enviar de novo" : "Abrir no WhatsApp");
        const linha = el("tr", { class: c.enviado_em ? "enviado" : "" },
          el("td", {}, el("strong", {}, c.nome), el("div", { class: "dica" }, c.telefone_formatado)), quando, el("td", { class: "acoes" }, botao));
        linhas.set(c.id, { linha, quando, botao });
        return linha;
      })));
      function marcar(c) {
        const l = linhas.get(c.id);
        l.linha.classList.add("enviado");
        l.quando.textContent = "✓ enviado em " + dataHora(c.enviado_em);
        l.botao.textContent = "Enviar de novo";
      }
      const sequencia = el("div");
      $("camp-lista").replaceChildren(sequencia,
        el("details", {}, el("summary", {}, `Ver a lista completa (${lista.length} clientes)`), tabela));
      if (lista.every((c) => c.enviado_em)) {
        sequencia.replaceChildren(el("p", { class: "progresso-campanha" }, `Todos os ${lista.length} clientes já receberam esta campanha. Para mandar de novo, use a lista abaixo ou dê outro nome à campanha.`));
      } else {
        iniciarSequencia(sequencia, lista, { texto: textoDe, campanha, modo, aoEnviar: marcar });
      }
    });

    $("camp-vcf").addEventListener("click", () => {
      location.href = `/api/campanhas/contatos.vcf?publico=${$("camp-publico").value}&campanha=contatos`;
    });
    $("camp-marcar-todos").addEventListener("click", async () => {
      try {
        const r = await dadosCampanha();
        const ids = r.clientes.filter((c) => !c.enviado_em).map((c) => c.id);
        if (!ids.length) { aviso(r.clientes.length ? "Todos desse público já estão marcados nesta campanha" : "Nenhum cliente nesse público", "ok"); return; }
        if (!confirm(`Marcar ${ids.length} cliente(s) como "já recebeu" a campanha "${r.campanha}"?`)) return;
        const res = await api("POST", "/api/mensagens/lote", { cliente_ids: ids, campanha: r.campanha, texto: $("camp-texto").value.trim() });
        aviso(`${res.marcados} cliente(s) marcados como enviados`, "ok");
        $("camp-lista").replaceChildren();
      } catch (e) { aviso(e.message, "erro"); }
    });

    // Lista de clientes
    async function carregarClientes() {
      const busca = $("busca-clientes").value.trim();
      const { clientes } = await api("GET", "/api/clientes?busca=" + encodeURIComponent(busca));
      $("n-clientes").textContent = clientes.length;
      $("lista-clientes").replaceChildren(clientes.length
        ? el("table", { class: "tabela" },
          el("thead", {}, el("tr", {}, ["Cliente", "CPF", "Nascimento", "Mensagens", "Visitas", "Gasto", ""].map((t) => el("th", {}, t)))),
          el("tbody", {}, clientes.map((c) => el("tr", {},
            el("td", {}, el("strong", {}, c.nome), c.aniversario_hoje ? " 🎂" : "", el("div", { class: "dica" }, c.telefone_formatado)),
            el("td", {}, c.cpf_formatado),
            el("td", {}, dataBR(c.nascimento)),
            el("td", {}, c.aceita_mensagens ? el("span", { class: "etiqueta pronto" }, "autorizou") : el("span", { class: "etiqueta" }, "não")),
            el("td", {}, c.visitas, c.ultima_visita ? el("div", { class: "dica" }, "última: " + dataHora(c.ultima_visita).slice(0, 10)) : null),
            el("td", {}, moeda(c.total_gasto)),
            el("td", { class: "acoes" }, el("button", { onclick: () => dialogoCliente(c) }, "Editar"))))))
        : el("div", { class: "vazio" }, busca ? "Nenhum cliente encontrado." : "Nenhum cliente cadastrado ainda."));
    }
    let tempoBusca = null;
    $("busca-clientes").addEventListener("input", () => { clearTimeout(tempoBusca); tempoBusca = setTimeout(carregarClientes, 300); });

    function dialogoCliente(c) {
      const form = formCliente(c || {});
      const remover = c ? el("button", { type: "button", class: "perigo", onclick: () => {
        if (!confirm(`Apagar os dados pessoais de ${c.nome}? Use quando o cliente pedir (LGPD). As vendas continuam nos relatórios, mas sem nome, telefone, CPF e nascimento. Não dá para desfazer.`)) return;
        api("DELETE", "/api/clientes/" + c.id).then(() => {
          aviso("Dados do cliente apagados", "ok");
          document.querySelector("dialog")?.close();
          carregarClientes();
        }).catch((e) => aviso(e.message, "erro"));
      } }, "Apagar dados (LGPD)") : null;
      dialogo({
        titulo: c ? "Editar cliente" : "Novo cliente",
        largo: true,
        corpo: el("div", {}, form.elemento, c && c.consentimento_em ? el("p", { class: "dica" }, "Autorizou mensagens em " + dataHora(c.consentimento_em)) : null,
          remover ? el("div", { style: "margin-top: 14px" }, remover) : null),
        confirmar: "Salvar",
        aoConfirmar: async () => {
          if (c) await api("PUT", "/api/clientes/" + c.id, form.valores());
          else await api("POST", "/api/clientes", form.valores());
          aviso("Cliente salvo", "ok");
          carregarClientes();
          carregarAniversarios();
        },
      });
    }
    $("cliente-novo").addEventListener("click", () => dialogoCliente(null));

    carregadores.clientes = () => {
      prepararCampanha().catch((e) => aviso(e.message, "erro"));
      carregarAniversarios().catch((e) => aviso(e.message, "erro"));
      carregarClientes().catch((e) => aviso(e.message, "erro"));
    };
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

    const CURTOS = { pedidos: "Caixa/pedidos", garcom: "Garçom", cozinha: "Cozinha", receber: "Receber", caixa: "Abrir/fechar caixa",
      cancelar: "Cancelar pedidos", estornar: "Estornar", comandas: "Comandas", clientes: "Clientes/WhatsApp",
      cardapio: "Cardápio", mesas: "Mesas", midias: "Mídias", configuracoes: "Configurações",
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
          secao("Pedidos e itens cancelados", tabela(["Quando", "Pedido", "Valor", "Quem cancelou / motivo"], r.cancelados.map((c) =>
            el("tr", {}, el("td", {}, dataHora(c.atualizado_em)), el("td", {}, "Nº " + c.codigo + (c.mesa ? " · mesa " + c.mesa : "")),
              el("td", {}, moeda(c.total_centavos)), el("td", {}, c.cancelado_por_nome, el("div", { class: "dica" }, c.motivo_cancelamento)))))))].filter(Boolean));
    }
    carregadores.relatorios = carregarRelatorio;

    // Exportação (PDF ou Excel) com as seções que o administrador escolher.
    const PADRAO = ["resumo", "formas", "produtos", "caixas", "movimentos", "estornos", "cancelamentos"];
    let opcoesCarregadas = false;
    $("abrir-exportar").addEventListener("click", async () => {
      $("cartao-exportar").hidden = !$("cartao-exportar").hidden;
      if (opcoesCarregadas) return;
      try {
        const { secoes } = await api("GET", "/api/relatorios/opcoes");
        $("exp-secoes").replaceChildren(...Object.entries(secoes).map(([k, titulo]) =>
          el("label", { class: "inline" }, el("input", { type: "checkbox", value: k, checked: PADRAO.includes(k) }), titulo)));
        opcoesCarregadas = true;
      } catch (e) { aviso(e.message, "erro"); }
    });
    const marcarTodas = (v) => $("exp-secoes").querySelectorAll("input").forEach((c) => (c.checked = v));
    $("exp-todos").addEventListener("click", () => marcarTodas(true));
    $("exp-nenhum").addEventListener("click", () => marcarTodas(false));

    $("exp-gerar").addEventListener("click", async () => {
      const secoes = [...$("exp-secoes").querySelectorAll("input:checked")].map((c) => c.value);
      if (!secoes.length) { aviso("Marque pelo menos uma informação", "erro"); return; }
      const formato = document.querySelector("input[name=exp-formato]:checked").value;
      const params = new URLSearchParams({ de: $("rel-de").value, ate: $("rel-ate").value, formato, secoes: secoes.join(",") });
      const botao = $("exp-gerar");
      botao.disabled = true;
      botao.textContent = "Gerando...";
      try {
        const res = await fetch("/api/relatorios/exportar?" + params, { cache: "no-store" });
        if (!res.ok) {
          let erro = "Erro " + res.status;
          try { erro = (await res.json()).erro || erro; } catch (e) { /* não era JSON */ }
          throw new Error(erro);
        }
        const nome = (res.headers.get("Content-Disposition") || "").match(/filename="?([^";]+)/);
        const url = URL.createObjectURL(await res.blob());
        const link = el("a", { href: url, download: nome ? nome[1] : "relatorio." + formato });
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        aviso("Relatório gerado — confira a pasta de downloads", "ok");
      } catch (e) {
        aviso(e.message, "erro");
      } finally {
        botao.disabled = false;
        botao.textContent = "Gerar e baixar";
      }
    });
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
