$ErrorActionPreference = 'Stop'
$report = [System.Collections.Generic.List[string]]::new()
function Check([bool]$Condition, [string]$Message) {
    if (!$Condition) { throw $Message }
    $report.Add($Message)
    Write-Host "PASS: $Message"
}
function Run-Installer([string]$Exe, [string[]]$Arguments, [bool]$ShouldPass = $true) {
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru
    if (!$process.WaitForExit(120000)) { $process.Kill(); throw "Timed out: $Exe" }
    if ($ShouldPass) { Check ($process.ExitCode -eq 0) "Installer succeeded: $Exe" }
    else { Check ($process.ExitCode -ne 0) "Unsafe/invalid installation was rejected: $Exe" }
}
function Smoke([string]$Exe) {
    & "$PSScriptRoot\validate_payload.ps1" -Executable $Exe
    Check ($LASTEXITCODE -eq 0) "Installed payload works: $Exe"
}
$target = "$env:RUNNER_TEMP\QCompressPDF installed"
$exe = "$target\versions\$env:QCOMPRESSPDF_VERSION\QCompressPDF.exe"
$setup = (Resolve-Path Output\QCompressPDF.exe).Path
$baseArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$target`"")
$menuKey = 'HKCU:\Software\Classes\SystemFileAssociations\.pdf\shell\QCompressPDF\command'
$shortcut = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\QCompressPDF.lnk"
$legacySetup = "$env:RUNNER_TEMP\QCompressPDF-1.5.5.exe"
Invoke-WebRequest 'https://github.com/doas-ice/QCompressPDF/releases/download/v1.5.5/QCompressPDF.exe' -OutFile $legacySetup -TimeoutSec 120
Check ((Get-FileHash $legacySetup).Hash -eq '5365804d11bc3fcc63e65768ef33d6c66a93bf77eff759c9ee82d415d1ff1bef') 'Published v1.5.5 installer checksum matches'
$pythonRoot = Split-Path (Get-Command python).Source
$pythonHash = (Get-FileHash "$pythonRoot\python.exe").Hash

foreach ($mode in @('CURRENTUSER', 'ALLUSERS')) {
    $legacy = "$env:RUNNER_TEMP\Legacy $mode"
    New-Item "$legacy\python" -ItemType Directory -Force | Out-Null
    # Seed working dependencies, avoiding the old installer's broken network
    # bootstrap. The actual published installer still creates all old records.
    Copy-Item "$pythonRoot\*" "$legacy\python" -Recurse -Force
    & "$legacy\python\python.exe" -m venv --system-site-packages "$legacy\venv"
    Check ($LASTEXITCODE -eq 0) "Legacy dependencies prepared ($mode)"
    [IO.File]::WriteAllText("$legacy\venv\.qcompresspdf_python_version", '3.13.5')
    Run-Installer $legacySetup @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/$mode", "/DIR=`"$legacy`"", "/LOG=`"$env:RUNNER_TEMP\legacy-$mode.log`"")
    Check (Test-Path "$legacy\compress_qt.pyw") "Actual legacy application installed ($mode)"
    [IO.File]::WriteAllText("$legacy\personal-file.txt", 'preserve during upgrade')
    $scriptHash = (Get-FileHash "$legacy\compress_qt.pyw").Hash
    Run-Installer $setup $baseArgs
    Smoke $exe
    Check ((Get-Item $menuKey).GetValue('') -eq "`"$exe`" `"%1`"") 'New context menu targets the bundled executable'
    Check (Test-Path $shortcut) 'New shortcut has an independent filename'
    Check ((Get-FileHash "$legacy\compress_qt.pyw").Hash -eq $scriptHash) 'Upgrade leaves the old application untouched'
    Check ((Get-Content "$legacy\personal-file.txt") -eq 'preserve during upgrade') 'Upgrade preserves files in the old installation'
    Check ((Get-FileHash "$pythonRoot\python.exe").Hash -eq $pythonHash) 'Existing Python installation is untouched'
    $oldMenu = 'HKCU:\Software\Classes\SystemFileAssociations\.pdf\shell\CompressPDF'
    Check ((Get-Item $oldMenu).GetValueNames() -contains 'LegacyDisable') 'Legacy context menu is hidden without deleting it'
    # Neither the old root nor a descendant may be used for the new payload.
    foreach ($badDir in @($legacy, "$legacy\nested")) {
        Run-Installer $setup @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/DIR=`"$badDir`"") $false
        Check ((Get-Item $menuKey).GetValue('').Contains($exe)) 'Rejected upgrade preserves the active menu'
    }
    # Exercise the real recursive legacy uninstall record; it must not remove
    # the new payload, new context command or new shortcut.
    Run-Installer "$legacy\unins000.exe" @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
    Smoke $exe
    Check (Test-Path $shortcut) 'Removing legacy installation preserves the new shortcut'
    Check ((Get-Item $menuKey).GetValue('').Contains($exe)) 'Removing legacy installation preserves the new context command'
}

