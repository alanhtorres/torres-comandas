# Torres Comandas

Sistema de comandas para restaurantes, lanchonetes, bares e comércios em geral:
pedidos no caixa e pelo QR code da mesa, cozinha (tela e/ou impressora), painel de
chamada na TV, controle de caixa com relatórios financeiros, usuários com
permissões e histórico de tudo o que cada um faz.

É um **programa de Windows**: instala-se o mesmo programa em cada computador da loja
(caixa, cozinha, bar, TV do painel). Um deles é o **computador principal** (guarda os
dados); os outros se conectam nele pelo **IP** dele na rede da loja (digitado uma
vez só, na instalação). Cada computador mostra as telas em **abas** numa janela própria.
**Não precisa de internet** (ver "Funcionamento sem internet").

## Instalando nos computadores da loja

1. Baixe o **`TorresComandas-Setup-x.y.z.exe`** na página **Releases** do GitHub e
   instale em cada computador da loja (Avançar → Avançar → Concluir).
2. **No computador principal** (normalmente o do caixa), na primeira vez escolha
   **"Este é o computador principal"** e crie o administrador. Ele precisa ficar ligado
   enquanto a loja funciona; fechar a janela não desliga o sistema (fica o ícone
   laranja perto do relógio — "Sair" nesse ícone desliga para todos).
3. **Nos outros computadores** (cozinha, bar, segundo caixa, TV), escolha
   **"Conectar ao computador principal"** e digite o **IP do principal** (aparece no
   principal em **Administração → Configurações → Conexões** e no ícone laranja perto
   do relógio). **Reserve esse IP no roteador** ("IP fixo"/"reserva DHCP"): se ele
   mudar, as outras máquinas mostram a tela de reconexão para digitar o novo.
   O papel de cada computador (principal ou conectado) é escolhido só na instalação;
   para recomeçar do zero, feche o programa ("Sair" no ícone) e apague a pasta
   `%LOCALAPPDATA%\TorresComandas`.
4. Em cada computador, **🖥️ Esta máquina** (no topo) escolhe só a tela que ele abre ao
   ligar (ex.: a TV abre o Painel, a cozinha abre a Cozinha) e se abre em tela cheia.
   Na TV do painel, **F2** volta para as abas; **F11** liga/desliga a tela cheia.

As abas aparecem conforme as permissões de quem entrou (o cozinheiro só vê Cozinha,
Bar e Painel). **Ctrl+1, Ctrl+2...** trocam de aba; trocar de aba não perde o que
estava sendo feito na outra.

A janela usa o **WebView2** (o motor do Edge), que já vem no Windows 10/11 atualizado;
se faltar, o instalador o instala (precisa de internet só nesse momento). Celulares
(garçom e cliente do QR code) continuam pelo app/navegador, como antes.

## Telas

No programa, essas telas aparecem como abas (o endereço `/` também abre as abas).
O único endereço que se usa no dia a dia é o do **painel da TV** (navegador da TV),
mostrado em Administração → Configurações → Conexões.

| Tela | Endereço | Quem acessa |
|---|---|---|
| Caixa | `/caixa` | Lançar pedidos, chamar no painel, contas a receber, pagamentos, abrir/fechar caixa |
| Comandas | `/comandas` | Entrada/recepção: cadastrar o cliente, abrir e fechar comandas, aniversariantes do dia |
| Garçom | `/garcom` | Celular/tablet: pedidos na mesa, alerta quando o cliente chama pelo QR code, pedidos prontos para entregar, contas das mesas |
| Cozinha | `/cozinha` | Só o que precisa de preparo, com tempo de espera (amarelo > 10 min, vermelho > 20 min) (quando a tela da cozinha está ligada) |
| Bar | `/bar` | Igual à cozinha, com os produtos do bar (quando a tela do bar está ligada) |
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
| Comandas | Abrir comanda e cadastrar cliente na entrada (vê nome e telefone, não vê CPF) |
| Clientes e WhatsApp | Lista completa de clientes (com CPF e aniversário), exportar, editar, apagar dados e enviar mensagens de WhatsApp |
| Estornar pagamentos | Desfazer um pagamento já recebido (aba Recebidos). Separada de propósito: por padrão só o administrador tem; ele decide se algum caixa também pode |
| Cardápio / Mesas e QR codes / Fotos e vídeos do painel / Configurações | As abas correspondentes da administração |
| Relatórios financeiros | Relatórios de vendas e de caixas, planilha para o Excel |
| Histórico de ações | Ver tudo o que cada usuário fez |
| Usuários e permissões | Criar/editar usuários e o que cada um pode fazer |

