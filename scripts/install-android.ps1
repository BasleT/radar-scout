# Install the built APK on a USB/wifi-debugging phone via adb.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
$apk = Get-ChildItem "$root\viewer\src-tauri\gen\android\app\build\outputs\apk" -Recurse -Filter *release*.apk | Select-Object -First 1
if (-not $apk) { throw "No APK found; run scripts\build-android.ps1 first." }
& $adb devices
& $adb install -r $apk.FullName
