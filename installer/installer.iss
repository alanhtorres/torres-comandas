; Instalador do Torres Comandas (Inno Setup 6+).
; Gerado por build_tools\build_windows.ps1, que passa /DMyAppVersion=<versão>.

#define MyAppName "Torres Comandas"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Torres"
#define MyAppExeName "TorresComandas.exe"

[Setup]
AppId={{B6C1D3F2-7A4E-4F0B-9C21-5E8A0D6F3C77}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=TorresComandas-Setup-{#MyAppVersion}
SetupIconFile=..\icon\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
; O executável é 64 bits: instala em "Arquivos de Programas" (e não no "(x86)").
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Fecha o programa aberto antes de atualizar os arquivos (atualização por cima).
CloseApplications=force
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "startupicon"; Description: "Abrir automaticamente ao ligar o computador (recomendado)"; GroupDescription: "Inicialização:"
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "..\dist\TorresComandas\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Só instala o WebView2 (janela do programa) se o Windows ainda não tiver.
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: FaltaWebView2

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
; Libera o programa no Firewall do Windows: sem isso as outras máquinas da
; loja e os celulares dos garçons não conseguem se conectar.
; 1) Apaga TODAS as regras deste programa, inclusive as de BLOQUEIO que o
;    Windows cria sozinho quando alguém clica em "Cancelar" no aviso do
;    Firewall (bloqueio vale mais que liberação). Também evita regras repetidas.
; 2) Libera o programa e a porta do sistema (8090), em qualquer tipo de rede
;    (o Windows costuma marcar a rede da loja como "Pública").
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=all program=""{app}\{#MyAppExeName}"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Torres Comandas"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Torres Comandas (porta 8090)"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Torres Comandas"" dir=in action=allow program=""{app}\{#MyAppExeName}"" enable=yes profile=any"; Flags: runhidden; StatusMsg: "Liberando o programa no Firewall do Windows..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Torres Comandas (porta 8090)"" dir=in action=allow protocol=TCP localport=8090 enable=yes profile=any"; Flags: runhidden
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; Flags: waituntilterminated; StatusMsg: "Instalando o componente da janela do programa (WebView2)..."; Check: FaltaWebView2
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "FecharApp"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Torres Comandas"""; Flags: runhidden; RunOnceId: "RemoverFirewall"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Torres Comandas (porta 8090)"""; Flags: runhidden; RunOnceId: "RemoverFirewallPorta"

[Code]
// O WebView2 (motor do Edge) mostra a janela do programa. Já vem no Windows 11
// e no Windows 10 atualizado.
function TemWebView2(Raiz: Integer; Chave: String): Boolean;
var
  Versao: String;
begin
  Result := RegQueryStringValue(Raiz, Chave, 'pv', Versao) and (Versao <> '') and (Versao <> '0.0.0.0');
end;

function FaltaWebView2: Boolean;
begin
  Result := not (TemWebView2(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')
    or TemWebView2(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')
    or TemWebView2(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'));
end;
