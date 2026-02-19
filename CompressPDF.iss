; -- CompressPDF.iss --
[Setup]
AppName=Compress PDF
AppVersion=1.4.0
DefaultDirName={userappdata}\CompressPDF
DefaultGroupName=Compress PDF
OutputBaseFilename=QCompressPDF
Compression=lzma
SolidCompression=yes
SetupIconFile=pdf.ico
UninstallDisplayIcon={app}\pdf.ico
UninstallDisplayName=Compress PDF
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousPrivileges=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
; Rename compress_qt.py to compress_qt.pyw on install
Source: "compress_qt.py"; DestName: "compress_qt.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "pdf.ico"; DestDir: "{app}"; Flags: ignoreversion
; Keep requirements embedded for bootstrap (do not install it as an app file)
Source: "requirements.txt"; DestDir: "{tmp}"; Flags: dontcopy

[Registry]
; Add context menu for PDF files
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: ""; ValueData: "Compress PDF (QCompressPDF)"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\pdf.ico"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\CompressPDF\command"; ValueType: string; ValueName: ""; ValueData: """{code:GetVenvPythonwExePath}"" ""{app}\compress_qt.pyw"" ""%1"""; Flags: uninsdeletekey

; Migration/cleanup: remove legacy machine-wide key if we're elevated (old versions wrote to HKCR while elevated)
Root: HKLM; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\CompressPDF"; Flags: deletekey; Check: IsAdminInstallMode

