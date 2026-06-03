param(
  [string]$OutZip = "dist\FLEX_Coach_SharePoint_Package.zip",
  [string]$SharepointZipHint = "<PASTE_SHAREPOINT_ZIP_URL_OR_LEAVE_BLANK>"
)
$ErrorActionPreference="Stop"
New-Item -ItemType Directory -Force -Path (Split-Path $OutZip) | Out-Null

# Minimal package tree
$pkg = "FLEX_Coach_SharePoint_Package"
Remove-Item -Recurse -Force $pkg -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$pkg\app\scripts","$pkg\resources\models","$pkg\docs" | Out-Null

# Copy scripts & docs
Copy-Item "app\scripts\*.sh" "$pkg\app\scripts\" -Force
Copy-Item "docs\*.md"        "$pkg\docs\" -Force

# Insert Start-FLEXCoach.sh stub that calls our scripts post-install
@"
#!/usr/bin/env bash
set -euo pipefail
echo "=== FLEX Coach Installer (Lite 2GB profile) ==="
# ... your existing installer steps (apt, build llama.cpp/whisper.cpp) ...
echo "Applying 2GB profile (tiny models + config) ..."
bash app/scripts/get_models_2gb.sh
bash app/scripts/patch_2gb_config.sh
echo "Self-test bundle ..."
bash app/scripts/capture_artifacts.sh || true
echo "Done."
"@ | Set-Content -Encoding UTF8 "$pkg\Start-FLEXCoach.sh"

# Zip it
if(Test-Path $OutZip){ Remove-Item $OutZip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($pkg, $OutZip)
Write-Host "Created $OutZip"
