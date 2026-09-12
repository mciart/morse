; Build through build.ps1, which reads version and validates the onedir bundle.
#define MyAppName "摩斯输入"
#define MyAppExeName "MorseWriter.exe"
#ifndef APP_VERSION
  #define APP_VERSION GetEnv('APP_VERSION')
#endif
#if APP_VERSION == ""
  #error APP_VERSION is required; use build.ps1
#endif

[Setup]
AppId={{2DB71CE2-A8F1-4EB9-BA6D-EE1EAD16659C}
AppName={#MyAppName}
AppVersion={#APP_VERSION}
AppVerName={#MyAppName} {#APP_VERSION}
AppPublisher=mciart
AppPublisherURL=https://github.com/mciart/morse
AppSupportURL=https://github.com/mciart/morse/issues
AppUpdatesURL=https://github.com/mciart/morse/releases
DefaultDirName={localappdata}\Programs\MorseWriter
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist
OutputBaseFilename=MorseWriter-Setup-v{#APP_VERSION}-x64
SetupIconFile=res\MorseWriterIcon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UsePreviousTasks=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "tools\installer\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："
Name: "autostart"; Description: "登录 Windows 后自动启动摩斯输入"; GroupDescription: "启动："; Flags: unchecked

[Files]
Source: "dist\MorseWriter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Older installers used a Startup shortcut in addition to the Run value.
Type: files; Name: "{userstartup}\MorseWriter.lnk"

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; A single per-user Run value is shared with the application's startup setting.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "MorseWriter"; ValueData: """{app}\{#MyAppExeName}"" --startup"; Flags: uninsdeletevalue; Tasks: autostart
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "MorseWriter"; Flags: deletevalue; Tasks: not autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行摩斯输入"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'MorseWriter');
end;
