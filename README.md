# Torres Comandas

Sistema de comandas para restaurantes, lanchonetes, bares e comércios em geral:
pedidos no caixa e pelo QR code da mesa, cozinha (tela e/ou impressora), painel de
chamada na TV, controle de caixa com relatórios financeiros, usuários com
permissões e histórico de tudo o que cada um faz.

Um PC da loja roda o servidor; todas as telas (caixa, cozinha, TV do painel,
celular do cliente) são apenas um navegador apontando para ele na rede local.
**Não precisa de internet** (ver "Funcionamento sem internet").

## Telas

| Tela | Endereço | Quem acessa |
|---|---|---|
| Início | `/` | Qualquer usuário logado (mostra só os atalhos que ele pode usar) |
| Caixa | `/caixa` | Lançar pedidos, chamar no painel, contas a receber, pagamentos, abrir/fechar caixa |
| Garçom | `/garcom` | Celular/tablet: pedidos na mesa, alerta quando o cliente chama pelo QR code, pedidos prontos para entregar, contas das mesas |
| Cozinha | `/cozinha` | Só o que precisa de preparo, com tempo de espera (amarelo > 10 min, vermelho > 20 min) |
| Painel (TV) | `/painel` | Público. Pedidos prontos + histórico na lateral; fotos e vídeos dos produtos no resto da tela |
| Cliente (QR code) | `/m/<código-da-mesa>` | Público. Cardápio no celular, pedido direto para a cozinha, chamar garçom, pedir a conta |
| Administração | `/admin` | Relatórios, cardápio, mesas e QR codes, mídias do painel, usuários e permissões, histórico, configurações |

## Usuários e permissões

No primeiro acesso o sistema pede para criar o **administrador** (dono/gerente), que
tem acesso a tudo. Ele cria um usuário para cada pessoa da equipe e marca, uma a
uma, o que ela pode acessar:

| Permissão | Libera |
|---|---|
| Caixa: lançar e acompanhar pedidos | Tela do caixa, lançar pedidos, chamar no painel, atender garçom |
| Página do garçom | Pedidos na mesa pelo celular/tablet, alertas do QR code, marcar entregue |
| Tela da cozinha | Tela da cozinha (iniciar preparo / pronto) |
| Receber pagamentos | Receber contas (dinheiro, Pix, cartões, vale), com desconto, taxa de serviço e troco |
| Abrir e fechar o caixa | Abertura com fundo de troco, sangria, suprimento e fechamento |
| Cancelar pedidos | Cancelar pedido ainda não pago (com motivo obrigatório) |
| Estornar pagamentos | Desfazer um pagamento já recebido (aba Recebidos). Separada de propósito: por padrão só o administrador tem; ele decide se algum caixa também pode |
| Cardápio / Mesas e QR codes / Fotos e vídeos do painel / Configurações | As abas correspondentes da administração |
| Relatórios financeiros | Relatórios de vendas e de caixas, planilha para o Excel |
| Histórico de ações | Ver tudo o que cada usuário fez |
| Usuários e permissões | Criar/editar usuários e o que cada um pode fazer |

Há modelos prontos (Administrador, Caixa, Garçom, Cozinha — o modelo Caixa não inclui estorno) que marcam as permissões
mais comuns; depois é só ajustar. Tirar uma permissão ou desativar um usuário vale
**na hora**, mesmo que ele esteja logado. O sistema não deixa ficar sem nenhum
usuário capaz de administrar usuários.

## Página do garçom

Feita para celular ou tablet. O garçom escolhe a mesa, toca nos produtos (com
observação por item, ex.: "sem cebola") e envia: o pedido vai para a cozinha e
para o caixa com o nome dele. Quando um cliente aperta **Chamar garçom** ou
**Pedir a conta** no QR code da mesa, aparece um alerta no topo da tela com som
e vibração (toque uma vez na tela para o navegador liberar o som). A aba
**Entregar** lista o que ficou pronto para levar às mesas e a aba **Mesas** mostra
as contas abertas (com botão para imprimir a conferência, se houver impressora
do caixa).

## O que vai para a cozinha

