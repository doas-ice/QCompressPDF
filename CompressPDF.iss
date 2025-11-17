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
Filename: "powershell.exe"; Parameters: "-Command ""$downloadedFile = '{tmp}\python-installer.exe'; $url = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'; Invoke-WebRequest -Uri $url -OutFile $downloadedFile; Start-Process -FilePath $downloadedFile -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_pip=1' -Wait"""; StatusMsg: "Downloading and Installing Python..."; Flags: waituntilterminated; Check: NeedsPython
; Download and install Ghostscript silently
Filename: "powershell.exe"; Parameters: "-Command ""$downloadedFile = '{tmp}\gs-installer.exe'; $url = 'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/gs10051w64.exe'; Invoke-WebRequest -Uri $url -OutFile $downloadedFile; Start-Process -FilePath $downloadedFile -ArgumentList '/S' -Wait"""; StatusMsg: "Downloading and Installing Ghostscript..."; Flags: waituntilterminated; Check: NeedsGhostscript
; Install Python dependencies using py launcher or python from PATH
Filename: "py.exe"; Parameters: "-3 -m pip install --upgrade pip"; StatusMsg: "Upgrading pip..."; Flags: runhidden waituntilterminated skipiferror
Filename: "py.exe"; Parameters: "-3 -m pip install -r ""{userappdata}\CompressPDF\requirements.txt"""; StatusMsg: "Installing Python dependencies from requirements.txt..."; Flags: runhidden waituntilterminated skipiferror
; Fallback: try using python from PATH if py launcher fails
Filename: "python.exe"; Parameters: "-m pip install --upgrade pip"; StatusMsg: "Upgrading pip (fallback)..."; Flags: runhidden waituntilterminated skipiferror; Check: not FileExists(ExpandConstant('{sys}\py.exe'))
Filename: "python.exe"; Parameters: "-m pip install -r ""{userappdata}\CompressPDF\requirements.txt"""; StatusMsg: "Installing Python dependencies (fallback)..."; Flags: runhidden waituntilterminated skipiferror; Check: not FileExists(ExpandConstant('{sys}\py.exe'))

[Registry]
; Add context menu for PDF files - using py launcher for better compatibility
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: ""; ValueData: "Compress PDF (QCompressPDF)"; Flags: uninsdeletekey
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: "Icon"; ValueData: "{userappdata}\CompressPDF\pdf.ico"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF\command"; ValueType: string; ValueName: ""; ValueData: """pythonw.exe"" ""{userappdata}\CompressPDF\compress_qt.pyw"" ""%1"""; Flags: uninsdeletekey

[Icons]
Name: "{userprograms}\Compress PDF (QCompressPDF)"; Filename: "pythonw.exe"; Parameters: """{userappdata}\CompressPDF\compress_qt.pyw"""; WorkingDir: "{userappdata}\CompressPDF"; IconFilename: "{userappdata}\CompressPDF\pdf.ico"

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\CompressPDF"

[Code]
var
  DownloadPage: TWizardPage;
  PythonInstalledLabel: TLabel;
  GhostscriptInstalledLabel: TLabel;

function NeedsPython: Boolean;
var
  ResultCode: Integer;
begin
  // Check if Python is available in PATH or via py launcher
  Result := True;
  // Try py launcher first
  if Exec('py.exe', '-3 --version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    Result := False;
    Exit;
  end;
  // Try python.exe in PATH
  if Exec('python.exe', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    Result := False;
    Exit;
  end;
  // Check common installation paths
  if FileExists(ExpandConstant('{autopf}\Python311\pythonw.exe')) or
     FileExists(ExpandConstant('{autopf}\Python312\pythonw.exe')) or
     FileExists(ExpandConstant('{autopf}\Python313\pythonw.exe')) or
     FileExists(ExpandConstant('{localappdata}\Programs\Python\Python311\pythonw.exe')) or
     FileExists(ExpandConstant('{localappdata}\Programs\Python\Python312\pythonw.exe')) or
     FileExists(ExpandConstant('{localappdata}\Programs\Python\Python313\pythonw.exe')) then
  begin
    Result := False;
  end;
end;

function NeedsGhostscript: Boolean;
begin
  Result := not DirExists(ExpandConstant('{autopf}\gs\gs10.05.1\bin'));
end;

procedure InitializeWizard();
var
  DownloadLabel: TLabel;
begin
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

    if NeedsPython() then
    begin
      PythonInstalledLabel := TLabel.Create(DownloadPage);
      PythonInstalledLabel.Caption := 'Installing Python 3.11.9...';
      PythonInstalledLabel.WordWrap := True;
      PythonInstalledLabel.Top := 80;
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
        GhostscriptInstalledLabel.Top := 120
      else
        GhostscriptInstalledLabel.Top := 80;
      GhostscriptInstalledLabel.Left := 0;
      GhostscriptInstalledLabel.Width := 500;
      GhostscriptInstalledLabel.Parent := DownloadPage.Surface;
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  if (PageID = DownloadPage.ID) and not (NeedsPython() or NeedsGhostscript()) then
  begin
    Result := True;
  end else
    Result := False;
end;
