param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference = 'Stop'
try {
    $process = Start-Process -FilePath $Executable -ArgumentList '--self-test' -PassThru -WindowStyle Hidden
    if (!$process.WaitForExit(30000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw 'Application validation timed out after 30 seconds.'
    }
    if ($process.ExitCode -ne 0) { throw "Application validation failed ($($process.ExitCode))." }
    exit 0
} catch {
    Write-Error $_
    exit 1
}
