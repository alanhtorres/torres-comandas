(function () {
  "use strict";
  const { el, moeda, bip, falar, somLiberado, liberarSom } = window.C;
  const $ = (id) => document.getElementById(id);

  const DURACAO_ANUNCIO_MS = 7000;
  let config = { som: true, voz: false, duracao_foto: 8 };
  let ultimaSeq = null; // null = ainda não carregou (não anuncia o que já estava chamado)
  const filaAnuncios = [];
  let anunciando = false;

  // --- Chamadas ---------------------------------------------------------------

  function textos(c) {
    const quem = c.cliente || (c.mesa ? "Mesa " + c.mesa : "");
    return {
      rotulo: "Pedido pronto — pode retirar",
      detalhe: quem,
      fala: "Pedido número " + c.codigo + (c.cliente ? ", " + c.cliente : "") + ", pode retirar",
    };
  }

  function renderChamadas(chamadas) {
    const [atual, ...resto] = chamadas;
    if (atual) {
      const t = textos(atual);
      $("atual-codigo").textContent = atual.codigo;
      $("atual-detalhe").textContent = t.detalhe;
      document.querySelector(".atual .rotulo").textContent = t.rotulo;
    } else {
      $("atual-codigo").textContent = "—";
      $("atual-detalhe").textContent = "";
    }
    $("historico").replaceChildren(...resto.map((c) =>
      el("li", { class: c.status },
        el("span", { class: "codigo" }, c.codigo),
        el("span", { class: "detalhe" }, textos(c).detalhe))));
  }

  function proximoAnuncio() {
    if (anunciando || !filaAnuncios.length) return;
    anunciando = true;
    const c = filaAnuncios.shift();
    const t = textos(c);
    $("anuncio-rotulo").textContent = t.rotulo;
    $("anuncio-codigo").textContent = c.codigo;
    $("anuncio-detalhe").textContent = t.detalhe;
    $("anuncio").hidden = false;
    if (config.som) bip("chamada");
    if (config.voz) setTimeout(() => falar(t.fala), 900);
    setTimeout(() => {
      $("anuncio").hidden = true;
      anunciando = false;
      setTimeout(proximoAnuncio, 400);
    }, DURACAO_ANUNCIO_MS);
  }

  function verificarNovas(chamadas) {
    const maior = chamadas.reduce((m, c) => Math.max(m, c.chamada_seq), 0);
    if (ultimaSeq !== null) {
      chamadas.filter((c) => c.chamada_seq > ultimaSeq)
        .sort((a, b) => a.chamada_seq - b.chamada_seq)
        .forEach((c) => filaAnuncios.push(c));
      proximoAnuncio();
    }
    ultimaSeq = Math.max(ultimaSeq || 0, maior);
  }

  // --- Vitrine (fotos e vídeos) ------------------------------------------

  let itens = [];
  let assinaturaItens = "";
  let indice = -1;
  let timer = null;

  function montarItens(dados) {
    if (dados.midias.length) return dados.midias.map((m) => ({ ...m }));
    return dados.produtos.map((p) => ({ tipo: "produto", url: p.foto, nome: p.nome, preco: p.preco_centavos }));
  }

  function proximo() {
    clearTimeout(timer);
    const vitrine = $("vitrine");
    if (!itens.length) {
      vitrine.replaceChildren(el("div", { class: "sem-midia" }, $("loja").textContent || ""));
      timer = setTimeout(proximo, 10000);
      return;
    }
    indice = (indice + 1) % itens.length;
    const item = itens[indice];
    const duracaoMs = (item.duracao || config.duracao_foto || 8) * 1000;

    if (item.tipo === "video") {
      const v = el("video", { src: item.url, autoplay: true, muted: true, playsinline: true });
      v.muted = true;
      v.addEventListener("ended", proximo);
      v.addEventListener("error", () => { timer = setTimeout(proximo, 1000); });
      vitrine.replaceChildren(v);
      v.play().catch(() => {});
      // segurança: vídeo que trava não segura a vitrine para sempre
      timer = setTimeout(proximo, 10 * 60 * 1000);
      return;
    }
    if (item.tipo === "produto") {
      vitrine.replaceChildren(el("div", { class: "slide-produto" },
        el("img", { src: item.url, alt: "" }),
        el("div", { class: "legenda" }, el("span", { class: "nome" }, item.nome), el("span", { class: "preco" }, moeda(item.preco)))));
    } else {
      const img = el("img", { src: item.url, alt: "" });
      img.addEventListener("error", () => { clearTimeout(timer); timer = setTimeout(proximo, 1000); });
      vitrine.replaceChildren(img);
    }
    timer = setTimeout(proximo, duracaoMs);
  }

  // --- Atualização -----------------------------------------------------------

  function aplicar(dados) {
    config = { som: dados.som, voz: dados.voz, duracao_foto: dados.duracao_foto };
    $("loja").textContent = dados.loja;
    renderChamadas(dados.chamadas);
    verificarNovas(dados.chamadas);

    const novos = montarItens(dados);
    const assinatura = JSON.stringify(novos);
    if (assinatura !== assinaturaItens) {
      const iniciar = !itens.length || indice === -1;
      itens = novos;
      assinaturaItens = assinatura;
      if (indice >= itens.length) indice = -1;
      if (iniciar || !itens.length) { indice = -1; proximo(); }
    }
  }

  function relogio() {
    $("relogio").textContent = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  relogio();
  setInterval(relogio, 10000);

  function checarSom() {
    $("ativar-som").hidden = !config.som || somLiberado();
  }
  setTimeout(checarSom, 2000);
  setInterval(checarSom, 10000);
  $("ativar-som").addEventListener("click", () => { liberarSom(); bip("chamada"); $("ativar-som").hidden = true; });

  C.acompanhar("/api/painel", aplicar, 2000);
})();
