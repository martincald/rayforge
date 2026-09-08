<#
.SYNOPSIS
    Smoke test for the windowed SwiftCut build.
.DESCRIPTION
    Starts the executable, waits for a window whose title contains "SwiftCut",
    asserts that no console host process was spawned anywhere in its process
    tree, then closes it cleanly. Exits 0 on success, 1 with a reason on
    failure.
.EXAMPLE
    ./scripts/win/win_smoke_test.ps1 -ExePath dist/SwiftCut/SwiftCut.exe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ExePath,

    [int] $TimeoutSeconds = 30,

    [string] $WindowTitleMatch = 'SwiftCut'
)

$ErrorActionPreference = 'Stop'

# Console hosts that must never appear under our process. conhost.exe is in
# the list on purpose: a console-subsystem build gets one even when the
# window is hidden with --hide-console, so this catches a regression back to
# that flag.
$ForbiddenImages = @(
    'cmd.exe', 'mintty.exe', 'conhost.exe', 'powershell.exe',
    'pwsh.exe', 'bash.exe', 'sh.exe', 'openconsole.exe',
    'windowsterminal.exe'
)

function Fail {
    param([string] $Message, [int] $KillPid)
    Write-Host "FAIL: $Message" -ForegroundColor Red
    if ($KillPid) {
        try { Stop-Process -Id $KillPid -Force -ErrorAction Stop } catch { }
    }
    exit 1
}

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    Fail "executable not found: $ExePath" 0
}
$resolved = (Resolve-Path -LiteralPath $ExePath).Path

Write-Host "--- SwiftCut windowed smoke test ---"
Write-Host "Executable : $resolved"
Write-Host "Timeout    : $TimeoutSeconds s"

# Started without -WindowStyle Hidden on purpose: hiding the window would
# also mask a console that a broken (console-subsystem) build allocates.
$proc = Start-Process -FilePath $resolved `
                      -WorkingDirectory (Split-Path -Parent $resolved) `
                      -PassThru
Write-Host "Started PID $($proc.Id)"

# --- 1. Wait for the main window ---------------------------------------
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$seenTitle = $null
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        Fail "process exited early with code $($proc.ExitCode)" 0
    }
    $proc.Refresh()
    # A handle with no matching title is what a splash window looks like;
    # accepting it would pass before the real UI exists.
    if ($proc.MainWindowTitle -like "*$WindowTitleMatch*") {
        $seenTitle = $proc.MainWindowTitle
        break
    }
    Start-Sleep -Milliseconds 250
}

if (-not $seenTitle) {
    $proc.Refresh()
    Fail ("no window whose title contains '$WindowTitleMatch' within " +
          "$TimeoutSeconds s (handle=$($proc.MainWindowHandle), " +
          "title='$($proc.MainWindowTitle)')") $proc.Id
}
Write-Host "PASS: window found, title = '$seenTitle'"

# --- 2. Assert no console host in the process tree ----------------------
$all = Get-CimInstance Win32_Process |
       Select-Object ProcessId, ParentProcessId, Name
$tree = @($proc.Id)
$frontier = @($proc.Id)
while ($frontier.Count -gt 0) {
    $next = @()
    foreach ($p in $all) {
        if ($frontier -contains $p.ParentProcessId -and
            $tree -notcontains $p.ProcessId) {
            $tree += $p.ProcessId
            $next += $p.ProcessId
        }
    }
    $frontier = $next
}

$offenders = $all | Where-Object {
    $tree -contains $_.ProcessId -and
    $ForbiddenImages -contains $_.Name.ToLower()
}
if ($offenders) {
    $names = ($offenders |
        ForEach-Object { "$($_.Name) (pid $($_.ProcessId))" }) -join ', '
    Fail "console host process(es) found in the tree: $names" $proc.Id
}
Write-Host "PASS: no console host in the tree ($($tree.Count) processes)"

# --- 3. Close cleanly ---------------------------------------------------
Write-Host "Closing main window..."
$null = $proc.CloseMainWindow()
if (-not $proc.WaitForExit(15000)) {
    Fail "process did not exit within 15 s of CloseMainWindow()" $proc.Id
}
if ($proc.ExitCode -ne 0) {
    Fail "non-zero exit code $($proc.ExitCode)" 0
}
Write-Host "PASS: exited cleanly with code $($proc.ExitCode)"

Write-Host "OK: windowed smoke test passed" -ForegroundColor Green
exit 0
