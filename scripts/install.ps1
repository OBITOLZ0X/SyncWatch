# SyncWatch Windows Installer — irm | iex
# Installs the latest SyncWatch release from GitHub.
#
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/OBITOLZ0X/SyncWatch/main/scripts/install.ps1 | iex
#
# Options (via environment variables before piping):
#   $env:SYNCWATCH_VERSION = "v2.0.0"   # specific version
#   $env:SYNCWATCH_NODESKTOP = "1"      # skip desktop shortcut
#   $env:SYNCWATCH_NOSTARTMENU = "1"    # skip start menu

param(
    [string]$Version = $env:SYNCWATCH_VERSION,
    [switch]$NoDesktop,
    [switch]$NoStartMenu,
    [switch]$Uninstall,
    [string]$InstallDir = "",
    [switch]$Help
)

$Repo = "OBITOLZ0X/SyncWatch"
$AppName = "SyncWatch"

# Env var overrides
if ($env:SYNCWATCH_NODESKTOP -eq "1") { $NoDesktop = $true }
if ($env:SYNCWATCH_NOSTARTMENU -eq "1") { $NoStartMenu = $true }
if (-not $Version) { $Version = "latest" }

function Write-Info    { param([string]$m) Write-Host "[INFO] $m" -ForegroundColor Blue }
function Write-Success { param([string]$m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn    { param([string]$m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err     { param([string]$m) Write-Host "[ERROR] $m" -ForegroundColor Red }

function Show-Help {
    @"
SyncWatch Installer for Windows

Usage:
  irm https://raw.githubusercontent.com/$Repo/main/scripts/install.ps1 | iex
  .\install.ps1 -Version v2.0.0
  .\install.ps1 -Uninstall

Options:
  -Version <tag>    Install specific version (default: latest)
  -NoDesktop        Skip desktop shortcut
  -NoStartMenu      Skip start menu shortcut
  -Uninstall        Uninstall SyncWatch
  -InstallDir <path> Custom install directory
  -Help             Show this help

Environment variables (alternative to flags):
  SYNCWATCH_VERSION=v2.0.0
  SYNCWATCH_NODESKTOP=1
  SYNCWATCH_NOSTARTMENU=1

"@
}

if ($Help) { Show-Help; exit 0 }

# ── Uninstall ──
if ($Uninstall) {
    Write-Host ""
    Write-Host "Uninstalling SyncWatch..." -ForegroundColor Cyan

    $dirsToCheck = @(
        "$env:LOCALAPPDATA\SyncWatch",
        "$env:APPDATA\SyncWatch",
        "$PSScriptRoot\SyncWatch"
    )
    if ($InstallDir) { $dirsToCheck = @($InstallDir) }

    foreach ($dir in $dirsToCheck) {
        if (Test-Path $dir) {
            Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
            Write-Success "Removed $dir"
        }
    }

    # Remove shortcuts
    $desktop = [Environment]::GetFolderPath("Desktop")
    $startMenu = [Environment]::GetFolderPath("StartMenu")
    $shortcuts = @(
        "$desktop\SyncWatch.lnk",
        "$startMenu\Programs\SyncWatch.lnk",
        "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\SyncWatch.lnk"
    )
    foreach ($lnk in $shortcuts) {
        if (Test-Path $lnk) {
            Remove-Item -Force $lnk -ErrorAction SilentlyContinue
            Write-Success "Removed $lnk"
        }
    }

    # Remove from PATH
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -and $userPath.Contains("SyncWatch")) {
        $newPath = ($userPath.Split(';') | Where-Object { $_ -notlike "*SyncWatch*" }) -join ';'
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Success "Removed SyncWatch from User PATH"
    }

    Write-Success "SyncWatch uninstalled."
    exit 0
}

# ── Header ──
Write-Host ""
Write-Host "╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║    SyncWatch — Windows Installer     ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Determine install dir ──
if (-not $InstallDir) {
    $InstallDir = "$env:LOCALAPPDATA\SyncWatch"
}
Write-Info "Install directory: $InstallDir"
Write-Info "Version: $Version"
Write-Host ""

# ── Check PowerShell version ──
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Warn "PowerShell $($PSVersionTable.PSVersion) detected. Recommended: 5.1+"
}

# ── Fetch release info ──
Write-Info "Fetching release info..."

$DownloadUrl = $null
$Tag = $Version

try {
    if ($Version -eq "latest") {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing -ErrorAction Stop
        $Tag = $release.tag_name
        Write-Info "Latest version: $Tag"
        # Prefer Windows asset
        $asset = $release.assets | Where-Object { $_.name -match "Windows" } | Select-Object -First 1
        if (-not $asset) {
            $asset = $release.assets | Where-Object { $_.name -match "\.zip" } | Select-Object -First 1
        }
        if ($asset) {
            $DownloadUrl = $asset.browser_download_url
        }
    } else {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/$Tag" -UseBasicParsing -ErrorAction Stop
        $asset = $release.assets | Where-Object { $_.name -match "Windows" } | Select-Object -First 1
        if (-not $asset) {
            $asset = $release.assets | Where-Object { $_.name -match "\.zip" } | Select-Object -First 1
        }
        if ($asset) {
            $DownloadUrl = $asset.browser_download_url
        }
    }
} catch {
    Write-Warn "Could not fetch release via API: $_"
}

if (-not $DownloadUrl) {
    Write-Host ""
    Write-Warn "No pre-built Windows release found for $Tag."
    Write-Warn "You can:"
    Write-Host "  1. Wait for the next release (builds run on every tag)" -ForegroundColor Yellow
    Write-Host "  2. Install from source:" -ForegroundColor Yellow
    Write-Host "     git clone https://github.com/$Repo.git" -ForegroundColor White
    Write-Host "     cd SyncWatch; pip install -r requirements.txt; python main.py" -ForegroundColor White
    Write-Host "  3. Build locally: pip install pyinstaller; python build.py" -ForegroundColor White
    Write-Host ""
    Write-Host "  Checking fallback URL..." -ForegroundColor Yellow
    $DownloadUrl = "https://github.com/$Repo/releases/download/$Tag/SyncWatch-Windows.zip"
    Write-Info "Trying: $DownloadUrl"

    # Test if fallback exists (HEAD request)
    try {
        $null = Invoke-WebRequest -Uri $DownloadUrl -Method Head -UseBasicParsing -ErrorAction Stop
        Write-Success "Fallback URL exists, proceeding..."
    } catch {
        Write-Err "No Windows build available for $Tag."
        Write-Err "See releases: https://github.com/$Repo/releases"
        Write-Host ""
        Write-Host "To install from source, run:" -ForegroundColor Cyan
        Write-Host "  git clone https://github.com/$Repo.git; cd SyncWatch; pip install -r requirements.txt; python main.py" -ForegroundColor White
        exit 1
    }
}

Write-Info "Download URL: $DownloadUrl"
Write-Host ""

# ── Download ──
$tmpZip = Join-Path $env:TEMP "SyncWatch-$Tag.zip"

Write-Info "Downloading..."
try {
    # Use Invoke-WebRequest with progress
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $tmpZip -UseBasicParsing -ErrorAction Stop
    $ProgressPreference = 'Continue'
} catch {
    Write-Err "Download failed: $_"
    Write-Err "Check: https://github.com/$Repo/releases"
    exit 1
}

if (-not (Test-Path $tmpZip) -or (Get-Item $tmpZip).Length -eq 0) {
    Write-Err "Downloaded file is empty or missing."
    exit 1
}

$sizeMB = [math]::Round((Get-Item $tmpZip).Length / 1MB, 1)
Write-Success "Downloaded ($sizeMB MB) to $tmpZip"

# ── Extract ──
Write-Info "Extracting to $InstallDir..."

# Backup existing install if present
if (Test-Path $InstallDir) {
    $backup = "$InstallDir.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Write-Warn "Existing install found, backing up to $backup"
    Move-Item -Path $InstallDir -Destination $backup -Force -ErrorAction SilentlyContinue
}

# Ensure clean dir
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

try {
    Expand-Archive -Path $tmpZip -DestinationPath $InstallDir -Force -ErrorAction Stop
} catch {
    Write-Err "Extraction failed: $_"
    # Try alternative with .NET
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($tmpZip, $InstallDir)
    } catch {
        Write-Err "Failed to extract even with fallback: $_"
        exit 1
    }
}

# Handle nested folder (if archive contains SyncWatchLz/SyncWatch.exe or SyncWatch-Windows/SyncWatch.exe)
$exeCandidates = @(
    (Join-Path $InstallDir "SyncWatch.exe"),
    (Join-Path $InstallDir "SyncWatch\SyncWatch.exe"),
    (Join-Path $InstallDir "SyncWatchLz\SyncWatch.exe"),
    (Join-Path $InstallDir "SyncWatch-Windows\SyncWatch.exe")
)
# Also search recursively
$foundExe = $exeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $foundExe) {
    $foundExe = Get-ChildItem -Path $InstallDir -Recurse -Filter "SyncWatch.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($foundExe) { $foundExe = $foundExe.FullName }
}

