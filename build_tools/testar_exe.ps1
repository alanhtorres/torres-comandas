# Sobe o executável empacotado (sem bandeja), faz um pedido completo pela
# API e confere se as telas respondem. Usado pelo GitHub Actions.
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [int]$Porta = 8099
)
$ErrorActionPreference = "Stop"
$dados = Join-Path $env:TEMP ("comandas-teste-" + [guid]::NewGuid())
$env:COMANDAS_DADOS = $dados
$base = "http://127.0.0.1:$Porta"
$proc = Start-Process $Exe -ArgumentList "--sem-bandeja", "--porta", "$Porta" -PassThru
try {
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-WebRequest "$base/painel" -UseBasicParsing | Out-Null; $ok = $true; break }
        catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ok) {
        Get-Content (Join-Path $dados "logs\comandas.log") -ErrorAction SilentlyContinue
        throw "O programa não respondeu em $base"
    }
    # Primeiro acesso: cria o administrador e já fica logado (sessão em $s)
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-WebRequest "$base/primeiro-acesso" -Method Post -WebSession $s -UseBasicParsing `
        -Body @{ nome = "Teste"; usuario = "teste"; senha = "teste123"; confirmar = "teste123" } | Out-Null
    foreach ($tela in "/", "/area", "/caixa", "/cozinha", "/bar", "/garcom", "/comandas", "/painel", "/admin", "/static/comum.js", "/static/painel.css") {
        $r = Invoke-WebRequest "$base$tela" -WebSession $s -UseBasicParsing
        if ($r.StatusCode -ne 200) { throw "$tela respondeu $($r.StatusCode)" }
        if ($tela -eq "/caixa" -and $r.Content -notmatch "Novo pedido") { throw "/caixa não abriu logado" }
    }
    $json = @{ "Content-Type" = "application/json; charset=utf-8" }
    $produto = Invoke-RestMethod "$base/api/produtos" -Method Post -Headers $json -WebSession $s -Body ([Text.Encoding]::UTF8.GetBytes('{"nome":"Pão de queijo","preco_centavos":500}'))
    # Sem caixa aberto o pedido não entra (desde a 3.5.0)
    $corpo = @{ itens = @(@{ produto_id = $produto.produto.id; quantidade = 2 }); cliente = "Teste" } | ConvertTo-Json -Depth 5
    try {
        Invoke-RestMethod "$base/api/pedidos" -Method Post -Headers $json -WebSession $s -Body $corpo | Out-Null
        throw "Pedido entrou com o caixa fechado"
    } catch {
        if ($_.Exception.Message -eq "Pedido entrou com o caixa fechado") { throw }
    }
    Invoke-RestMethod "$base/api/caixa/abrir" -Method Post -Headers $json -WebSession $s -Body '{"valor_abertura":10000}' | Out-Null
    $pedido = Invoke-RestMethod "$base/api/pedidos" -Method Post -Headers $json -WebSession $s -Body $corpo
    Invoke-RestMethod "$base/api/pedidos/$($pedido.pedido.id)/chamar" -Method Post -Headers $json -WebSession $s -Body '{}' | Out-Null
    $painel = Invoke-RestMethod "$base/api/painel"
    if ($painel.chamadas[0].codigo -ne "1") { throw "Pedido chamado não apareceu no painel" }
    $pag = @{ pedido_ids = @($pedido.pedido.id); formas = @(@{ forma = "dinheiro"; valor = 2000 }) } | ConvertTo-Json -Depth 5
    $rec = Invoke-RestMethod "$base/api/recebimentos" -Method Post -Headers $json -WebSession $s -Body $pag
    if ($rec.recebimento.troco -ne 1000) { throw "Troco calculado errado" }
    $fech = Invoke-RestMethod "$base/api/caixa/fechar" -Method Post -Headers $json -WebSession $s -Body '{"valor_contado":11000}'
    if ($fech.sessao.diferenca -ne 0) { throw "Fechamento de caixa com diferença inesperada" }
    $hist = Invoke-RestMethod "$base/api/auditoria" -WebSession $s
    if (-not ($hist.registros | Where-Object { $_.acao -eq "Fechou o caixa" })) { throw "Histórico não registrou o fechamento" }
    # sem login, o caixa é bloqueado
    try { Invoke-WebRequest "$base/api/estado" -UseBasicParsing | Out-Null; throw "API do caixa aberta sem login!" }
    catch { if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw } }
    Invoke-RestMethod "$base/api/mesas" -Method Post -Headers $json -WebSession $s -Body '{"numero":"1"}' | Out-Null
    $qr = Invoke-WebRequest "$base/qrcode/mesa/1.svg" -WebSession $s -UseBasicParsing
    if ($qr.Content -notmatch "<svg") { throw "QR code não foi gerado" }
    if (-not (Get-ChildItem (Join-Path $dados "backups") -Filter "comandas-*.db")) { throw "Backup diário não foi criado" }
    # Comanda com cadastro do cliente
    Invoke-RestMethod "$base/api/config" -Method Put -Headers $json -WebSession $s -Body '{"modo_comandas_ativo":true}' | Out-Null
    $cli = Invoke-RestMethod "$base/api/clientes" -Method Post -Headers $json -WebSession $s -Body ([Text.Encoding]::UTF8.GetBytes('{"nome":"Maria Conceição","telefone":"(11) 98765-4321","aceita_mensagens":true}'))
    $cmd = Invoke-RestMethod "$base/api/comandas" -Method Post -Headers $json -WebSession $s -Body (@{ cliente_id = $cli.cliente.id } | ConvertTo-Json)
    if ($cmd.comanda.numero -ne "1") { throw "Comanda não abriu" }
    # Relatórios para download (PDF e Excel gerados pelo programa empacotado)
    $pdf = Invoke-WebRequest "$base/api/relatorios/exportar?formato=pdf&secoes=resumo,vendas,caixas,comandas,historico,clientes" -WebSession $s -UseBasicParsing
    if ([Text.Encoding]::ASCII.GetString($pdf.RawContentStream.ToArray()[0..3]) -ne "%PDF") { throw "PDF não foi gerado" }
    $xlsx = Invoke-WebRequest "$base/api/relatorios/exportar?formato=xlsx&secoes=resumo,vendas,produtos" -WebSession $s -UseBasicParsing
    if ([Text.Encoding]::ASCII.GetString($xlsx.RawContentStream.ToArray()[0..1]) -ne "PK") { throw "Planilha Excel não foi gerada" }
    # App Android do garçom embutido: o celular baixa direto deste PC
    $ident = Invoke-RestMethod "$base/api/identificar"
    if (-not $ident.app -or $ident.app.versao_codigo -le 0) { throw "O app Android não veio no programa empacotado" }
    $apk = Invoke-WebRequest "$base/app/torres-garcom.apk" -UseBasicParsing
    if ([Text.Encoding]::ASCII.GetString($apk.RawContentStream.ToArray()[0..1]) -ne "PK") { throw "Download do app Android falhou" }
    if ((Invoke-WebRequest "$base/app" -UseBasicParsing).Content -notmatch "Baixar o app") { throw "Página /app sem o botão de baixar" }
    Write-Host "OK: $Exe funcionando (login, telas, pedido, painel, caixa, histórico, QR code, backup, comanda, PDF, Excel, app Android)" -ForegroundColor Green
}
finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
