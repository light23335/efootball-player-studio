param(
    [string]$Stage = (Join-Path $env:TEMP ('PlayerStudioAndroid-' + [guid]::NewGuid().ToString('N'))),
    [string]$Core = (Join-Path $PSScriptRoot 'core')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Core) -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot '../player-studio-v15/app.py'))) { $Core = Join-Path $PSScriptRoot '../player-studio-v15' }
if ($Stage -match '[^\x00-\x7F]') { throw 'Stage must be an ASCII path. Use -Stage C:\AndroidBuild\PlayerStudio' }
if (Test-Path -LiteralPath $Stage) { throw 'Stage must be a new, empty build directory' }
if (-not $env:ANDROID_SDK_ROOT) { throw 'Set ANDROID_SDK_ROOT to the Android SDK directory' }
if (-not (Test-Path -LiteralPath (Join-Path $Core 'app.py'))) { throw 'Public core source not found; pass -Core' }
$python = (Get-Command python -ErrorAction Stop).Source
$gradle = (Get-Command gradle -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $Stage | Out-Null
Get-ChildItem -LiteralPath $PSScriptRoot -Force | Where-Object { $_.Name -notin @('.gradle','core','output','local.properties') } | Copy-Item -Destination $Stage -Recurse
& $python -B (Join-Path $Stage 'prepare_build.py') --sdk $env:ANDROID_SDK_ROOT --core $Core
if ($LASTEXITCODE -ne 0) { throw 'Asset or codec build failed' }
& $gradle -p $Stage --no-daemon --console=plain "-PstudioBuildPython=$python" :app:assembleRelease
if ($LASTEXITCODE -ne 0) { throw 'Gradle build failed' }
$out = Join-Path $PSScriptRoot 'output'
New-Item -ItemType Directory -Path $out -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Stage 'app/build/outputs/apk/release/app-release-unsigned.apk') -Destination $out
Write-Host "Unsigned APK: $out\app-release-unsigned.apk"
Write-Host "Build directory (may be removed after checking): $Stage"