if (-not $foundExe -or -not (Test-Path $foundExe)) {
    Write-Err "Could not find SyncWatch.exe in archive. Contents:"
    Get-ChildItem -Path $InstallDir -Recurse | Select-Object FullName | Format-Table -AutoSize | Out-String | Write-Host
    exit 1
}

# If exe is in subdirectory, move contents up one level
$exeDir = Split-Path $foundExe -Parent
if ($exeDir -ne $InstallDir) {
    Write-Info "Flattening nested directory: $exeDir -> $InstallDir"
    Get-ChildItem -Path $exeDir -Force | ForEach-Object {
        $dest = Join-Path $InstallDir $_.Name
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest -ErrorAction SilentlyContinue }
        Move-Item -Path $_.FullName -Destination $dest -Force -ErrorAction SilentlyContinue
    }
    # Clean up empty nested dir
    Remove-Item -Recurse -Force $exeDir -ErrorAction SilentlyContinue
    $foundExe = Join-Path $InstallDir "SyncWatch.exe"
}

Write-Success "Extracted to $InstallDir"
Write-Info "Binary: $foundExe"

# Cleanup zip
Remove-Item -Force $tmpZip -ErrorAction SilentlyContinue

# ── Add to PATH (User) ──
Write-Info "Adding to PATH..."

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }

