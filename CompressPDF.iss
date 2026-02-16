; -- CompressPDF.iss --
[Setup]
AppName=Compress PDF
AppVersion=1.2.0
DefaultDirName={userappdata}\CompressPDF
DefaultGroupName=Compress PDF
OutputBaseFilename=QCompressPDF
Compression=lzma
SolidCompression=yes
SetupIconFile=pdf.ico
UninstallDisplayIcon={userappdata}\CompressPDF\compress_qt.pyw
UninstallDisplayName=Compress PDF
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
; Rename compress_qt.py to compress_qt.pyw on install
Source: "compress_qt.py"; DestName: "compress_qt.pyw"; DestDir: "{userappdata}\CompressPDF"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{userappdata}\CompressPDF"; Flags: ignoreversion
Source: "pdf.ico"; DestDir: "{userappdata}\CompressPDF"; Flags: ignoreversion

[Run]
; Download and install Python silently if not present
Filename: "powershell.exe"; Parameters: "-Command ""$downloadedFile = '{tmp}\python-installer.exe'; $url = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'; Invoke-WebRequest -Uri $url -OutFile $downloadedFile; Start-Process -FilePath $downloadedFile -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_pip=1' -Wait"""; StatusMsg: "Downloading and Installing Python..."; Flags: runhidden waituntilterminated; Check: NeedsPython
; Download and install Ghostscript silently
Filename: "powershell.exe"; Parameters: "-Command ""$downloadedFile = '{tmp}\gs-installer.exe'; $url = 'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/gs10051w64.exe'; Invoke-WebRequest -Uri $url -OutFile $downloadedFile; Start-Process -FilePath $downloadedFile -ArgumentList '/S' -Wait"""; StatusMsg: "Downloading and Installing Ghostscript..."; Flags: runhidden waituntilterminated; Check: NeedsGhostscript
; Install Python dependencies using the installed Python
Filename: "{code:GetPythonExePath}"; Parameters: "-m pip install --upgrade pip"; StatusMsg: "Upgrading pip..."; Flags: runhidden waituntilterminated skipifdoesntexist
Filename: "{code:GetPythonExePath}"; Parameters: "-m pip install -r ""{userappdata}\CompressPDF\requirements.txt"""; StatusMsg: "Installing Python dependencies from requirements.txt..."; Flags: runhidden waituntilterminated skipifdoesntexist

