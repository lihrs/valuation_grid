# ========================================
# valuation_grid 一键启动脚本
# Powershell: 右键 → 使用 PowerShell 运行
# ========================================

Write-Host "=== 停掉旧进程 ===" -ForegroundColor Cyan
Get-Process -Name python,cloudflared,node -ErrorAction SilentlyContinue | Stop-Process -Force
npx kill-port 8000 2>$null
Start-Sleep 2

Write-Host "=== 启动后端 API (port 8000) ===" -ForegroundColor Cyan
cd E:\Git\valuation_grid
$env:PYTHONPATH = "E:\Git\valuation_grid"
$env:HTTP_PROXY = "http://127.0.0.1:7892"
$env:HTTPS_PROXY = "http://127.0.0.1:7892"
Start-Process -NoNewWindow -FilePath "python" -ArgumentList "app.py"

Start-Sleep 4

Write-Host "=== 启动隧道 (固定URL) ===" -ForegroundColor Cyan
Start-Process -NoNewWindow -FilePath "npx" -ArgumentList "localtunnel --port 8000 --subdomain valuation-grid"

Start-Sleep 5

Write-Host "=== 验证 ===" -ForegroundColor Cyan
curl.exe -s http://localhost:8000/health 2>$null
Write-Host ""
Write-Host ""
Write-Host "前端: https://valuation-grid.loca.lt" -ForegroundColor Green
Write-Host "API:  https://valuation-grid.loca.lt/v1/valuation/state" -ForegroundColor Green
Write-Host "本地: http://localhost:8000" -ForegroundColor Green
Write-Host ""
