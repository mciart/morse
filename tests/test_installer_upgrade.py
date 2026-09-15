"""Compile and exercise the installer's actual Pascal upgrade policy safely.

The probe substitutes registry reads and wizard selections, then aborts from
InitializeSetup before installation. It never writes the registry or runs the
real install/uninstall sections.
"""

from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


PROJECT = Path(__file__).resolve().parents[1]
COMPILER = PROJECT / 'build/tools/inno-setup-6.7.3/ISCC.exe'


MOCKS = r'''
  TestPreviousDirectory, TestRunCommand: String;
  TestHasRunValue, TestAutostart, TestDesktop: Boolean;
  TestArguments: TArrayOfString;

function MockParamCount: Integer;
begin
  Result := GetArrayLength(TestArguments);
end;

function MockParamStr(Index: Integer): String;
begin
  Result := TestArguments[Index - 1];
end;

function MockReadRegistry(RootKey: Integer; const Subkey, Name: String;
  var Value: String): Boolean;
begin
  if RootKey <> HKCU then
    RaiseException('Unexpected registry hive');
  if (Subkey = MorseWriterUninstallKey) and (Name = 'Inno Setup: App Path') then begin
    Value := TestPreviousDirectory;
    Result := Value <> '';
  end else if (Subkey = MorseWriterRunKey) and (Name = 'MorseWriter') then begin
    Value := TestRunCommand;
    Result := TestHasRunValue;
  end else
    RaiseException('Unexpected registry value');
end;

procedure MockSelectTasks(const Tasks: String);
begin
  if Tasks = 'autostart' then
    TestAutostart := True
  else if Tasks = '!autostart' then
    TestAutostart := False
  else
    RaiseException('Unexpected task mutation');
end;
'''


CASES = r'''
procedure Check(Condition: Boolean; const Name: String);
begin
  if not Condition then
    RaiseException(Name);
end;

procedure PolicyCase(const Name, Directory, Command, Parameter: String;
  HasRunValue, InitiallySelected, DesktopSelected, Expected: Boolean);
begin
  StartupDefaultApplied := False;
  TestPreviousDirectory := Directory;
  TestRunCommand := Command;
  TestHasRunValue := HasRunValue;
  TestAutostart := InitiallySelected;
  TestDesktop := DesktopSelected;
  SetArrayLength(TestArguments, 0);
  if Parameter <> '' then begin
    SetArrayLength(TestArguments, 1);
    TestArguments[0] := Parameter;
  end;
  CurPageChanged(wpWelcome);
  Check(TestAutostart = InitiallySelected, Name + ': changed before task page');
  CurPageChanged(wpSelectTasks);
  Check(TestAutostart = Expected, Name + ': incorrect startup default');
  Check(TestDesktop = DesktopSelected, Name + ': desktop preference changed');
  TestAutostart := not Expected;
  CurPageChanged(wpSelectTasks);
  Check(TestAutostart = not Expected, Name + ': overwrote user Back/Next choice');
end;

function InitializeSetup: Boolean;
var
  Directory, Command: String;
begin
  Directory := 'C:\Old Location\MorseWriter';
  Command := '"' + Directory + '\MorseWriter.exe" --startup';
  PolicyCase('fresh install', '', '', '', False, False, True, False);
  PolicyCase('enabled after prior installation', Directory, Command, '', True, False, True, True);
  PolicyCase('disabled after prior installation', Directory, '', '', False, True, False, False);
  PolicyCase('path case and trailing slash', Directory + '\', Lowercase(Command), '', True, False, False, True);
  PolicyCase('different executable', Directory, '"C:\Other\Other.exe"', '', True, True, True, False);
  PolicyCase('explicit all tasks enable', Directory, '', '/TASKS=autostart', False, True, False, True);
  PolicyCase('explicit all tasks disable', Directory, Command, '/TASKS=', True, False, True, False);
  PolicyCase('explicit merge enable', Directory, '', '/MERGETASKS=autostart', False, True, True, True);
  PolicyCase('explicit merge disable', Directory, Command, '/MERGETASKS="desktopicon, !autostart"', True, False, True, False);
  PolicyCase('merge unrelated task', Directory, Command, '/MERGETASKS=desktopicon', True, False, True, True);
  PolicyCase('similar task name', Directory, Command, '/MERGETASKS=autostart-extra', True, False, False, True);
  PolicyCase('explicit saved preferences', Directory, Command, '/LOADINF=settings.inf', True, False, False, False);
  Check(ParameterSetsStartup('/mergetasks=*AUTOSTART'), 'Case-insensitive wildcard task');
  Check(not ParameterSetsStartup('/DIR=C:\autostart'), 'Unrelated command parameter');
  SaveStringToFile(ExpandConstant('{src}\policy-report.txt'), 'ok: 14 policy cases', False);
  Result := False;
end;
'''


