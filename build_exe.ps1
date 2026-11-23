# Build standalone native desktop TuxHarbor.exe locally on Windows using an isolated .venv
$ErrorActionPreference = "Stop"

Write-Host "=== Building TuxHarbor.exe (Native Desktop, Windowed) ===" -ForegroundColor Cyan

if (-not (Test-Path ".venv")) {
    Write-Host "Creating isolated build virtual environment (.venv)..."
    py -m venv .venv
}

$venvPy = ".\.venv\Scripts\python.exe"
Write-Host "Installing CustomTkinter and PyInstaller in .venv..."
& $venvPy -m pip install --upgrade pip "customtkinter==6.0.0" "pyinstaller==6.22.3"

Write-Host "Running unit & security tests before packaging..."
& $venvPy -m unittest discover -s tests -v

Write-Host "Compiling standalone single-file windowed TuxHarbor.exe..."
& $venvPy -m PyInstaller `
    --onefile `
    --windowed `
    --clean `
    --noconfirm `
    --name TuxHarbor `
    --collect-all customtkinter `
    --add-data "tuxharbor\data;tuxharbor\data" `
    main.py

if (Test-Path "dist\TuxHarbor.exe") {
    $sizeMB = [math]::Round((Get-Item "dist\TuxHarbor.exe").Length / 1MB, 2)
    Write-Host "`nSUCCESS! Built dist\TuxHarbor.exe ($sizeMB MB)" -ForegroundColor Green
} else {
    throw "Build failed: dist\TuxHarbor.exe not found."
}