Há modelos prontos (Administrador, Caixa, Garçom, Cozinha — o modelo Caixa não inclui estorno) que marcam as permissões
mais comuns; depois é só ajustar. Tirar uma permissão ou desativar um usuário vale
**na hora**, mesmo que ele esteja logado. O sistema não deixa ficar sem nenhum
usuário capaz de administrar usuários.

### Segurança do login

- Contas com acesso a dinheiro, clientes ou administração (caixa, administrador…)
  **saem sozinhas quando o programa é reiniciado** e depois de um tempo sem uso
  (padrão 30 minutos; ajuste em Configurações → Segurança). A tela volta para o login
  explicando o motivo e, depois de entrar, abre de novo onde estava.
- Contas só de cozinha, garçom ou entrada continuam logadas, para a tela da cozinha
  não parar de mostrar pedidos.
- A atualização automática das telas não conta como uso: só cliques e páginas abertas.
- Trocar a senha de alguém tira essa pessoa de todos os aparelhos.
- Depois de 5 senhas erradas seguidas, o aparelho fica 5 minutos sem poder tentar
  (fica registrado no histórico).

## Página do garçom

Feita para celular ou tablet. O garçom escolhe a mesa, toca nos produtos (com
observação por item, ex.: "sem cebola") e envia: o pedido vai para a cozinha e
para o caixa com o nome dele. Quando um cliente aperta **Chamar garçom** ou
**Pedir a conta** no QR code da mesa, aparece um alerta no topo da tela com som
e vibração (toque uma vez na tela para o navegador liberar o som). A aba
**Entregar** lista o que ficou pronto para levar às mesas e a aba **Mesas** mostra
as contas abertas (com botão para imprimir a conferência, se houver impressora
do caixa).

O pedido que está sendo anotado fica guardado no aparelho: se o garçom sair da
página (ou o celular fechar o navegador), ao voltar a mesa e os itens estão lá.

### App Android do garçom

Mais prático que o navegador: abre direto na tela do garçom, não se perde ao
sair e voltar, e **avisa com notificação, som e vibração mesmo com o celular no
bolso, a tela apagada ou outro app aberto** (mesa chamando, pedindo a conta,
pedido pronto para levar). A notificação do chamado tem o botão **✓ Atendi**.

Instalação (sem Play Store e sem internet — o celular baixa direto do PC):
1. No PC, em **Administração → Configurações → Conexões**, clique em **QR code para
   baixar** e aponte a câmera do celular (o celular precisa estar no Wi-Fi da loja).
2. Toque em **Baixar o app**, instale (permita "instalar desta fonte") e toque em
   **Abrir no app**: ele já abre ligado ao PC. Ou abra o app e **digite o IP** do
   computador principal (o mesmo das Conexões).
3. Entre com o usuário do garçom e permita as notificações.

Se não conectar, o app explica o motivo (IP sem resposta, celular fora do Wi-Fi da
loja, firewall/antivírus do principal). Se o IP do PC mudar, toque em **Trocar o IP
do computador principal**. Dentro do app só existe a tela do garçom (sem "Início",
abas ou painel).

**Pedidos em contingência (longe do Wi-Fi):** se o garçom fizer o pedido sem
conexão, ele fica **guardado no celular** (faixa azul "📡 pedido guardado") e é
**enviado sozinho quando o Wi-Fi volta** — mesmo que o app seja fechado e aberto
de novo nesse meio tempo (a tela do garçom abre pela cópia guardada no celular, com
o cardápio e as mesas da última vez). Cada pedido leva um código: se chegar duas
vezes, o sistema lança uma vez só. Se o sistema recusar o pedido guardado (produto
indisponível, comanda fechada), a faixa avisa e o garçom escolhe tentar de novo ou
descartar. O histórico registra "feito sem Wi-Fi às HH:MM e enviado depois".

