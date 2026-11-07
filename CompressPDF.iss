; A new identity and directory isolate this app from legacy recursive uninstall logs.
#define PayloadVersion GetEnv("QCOMPRESSPDF_VERSION")
#if PayloadVersion == ""
  #undef PayloadVersion
  #define PayloadVersion "1.6.0"
#endif
[Setup]
AppId=QCompressPDF.Bundled
AppName=QCompressPDF
AppVersion={#PayloadVersion}
DefaultDirName={localappdata}\Programs\QCompressPDF
DefaultGroupName=QCompressPDF
OutputBaseFilename=QCompressPDF
Compression=lzma2
SolidCompression=yes
SetupIconFile=pdf.ico
UninstallDisplayIcon={app}\versions\{#PayloadVersion}\QCompressPDF.exe
UninstallDisplayName=QCompressPDF
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
AppMutex=QCompressPDF.App
CloseApplications=no
RestartApplications=no

[Files]
Source: "scripts\validate_payload.ps1"; Flags: dontcopy
Source: "dist\QCompressPDF\*"; Excludes: "QCompressPDF.exe"; DestDir: "{app}\versions\{#PayloadVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Validate the complete payload before Inno writes shortcuts or registry entries.
Source: "dist\QCompressPDF\QCompressPDF.exe"; DestDir: "{app}\versions\{#PayloadVersion}"; Flags: ignoreversion; AfterInstall: ValidatePayload

[Registry]
; The old uninstall log owns CompressPDF. It must never own these new entries.
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QCompressPDF"; ValueType: string; ValueName: ""; ValueData: "Compress PDF (QCompressPDF)"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QCompressPDF"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\versions\{#PayloadVersion}\QCompressPDF.exe"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\QCompressPDF\command"; ValueType: string; ValueName: ""; ValueData: """{app}\versions\{#PayloadVersion}\QCompressPDF.exe"" ""%1"""; Flags: uninsdeletekey
; Hide the old context command without deleting it or requiring elevation.
; Removing the new app re-enables the old command if the old installation remains.
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: "LegacyDisable"; ValueData: ""; Flags: uninsdeletevalue; Check: HasLegacyMenu

[Icons]
Name: "{userprograms}\QCompressPDF"; Filename: "{app}\versions\{#PayloadVersion}\QCompressPDF.exe"; WorkingDir: "{app}"

[Code]
const
  LegacyUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Compress PDF_is1';
  LegacyMenuKey = 'Software\Classes\SystemFileAssociations\.pdf\shell\CompressPDF';

function HasLegacyMenu(): Boolean;
begin
  Result := RegKeyExists(HKCU, LegacyMenuKey) or RegKeyExists(HKLM, LegacyMenuKey);
end;

function InsideDirectory(const Child, Parent: String): Boolean;
var
  FullChild, FullParent: String;
begin
  Result := False;
  if Parent = '' then Exit;
  FullChild := AddBackslash(ExpandFileName(Child));
  FullParent := AddBackslash(ExpandFileName(Parent));
  Result := CompareText(Copy(FullChild, 1, Length(FullParent)), FullParent) = 0;
end;

function UsesLegacyDirectory(const Target: String; Root: Integer): Boolean;
var
  LegacyDir: String;
begin
  Result := False;
  if RegQueryStringValue(Root, LegacyUninstallKey, 'InstallLocation', LegacyDir) or
     RegQueryStringValue(Root, LegacyUninstallKey, 'Inno Setup: App Path', LegacyDir) then
    Result := InsideDirectory(Target, LegacyDir);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Candidate, Parent: String;
begin
  Result := '';
  Candidate := WizardDirValue;
  if InsideDirectory(Candidate, ExpandConstant('{userappdata}\CompressPDF')) or
     UsesLegacyDirectory(Candidate, HKCU) or UsesLegacyDirectory(Candidate, HKLM32) or
     UsesLegacyDirectory(Candidate, HKLM64) then
  begin
    Result := 'Choose a separate directory for QCompressPDF. The old Compress PDF uninstaller can delete its entire directory. The recommended location is ' + ExpandConstant('{localappdata}\Programs\QCompressPDF') + '.';
    Exit;
  end;
  // Also protect custom/unregistered legacy directories and their descendants.
  while Candidate <> '' do
  begin
    if FileExists(AddBackslash(Candidate) + 'compress_qt.pyw') then
    begin
      Result := 'This directory belongs to a legacy Compress PDF installation. Choose the recommended QCompressPDF directory instead.';
      Exit;
    end;
    Parent := ExtractFileDir(RemoveBackslashUnlessRoot(Candidate));
    if CompareText(Parent, Candidate) = 0 then Break;
    Candidate := Parent;
  end;
end;

procedure ValidatePayload();
var
  Code: Integer;
  Exe, Params: String;
begin
  Exe := ExpandConstant('{app}\versions\{#PayloadVersion}\QCompressPDF.exe');
  Log('Validating bundled Python, Qt and Ghostscript before activating this release.');
  ExtractTemporaryFile('validate_payload.ps1');
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' +
    AddQuotes(ExpandConstant('{tmp}\validate_payload.ps1')) + ' -Executable ' + AddQuotes(Exe);
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    RaiseException('The bundled application could not start. Installation has not activated the new release.');
  if Code <> 0 then
    RaiseException('The bundled application failed its self-test. Installation has not activated the new release.');
end;

function LegacyUninstaller(Root: Integer): String;
var
  Command, InstallDir: String;
begin
  Result := '';
  if not RegQueryStringValue(Root, LegacyUninstallKey, 'UninstallString', Command) then Exit;
  if not RegQueryStringValue(Root, LegacyUninstallKey, 'InstallLocation', InstallDir) then
    if not RegQueryStringValue(Root, LegacyUninstallKey, 'Inno Setup: App Path', InstallDir) then Exit;
  Command := RemoveQuotes(Trim(Command));
  // Launch only the registered Inno executable, not arbitrary command arguments.
  if FileExists(Command) and InsideDirectory(Command, InstallDir) and
     (CompareText(ExtractFileExt(Command), '.exe') = 0) and
     (CompareText(Copy(ExtractFileName(Command), 1, 5), 'unins') = 0) and
     (not InsideDirectory(WizardDirValue, InstallDir)) then Result := Command;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Uninstaller, Verb: String;
  ErrorCode: Integer;
begin
  if (CurStep <> ssDone) or WizardSilent then Exit;
  Uninstaller := LegacyUninstaller(HKCU);
  Verb := 'open';
  if Uninstaller = '' then
  begin
    Uninstaller := LegacyUninstaller(HKLM64);
    if Uninstaller = '' then Uninstaller := LegacyUninstaller(HKLM32);
    Verb := 'runas';
  end;
  if Uninstaller = '' then Exit;
  if MsgBox('QCompressPDF is installed and has passed its self-test.' + #13#10 + #13#10 +
    'Remove the legacy Compress PDF installation now?' + #13#10 +
    ExtractFileDir(Uninstaller) + #13#10 + #13#10 +
    'Its uninstaller may delete everything in that old folder. Move any personal files out first. The new QCompressPDF installation is separate.' + #13#10 + #13#10 +
    'Choose No to keep the legacy version for now.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    if not ShellExec(Verb, Uninstaller, '', ExtractFileDir(Uninstaller), SW_SHOWNORMAL, ewNoWait, ErrorCode) then
      MsgBox('The legacy uninstaller could not be opened. You can remove Compress PDF later from Windows Installed apps. QCompressPDF remains installed.', mbInformation, MB_OK);
end;
