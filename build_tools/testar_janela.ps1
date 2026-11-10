# Testa a janela do programa (WebView2) de verdade no Windows do GitHub:
# 1) um computador principal no ar (sem janela);
# 2) um "terminal" que acha o principal sozinho na rede, abre a janela, entra
#    com o usuário e mostra as telas em abas;
# 3) um computador principal com janela (primeiro acesso).
param(
    [Parameter(Mandatory = $true)][string]$Exe
)
$ErrorActionPreference = "Stop"
$Exe = (Resolve-Path $Exe).Path
$raiz = Join-Path $env:TEMP ("janela-teste-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $raiz | Out-Null

function Esperar-Resultado($proc, $arquivo, $segundos = 150) {
    if (-not $proc.WaitForExit($segundos * 1000)) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        throw "A janela não terminou o teste em $segundos s"
    }
    if (-not (Test-Path $arquivo)) {
        Get-ChildItem $raiz -Recurse -Filter "comandas.log" | ForEach-Object { Write-Host "--- $($_.FullName)"; Get-Content $_.FullName }
        throw "O teste da janela não gravou o resultado"
    }
    $r = Get-Content $arquivo -Raw -Encoding utf8 | ConvertFrom-Json
    Write-Host ($r | ConvertTo-Json -Depth 5)
    if (-not $r.ok) {
        Get-ChildItem $raiz -Recurse -Filter "comandas.log" | ForEach-Object { Write-Host "--- $($_.FullName)"; Get-Content $_.FullName }
        throw "Teste da janela falhou: $($r.erro)"
    }
    return $r
}

# 1) principal sem janela, com usuário e tela do bar ligada
$env:COMANDAS_DADOS = Join-Path $raiz "principal"
$principal = Start-Process $Exe -ArgumentList "--sem-bandeja", "--porta", "8095" -PassThru
try {
    $base = "http://127.0.0.1:8095"
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-WebRequest "$base/api/identificar" -UseBasicParsing | Out-Null; break } catch { Start-Sleep -Seconds 1 }
    }
    $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-WebRequest "$base/primeiro-acesso" -Method Post -WebSession $s -UseBasicParsing `
        -Body @{ nome = "Teste"; usuario = "teste"; senha = "teste123"; confirmar = "teste123" } | Out-Null
    Invoke-RestMethod "$base/api/config" -Method Put -WebSession $s -ContentType "application/json" -Body '{"tela_bar":true}' | Out-Null

    # 2) terminal: acha o principal pela rede (--servidor auto), abre na aba do bar
    $env:COMANDAS_DADOS = Join-Path $raiz "terminal"
    $saida = Join-Path $raiz "terminal.json"
    $p = Start-Process $Exe -ArgumentList "--modo", "terminal", "--servidor", "auto", "--tela", "bar",
        "--teste-janela", $saida, "--teste-login", "teste:teste123" -PassThru
    $r = Esperar-Resultado $p $saida
    if ($r.modo -ne "terminal" -or $r.servidor -notmatch ":8095$") { throw "Terminal não achou o principal pela rede" }
    if ($r.caminho -ne "/area") { throw "Terminal não abriu as abas (abriu $($r.caminho))" }
    foreach ($aba in "caixa", "cozinha", "bar", "painel", "admin") {
        if ($r.abas -notcontains $aba) { throw "Falta a aba $aba" }
    }
    if ($r.aba_ativa -ne "bar" -or $r.tela_na_aba -notmatch "^Bar") { throw "Não abriu na tela do bar" }
    if (-not $r.ponte) { throw "A página não fala com o programa (window.pywebview)" }
    $maquina = Get-Content (Join-Path $raiz "terminal\maquina.json") -Raw | ConvertFrom-Json
    if ($maquina.modo -ne "terminal" -or $maquina.tela -ne "bar") { throw "maquina.json do terminal errado" }
}
finally {
    Stop-Process -Id $principal.Id -Force -ErrorAction SilentlyContinue
}

# 3) principal com janela: liga o sistema e mostra o primeiro acesso
Start-Sleep -Seconds 2
$env:COMANDAS_DADOS = Join-Path $raiz "principal-janela"
$saida = Join-Path $raiz "principal.json"
$p = Start-Process $Exe -ArgumentList "--modo", "principal", "--porta", "8094", "--teste-janela", $saida -PassThru
$r = Esperar-Resultado $p $saida
if ($r.caminho -ne "/primeiro-acesso") { throw "Principal com janela não abriu o primeiro acesso (abriu $($r.caminho))" }
if (-not $r.ponte) { throw "A página não fala com o programa (window.pywebview)" }
Write-Host "OK: janela do programa funcionando (terminal achou o principal na rede, abas, tela do bar, principal com janela)" -ForegroundColor Green