Enquanto o turno está ativo aparece
um aviso fixo na barra do celular; ao final do dia, **⚙️ App → Encerrar turno**.
Em alguns celulares (Xiaomi, Samsung) vale tocar em **⚙️ App → Não deixar o
Android pausar os avisos**. Quando o sistema é atualizado, o app avisa que há
versão nova e é só baixar de novo pela mesma página.

O .apk também fica na página Releases do GitHub. Ele é assinado com a chave da
loja (segredos `ANDROID_KEYSTORE_B64` e `ANDROID_KEYSTORE_SENHA` do repositório):
use sempre a mesma chave, senão o Android não instala a atualização por cima.

## Comandas com cadastro do cliente

Modo opcional (Administração → Configurações → "Comandas e clientes"). Todo cliente
que entra é cadastrado — **nome e telefone obrigatórios**, CPF e data de nascimento
opcionais — e recebe uma comanda (o número do cartão físico ou o próximo livre).
Na próxima visita basta buscar pelo nome, telefone ou CPF.

- O caixa e o garçom lançam os pedidos **na comanda** do cliente; a conta aparece em
  "A receber" como "Comanda 12 · Fulano".
- No caixa, o botão **"+ Abrir comanda"** (ao lado da escolha da comanda) busca ou
  cadastra o cliente e abre a comanda sem sair da venda — ela já fica escolhida no
  pedido. Aparece para quem tem a permissão "Comandas".
- Quando a comanda é paga ela **fecha sozinha** e o número fica livre para outro cliente
  (se o pagamento for estornado, ela reabre). Quem sai sem consumir tem a comanda
  fechada na tela de Comandas.
- Telefone e CPF são conferidos (DDD, celular com 9, dígitos do CPF) e não se repetem
  entre clientes.

## Clientes, aniversários e WhatsApp

Em **Administração → Clientes e WhatsApp**:
- **Aniversariantes** de hoje e dos próximos 7 dias, com botão "Enviar parabéns no
  WhatsApp" (a mensagem é configurável). Os aniversariantes do dia também aparecem
  na tela de Comandas, e o sistema avisa quando a comanda é aberta para quem está de
  aniversário.
  Com mais de um aniversariante no dia, o botão "Enviar parabéns para os N
  aniversariantes de hoje" manda um após o outro.
- **Campanhas**: escreva a mensagem (use `{nome}` e `{loja}`), escolha o público
  (todos, aniversariantes do mês/semana, clientes que não vêm há 30 dias, novos) e
  clique em **Começar envio**. O sistema abre a conversa de um cliente por vez com o
  texto pronto: aperte enviar no WhatsApp, volte e aperte **Enter** para o próximo
  (dá para pular e voltar aos pulados no final). O nome da campanha é opcional e o
  sistema marca quem já recebeu, sem repetir.
- **Lista de transmissão** (para muitos clientes de uma vez): "Baixar contatos (.vcf)"
  gera o arquivo para importar os clientes no celular da loja; no WhatsApp, crie uma
  transmissão com eles (até 256 por lista) e mande a mensagem uma vez só. Depois,
  "Marcar todos como enviados". A transmissão só chega para quem também salvou o
  número da loja.
- Lista de clientes com visitas, última visita e quanto gastou; planilha para o Excel.

**Como o WhatsApp é aberto** (Configurações): WhatsApp Web no navegador do PC, o
aplicativo WhatsApp instalado no PC (o mais rápido para campanhas: não recarrega a cada
cliente), ou link wa.me (celular/tablet); dá para trocar na hora do envio. Não usa robô nem
API paga: quem envia é a pessoa, pelo WhatsApp da loja — isso evita o bloqueio do
número, que acontece com programas de envio automático em massa. Precisa de internet
só no momento do envio; o resto do sistema continua funcionando sem internet.

