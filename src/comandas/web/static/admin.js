(function () {
  "use strict";
  const { api, moeda, el, aviso } = window.C;
  const $ = (id) => document.getElementById(id);

  // --- Abas -------------------------------------------------------------------

  const carregadores = {};
  function abrirAba() {
    const nome = (location.hash || "#produtos").slice(1);
    const aba = $("aba-" + nome) ? nome : "produtos";
    document.querySelectorAll(".aba").forEach((s) => (s.hidden = s.id !== "aba-" + aba));
    document.querySelectorAll(".abas a").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === aba));
    if (carregadores[aba]) carregadores[aba]();
  }
  window.addEventListener("hashchange", abrirAba);

  // --- Produtos ---------------------------------------------------------------

  let produtos = [];

  function precoParaCentavos(texto) {
    const limpo = String(texto).replace(/[^\d,.-]/g, "");
    // aceita "12,50", "12.50" e "1.234,50"
    const normalizado = limpo.includes(",") ? limpo.replace(/\./g, "").replace(",", ".") : limpo;
    const valor = Number(normalizado);
    return Number.isFinite(valor) ? Math.round(valor * 100) : NaN;
  }

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

  // --- Mesas ------------------------------------------------------------------

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

  // --- Mídias do painel -----------------------------------------------------

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

  // --- Configurações ----------------------------------------------------------

  async function carregarConfig() {
    const { config, url_base_detectada } = await api("GET", "/api/config");
    const form = $("form-config");
    for (const campo of form.querySelectorAll("[name]")) {
      const valor = config[campo.name];
      if (campo.type === "checkbox") campo.checked = !!valor;
      else campo.value = valor === undefined || valor === null ? "" : valor;
    }
    $("cfg-url_base").placeholder = url_base_detectada ? "Detectado: " + url_base_detectada : "http://192.168.0.10:8090";
    $("estado-pin").textContent = config.pin_definido
      ? "🔒 PIN ativo: caixa, cozinha, totem e administração pedem o PIN no primeiro acesso de cada aparelho."
      : "⚠️ Sem PIN: qualquer pessoa na rede da loja pode abrir o caixa e a administração.";
    $("novo-pin").value = "";
    $("remover-pin").checked = false;
  }
  carregadores.config = () => carregarConfig().catch((e) => aviso(e.message, "erro"));

  async function salvarConfig() {
    const corpo = {};
    for (const campo of $("form-config").querySelectorAll("[name]")) {
      corpo[campo.name] = campo.type === "checkbox" ? campo.checked : campo.value;
    }
    if ($("novo-pin").value.trim()) corpo.novo_pin = $("novo-pin").value.trim();
    else if ($("remover-pin").checked) corpo.remover_pin = true;
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

  abrirAba();
})();
