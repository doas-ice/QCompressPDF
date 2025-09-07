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
Source: "compress_qt.pyw"; DestDir: "{userappdata}\CompressPDF"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{userappdata}\CompressPDF"; Flags: ignoreversion
Source: "pdf.ico"; DestDir: "{userappdata}\CompressPDF"; Flags: ignoreversion

[Run]
; Download and install Python silently if not present
Filename: "powershell.exe"; Parameters: "-Command ""$downloadedFile = '{tmp}\python-installer.exe'; $url = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'; Invoke-WebRequest -Uri $url -OutFile $downloadedFile; Start-Process -FilePath $downloadedFile -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1','Include_pip=1' -Wait"""; StatusMsg: "Downloading and Installing Python..."; Check: NeedsPython
; Download and install Ghostscript silently
Filename: "powershell.exe"; Parameters: "-Command ""$downloadedFile = '{tmp}\gs-installer.exe'; $url = 'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/gs10051w64.exe'; Invoke-WebRequest -Uri $url -OutFile $downloadedFile; Start-Process -FilePath $downloadedFile -ArgumentList '/S' -Wait"""; StatusMsg: "Downloading and Installing Ghostscript..."; Check: NeedsGhostscript
; Install Python dependencies using the installed Python
Filename: "{autopf}\Python311\python.exe"; Parameters: "-m pip install --upgrade pip"; StatusMsg: "Upgrading pip..."
Filename: "{autopf}\Python311\python.exe"; Parameters: "-m pip install -r ""{userappdata}\CompressPDF\requirements.txt"""; StatusMsg: "Installing Python dependencies from requirements.txt..."

[Registry]
; Add context menu for PDF files
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: ""; ValueData: "Compress PDF (QCompressPDF)"; Flags: uninsdeletekey
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: "Icon"; ValueData: "{userappdata}\CompressPDF\pdf.ico"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF\command"; ValueType: string; ValueName: ""; ValueData: """{autopf}\Python311\pythonw.exe"" ""{userappdata}\CompressPDF\compress_qt.pyw"" ""%1"""; Flags: uninsdeletekey

[Icons]
Name: "{userprograms}\Compress PDF (QCompressPDF)"; Filename: "{userappdata}\CompressPDF\compress_qt.pyw"; WorkingDir: "{userappdata}\CompressPDF"; IconFilename: "{userappdata}\CompressPDF\pdf.ico"

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\CompressPDF"

[Code]
var
  DownloadPage: TWizardPage;
  PythonInstalledLabel: TLabel;
  GhostscriptInstalledLabel: TLabel;

function NeedsPython: Boolean;
begin
  Result := not FileExists(ExpandConstant('{autopf}\Python311\pythonw.exe'));
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
      GhostscriptInstalledLabel.Top := ifthen(NeedsPython(), 120, 80);
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
