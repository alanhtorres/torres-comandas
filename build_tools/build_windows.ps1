# Empacota o Torres Comandas com PyInstaller e gera o instalador com Inno Setup.
# Uso (PowerShell, no Windows, na raiz do projeto):
#   .\build_tools\build_windows.ps1
#   .\build_tools\build_windows.ps1 -SkipInstaller   # só gera o executável
# O GitHub Actions (.github/workflows/instalador.yml) roda este mesmo script.

param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Run($exe, [string[]]$argumentos) {
    & $exe @argumentos
    if ($LASTEXITCODE -ne 0) { throw "Falhou: $exe $($argumentos -join ' ')" }
}

Write-Host "==> Criando ambiente virtual (.venv)" -ForegroundColor Cyan
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Run "python" @("-m", "venv", ".venv")
}
$py = Join-Path $root ".venv\Scripts\python.exe"

Write-Host "==> Instalando dependências" -ForegroundColor Cyan
Run $py @("-m", "pip", "install", "--upgrade", "pip")
Run $py @("-m", "pip", "install", "-r", "requirements-build.txt")

$versao = (& $py -c "import sys; sys.path.insert(0, 'src'); import comandas; print(comandas.__version__)").Trim()
Write-Host "==> Versão $versao" -ForegroundColor Cyan

Write-Host "==> Limpando builds anteriores" -ForegroundColor Cyan
Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue

Write-Host "==> Gerando ícone" -ForegroundColor Cyan
Run $py @("icon\gerar_icone.py")

# Instalador do WebView2 (componente do Windows que mostra a janela do
# programa). O Windows 10/11 atualizado já tem; o instalador só roda este
# quando falta (precisa de internet nesse momento).
$webview2 = "installer\MicrosoftEdgeWebview2Setup.exe"
if (-not (Test-Path $webview2)) {
    Write-Host "==> Baixando o instalador do WebView2" -ForegroundColor Cyan
    Invoke-WebRequest "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $webview2
}

Write-Host "==> Empacotando com PyInstaller" -ForegroundColor Cyan
Run $py @("-m", "PyInstaller", "build_tools\torres_comandas.spec", "--noconfirm")
if (-not (Test-Path "dist\TorresComandas\TorresComandas.exe")) {
    throw "Build do PyInstaller falhou: executável não encontrado."
}

if (-not $SkipInstaller) {
    $iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    $isccPath = if ($iscc) { $iscc.Source } else { $null }
    if (-not $isccPath) {
        $pastas = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }
        foreach ($pasta in $pastas) {
            $achado = Get-ChildItem -Path $pasta -Directory -Filter "Inno Setup*" -ErrorAction SilentlyContinue |
                ForEach-Object { Join-Path $_.FullName "ISCC.exe" } |
                Where-Object { Test-Path $_ } |
                Select-Object -First 1
            if ($achado) { $isccPath = $achado; break }
        }
    }
    if (-not $isccPath) {
        throw "Inno Setup (ISCC.exe) não encontrado. Instale em https://jrsoftware.org/isdl.php ou rode com -SkipInstaller."
    }
    Write-Host "==> Gerando instalador com Inno Setup" -ForegroundColor Cyan
    Run $isccPath @("/DMyAppVersion=$versao", "installer\installer.iss")
}

Write-Host "==> Concluído!" -ForegroundColor Green
Write-Host "    Executável: dist\TorresComandas\TorresComandas.exe"
Write-Host "    Instalador: installer\Output\TorresComandas-Setup-$versao.exe"