# No system Python/GS on PATH, and conflicting environment variables inherited
# from another development environment must not affect the frozen app.
$saved = @{}
foreach ($name in @('PATH','PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QT_QPA_PLATFORM','GS_LIB','GS_OPTIONS')) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONHOME = 'Z:\missing-python'
    $env:PYTHONPATH = 'Z:\other-python'
    $env:QT_PLUGIN_PATH = 'Z:\other-qt'
    $env:QT_QPA_PLATFORM_PLUGIN_PATH = 'Z:\other-qt'
    $env:QT_QPA_PLATFORM = 'invalid-platform'
    $env:GS_LIB = 'Z:\other-gs'
    $env:GS_OPTIONS = '-sDEVICE=invalid-device'
    Run-Installer $setup $baseArgs
    Smoke $exe
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}

# AppMutex rejects a silent update instead of terminating an active compression.
$running = Start-Process -FilePath $exe -PassThru
try {
    Check ($running.WaitForInputIdle(15000)) 'Application entered its normal GUI event loop'
    Run-Installer $setup $baseArgs $false
    Check (!$running.HasExited) 'Blocked update leaves the running app alive'
} finally { Stop-Process -Id $running.Id -Force -ErrorAction SilentlyContinue }

# Build an intentionally invalid payload under another version. Validation must
# fail before activation; the installed working application must remain usable.
$payload = 'dist\QCompressPDF\QCompressPDF.exe'
$backup = "$env:RUNNER_TEMP\valid-payload.exe"
Copy-Item $payload $backup
$version = $env:QCOMPRESSPDF_VERSION
try {
    $env:QCOMPRESSPDF_VERSION = '99.0.0'
    [IO.File]::WriteAllText((Join-Path $PWD $payload), 'invalid executable for rollback test')
    iscc /FQCompressPDF-invalid CompressPDF.iss
    Check ($LASTEXITCODE -eq 0) 'Failure-injection installer compiled'
    Run-Installer (Resolve-Path Output\QCompressPDF-invalid.exe).Path $baseArgs $false
    Check ((Get-Item $menuKey).GetValue('').Contains($exe)) 'Failed validation preserves the previous active menu'
    Smoke $exe
} finally {
    $env:QCOMPRESSPDF_VERSION = $version
    Copy-Item $backup $payload -Force
    Remove-Item Output\QCompressPDF-invalid.exe -ErrorAction SilentlyContinue
}
Run-Installer $setup $baseArgs
Smoke $exe
Run-Installer "$target\unins000.exe" @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
Check (!(Test-Path $exe)) 'New uninstall removes its own payload'
Check (!(Test-Path $menuKey)) 'New uninstall removes its own context command'
Check ((Get-FileHash "$pythonRoot\python.exe").Hash -eq $pythonHash) 'New uninstall preserves existing Python'
$report | Set-Content Output\windows-migration-tests.txt
