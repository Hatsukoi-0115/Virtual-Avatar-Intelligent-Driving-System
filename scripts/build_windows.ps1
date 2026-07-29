$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $ProjectRoot

try {
    Write-Host "Stopping running app..."
    Get-Process VirtualAvatarIntelligentDrivingSystem -ErrorAction SilentlyContinue |
        Stop-Process -Force

    Write-Host "Syncing uv environment..."
    uv sync --group dev

    Write-Host "Preparing Windows icon..."
    uv run python scripts/prepare_app_icon.py

    Write-Host "Building with PyInstaller..."
    uv run pyinstaller --clean --noconfirm VirtualAvatarIntelligentDrivingSystem.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code: $LASTEXITCODE"
    }

    if (Test-Path ".env") {
        $DistEnvPath = Join-Path "dist\VirtualAvatarIntelligentDrivingSystem" ".env"
        Copy-Item -LiteralPath ".env" -Destination $DistEnvPath -Force
        Write-Host "Copied local .env next to the exe."
    }

    Write-Host "Build completed: dist\VirtualAvatarIntelligentDrivingSystem\VirtualAvatarIntelligentDrivingSystem.exe"
}
finally {
    Pop-Location
}