class InstallerUpgradeTests(unittest.TestCase):
    def test_retired_bundle_cleanup_cannot_target_personal_data(self):
        text = (PROJECT / 'MorseWriterInstaller.iss').read_text(encoding='utf-8')
        section = text.split('[InstallDelete]', 1)[1].split('[Icons]', 1)[0]
        targets = re.findall(r'Type: files; Name: "([^"]+)"', section)
        self.assertEqual(set(targets), {
            r'{userstartup}\MorseWriter.lnk',
            r'{app}\_internal\defaults\morsewriter.sqlite',
            r'{app}\_internal\res\morsewriter_pressagio.ini',
        })
        self.assertNotIn('filesandordirs', section)
        self.assertNotIn('*', section)

    def test_installer_uses_mutex_shell_launch_and_file_metadata(self):
        from windows_integration import INSTANCE_ID
        text = (PROJECT / 'MorseWriterInstaller.iss').read_text(encoding='utf-8')
        self.assertIn('AppMutex=' + INSTANCE_ID, text)
        self.assertIn('Parameters: "--from-installer"', text)
        self.assertRegex(text, r'Flags: postinstall nowait skipifsilent shellexec')
        self.assertIn('VersionInfoCompany=mciart', text)
        self.assertIn('VersionInfoProductName=摩斯输入', text)

    @unittest.skipUnless(sys.platform == 'win32' and COMPILER.is_file(),
                         'Requires the bundled Inno Setup compiler')
    def test_actual_pascal_policy_preserves_current_and_explicit_preferences(self):
        source = (PROJECT / 'MorseWriterInstaller.iss').read_text(encoding='utf-8')
        code = source.split('[Code]', 1)[1]
        for original, mock in (('ParamCount', 'MockParamCount'), ('ParamStr', 'MockParamStr'),
                               ('RegQueryStringValue', 'MockReadRegistry'),
                               ('WizardSelectTasks', 'MockSelectTasks')):
            code = re.sub(r'\b' + original + r'\b', mock, code)
        code = code.replace('function ParameterSetsStartup', MOCKS + '\nfunction ParameterSetsStartup', 1)
        header = '''#define MyAppExeName "MorseWriter.exe"
[Setup]
AppId=MorseWriterPolicyProbe
AppName=Policy probe
AppVersion=0.0.0
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
DisableStartupPrompt=yes
OutputDir=.
OutputBaseFilename=policy-probe
[Code]
'''
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            script = directory / 'policy-probe.iss'
            script.write_text(header + code + CASES, encoding='utf-8-sig')
            compiled = subprocess.run([str(COMPILER), '/Q', str(script)], capture_output=True,
                                      timeout=60, startupinfo=startup)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(directory / 'policy-probe.exe'), '/VERYSILENT',
                                     '/SUPPRESSMSGBOXES', '/NORESTART'], capture_output=True,
                                    timeout=30, startupinfo=startup)
            self.assertEqual(result.returncode, 1, 'Probe must abort before installation')
            self.assertEqual((directory / 'policy-report.txt').read_text(), 'ok: 14 policy cases')