if ($userPath.Split(';') -notcontains $InstallDir) {
    $newPath = if ($userPath) { "$userPath;$InstallDir" } else { $InstallDir }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    # Also update current session
    $env:Path = "$env:Path;$InstallDir"
    Write-Success "Added $InstallDir to User PATH"
    Write-Warn "You may need to restart your terminal for PATH to take effect."
} else {
    Write-Success "Already in PATH"
}

# ── Start Menu shortcut ──
if (-not $NoStartMenu) {
    try {
        $startMenuDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
        # Ensure dir exists
        New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null
        $lnkPath = Join-Path $startMenuDir "SyncWatch.lnk"

        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($lnkPath)
        $shortcut.TargetPath = $foundExe
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.Description = "SyncWatch — Watch Together, Perfectly Synced"
        # Try to set icon if exists
        $iconPath = Join-Path $InstallDir "SyncWatch.ico"
        if (Test-Path $iconPath) {
            $shortcut.IconLocation = $iconPath
        } elseif (Test-Path $foundExe) {
            $shortcut.IconLocation = $foundExe
        }
        $shortcut.Save()
        Write-Success "Start Menu shortcut: $lnkPath"
    } catch {
        Write-Warn "Could not create Start Menu shortcut: $_"
    }
}

# ── Desktop shortcut ──
if (-not $NoDesktop) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $lnkPath = Join-Path $desktop "SyncWatch.lnk"

        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($lnkPath)
        $shortcut.TargetPath = $foundExe
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.Description = "SyncWatch — Watch Together, Perfectly Synced"
        $iconPath = Join-Path $InstallDir "SyncWatch.ico"
        if (Test-Path $iconPath) {
            $shortcut.IconLocation = $iconPath
        } elseif (Test-Path $foundExe) {
            $shortcut.IconLocation = $foundExe
        }
        $shortcut.Save()
        Write-Success "Desktop shortcut: $lnkPath"
    } catch {
        Write-Warn "Could not create Desktop shortcut: $_"
    }
}

# ── Create uninstaller ──
$uninstallScript = @"
# SyncWatch Uninstaller
`$InstallDir = "$InstallDir"
Write-Host "Uninstalling SyncWatch from `$InstallDir..." -ForegroundColor Cyan
if (Test-Path `$InstallDir) {
    Remove-Item -Recurse -Force `$InstallDir -ErrorAction SilentlyContinue
    Write-Host "Removed `$InstallDir" -ForegroundColor Green
}
`$desktop = [Environment]::GetFolderPath("Desktop")
`$startMenu = [Environment]::GetFolderPath("StartMenu")
Remove-Item -Force "`$desktop\SyncWatch.lnk" -ErrorAction SilentlyContinue
Remove-Item -Force "`$startMenu\Programs\SyncWatch.lnk" -ErrorAction SilentlyContinue
`$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (`$userPath -and `$userPath.Contains("SyncWatch")) {
    `$newPath = (`$userPath.Split(';') | Where-Object { `$_ -notlike "*SyncWatch*" }) -join ';'
    [Environment]::SetEnvironmentVariable("Path", `$newPath, "User")
    Write-Host "Removed from PATH" -ForegroundColor Green
}
Write-Host "SyncWatch uninstalled." -ForegroundColor Green
"@
$uninstallPath = Join-Path $InstallDir "SyncWatch-Uninstall.ps1"
$uninstallScript | Out-File -FilePath $uninstallPath -Encoding utf8 -Force

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Success "SyncWatch installed successfully! 🎉"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Run:        SyncWatch  (or double-click the shortcut)" -ForegroundColor White
Write-Host "  Location:   $foundExe" -ForegroundColor White
Write-Host "  Uninstall:  $uninstallPath" -ForegroundColor White
Write-Host "  Update:     irm https://raw.githubusercontent.com/$Repo/main/scripts/install.ps1 | iex" -ForegroundColor White
Write-Host ""
Write-Host "  Tip: Restart your terminal, then type 'SyncWatch' to launch." -ForegroundColor Yellow
Write-Host ""

# Optionally launch?
# Start-Process $foundExe
