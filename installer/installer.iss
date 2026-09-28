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
UninstallDisplayIcon={app}\{#MyAppExeName}
; Fecha o programa aberto antes de atualizar os arquivos (atualização por cima).
CloseApplications=force
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "startupicon"; Description: "Iniciar automaticamente com o Windows (recomendado: é o servidor da loja)"; GroupDescription: "Inicialização:"
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "..\dist\TorresComandas\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
; Libera o programa no Firewall do Windows: sem isso as outras telas da loja
; (caixa, cozinha, TV, celulares no QR code) não conseguem se conectar.
; Remove antes pra não acumular regras repetidas ao atualizar por cima.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Torres Comandas"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Torres Comandas"" dir=in action=allow program=""{app}\{#MyAppExeName}"" enable=yes profile=any"; Flags: runhidden; StatusMsg: "Liberando o programa no Firewall do Windows..."
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "FecharApp"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Torres Comandas"""; Flags: runhidden; RunOnceId: "RemoverFirewall"
