/* O programa: cada tela numa aba. As abas já abertas continuam vivas em
   segundo plano (o pedido em andamento no caixa, os alertas da cozinha...),
   então trocar de aba não perde nada. */
(function () {
  "use strict";
  const { el } = window.C;
  const $ = (id) => document.getElementById(id);
  const botoes = [...document.querySelectorAll("#abas button")];
  const quadros = {};

  function abrir(chave) {
    const botao = botoes.find((b) => b.dataset.aba === chave) || botoes[0];
    if (!botao) return;
    chave = botao.dataset.aba;
    if (!quadros[chave]) {
      quadros[chave] = el("iframe", { src: botao.dataset.url, title: botao.title, allow: "autoplay; fullscreen" });
      $("telas").append(quadros[chave]);
    }
    for (const [k, q] of Object.entries(quadros)) q.hidden = k !== chave;
    botoes.forEach((b) => b.classList.toggle("ativa", b === botao));
    document.title = botao.title + " — " + document.title.split(" — ").slice(-2).join(" — ");
    history.replaceState(null, "", "?tela=" + chave);
    try { localStorage.setItem("aba-programa", chave); } catch (e) { /* sem armazenamento */ }
    quadros[chave].focus();
  }

  botoes.forEach((b) => b.addEventListener("click", () => abrir(b.dataset.aba)));
  // Ctrl+1, Ctrl+2... trocam de aba
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key >= "1" && e.key <= "9" && botoes[e.key - 1]) { e.preventDefault(); abrir(botoes[e.key - 1].dataset.aba); }
  });

  let lembrada = "";
  try { lembrada = localStorage.getItem("aba-programa") || ""; } catch (e) { /* sem armazenamento */ }
  abrir($("telas").dataset.inicial || lembrada);

  $("trocar-senha").addEventListener("click", () => C.trocarMinhaSenha());

  // No programa instalado (janela própria), o botão "Esta máquina" configura
  // o que este computador mostra e a qual computador principal ele se liga.
  function quandoNoPrograma(fazer) {
    if (window.pywebview && window.pywebview.api) fazer();
    else window.addEventListener("pywebviewready", fazer);
  }
  quandoNoPrograma(() => {
    $("esta-maquina").hidden = false;
    $("esta-maquina").addEventListener("click", configurarMaquina);
  });

  async function configurarMaquina() {
    const api = window.pywebview.api;
    const info = await api.info();
    const tela = el("select", {}, el("option", { value: "" }, "A última aba usada"),
      ...botoes.map((b) => el("option", { value: b.dataset.aba }, b.title)));
    tela.value = info.tela || "";
    const cheia = el("input", { type: "checkbox" });
    cheia.checked = !!info.tela_cheia;
    const trocar = el("button", { type: "button", onclick: async () => {
      if (!confirm("Escolher de novo se este computador é o principal ou a qual principal ele se conecta?")) return;
      await api.reconfigurar();
    } }, info.modo === "principal" ? "Mudar o papel deste computador" : "Trocar o computador principal");
    C.dialogo({
      titulo: "🖥️ Esta máquina",
      corpo: el("div", {},
        el("p", { class: "dica" }, info.modo === "principal"
          ? "Este é o computador principal: os dados ficam aqui e as outras máquinas se conectam nele. Ele precisa ficar ligado."
          : "Conectado ao computador principal: " + info.loja + " (" + info.servidor.replace("http://", "") + ")."),
        el("label", {}, "Tela que esta máquina abre ao ligar"), tela,
        el("label", { class: "inline" }, cheia, "Abrir em tela cheia (TV do painel, tela da cozinha) — F11 alterna"),
        el("div", { style: "margin-top: 16px" }, trocar),
        el("p", { class: "dica" }, "Versão " + info.versao)),
      confirmar: "Salvar",
      aoConfirmar: async () => {
        await api.configurar(tela.value, cheia.checked);
        C.aviso("Configuração desta máquina salva", "ok");
      },
    });
  }
})();
