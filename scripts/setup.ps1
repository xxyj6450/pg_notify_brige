# 创建并激活虚拟环境，安装依赖（Windows PowerShell）

$ErrorActionPreference = "Stop"

$venv = ".venv"
$python = "python"

if (-not (Test-Path $venv)) {
    & $python -m venv $venv
}

$pip = Join-Path $venv "Scripts\pip.exe"
$py = Join-Path $venv "Scripts\python.exe"

& $pip install --upgrade pip
& $pip install -r requirements.txt
& $pip install -e .

Write-Host "Setup complete. Run with:"
Write-Host "  .\.venv\Scripts\python.exe -m pg_notify_bridge"