[Registry]
; Add context menu for PDF files
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: ""; ValueData: "Compress PDF (QCompressPDF)"; Flags: uninsdeletekey
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: "Icon"; ValueData: "{userappdata}\CompressPDF\pdf.ico"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF\command"; ValueType: string; ValueName: ""; ValueData: """{code:GetPythonwExePath}"" ""{userappdata}\CompressPDF\compress_qt.pyw"" ""%1"""; Flags: uninsdeletekey

[Icons]
Name: "{userprograms}\Compress PDF (QCompressPDF)"; Filename: "{userappdata}\CompressPDF\compress_qt.pyw"; WorkingDir: "{userappdata}\CompressPDF"; IconFilename: "{userappdata}\CompressPDF\pdf.ico"

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\CompressPDF"

[Code]
var
  DownloadPage: TWizardPage;
  PythonInstalledLabel: TLabel;
  GhostscriptInstalledLabel: TLabel;
  DebugLoggingCheckBox: TCheckBox;
  EnableDebugLogging: Boolean;
  PythonPath: String;
  LogFilePath: String;

procedure LogDebug(Message: String);
var
  LogFile: String;
begin
  if EnableDebugLogging then
  begin
    LogFile := ExpandConstant('{userappdata}\CompressPDF\install_debug.log');
    SaveStringToFile(LogFile, FormatDateTime('yyyy-MM-dd hh:nn:ss', Now) + ' - ' + Message + #13#10, True);
    Log('DEBUG: ' + Message);
  end;
end;

function GetPythonPath: String;
var
  PythonInstallPath: String;
  PythonExePath: String;
begin
  // Try to get Python path from registry (Python 3.11 install location)
  if RegQueryStringValue(HKLM, 'SOFTWARE\Python\PythonCore\3.11\InstallPath', '', PythonInstallPath) then
  begin
    PythonExePath := AddBackslash(PythonInstallPath) + 'python.exe';
    if FileExists(PythonExePath) then
    begin
      LogDebug('Found Python 3.11 in registry: ' + PythonInstallPath);
      Result := PythonInstallPath;
      Exit;
    end;
  end;

  // Fallback to default installation path
  PythonInstallPath := ExpandConstant('{autopf}\Python311');
  PythonExePath := AddBackslash(PythonInstallPath) + 'python.exe';
  if FileExists(PythonExePath) then
  begin
    LogDebug('Found Python 3.11 at default location: ' + PythonInstallPath);
    Result := PythonInstallPath;
    Exit;
  end;

  // Return default path even if not found (for new installations)
  LogDebug('Python not found, using default path: ' + PythonInstallPath);
  Result := PythonInstallPath;
end;

function IsPythonFunctional(PythonExePath: String): Boolean;
var
  ResultCode: Integer;
begin
  // Test if python.exe can execute successfully
  Result := False;
  if FileExists(PythonExePath) then
  begin
    if Exec(PythonExePath, '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    begin
      if ResultCode = 0 then
      begin
        LogDebug('Python is functional at: ' + PythonExePath);
        Result := True;
      end
      else
      begin
        LogDebug('Python exists but is not functional (exit code ' + IntToStr(ResultCode) + '): ' + PythonExePath);
      end;
    end
    else
    begin
      LogDebug('Failed to execute Python at: ' + PythonExePath);
    end;
  end
  else
  begin
    LogDebug('Python not found at: ' + PythonExePath);
  end;
end;

function NeedsPython: Boolean;
var
  PythonExePath: String;
  PythonwExePath: String;
begin
  PythonPath := GetPythonPath();
  PythonExePath := AddBackslash(PythonPath) + 'python.exe';
  PythonwExePath := AddBackslash(PythonPath) + 'pythonw.exe';
  
  // Check if both python.exe and pythonw.exe exist
  if FileExists(PythonExePath) and FileExists(PythonwExePath) then
  begin
    // Verify that Python is actually functional
    if IsPythonFunctional(PythonExePath) then
    begin
      LogDebug('Python 3.11 is already installed and functional.');
      Result := False;
    end
    else
    begin
      LogDebug('Python 3.11 exists but is broken/non-functional. Will reinstall.');
      Result := True;
    end;
  end
  else
  begin
    LogDebug('Python 3.11 not found. Will install.');
    Result := True;
  end;
end;

function NeedsGhostscript: Boolean;
begin
  Result := not DirExists(ExpandConstant('{autopf}\gs\gs10.05.1\bin'));
  if Result then
    LogDebug('Ghostscript not found. Will install.')
  else
    LogDebug('Ghostscript is already installed.');
end;

procedure InitializeWizard();
var
  DownloadLabel: TLabel;
  DebugLoggingLabel: TLabel;
begin
  EnableDebugLogging := False;
  LogFilePath := ExpandConstant('{userappdata}\CompressPDF\install_debug.log');

  if NeedsPython() or NeedsGhostscript() then
  begin
    DownloadPage := CreateCustomPage(wpReady, 'Install Dependencies', 'The installer will download and install required software');

    DownloadLabel := TLabel.Create(DownloadPage);
    DownloadLabel.Caption := 'This application requires Python and Ghostscript. The installer will automatically download and install them if they are not already present.';
    DownloadLabel.WordWrap := True;
    DownloadLabel.Top := 16;
    DownloadLabel.Left := 0;
    DownloadLabel.Width := 500;
    DownloadLabel.Parent := DownloadPage.Surface;

    // Add debug logging checkbox
    DebugLoggingCheckBox := TCheckBox.Create(DownloadPage);
    DebugLoggingCheckBox.Caption := 'Enable debug logging (recommended for troubleshooting)';
    DebugLoggingCheckBox.Top := 50;
    DebugLoggingCheckBox.Left := 0;
    DebugLoggingCheckBox.Width := 500;
    DebugLoggingCheckBox.Parent := DownloadPage.Surface;
    DebugLoggingCheckBox.Checked := False;

    DebugLoggingLabel := TLabel.Create(DownloadPage);
    DebugLoggingLabel.Caption := 'Debug log will be saved to: ' + LogFilePath;
    DebugLoggingLabel.WordWrap := True;
    DebugLoggingLabel.Top := 70;
    DebugLoggingLabel.Left := 20;
    DebugLoggingLabel.Width := 480;
    DebugLoggingLabel.Font.Color := clGray;
    DebugLoggingLabel.Font.Size := 7;
    DebugLoggingLabel.Parent := DownloadPage.Surface;

    if NeedsPython() then
    begin
      PythonInstalledLabel := TLabel.Create(DownloadPage);
      PythonInstalledLabel.Caption := 'Installing Python 3.11.9...';
      PythonInstalledLabel.WordWrap := True;
      PythonInstalledLabel.Top := 100;
      PythonInstalledLabel.Left := 0;
      PythonInstalledLabel.Width := 500;
      PythonInstalledLabel.Parent := DownloadPage.Surface;
    end;

    if NeedsGhostscript() then
    begin
      GhostscriptInstalledLabel := TLabel.Create(DownloadPage);
      GhostscriptInstalledLabel.Caption := 'Installing Ghostscript...';
      GhostscriptInstalledLabel.WordWrap := True;
      if NeedsPython() then
        GhostscriptInstalledLabel.Top := 140
      else
        GhostscriptInstalledLabel.Top := 100;
      GhostscriptInstalledLabel.Left := 0;
      GhostscriptInstalledLabel.Width := 500;
      GhostscriptInstalledLabel.Parent := DownloadPage.Surface;
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // Only compare PageID to DownloadPage.ID if DownloadPage has been created
  if (DownloadPage <> nil) and (PageID = DownloadPage.ID) and not (NeedsPython() or NeedsGhostscript()) then
  begin
    Result := True;
  end else
    Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  // Capture the checkbox state when leaving the download page
  if (DownloadPage <> nil) and (CurPageID = DownloadPage.ID) then
  begin
    EnableDebugLogging := DebugLoggingCheckBox.Checked;
    if EnableDebugLogging then
    begin
      // Create the log directory if it doesn't exist
      ForceDirectories(ExpandConstant('{userappdata}\CompressPDF'));
      LogDebug('=== CompressPDF Installation Started ===');
      LogDebug('Installer Version: 1.2.0');
      LogDebug('Debug logging enabled by user.');
    end;
  end;
end;

function GetPythonExePath(Param: String): String;
begin
  // Ensure PythonPath is initialized
  if PythonPath = '' then
    PythonPath := GetPythonPath();
  
  Result := AddBackslash(PythonPath) + 'python.exe';
  LogDebug('Using Python path for pip: ' + Result);
end;

function GetPythonwExePath(Param: String): String;
begin
  // Ensure PythonPath is initialized
  if PythonPath = '' then
    PythonPath := GetPythonPath();
  
  Result := AddBackslash(PythonPath) + 'pythonw.exe';
  LogDebug('Using Pythonw path for shortcuts: ' + Result);
end;
