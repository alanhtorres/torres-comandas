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
    foreach ($tela in "/", "/caixa", "/cozinha", "/painel", "/admin", "/static/comum.js", "/static/painel.css") {
        $r = Invoke-WebRequest "$base$tela" -WebSession $s -UseBasicParsing
        if ($r.StatusCode -ne 200) { throw "$tela respondeu $($r.StatusCode)" }
        if ($tela -eq "/caixa" -and $r.Content -notmatch "Novo pedido") { throw "/caixa não abriu logado" }
    }
    $json = @{ "Content-Type" = "application/json; charset=utf-8" }
    $produto = Invoke-RestMethod "$base/api/produtos" -Method Post -Headers $json -WebSession $s -Body ([Text.Encoding]::UTF8.GetBytes('{"nome":"Pão de queijo","preco_centavos":500}'))
    $corpo = @{ itens = @(@{ produto_id = $produto.produto.id; quantidade = 2 }); cliente = "Teste" } | ConvertTo-Json -Depth 5
    $pedido = Invoke-RestMethod "$base/api/pedidos" -Method Post -Headers $json -WebSession $s -Body $corpo
    Invoke-RestMethod "$base/api/pedidos/$($pedido.pedido.id)/chamar" -Method Post -Headers $json -WebSession $s -Body '{}' | Out-Null
    $painel = Invoke-RestMethod "$base/api/painel"
    if ($painel.chamadas[0].codigo -ne "1") { throw "Pedido chamado não apareceu no painel" }
    Invoke-RestMethod "$base/api/caixa/abrir" -Method Post -Headers $json -WebSession $s -Body '{"valor_abertura":10000}' | Out-Null
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
    Write-Host "OK: $Exe funcionando (login, telas, pedido, painel, caixa, histórico, QR code, backup)" -ForegroundColor Green
}
finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
