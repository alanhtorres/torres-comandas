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
    foreach ($tela in "/", "/caixa", "/cozinha", "/painel", "/totem", "/admin", "/static/comum.js", "/static/painel.css") {
        $r = Invoke-WebRequest "$base$tela" -UseBasicParsing
        if ($r.StatusCode -ne 200) { throw "$tela respondeu $($r.StatusCode)" }
    }
    $json = @{ "Content-Type" = "application/json" }
    $produto = Invoke-RestMethod "$base/api/produtos" -Method Post -Headers $json -Body '{"nome":"Pão de queijo","preco_centavos":500}'
    $corpo = @{ itens = @(@{ produto_id = $produto.produto.id; quantidade = 2 }); cliente = "Teste" } | ConvertTo-Json -Depth 5
    $pedido = Invoke-RestMethod "$base/api/pedidos" -Method Post -Headers $json -Body $corpo
    Invoke-RestMethod "$base/api/pedidos/$($pedido.pedido.id)/chamar" -Method Post -Headers $json -Body '{}' | Out-Null
    $painel = Invoke-RestMethod "$base/api/painel"
    if ($painel.chamadas[0].codigo -ne "1") { throw "Pedido chamado não apareceu no painel" }
    $mesa = Invoke-RestMethod "$base/api/mesas" -Method Post -Headers $json -Body '{"numero":"1"}'
    $qr = Invoke-WebRequest "$base/qrcode/mesa/1.svg" -UseBasicParsing
    if ($qr.Content -notmatch "<svg") { throw "QR code não foi gerado" }
    Write-Host "OK: $Exe funcionando (telas, pedido, painel, QR code)" -ForegroundColor Green
}
finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
