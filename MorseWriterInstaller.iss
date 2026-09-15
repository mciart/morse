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
AppMutex=MorseWriter.mciart
SetupMutex=MorseWriter.mciart.setup
AppName={#MyAppName}
AppVersion={#APP_VERSION}
AppVerName={#MyAppName} {#APP_VERSION}
AppPublisher=mciart
AppPublisherURL=https://github.com/mciart/morse
AppSupportURL=https://github.com/mciart/morse/issues
AppUpdatesURL=https://github.com/mciart/morse/releases
VersionInfoCompany=mciart
VersionInfoCopyright=Copyright (C) mciart
VersionInfoDescription=摩斯输入安装程序
VersionInfoProductName=摩斯输入
VersionInfoVersion={#APP_VERSION}
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
; Remove only retired bundled seeds; never touch writable user_data.
Type: files; Name: "{app}\_internal\defaults\morsewriter.sqlite"
Type: files; Name: "{app}\_internal\res\morsewriter_pressagio.ini"

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; A single per-user Run value is shared with the application's startup setting.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "MorseWriter"; ValueData: """{app}\{#MyAppExeName}"" --startup"; Flags: uninsdeletevalue; Tasks: autostart
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "MorseWriter"; Flags: deletevalue; Tasks: not autostart

[Code]
const
  MorseWriterUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{2DB71CE2-A8F1-4EB9-BA6D-EE1EAD16659C}_is1';
  MorseWriterRunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  StartupDefaultApplied: Boolean;

function ParameterSetsStartup(const Parameter: String): Boolean;
var
  Value: String;
begin
  Value := Lowercase(Parameter);
  { /TASKS replaces every task; /LOADINF supplies explicit saved choices. }
  Result := (Pos('/tasks=', Value) = 1) or (Pos('/loadinf=', Value) = 1);
  if Result or (Pos('/mergetasks=', Value) <> 1) then
    Exit;
  Value := Copy(Value, 13, Length(Value));
  StringChangeEx(Value, ' ', '', True);
  StringChangeEx(Value, '"', '', True);
  Value := ',' + Value + ',';
  Result := (Pos(',autostart,', Value) > 0) or
    (Pos(',!autostart,', Value) > 0) or (Pos(',*autostart,', Value) > 0);
end;

function HasExplicitStartupChoice: Boolean;
var
  Index: Integer;
begin
  Result := True;
  for Index := 1 to ParamCount do
    if ParameterSetsStartup(ParamStr(Index)) then
      Exit;
  Result := False;
end;

function ReadPreviousStartupPreference(var Enabled: Boolean): Boolean;
var
  PreviousDirectory, Command: String;
begin
  { Use this AppId's installed path, even when the new destination changes. }
  Result := RegQueryStringValue(HKCU, MorseWriterUninstallKey,
    'Inno Setup: App Path', PreviousDirectory);
  if not Result or (PreviousDirectory = '') then begin
    Result := False;
    Exit;
  end;
  Enabled := RegQueryStringValue(HKCU, MorseWriterRunKey, 'MorseWriter', Command) and
    (CompareText(Trim(Command), '"' + AddBackslash(PreviousDirectory) +
      '{#MyAppExeName}" --startup') = 0);
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Enabled: Boolean;
begin
  { Task controls are created on this page, including in silent installs.
    Apply once so Back/Next never discards the user's current checkbox choice. }
  if (CurPageID <> wpSelectTasks) or StartupDefaultApplied then
    Exit;
  StartupDefaultApplied := True;
  if HasExplicitStartupChoice then
    Exit;
  if ReadPreviousStartupPreference(Enabled) then begin
    if Enabled then
      WizardSelectTasks('autostart')
    else
      WizardSelectTasks('!autostart');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'MorseWriter');
end;