**LGPD**: o cadastro tem a caixinha "o cliente autoriza receber mensagens" (a data da
autorização fica guardada) e as campanhas e parabéns só vão para quem autorizou. O CPF
só aparece para quem tem a permissão "Clientes e WhatsApp". A pedido do cliente, o
botão "Apagar dados (LGPD)" apaga nome, telefone, CPF e nascimento — as vendas
continuam nos relatórios, sem os dados pessoais.

## Ambientes: cozinha, bar, pizzaria... (tela ou impressora)

Cada lugar de preparo é um **ambiente**. Cozinha e bar já vêm prontos; em
Administração → Configurações → "Ambientes: como saem os pedidos", o botão
**➕ Novo ambiente** cria outros (pizzaria, confeitaria, chapa...), com nome e ícone.
Para cada ambiente o administrador escolhe **tela**, **impressora** ou os dois:
- **Com tela**: ganha uma aba igual à da cozinha (endereço `/preparo/<nome>` para os
  criados) e marca "pronto" na sua parte. Pedido que vai para mais de um ambiente só
  fica pronto (e vai para o painel) quando todos terminarem.
- **Sem tela**: só imprime e não segura o pedido (a aba some).
- Sem tela e sem impressora, a configuração avisa.

Cada produto tem **"Vai para"**: um ambiente ou **Nenhum lugar** (já pronto: bebida
em lata, chips — aparece só no caixa e no garçom). Em Administração → Cardápio, a
linha de cada categoria escolhe de uma vez para onde vai a categoria inteira (ex.:
Pizzas → Pizzaria). Produto novo numa categoria que já existe vem com o ambiente dela.
Pedido misto é dividido: cada ambiente vê e imprime só os itens dele.

Ambiente criado pode ser renomeado ou excluído (só sem produtos indo para ele e sem
pedidos na fila dele); cozinha e bar não são excluídos, só desligados.

**Logo do estabelecimento** (Configurações → Estabelecimento → 📤 Enviar logo): aparece
junto do nome nas abas do programa, no login, no painel da TV (grande, quando não há
fotos), no cardápio do QR code e nos QR codes impressos.

## Histórico (auditoria)

Tudo o que muda dados fica gravado com **quem**, **quando** e **o quê**: entradas e
saídas do sistema (e tentativas de senha erradas), pedidos lançados, chamados,
cancelados (com motivo), pagamentos recebidos (formas, desconto, troco), estornos,
abertura/sangria/suprimento/fechamento de caixa, mudanças de preço e de cardápio,
mesas, configurações, usuários e permissões. Pedidos e chamados feitos pelo QR code
aparecem como "Cliente (mesa X)". A ação e o registro no histórico são gravados
juntos: nunca fica uma coisa sem a outra.

## Controle de caixa

1. **Abrir o caixa** informando o fundo de troco. **Sem o caixa aberto não entra
   pedido** — nem pelo caixa, nem pelo garçom, nem pelo QR code da mesa (o caixa e
   o garçom veem o aviso "caixa fechado"; pedido feito sem Wi-Fi no celular fica
   guardado e é enviado de novo pelo botão "Tentar de novo" depois que o caixa abrir).
2. Receber as contas. Pedidos ainda não pagos ficam em **A receber**, agrupados por
   mesa (a conta da mesa inteira é paga de uma vez) ou por pedido (balcão). No balcão,
   **Enviar e receber** já abre o pagamento.
   - A janela de pagamento mostra **um valor só**: a pessoa toca na forma de
     pagamento (Dinheiro, Pix, cartões...) e confirma. Em dinheiro, digita quanto o
     cliente entregou e o troco aparece.
   - **Desconto**, **Taxa** de serviço, **Dividir conta** e **Pagar só uma parte**
     ficam em botões, escondidos até serem usados.
   - **Dividir conta**: o caixa digita em quantas partes (de 2 a 50, ou toca nos
     atalhos 2 a 6). Cada parte é paga separada (e pode ser de um jeito diferente);
     a janela já reabre para a próxima parte. Os centavos que não dividem certo
     ficam na primeira parte.
   - **Pagar por item**: aparecem os itens da conta que ainda não foram pagos; o
     caixa toca em + nos que o cliente consumiu e ele paga só esses (a taxa de
     serviço, se ligada, é calculada sobre esses itens). Os itens ficam marcados
     como pagos ("1 pago") e não aparecem de novo; o último pagamento fecha a conta.
   - **Pagar só uma parte** (abater): o valor pago é descontado e a conta/comanda
     continua aberta com o que falta. Serve também para quem paga com duas formas.
     A comanda só fecha no último pagamento.
   - A conta mostra "já pago / falta", e a conferência impressa também. Um valor
     abatido só pode ser estornado antes do pagamento final da conta.