Cada produto tem a opção **"Vai para a cozinha (precisa de preparo)"**. Bebidas em
lata, chips, sobremesas embaladas etc. podem ficar desmarcados: eles aparecem no
caixa e no garçom, mas não na tela nem na impressora da cozinha. Dá para marcar
uma categoria inteira de uma vez (ex.: "Tirar a categoria da cozinha" em Bebidas)
e depois ajustar produto por produto (ex.: o suco natural volta para a cozinha).
Pedido só com itens prontos já nasce "pronto"; pedido misto mostra na cozinha
só o que precisa ser preparado.

## Histórico (auditoria)

Tudo o que muda dados fica gravado com **quem**, **quando** e **o quê**: entradas e
saídas do sistema (e tentativas de senha erradas), pedidos lançados, chamados,
cancelados (com motivo), pagamentos recebidos (formas, desconto, troco), estornos,
abertura/sangria/suprimento/fechamento de caixa, mudanças de preço e de cardápio,
mesas, configurações, usuários e permissões. Pedidos e chamados feitos pelo QR code
aparecem como "Cliente (mesa X)". A ação e o registro no histórico são gravados
juntos: nunca fica uma coisa sem a outra.

## Controle de caixa

1. **Abrir o caixa** informando o fundo de troco.
2. Receber as contas. Pedidos ainda não pagos ficam em **A receber**, agrupados por
   mesa (a conta da mesa inteira é paga de uma vez) ou por pedido (balcão). No balcão,
   **Enviar e receber** já abre o pagamento. Dá para dividir entre várias formas,
   aplicar desconto ou taxa de serviço, e o troco é calculado sozinho.
3. **Sangria** (retirada) e **suprimento** (reforço) com motivo.
4. **Fechar o caixa**: a pessoa conta o dinheiro da gaveta **sem ver** quanto
   deveria ter (fechamento "cego"); o sistema então mostra o esperado, o contado e
   a **sobra ou falta**, e imprime o comprovante se houver impressora do caixa.

Pedido pago não pode ser cancelado sem antes estornar o pagamento, e só dá para
estornar pagamentos do caixa que está aberto — o que já foi fechado não muda mais.

**Relatórios** (Administração → Relatórios do caixa), por período: total vendido,
número de vendas, ticket médio, por forma de pagamento, por dia, por produto, por
atendente, todos os caixas com diferença de fechamento, estornos e cancelamentos
com motivo, e quanto há a receber. O botão **Planilha (Excel)** baixa as vendas do
período para enviar ao contador.

## Impressoras

Impressoras térmicas com rede (Ethernet/Wi-Fi) no padrão ESC/POS — Epson, Elgin,
Bematech, Tanca, Daruma e as genéricas — pela porta TCP 9100, sem driver:
- **Cozinha**: cada pedido sai impresso (itens em letra grande, observações).
- **Caixa**: conferência de conta da mesa e comprovante de fechamento de caixa.

Pode ser a mesma impressora para as duas. Se a impressora estiver desligada, o
pedido **não se perde**: continua na tela da cozinha e pode ser reimpresso.

## Funcionamento sem internet

Tudo roda dentro da rede da loja: nenhuma tela, função ou biblioteca depende de
internet. Se a internet cair, o sistema continua funcionando normalmente — desde
que o PC servidor e o roteador/Wi-Fi da loja estejam ligados. Além disso:
- O endereço do PC na rede é **redescoberto sozinho** a cada minuto (se o PC ligar
  antes do roteador ou o IP mudar, não precisa reiniciar o programa). Mesmo assim,
  reserve um **IP fixo** para o PC no roteador e preencha em Configurações, porque
  esse endereço vai impresso nos QR codes.
- Cada venda confirmada é gravada no disco na hora (mesmo que falte energia logo
  depois), e o programa faz **backup automático diário** do banco na pasta
  `backups` (guarda os últimos 30 dias). Copie essa pasta para um pendrive de vez
  em quando.
