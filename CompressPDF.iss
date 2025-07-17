; -- CompressPDF.iss --
[Setup]
AppName=Compress PDF
AppVersion=1.1
DefaultDirName={userappdata}\CompressPDF
DefaultGroupName=Compress PDF
OutputBaseFilename=CompressPDFSetup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={userappdata}\CompressPDF\compress_qt.pyw
UninstallDisplayName=Compress PDF
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64

[Files]
; Rename compress_qt.py to compress_qt.pyw on install
Source: "compress_qt.py"; DestName: "compress_qt.pyw"; DestDir: "{userappdata}\CompressPDF"; Flags: ignoreversion
Source: "python-3.13.5-amd64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "gs10051w64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Run]
; Install Python silently if not present
Filename: "{tmp}\python-3.13.5-amd64.exe"; Parameters: "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1"; StatusMsg: "Installing Python..."; Check: NeedsPython
; Install Ghostscript silently
Filename: "{tmp}\gs10051w64.exe"; Parameters: "/S"; StatusMsg: "Installing Ghostscript..."; Check: NeedsGhostscript
; Upgrade pip and install PySide6 and pypdf2 using the installed Python
Filename: "{autopf}\Python313\python.exe"; Parameters: "-m pip install --upgrade pip"; StatusMsg: "Upgrading pip..."
Filename: "{autopf}\Python313\python.exe"; Parameters: "-m pip install pyside6 pypdf2"; StatusMsg: "Installing PySide6 and pypdf2..."

[Registry]
; Add context menu for PDF files
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: ""; ValueData: "Compress PDF"; Flags: uninsdeletekey
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF"; ValueType: string; ValueName: "Icon"; ValueData: "%SystemRoot%\System32\imageres.dll,15"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "SystemFileAssociations\.pdf\shell\CompressPDF\command"; ValueType: string; ValueName: ""; ValueData: """{autopf}\Python313\pythonw.exe"" ""{userappdata}\CompressPDF\compress_qt.pyw"" ""%1"""; Flags: uninsdeletekey

[Icons]
Name: "{group}\Compress PDF"; Filename: "{userappdata}\CompressPDF\compress_qt.pyw"; WorkingDir: "{userappdata}\CompressPDF"; IconFilename: "shell32.dll"; IconIndex: 15

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\CompressPDF"

[Code]
function NeedsPython: Boolean;
begin
  Result := not FileExists(ExpandConstant('{autopf}\Python313\pythonw.exe'));
end;

function NeedsGhostscript: Boolean;
begin
  Result := not DirExists(ExpandConstant('{autopf}\gs\gs10.05.1\bin'));
end; 