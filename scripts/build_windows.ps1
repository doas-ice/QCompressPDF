$ErrorActionPreference = 'Stop'
function Assert-Native([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)" } }
function Download-Checked([string]$Url, [string]$Destination, [string]$Hash) {
    Invoke-WebRequest -Uri $Url -OutFile $Destination -TimeoutSec 120
    if ((Get-FileHash $Destination -Algorithm SHA256).Hash -ne $Hash) { throw "Checksum mismatch: $Destination" }
}
python -m PyInstaller --noconfirm --clean --windowed --onedir --name QCompressPDF --icon pdf.ico compress_qt.py
Assert-Native 'PyInstaller'
$gsInstaller = "$env:RUNNER_TEMP\qcompresspdf-gs.exe"
Download-Checked 'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/gs10080w64.exe' $gsInstaller '52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50'
$gsDir = "$env:RUNNER_TEMP\qcompresspdf-gs"
# NSIS silent setup can launch an interactive VC redistributable. Extract only
# the runtime/resources instead: CI and end users need no nested installation.
7z x -y "-o$gsDir" $gsInstaller bin doc lib Resource iccprofiles
Assert-Native 'Ghostscript extraction'
# Ship app-local MSVC runtime DLLs so a clean Windows machine does not need the
# global Visual C++ redistributable either. Use the runner's licensed VS redist.
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsRoot = & $vswhere -latest -products '*' -property installationPath
$crt = Get-ChildItem "$vsRoot\VC\Redist\MSVC\*\x64\Microsoft.VC*.CRT" -Directory | Sort-Object FullName -Descending | Select-Object -First 1
if (!$crt) { throw 'MSVC redistributable directory was not found' }
Copy-Item "$($crt.FullName)\*.dll" "$gsDir\bin" -Force
Copy-Item "$($crt.FullName)\*.dll" dist\QCompressPDF\_internal -Force
& "$gsDir\bin\gswin64c.exe" --version
Assert-Native 'Ghostscript'
Copy-Item $gsDir dist\QCompressPDF\ghostscript -Recurse
"$gsDir\bin" >> $env:GITHUB_PATH
Copy-Item LICENSE dist\QCompressPDF\LICENSE.txt
Copy-Item THIRD-PARTY-NOTICES.txt dist\QCompressPDF\THIRD-PARTY-NOTICES.txt
# Include the complete license metadata alongside the frozen packages.
$licenses = 'dist\QCompressPDF\licenses'
New-Item $licenses -ItemType Directory -Force | Out-Null
python scripts/copy_package_licenses.py $licenses
Assert-Native 'License collection'
& scripts\validate_payload.ps1 -Executable (Resolve-Path dist\QCompressPDF\QCompressPDF.exe)
Assert-Native 'Frozen payload'
iscc CompressPDF.iss
Assert-Native 'Inno Setup'
# Publish equivalent access to the exact unmodified Ghostscript source with the binary.
Download-Checked 'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/ghostscript-10.08.0.tar.xz' 'Output/ghostscript-10.08.0.tar.xz' 'c20492bc8ebb96c87fa2e52a0926e1cda8cde95d66145e018ac713fed5da38cf'
