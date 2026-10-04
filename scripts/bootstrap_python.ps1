<#
  MinerU portable package -- step 0 bootstrap.

  Downloads a portable CPython (python-build-standalone) into runtime\python.
  This is the ONLY step that has to happen before any Python exists, which is
  why it lives in PowerShell instead of app\bootstrap.py.

  Encoding note: this file is intentionally PURE ASCII and prints English only.
  cmd.exe parses .bat files as OEM (936/GBK on zh-CN Windows) and PowerShell 5.1
  reads .ps1 as ANSI unless a UTF-8 BOM is present, so non-ASCII text here is a
  needless encoding risk.  All Chinese UI text is printed afterwards by
  app\bootstrap.py and app\launcher.py.

  Usage (normally called automatically by ..\Start-MinerU.bat):
      powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_python.ps1
  Options:
      -TargetDir <dir>   install into <dir>\python instead of <root>\runtime
      -Force             re-download even if a runtime is already present
#>
param(
    [string]$TargetDir = "",
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# --- pinned release: keep in sync with requirements.lock.txt / README -------
$PyVersion = '3.12.15'
$PyTag     = '20261003'
$PyFile    = 'cpython-3.12.15%2B20261003-x86_64-pc-windows-msvc-install_only.tar.gz'
$MinBytes  = 40000000

# --- download sources, tried in order (China-first, GitHub last) -----------
$Sources = @(
    "https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone/$PyTag/$PyFile",
    "https://mirrors.ustc.edu.cn/github-release/astral-sh/python-build-standalone/$PyTag/$PyFile",
    "https://github.com/astral-sh/python-build-standalone/releases/download/$PyTag/$PyFile"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Split-Path -Parent $ScriptDir
if ([string]::IsNullOrWhiteSpace($TargetDir)) { $TargetDir = Join-Path $Root 'runtime' }

$Dest  = Join-Path $TargetDir 'python'
$PyExe = Join-Path $Dest 'python.exe'

# Deleting a just-downloaded / just-extracted tree can hit a transient sharing
# violation (indexer, Defender, or a recycle-bin interception layer), and a
# silenced failure would leave ~45 MB of leftovers inside the package. So the
# helper below retries, and callers report when it ultimately fails.
function Remove-Tree([string]$Path) {
    for ($i = 1; $i -le 5; $i++) {
        if (-not (Test-Path $Path)) { return $true }
        try {
            Remove-Item $Path -Recurse -Force -ErrorAction Stop
            return $true
        } catch {
            Start-Sleep -Milliseconds (200 * $i)
        }
    }
    return (-not (Test-Path $Path))
}

if ((Test-Path $PyExe) -and (-not $Force)) {
    Write-Host "  [skip] Python runtime already present: $PyExe"
    exit 0
}

Write-Host ""
Write-Host "  =============================================================="
Write-Host "   First run: portable Python $PyVersion runtime is required."
Write-Host "   It will be downloaded now, about 47 MB."
Write-Host "  =============================================================="
Write-Host ""

# --- work inside the package dir so nothing is left in the host temp -------
$CacheDir = Join-Path $Root '_cache'
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
$Archive  = Join-Path $CacheDir ("cpython-$PyVersion-windows.tar.gz")

[void](Remove-Tree $Archive)

$Downloaded = $false
foreach ($url in $Sources) {
    Write-Host "  [downloading] $url"
    try {
        Invoke-WebRequest -Uri $url -OutFile $Archive -UseBasicParsing -TimeoutSec 1800
        $len = (Get-Item $Archive).Length
        if ($len -ge $MinBytes) {
            Write-Host ("  [ok] got {0:N1} MB" -f ($len / 1MB))
            $Downloaded = $true
            break
        }
        Write-Host ("  [warn] file too small, {0} bytes -- trying next source" -f $len)
    } catch {
        Write-Host "  [warn] $($_.Exception.Message)"
    }
}

if (-not $Downloaded) {
    Write-Host ""
    Write-Host "  [error] Could not download the Python runtime from any source."
    Write-Host "          Check the network, or use the full offline package"
    Write-Host "          instead -- see README, section 'offline bundle'."
    Write-Host ""
    [void](Remove-Tree $CacheDir)
    exit 1
}

# --- extract (bsdtar ships with Windows 10 1803+) --------------------------
$Tar = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path $Tar)) {
    Write-Host "  [error] tar.exe not found. Windows 10 1803 or newer is required."
    [void](Remove-Tree $CacheDir)
    exit 1
}

$Stage = Join-Path $CacheDir 'stage'
[void](Remove-Tree $Stage)
New-Item -ItemType Directory -Path $Stage -Force | Out-Null

Write-Host "  [extracting] ..."
& $Tar -xzf $Archive -C $Stage
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [error] tar failed with exit code $LASTEXITCODE"
    [void](Remove-Tree $CacheDir)
    exit 1
}

# the archive contains a single top-level "python" directory
$Extracted = Join-Path $Stage 'python'
if (-not (Test-Path (Join-Path $Extracted 'python.exe'))) {
    Write-Host "  [error] unexpected archive layout: python\python.exe not found"
    [void](Remove-Tree $CacheDir)
    exit 1
}

New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
[void](Remove-Tree $Dest)
Move-Item -Path $Extracted -Destination $Dest

# --- verify ----------------------------------------------------------------
Write-Host "  [verifying] ..."
$version = & $PyExe -c "import sys; print(sys.version.split()[0])" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [error] the interpreter failed to run: $version"
    [void](Remove-Tree $CacheDir)
    exit 1
}

# --- tidy up: leave no build leftovers inside the package ------------------
if (-not (Remove-Tree $CacheDir)) {
    Write-Host "  [warn] could not remove $CacheDir -- please delete it by hand."
} elseif (Test-Path $CacheDir) {
    Write-Host "  [warn] $CacheDir still exists -- please delete it by hand."
}

Write-Host "  [done] Python $version ready at $Dest"
Write-Host ""
exit 0
