# Torres Comandas

Sistema de pedidos, senhas e painel de chamada para restaurantes, lanchonetes,
lotéricas e qualquer comércio que organize o atendimento por senha.

Um PC da loja roda o servidor; todas as telas (caixa, cozinha, TV do painel,
totem, celular do cliente) são apenas um navegador apontando para ele na rede
local. Não precisa de internet.

## Telas

| Tela | Endereço | Para quê |
|---|---|---|
| Início | `/` | Links de todas as telas com o endereço de rede |
| Caixa | `/caixa` | Lança pedidos, chama o cliente no painel, marca entregue, emite e chama senhas, recebe os chamados de garçom |
| Cozinha | `/cozinha` | Pedidos a preparar, com tempo de espera (amarelo > 10 min, vermelho > 20 min). "Iniciar preparo" e "Pronto" |
| Painel (TV) | `/painel` | Lateral com a chamada atual + histórico; na maior parte da tela, fotos e vídeos dos produtos |
| Totem | `/totem` | O cliente retira a senha: normal (N001...) ou preferencial (P001...) |
| Cliente (QR code) | `/m/<código-da-mesa>` | Cardápio no celular, pedido direto para a cozinha, chamar garçom, pedir a conta, acompanhar o status |
| Administração | `/admin` | Cardápio (com fotos), mesas e QR codes, mídias do painel, impressoras, PIN |

## Fluxo de um pedido

1. O pedido é feito **no caixa** ou **pelo cliente, no QR code da mesa**.
2. Ele aparece na hora na **tela da cozinha** e/ou sai na **impressora de rede** da cozinha.
3. A cozinha marca **Pronto** → o caixa recebe um aviso sonoro e o pedido vai para "Prontos".
4. O caixa clica **Chamar no painel** → a TV mostra o número em tela cheia (com aviso
   sonoro e, se ativado, voz) e depois o mantém no histórico.
5. O cliente retira; o caixa marca **Entregue**.

Opção nas configurações: chamar no painel automaticamente assim que a cozinha
marcar "pronto", sem esperar o caixa.

Senhas (lotéricas, clínicas, balcões): o totem ou o caixa emite a senha; o caixa
informa o seu guichê e clica **Chamar próxima senha** — preferenciais primeiro
(configurável), e a senha anterior daquele guichê é dada como atendida.

## Impressoras

Impressoras térmicas com rede (Ethernet/Wi-Fi) no padrão ESC/POS — Epson, Elgin,
Bematech, Tanca, Daruma e as genéricas — pela porta TCP 9100. Não precisa de
driver: basta o IP da impressora (sai na folha de autoteste). Dá para ter uma
impressora na cozinha e outra para as senhas, em bobina de 80 mm ou 58 mm.
Se os acentos saírem errados, troque a opção "Acentuação" nas configurações.

Se a impressora estiver desligada, o pedido **não se perde**: continua na tela
da cozinha, fica marcado "falha na impressão" no caixa e pode ser reimpresso.

## Segurança

Clientes no Wi-Fi da loja conseguem acessar o servidor (é assim que o QR code
funciona). Por isso, **defina um PIN** em Administração → Configurações: caixa,
cozinha, totem e administração passam a pedir o PIN no primeiro acesso de cada
aparelho. O painel da TV e o cardápio do QR code continuam livres.

Cada mesa tem um código aleatório no QR code (não dá para "adivinhar" a mesa
vizinha). Se a foto de um QR code circular por aí, use "Novo QR" na mesa.

Reserve um IP fixo para o PC servidor no roteador: o endereço vai dentro dos QR
codes impressos.

## Som no painel e na cozinha

Navegadores só liberam som depois do primeiro toque/clique na página. O painel
mostra um botão "Toque aqui para ativar o som" enquanto o som estiver bloqueado.
Em TVs/PCs dedicados, dá para abrir o Chrome já com som liberado:

```
chrome --kiosk --autoplay-policy=no-user-gesture-required http://IP-DO-SERVIDOR:8090/painel
```

Os vídeos do painel sempre tocam sem som.

## Instalando no Windows (modo simples)

1. Instale o Python em https://www.python.org/downloads/ marcando **"Add python.exe to PATH"**.
2. Baixe este projeto (botão **Code → Download ZIP** no GitHub) e extraia em uma pasta, ex.: `C:\TorresComandas`.
3. Dê dois cliques em **`instalar.bat`** (uma vez só; precisa de internet).
4. Dê dois cliques em **`iniciar.bat`**. A janela mostra os endereços das telas. Deixe-a aberta.
5. Na primeira vez o Windows pergunta sobre o firewall: permita em **Redes privadas**.

## Rodando (desenvolvimento)

Requer Python 3.10+.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip ...
.venv/bin/python main.py                           # porta padrão 8090
```

Opções: `--porta 8090`, `--host 0.0.0.0`. Os dados (banco SQLite, fotos, mídias,
logs) ficam em `%LOCALAPPDATA%\TorresComandas` no Windows ou
`~/.local/share/TorresComandas` no Linux; a variável `COMANDAS_DADOS` muda o local.

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
  app.py                    inicialização, pasta de dados, IP da rede
  banco.py                  SQLite + regras (pedidos, senhas, chamadas, mesas, mídias, config)
  servidor.py               rotas Flask (telas + API) e upload de fotos/vídeos
  impressora.py             cupons ESC/POS e envio TCP
  web/templates, web/static telas (HTML/CSS/JS puro, sem build)
tests/
```