- O programa inicia junto com o Windows e as telas se reconectam sozinhas.
- Atenção ao **celular do cliente**: sem internet no Wi-Fi, alguns celulares trocam
  sozinhos para o 4G e aí o QR code não abre. Peça para o cliente manter o Wi-Fi da
  loja ("manter conectado sem internet").

## Som no painel e na cozinha

Navegadores só liberam som depois do primeiro toque/clique na página. O painel
mostra um botão "Toque aqui para ativar o som" enquanto o som estiver bloqueado.
Em TVs/PCs dedicados, dá para abrir o Chrome já com som liberado:

```
chrome --kiosk --autoplay-policy=no-user-gesture-required http://IP-DO-SERVIDOR:8090/painel
```

Os vídeos do painel sempre tocam sem som.

## Instalando no Windows

1. Baixe o **`TorresComandas-Setup-x.y.z.exe`** na página **Releases** do GitHub.
2. Dê dois cliques e siga o assistente (Avançar → Avançar → Concluir). Não precisa
   instalar Python nem nada mais: vem tudo dentro.
3. Na primeira vez a tela inicial abre sozinha no navegador pedindo para criar o
   administrador. Depois o programa fica em segundo plano, com um **ícone laranja
   perto do relógio do Windows** (abrir as telas, ver o endereço na rede, abrir a
   pasta de dados/backups).

O instalador libera o programa no Firewall do Windows e, por padrão, faz ele
**iniciar junto com o Windows**. Para atualizar, rode o instalador da versão nova
por cima: os dados são preservados (ficam em `%LOCALAPPDATA%\TorresComandas`).

**Atualizando da versão 1.x:** pedidos, cardápio e mesas continuam lá. O antigo PIN
deixa de existir: na primeira abertura o sistema pede para criar o administrador.
As senhas de atendimento (totem) foram retiradas desta versão.

Se a porta 8090 estiver ocupada por outro programa, troque em
`%LOCALAPPDATA%\TorresComandas\servidor.json` e reinicie.

## Gerando o instalador

O instalador é gerado **automaticamente pelo GitHub** (Actions → "Instalador
Windows"), num Windows da nuvem, que também roda os testes, testa o executável
(login, pedido, caixa, histórico, backup) e testa instalar/desinstalar de verdade
antes de publicar. Para lançar uma versão:

1. Altere `__version__` em `src/comandas/__init__.py` (ex.: `2.1.0`).
2. Crie a tag e envie: `git tag v2.1.0 && git push origin v2.1.0`.
3. Em alguns minutos o `TorresComandas-Setup-2.1.0.exe` aparece em Releases.

Para gerar num Windows local: instale Python e o [Inno Setup 6](https://jrsoftware.org/isdl.php)
e rode `build_tools\build_windows.bat` (saída em `installer\Output\`).

## Rodando (desenvolvimento)

Requer Python 3.10+.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip ...
.venv/bin/python main.py                           # porta padrão 8090
```

Opções: `--porta 8090`, `--host 0.0.0.0`, `--sem-bandeja`. Os dados (banco SQLite,
fotos, mídias, backups, logs) ficam em `%LOCALAPPDATA%\TorresComandas` no Windows
ou `~/.local/share/TorresComandas` no Linux; a variável `COMANDAS_DADOS` muda o local.

## Testes

```bash
.venv/bin/python -m pytest
```

Os testes de impressão abrem um servidor TCP de verdade fazendo papel da
impressora e conferem os bytes ESC/POS recebidos.

## Estrutura

```
main.py                     ponto de entrada
src/comandas/
  app.py                    inicialização, IP da rede, backup diário, instância única
  bandeja.py                ícone na bandeja do Windows
  banco.py                  SQLite + regras: usuários/permissões, auditoria, pedidos, caixa, relatórios
  servidor.py               rotas Flask (telas + API) com checagem de permissão
  impressora.py             cupons ESC/POS (cozinha, conta, fechamento) e envio TCP
  web/templates, web/static telas (HTML/CSS/JS puro, sem build)
tests/
build_tools/                PyInstaller (.spec), script de build e teste do .exe
installer/installer.iss     instalador (Inno Setup)
.github/workflows/          build automático do instalador no GitHub
```
