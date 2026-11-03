# Build the debug-signed Android APK locally. Usage: scripts\build-android.ps1 [-Server http://pve1:8080/data]
param([string]$Server = "")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk" }
if (-not $env:NDK_HOME) { $env:NDK_HOME = (Get-ChildItem "$env:ANDROID_HOME\ndk" | Sort-Object Name | Select-Object -Last 1).FullName }
if ($Server) { $env:VITE_DEFAULT_SERVER = $Server }
Push-Location "$root\viewer"
try {
  npm ci --no-audit --no-fund
  npx tauri android build --debug --apk --target aarch64
  Get-ChildItem "src-tauri\gen\android\app\build\outputs\apk" -Recurse -Filter *.apk | ForEach-Object { $_.FullName }
} finally { Pop-Location }