3. **Sangria** (retirada) e **suprimento** (reforço) com motivo.
4. **Fechar o caixa**: a pessoa conta o dinheiro da gaveta **sem ver** quanto
   deveria ter (fechamento "cego"); o sistema então mostra o esperado, o contado e
   a **sobra ou falta**, e imprime o comprovante se houver impressora do caixa.

**Conferência da conta** (botão 🖨️ Conta em todo pedido ainda não pago, e 🖨️ Imprimir
conta na aba "A receber"): imprime os itens e o total para o cliente conferir antes de
pagar. Sai na impressora térmica do caixa, se estiver ligada; senão abre uma página para
imprimir pelo navegador. Se parte já foi paga, mostra "já pago" e "falta pagar". Pedido
pago não mostra o botão.

**Cancelar item ou pedido** (botão ✏️ Editar / cancelar no pedido, para quem pode
cancelar), em três toques: 1) toque em **🗑️ Cancelar** no item que vai sair (se tiver
mais de uma unidade, ajuste quantas com − e +; "↩ Desfazer" volta atrás); 2) toque no
motivo (Cliente desistiu, Lançado errado, Acabou o produto, Demorou muito) ou escreva
outro; 3) **Confirmar**. Para cancelar tudo, escolha o motivo e toque em **❌ Cancelar
o pedido inteiro**. O motivo fica no histórico e nos relatórios ("Pedidos e itens
cancelados"). Se a cozinha/bar tem impressora, sai um aviso "CANCELADO — não preparar".
O que já foi pago (inclusive item pago no pagamento por item) não pode ser cancelado.

Pedido pago não pode ser cancelado sem antes estornar o pagamento, e só dá para
estornar pagamentos do caixa que está aberto — o que já foi fechado não muda mais.

**Relatórios** (Administração → Relatórios do caixa), por período: total vendido,
número de vendas, ticket médio, por forma de pagamento, por dia, por produto, por
atendente, todos os caixas com diferença de fechamento, estornos e cancelamentos
com motivo, e quanto há a receber.

**Exportar relatório (PDF ou Excel)**: no mesmo lugar, o botão "Exportar relatório"
deixa o administrador marcar o que entra — resumo, formas de pagamento, vendas por dia,
produtos, atendentes, todas as vendas uma a uma, abertura/fechamento de caixa, sangrias
e suprimentos, estornos, cancelamentos, comandas, histórico de ações e cadastro de
clientes — e escolher **PDF** (para imprimir ou enviar ao contador) ou **planilha
Excel** (uma aba por assunto, com valores e datas de verdade para somar e filtrar).
O arquivo é gerado no próprio PC e baixa sozinho. Histórico e clientes só aparecem
para quem tem essas permissões.

## Delivery

1. No caixa, ao montar o pedido, toque em **🛵 Delivery** (no lugar de "No local /
   balcão") e preencha telefone, nome, endereço, bairro, complemento/referência,
   **taxa de entrega** (somada ao total) e como o cliente vai pagar na entrega
   (em dinheiro, o "troco para quanto").
2. Cliente que já pediu antes: ao digitar o telefone, nome e endereço do último
   delivery dele já vêm preenchidos. A taxa de entrega usada por último também.
3. A cozinha vê o pedido marcado **🛵 DELIVERY** (na tela e no cupom impresso).
   Delivery não é chamado no painel.
4. Quando fica pronto, o caixa toca em **🏷️ Etiqueta do entregador**: sai na
   impressora do caixa (ou, sem impressora térmica, abre a etiqueta para imprimir
   pelo navegador). A etiqueta tem o número do pedido, cliente, telefone, endereço,
   itens, taxa de entrega, total e quanto **cobrar** (ou "JÁ PAGO"), com a forma de
   pagamento e o troco a levar.
5. **🛵 Saiu para entrega** tira o pedido da lista. Se não foi pago antes, ele
   continua em **A receber** até o entregador voltar com o pagamento.

## Modo claro

As telas da equipe (caixa, cozinha, garçom, comandas, administração) podem ficar no
**modo claro** — fundo branco, mais fácil de ler em ambiente iluminado. O padrão de
todos os aparelhos é escolhido em Administração → Configurações → Estabelecimento;
cada aparelho ainda pode trocar só para ele no botão **☀️ Claro / 🌙 Escuro** do topo.
O cardápio do QR code já é claro e o painel da TV continua escuro.

## Impressoras

Impressoras térmicas no padrão ESC/POS — Epson, Elgin, Bematech, Tanca, Daruma e
as genéricas. Cada uma pode ser ligada de dois jeitos (Administração → Configurações):
- **Rede** (Ethernet/Wi-Fi): pelo IP, porta TCP 9100, sem driver.
- **USB**: instalada no Windows **do PC que roda o Torres Comandas** (driver do
  fabricante ou "Generic / Text Only"); escolha pelo nome na lista. Os comandos vão
  "crus" (RAW) pelo spooler do Windows, com corte de papel e letra grande.

São três impressoras:
- **Cozinha**: os itens de preparo de cada pedido (letra grande, observações).
- **Bar**: os itens marcados para sair no bar.
- **Caixa**: conferência de conta da mesa e comprovante de fechamento de caixa.

Pode ser a mesma impressora para mais de uma. Se a impressora estiver desligada, o
pedido **não se perde**: continua na tela e pode ser reimpresso (🖨️ no caixa).

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

Ver "Instalando nos computadores da loja" no começo. Não precisa instalar Python
nem nada mais: vem tudo dentro.

O instalador libera o programa e a porta 8090 no Firewall do Windows (e apaga regras
de bloqueio antigas que o Windows cria quando alguém clica "Cancelar" no aviso do
Firewall) e, por padrão, faz ele **abrir junto com o Windows**. Antivírus com
firewall próprio (Avast, Kaspersky, Norton...) podem precisar liberar o
Torres Comandas manualmente.
**Atualizando da 2.x:** o computador que já tinha os dados continua sendo o principal,
sem perguntar nada; nos outros, instale e escolha "Conectar ao computador principal".
Navegadores e celulares continuam funcionando pelos endereços de antes. Para atualizar, rode o instalador da versão nova
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
  app.py                    inicialização (principal ou terminal), backup diário
  programa.py               janela do programa (pywebview/WebView2), primeira vez, abas
  maquina.py                papel deste computador e tela que ele abre (maquina.json)
  descoberta.py             IP deste PC na rede e conexão ao principal pelo IP
  bandeja.py                ícone do computador principal perto do relógio
  banco.py                  SQLite + regras: usuários/permissões, auditoria, pedidos, caixa, relatórios
  servidor.py               rotas Flask (telas + API) com checagem de permissão
  impressora.py             cupons ESC/POS (cozinha, conta, fechamento) e envio TCP
  exportar.py               relatório para download em PDF (reportlab) ou Excel (openpyxl)
  web/templates, web/static telas (HTML/CSS/JS puro, sem build); area.html = as abas
  web/assistente.html       tela de primeira vez (principal ou conectar)
  app_android/              o .apk do garçom entra aqui no build (para a página /app)
android/                    app Android do garçom (Kotlin, sem bibliotecas externas)
tests/
build_tools/                PyInstaller (.spec), script de build, teste do .exe e do app no Android emulado
installer/installer.iss     instalador (Inno Setup)
.github/workflows/          build automático do instalador no GitHub
```