[Icons]
Name: "{userprograms}\Compress PDF (QCompressPDF)"; Filename: "{code:GetVenvPythonwExePath}"; Parameters: """{app}\compress_qt.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\pdf.ico"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  BootstrapPage: TWizardPage;
  DebugLoggingCheckBox: TCheckBox;
  LogMemo: TNewMemo;
  EnableDebugLogging: Boolean;
  LogFilePath: String;
  BootstrapCompleted: Boolean;
  BootstrapSucceeded: Boolean;
  BootstrapRunning: Boolean;

const
  PrivatePythonVersion = '3.13.5';
  PrivatePythonInstallerUrl = 'https://www.python.org/ftp/python/' + PrivatePythonVersion + '/python-' + PrivatePythonVersion + '-amd64.exe';
  GhostscriptInstallerUrl = 'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/gs10051w64.exe';
  GhostscriptMinBytes = 1000000;
  PythonMinBytes = 20000000;

  PrivatePythonDirName = 'python';
  VenvDirName = 'venv';
  VenvPythonVersionMarkerRelPath = VenvDirName + '\.qcompresspdf_python_version';

function Quote(const S: String): String;
begin
  Result := '"' + S + '"';
end;

procedure AppendLogLine(const Message: String);
begin
  if LogFilePath = '' then
    Exit;
  ForceDirectories(ExtractFileDir(LogFilePath));
  SaveStringToFile(LogFilePath,
    GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + ' - ' + Message + #13#10,
    True);
  if EnableDebugLogging then
    Log('DEBUG: ' + Message);
end;

procedure RefreshLogMemo();
var
  S: String;
begin
  if (LogMemo = nil) or (LogFilePath = '') then
    Exit;
  if LoadStringFromFile(LogFilePath, S) then
  begin
    LogMemo.Text := S;
    LogMemo.SelStart := Length(LogMemo.Text);
  end;
end;

function ExecLogged(const ExePath, Params, WorkDir, StepName: String; var ResultCode: Integer): Boolean;
var
  CmdParams: String;
begin
  AppendLogLine('--- ' + StepName + ' ---');
  AppendLogLine('Running: ' + ExePath + ' ' + Params);

  CmdParams := '/S /C ' + Quote(Quote(ExePath) + ' ' + Params + ' >> ' + Quote(LogFilePath) + ' 2>&1');
  Result := Exec('cmd.exe', CmdParams, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if not Result then
    AppendLogLine('Failed to start process for: ' + StepName)
  else
    AppendLogLine('Exit code: ' + IntToStr(ResultCode));

  RefreshLogMemo();
end;

procedure EnsureDownloadScript();
var
  ScriptPath: String;
  Script: String;
begin
  ScriptPath := ExpandConstant('{tmp}\\qcompresspdf_download.ps1');
  if FileExists(ScriptPath) then
    Exit;

  Script :=
    'param(' + #13#10 +
    '  [Parameter(Mandatory=$true)][string]$Url,' + #13#10 +
    '  [Parameter(Mandatory=$true)][string]$OutFile,' + #13#10 +
    '  [int]$Retries = 3,' + #13#10 +
    '  [int]$MinBytes = 1' + #13#10 +
    ')' + #13#10 +
    '$ErrorActionPreference = "Stop"' + #13#10 +
    '[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12' + #13#10 +
    'for ($i = 1; $i -le $Retries; $i++) {' + #13#10 +
    '  try {' + #13#10 +
    '    Write-Host "Downloading $Url -> $OutFile (attempt $i/$Retries)"' + #13#10 +
    '    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing' + #13#10 +
    '    $len = (Get-Item $OutFile).Length' + #13#10 +
    '    if ($len -lt $MinBytes) { throw "Downloaded file too small: $len bytes" }' + #13#10 +
    '    exit 0' + #13#10 +
    '  } catch {' + #13#10 +
    '    Write-Host "Download failed: $($_.Exception.Message)"' + #13#10 +
    '    if ($i -eq $Retries) { throw }' + #13#10 +
    '    Start-Sleep -Seconds ([Math]::Min(30, 2 * $i))' + #13#10 +
    '  }' + #13#10 +
    '}' + #13#10;

  SaveStringToFile(ScriptPath, Script, False);
end;

function DownloadWithRetry(const Url, DestFile, FriendlyName: String; MinBytes: Integer): Boolean;
var
  Ps1Path: String;
  ResultCode: Integer;
  Params: String;
begin
  EnsureDownloadScript();
  Ps1Path := ExpandConstant('{tmp}\\qcompresspdf_download.ps1');
  Params :=
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' + Quote(Ps1Path) +
    ' -Url ' + Quote(Url) +
    ' -OutFile ' + Quote(DestFile) +
    ' -Retries 3 -MinBytes ' + IntToStr(MinBytes);

  Result := ExecLogged('powershell.exe', Params, ExpandConstant('{tmp}'), 'Download ' + FriendlyName, ResultCode) and (ResultCode = 0) and FileExists(DestFile);
end;

function PrivatePythonBaseDir(): String;
begin
  Result := AddBackslash(WizardDirValue) + PrivatePythonDirName;
end;

function PrivatePythonExe(): String;
begin
  Result := AddBackslash(PrivatePythonBaseDir()) + 'python.exe';
end;

function PrivatePythonwExe(): String;
begin
  Result := AddBackslash(PrivatePythonBaseDir()) + 'pythonw.exe';
end;

function VenvBaseDir(): String;
begin
  Result := AddBackslash(WizardDirValue) + VenvDirName;
end;

function VenvPythonExe(): String;
begin
  Result := AddBackslash(VenvBaseDir()) + 'Scripts\\python.exe';
end;

function VenvPythonwExe(): String;
begin
  Result := AddBackslash(VenvBaseDir()) + 'Scripts\\pythonw.exe';
end;

function IsPythonFunctional(const PythonExePath: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if not FileExists(PythonExePath) then
    Exit;

  if Exec(PythonExePath, '-c "import sys, venv, ensurepip; print(sys.executable)"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := (ResultCode = 0);
end;

function ReadTextFileOrEmpty(const Path: String): String;
var
  S: String;
begin
  if LoadStringFromFile(Path, S) then
    Result := Trim(S)
  else
    Result := '';
end;

procedure WriteTextFile(const Path, Content: String);
begin
  ForceDirectories(ExtractFileDir(Path));
  SaveStringToFile(Path, Content + #13#10, False);
end;

function EnsurePrivatePythonInstalled(): Boolean;
var
  InstallerPath: String;
  ResultCode: Integer;
  Params: String;
  MarkerPath: String;
begin
  Result := False;

  if IsPythonFunctional(PrivatePythonExe()) and FileExists(PrivatePythonwExe()) then
  begin
    AppendLogLine('Private Python already installed and functional: ' + PrivatePythonExe());
    Result := True;
    Exit;
  end;

  AppendLogLine('Installing private Python into: ' + PrivatePythonBaseDir());
  ForceDirectories(PrivatePythonBaseDir());

  InstallerPath := ExpandConstant('{tmp}\\python-installer.exe');
  if FileExists(InstallerPath) then
    DeleteFile(InstallerPath);

  if not DownloadWithRetry(PrivatePythonInstallerUrl, InstallerPath, 'Python ' + PrivatePythonVersion, PythonMinBytes) then
  begin
    AppendLogLine('Python download failed.');
    Exit;
  end;

  Params :=
    '/quiet InstallAllUsers=0 PrependPath=0 Include_pip=1 Include_launcher=0 Include_test=0 SimpleInstall=1 TargetDir=' + Quote(PrivatePythonBaseDir());

  if not ExecLogged(InstallerPath, Params, ExpandConstant('{tmp}'), 'Install Python ' + PrivatePythonVersion, ResultCode) then
    Exit;
  if ResultCode <> 0 then
    Exit;

  if not (IsPythonFunctional(PrivatePythonExe()) and FileExists(PrivatePythonwExe())) then
  begin
    AppendLogLine('Python installation completed but validation failed.');
    Exit;
  end;

  MarkerPath := AddBackslash(PrivatePythonBaseDir()) + '.qcompresspdf_python_version';
  WriteTextFile(MarkerPath, PrivatePythonVersion);

  AppendLogLine('Private Python installed and validated.');
  Result := True;
end;

function EnsureVenvAndRequirementsInstalled(): Boolean;
var
  ReqPath: String;
  ResultCode: Integer;
  MarkerPath: String;
  ExistingVersion: String;
  NeedsRecreate: Boolean;
begin
  Result := False;

  ReqPath := ExpandConstant('{tmp}\\requirements.txt');
  ExtractTemporaryFile('requirements.txt');

  MarkerPath := AddBackslash(WizardDirValue) + VenvPythonVersionMarkerRelPath;
  ExistingVersion := ReadTextFileOrEmpty(MarkerPath);
  NeedsRecreate := False;

  if not FileExists(VenvPythonExe()) then
    NeedsRecreate := True
  else if not IsPythonFunctional(VenvPythonExe()) then
    NeedsRecreate := True
  else if ExistingVersion <> PrivatePythonVersion then
    NeedsRecreate := True;

  if NeedsRecreate then
  begin
    if DirExists(VenvBaseDir()) then
    begin
      AppendLogLine('Removing existing venv: ' + VenvBaseDir());
      DelTree(VenvBaseDir(), True, True, True);
    end;

    AppendLogLine('Creating venv: ' + VenvBaseDir());
    if not ExecLogged(PrivatePythonExe(), '-m venv --upgrade-deps ' + Quote(VenvBaseDir()), WizardDirValue, 'Create venv', ResultCode) then
      Exit;
    if ResultCode <> 0 then
      Exit;
  end
  else
  begin
    AppendLogLine('Reusing existing venv: ' + VenvBaseDir());
  end;

  // Ensure pip is present and reasonably up-to-date
  if not ExecLogged(VenvPythonExe(), '-m pip install --upgrade pip --disable-pip-version-check --progress-bar off', WizardDirValue, 'Upgrade pip (venv)', ResultCode) then
    Exit;
  if ResultCode <> 0 then
    Exit;

  // Install requirements (retry once for flaky networks)
  if not ExecLogged(VenvPythonExe(), '-m pip install -r ' + Quote(ReqPath) + ' --disable-pip-version-check --progress-bar off', WizardDirValue, 'Install requirements (attempt 1)', ResultCode) then
    Exit;
  if ResultCode <> 0 then
  begin
    AppendLogLine('Requirements install failed, retrying once...');
    if not ExecLogged(VenvPythonExe(), '-m pip install -r ' + Quote(ReqPath) + ' --disable-pip-version-check --progress-bar off', WizardDirValue, 'Install requirements (attempt 2)', ResultCode) then
      Exit;
    if ResultCode <> 0 then
      Exit;
  end;

  // Validate key imports
  if not ExecLogged(VenvPythonExe(), '-c "import PySide6, PyPDF2; print(\"Imports OK\")"', WizardDirValue, 'Validate Python imports', ResultCode) then
    Exit;
  if ResultCode <> 0 then
    Exit;

  if not FileExists(VenvPythonwExe()) then
  begin
    AppendLogLine('venv pythonw.exe not found: ' + VenvPythonwExe());
    Exit;
  end;

  WriteTextFile(MarkerPath, PrivatePythonVersion);
  AppendLogLine('venv ready.');
  Result := True;
end;

function FindOnPath(const FileName: String): String;
var
  PathEnv: String;
  I: Integer;
  Parts: TArrayOfString;
  Candidate: String;
begin
  Result := '';
  PathEnv := GetEnv('PATH');
  if PathEnv = '' then
    Exit;
  Parts := SplitString(PathEnv, ';');
  for I := 0 to GetArrayLength(Parts) - 1 do
  begin
    Candidate := AddBackslash(Trim(Parts[I])) + FileName;
    if FileExists(Candidate) then
    begin
      Result := Candidate;
      Exit;
    end;
  end;
end;

function IsGhostscriptAvailable(): Boolean;
var
  Subkeys: TArrayOfString;
  I: Integer;
  GsDll: String;
begin
  Result := False;
  if FindOnPath('gswin64c.exe') <> '' then
    Result := True
  else if FindOnPath('gswin32c.exe') <> '' then
    Result := True
  else
  begin
    // Registry installs typically store values under version subkeys
    if RegGetSubkeyNames(HKLM, 'SOFTWARE\\GPL Ghostscript', Subkeys) then
    begin
      for I := 0 to GetArrayLength(Subkeys) - 1 do
      begin
        if RegQueryStringValue(HKLM, 'SOFTWARE\\GPL Ghostscript\\' + Subkeys[I], 'GS_DLL', GsDll) then
        begin
          if FileExists(GsDll) then
          begin
            Result := True;
            Exit;
          end;
        end;
      end;
    end;

    if RegGetSubkeyNames(HKLM, 'SOFTWARE\\WOW6432Node\\GPL Ghostscript', Subkeys) then
    begin
      for I := 0 to GetArrayLength(Subkeys) - 1 do
      begin
        if RegQueryStringValue(HKLM, 'SOFTWARE\\WOW6432Node\\GPL Ghostscript\\' + Subkeys[I], 'GS_DLL', GsDll) then
        begin
          if FileExists(GsDll) then
          begin
            Result := True;
            Exit;
          end;
        end;
      end;
    end;
  end;
  else if FileExists(ExpandConstant('{autopf}\\gs\\gs10.05.1\\bin\\gswin64c.exe')) then
    Result := True
  else if FileExists(ExpandConstant('{autopf}\\gs\\gs10.05.1\\bin\\gswin32c.exe')) then
    Result := True;
end;

function EnsureGhostscriptInstalled(): Boolean;
var
  InstallerPath: String;
  ResultCode: Integer;
begin
  Result := False;

  if IsGhostscriptAvailable() then
  begin
    AppendLogLine('Ghostscript detected.');
    Result := True;
    Exit;
  end;

  if not IsAdminInstallMode() then
  begin
    AppendLogLine('Ghostscript not found and installer is not elevated.');
    AppendLogLine('Please install Ghostscript manually or rerun this installer as Administrator.');
    Exit;
  end;

  InstallerPath := ExpandConstant('{tmp}\\gs-installer.exe');
  if FileExists(InstallerPath) then
    DeleteFile(InstallerPath);

  if not DownloadWithRetry(GhostscriptInstallerUrl, InstallerPath, 'Ghostscript', GhostscriptMinBytes) then
  begin
    AppendLogLine('Ghostscript download failed.');
    Exit;
  end;

  if not ExecLogged(InstallerPath, '/S', ExpandConstant('{tmp}'), 'Install Ghostscript', ResultCode) then
    Exit;
  if ResultCode <> 0 then
    Exit;

  if not IsGhostscriptAvailable() then
  begin
    AppendLogLine('Ghostscript installation completed but was not detected afterwards.');
    Exit;
  end;

  AppendLogLine('Ghostscript installed and detected.');
  Result := True;
end;

function NeedsBootstrap(): Boolean;
var
  MarkerPath: String;
  ExistingVersion: String;
  ResultCode: Integer;
begin
  // We bootstrap if private python/venv is missing, version marker mismatches, or required imports fail.
  Result := True;

  if not (IsPythonFunctional(PrivatePythonExe()) and FileExists(PrivatePythonwExe())) then
    Exit;
  if not (IsPythonFunctional(VenvPythonExe()) and FileExists(VenvPythonwExe())) then
    Exit;

  MarkerPath := AddBackslash(WizardDirValue) + VenvPythonVersionMarkerRelPath;
  ExistingVersion := ReadTextFileOrEmpty(MarkerPath);
  if ExistingVersion <> PrivatePythonVersion then
    Exit;

  if not IsGhostscriptAvailable() then
    Exit;

  // Validate key imports quickly
  if Exec(VenvPythonExe(), '-c "import PySide6, PyPDF2"', WizardDirValue, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := (ResultCode <> 0)
  else
    Result := True;
end;

procedure InitializeWizard();
var
  DownloadLabel: TLabel;
  DebugLoggingLabel: TLabel;
begin
  EnableDebugLogging := True;
  BootstrapCompleted := False;
  BootstrapSucceeded := False;
  BootstrapRunning := False;
  LogFilePath := '';

  BootstrapPage := CreateCustomPage(wpReady, 'Dependency Setup', 'Downloading and configuring private Python environment');

  DownloadLabel := TLabel.Create(BootstrapPage);
  DownloadLabel.Caption :=
    'QCompressPDF will set up a private Python runtime and a virtual environment in the install folder.' + #13#10 +
    'Command output will be shown below. If something fails, the log will help troubleshooting.';
  DownloadLabel.WordWrap := True;
  DownloadLabel.Top := 16;
  DownloadLabel.Left := 0;
  DownloadLabel.Width := BootstrapPage.SurfaceWidth;
  DownloadLabel.Parent := BootstrapPage.Surface;

  DebugLoggingCheckBox := TCheckBox.Create(BootstrapPage);
  DebugLoggingCheckBox.Caption := 'Enable extra debug logging';
  DebugLoggingCheckBox.Top := DownloadLabel.Top + DownloadLabel.Height + 8;
  DebugLoggingCheckBox.Left := 0;
  DebugLoggingCheckBox.Width := BootstrapPage.SurfaceWidth;
  DebugLoggingCheckBox.Parent := BootstrapPage.Surface;
  DebugLoggingCheckBox.Checked := True;

  DebugLoggingLabel := TLabel.Create(BootstrapPage);
  DebugLoggingLabel.Caption := 'Log file: (set when this page opens)';
  DebugLoggingLabel.WordWrap := True;
  DebugLoggingLabel.Top := DebugLoggingCheckBox.Top + 22;
  DebugLoggingLabel.Left := 20;
  DebugLoggingLabel.Width := BootstrapPage.SurfaceWidth - 20;
  DebugLoggingLabel.Font.Color := clGray;
  DebugLoggingLabel.Font.Size := 7;
  DebugLoggingLabel.Parent := BootstrapPage.Surface;

  LogMemo := TNewMemo.Create(BootstrapPage);
  LogMemo.Parent := BootstrapPage.Surface;
  LogMemo.Left := 0;
  LogMemo.Top := DebugLoggingLabel.Top + 18;
  LogMemo.Width := BootstrapPage.SurfaceWidth;
  LogMemo.Height := BootstrapPage.SurfaceHeight - LogMemo.Top;
  LogMemo.ScrollBars := ssVertical;
  LogMemo.ReadOnly := True;
  LogMemo.WordWrap := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  if (BootstrapPage <> nil) and (PageID = BootstrapPage.ID) and (not NeedsBootstrap()) then
    Result := True
  else
    Result := False;
end;

procedure RunBootstrap();
var
  LegacyKeyExists: Boolean;
begin
  if BootstrapRunning or BootstrapCompleted then
    Exit;

  BootstrapRunning := True;
  EnableDebugLogging := DebugLoggingCheckBox.Checked;

  ForceDirectories(WizardDirValue);
  LogFilePath := AddBackslash(WizardDirValue) + 'install_debug.log';
  DeleteFile(LogFilePath);
  AppendLogLine('=== QCompressPDF dependency bootstrap started ===');
  AppendLogLine('Install directory: ' + WizardDirValue);
  AppendLogLine('Pinned Python version: ' + PrivatePythonVersion);
  if not IsAdminInstallMode() then
    AppendLogLine('Installer running without elevation (per-user mode).');

  BootstrapSucceeded := EnsurePrivatePythonInstalled() and EnsureVenvAndRequirementsInstalled() and EnsureGhostscriptInstalled();
  RefreshLogMemo();

  if BootstrapSucceeded then
  begin
    AppendLogLine('=== Bootstrap finished: OK ===');
    BootstrapCompleted := True;
  end
  else
  begin
    AppendLogLine('=== Bootstrap finished: FAILED ===');
    BootstrapCompleted := True;
  end;

  // If the user is not elevated and a legacy machine-wide key exists, warn after bootstrap.
  if not IsAdminInstallMode() then
  begin
    LegacyKeyExists := RegKeyExists(HKLM, 'Software\\Classes\\SystemFileAssociations\\.pdf\\shell\\CompressPDF');
    if LegacyKeyExists then
      AppendLogLine('NOTE: A legacy machine-wide context-menu entry exists (from older admin installs). To remove it, rerun this installer as Administrator.');
  end;

  RefreshLogMemo();

  WizardForm.BackButton.Enabled := True;
  WizardForm.CancelButton.Enabled := True;
  WizardForm.NextButton.Enabled := BootstrapSucceeded;

  if not BootstrapSucceeded then
    MsgBox('Dependency setup failed.' + #13#10 + #13#10 +
      'Log file: ' + LogFilePath + #13#10 +
      'Please review the embedded output for details.' + #13#10 + #13#10 +
      'Common causes: blocked downloads (proxy/firewall), missing admin rights for Ghostscript, or network issues.',
      mbError, MB_OK);

  BootstrapRunning := False;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (BootstrapPage <> nil) and (CurPageID = BootstrapPage.ID) then
  begin
    LogFilePath := AddBackslash(WizardDirValue) + 'install_debug.log';
    if LogMemo <> nil then
      LogMemo.Text := '';
    WizardForm.NextButton.Enabled := False;
    WizardForm.BackButton.Enabled := False;
    WizardForm.CancelButton.Enabled := True;
    RunBootstrap();
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (BootstrapPage <> nil) and (CurPageID = BootstrapPage.ID) then
  begin
    // Prevent continuing if bootstrap failed
    if not BootstrapSucceeded then
      Result := False;
  end;
end;

function GetVenvPythonwExePath(Param: String): String;
begin
  if FileExists(VenvPythonwExe()) then
    Result := VenvPythonwExe()
  else if FileExists(PrivatePythonwExe()) then
    Result := PrivatePythonwExe()
  else
    Result := 'pythonw.exe';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Post-install: if we are not elevated and a legacy machine-wide key remains, notify clearly.
  if CurStep = ssPostInstall then
  begin
    if (not IsAdminInstallMode()) and RegKeyExists(HKLM, 'Software\\Classes\\SystemFileAssociations\\.pdf\\shell\\CompressPDF') then
      MsgBox('A legacy machine-wide context-menu entry from an older installation is still present.' + #13#10 + #13#10 +
        'This installer now uses a per-user context-menu entry. If you see duplicate or broken menu items, rerun this installer as Administrator once to clean up the old machine-wide key.',
        mbInformation, MB_OK);
  end;
end;
