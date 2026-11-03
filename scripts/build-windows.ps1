# Build the optional Windows .exe (portable exe + NSIS installer). Usage: scripts\build-windows.ps1 [-Server http://pve1:8080/data]
param([string]$Server = "")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
if ($Server) { $env:VITE_DEFAULT_SERVER = $Server }
Push-Location "$root\viewer"
try {
  npm ci --no-audit --no-fund
  npx tauri build
  Write-Host "Portable: viewer\src-tauri\target\release\radar-scout.exe"
  Get-ChildItem "src-tauri\target\release\bundle\nsis" -Filter *.exe | ForEach-Object { Write-Host "Installer: $($_.FullName)" }
} finally { Pop-Location }
