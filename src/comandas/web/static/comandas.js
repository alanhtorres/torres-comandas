(function () {
  "use strict";
  const { api, moeda, el, aviso, dialogo, formCliente, minutosDesde, preencherMensagem, abrirWhatsapp } = window.C;
  const $ = (id) => document.getElementById(id);
  let comandas = [];

  // --- Aniversariantes do dia ---------------------------------------------

  async function carregarAniversariantes() {
    try {
      const r = await api("GET", "/api/aniversariantes?dias=0");
      const hoje = r.aniversariantes;
      $("aniversariantes").hidden = !hoje.length;
      $("aniversariantes").replaceChildren(
        el("h2", {}, "🎂 Aniversariantes de hoje"),
        el("div", { class: "lista" }, hoje.map((c) => el("span", { class: "pessoa" },
          `${c.nome} (${c.idade} anos)`,
          r.pode_enviar && c.aceita_mensagens && !c.parabens_enviado ? el("button", { onclick: async () => {
            const texto = preencherMensagem(r.mensagem, c, r.loja);
            abrirWhatsapp(c.telefone, texto, r.whatsapp_abrir_em);
            await api("POST", "/api/mensagens", { cliente_id: c.id, campanha: "aniversario-" + new Date().getFullYear(), texto });
            carregarAniversariantes();
          } }, "Enviar parabéns") : c.parabens_enviado ? el("small", {}, "✓ parabéns enviado") : null))));
    } catch (e) { /* sem permissão ou sem rede: só não mostra */ }
  }

  // --- Busca e abertura ---------------------------------------------------

  let temporizador = null;
  $("busca").addEventListener("input", () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(buscar, 250);
  });

  async function buscar() {
    const q = $("busca").value.trim();
    if (q.length < 2) {
      $("resultados").replaceChildren();
      return;
    }
    const { clientes } = await api("GET", "/api/clientes/busca?q=" + encodeURIComponent(q));
    const abertaPor = new Map(comandas.map((k) => [k.cliente_id, k]));
    $("resultados").replaceChildren(...(clientes.length ? clientes.map((c) => {
      const aberta = abertaPor.get(c.id);
      return el("div", { class: "resultado" },
        el("div", { class: "info" }, el("strong", {}, c.nome), c.aniversario_hoje ? el("span", { class: "etiqueta aniversario" }, " 🎂 aniversário hoje") : null,
          el("small", {}, c.telefone_formatado + (c.cpf_formatado ? " · CPF " + c.cpf_formatado : ""))),
        aberta ? el("span", { class: "etiqueta" }, "comanda " + aberta.numero + " aberta")
          : el("button", { class: "verde", onclick: () => dialogoAbrir(c) }, "Abrir comanda"));
    }) : [el("div", { class: "vazio" }, "Nenhum cliente encontrado. Use \"+ Cliente novo\".")]));
  }

  function campoNumero() {
    return el("input", { maxlength: 20, placeholder: "Deixe vazio para usar o próximo livre", inputmode: "numeric" });
  }

  function dialogoAbrir(cliente) {
    const numero = campoNumero();
    dialogo({
      titulo: "Abrir comanda para " + cliente.nome,
      corpo: el("div", {},
        cliente.aniversario_hoje ? el("p", { class: "etiqueta aniversario" }, "🎂 Hoje é aniversário deste cliente!") : null,
        el("label", {}, "Número da comanda / cartão"), numero),
      confirmar: "Abrir comanda",
      aoConfirmar: async () => {
        const r = await api("POST", "/api/comandas", { cliente_id: cliente.id, numero: numero.value });
        avisoAberta(r.comanda);
      },
    });
  }

  function avisoAberta(k) {
    aviso(`Comanda ${k.numero} aberta para ${k.cliente_nome}` + (k.aniversario_hoje ? " — 🎂 aniversariante do dia!" : ""), "ok");
    $("busca").value = "";
    $("resultados").replaceChildren();
    monitor.forcar();
  }

  $("novo-cliente").addEventListener("click", () => {
    const form = formCliente({ nome: /\d/.test($("busca").value) ? "" : $("busca").value });
    const numero = campoNumero();
    let criado = null; // se o cadastro der certo e a abertura falhar, não cadastra de novo
    dialogo({
      titulo: "Cliente novo e comanda",
      largo: true,
      corpo: el("div", {}, form.elemento, el("label", {}, "Número da comanda / cartão"), numero),
      confirmar: "Cadastrar e abrir comanda",
      aoConfirmar: async () => {
        if (!criado) criado = (await api("POST", "/api/clientes", form.valores())).cliente;
        const r = await api("POST", "/api/comandas", { cliente_id: criado.id, numero: numero.value });
        avisoAberta(r.comanda);
        carregarAniversariantes();
      },
    });
  });

  // --- Comandas abertas -----------------------------------------------------

  function render() {
    const filtro = $("filtro").value.trim().toLowerCase();
    const lista = comandas.filter((k) => !filtro || k.numero.toLowerCase() === filtro || k.cliente_nome.toLowerCase().includes(filtro));
    $("n-abertas").textContent = comandas.length;
    $("lista-comandas").replaceChildren(...(lista.length ? lista.map((k) => el("div", { class: "comanda" + (k.a_receber ? " pendente" : "") },
      el("div", { class: "numero" }, k.numero),
      el("div", { class: "nome" }, k.cliente_nome, k.aniversario_hoje ? " 🎂" : ""),
      el("small", {}, k.telefone_formatado + " · há " + minutosDesde(k.aberta_em) + " min"),
      el("div", { class: "valores" }, el("span", {}, "Consumo: " + moeda(k.total)), el("strong", {}, k.a_receber ? "A pagar: " + moeda(k.a_receber) : "")),
      k.a_receber ? el("small", {}, "Pagamento no caixa (aba \"A receber\") — a comanda fecha sozinha ao pagar.")
        : el("button", { onclick: () => dialogo({
          titulo: "Fechar a comanda " + k.numero + "?",
          corpo: el("p", {}, `${k.cliente_nome} ${k.total ? "já pagou tudo" : "saiu sem consumir"}. A comanda fica livre para outro cliente.`),
          confirmar: "Fechar comanda",
          aoConfirmar: async () => { await api("POST", `/api/comandas/${k.id}/fechar`); aviso("Comanda " + k.numero + " fechada", "ok"); monitor.forcar(); },
        }) }, k.total ? "Fechar comanda" : "Fechar (saiu sem consumir)")))
      : [el("div", { class: "vazio" }, comandas.length ? "Nenhuma comanda com esse filtro." : "Nenhuma comanda aberta.")]));
  }
  $("filtro").addEventListener("input", render);

  const monitor = C.acompanhar("/api/comandas", (dados) => { comandas = dados.comandas; render(); }, 3000);
  setInterval(() => monitor.forcar(), 30000);
  carregarAniversariantes();
})();
