#!/usr/bin/env pwsh
# go-proxy/build.ps1 — 一键构建 Go 反代可执行文件
# 用法: .\build.ps1
# 产出: go-proxy/go-proxy.exe (Windows) 或 go-proxy/go-proxy (Linux)

$ErrorActionPreference = "Stop"
$Version = "1.0.0"

Push-Location $PSScriptRoot

Write-Host "=== Misaka MediaFlow Go Proxy 构建 ===" -ForegroundColor Cyan
Write-Host "版本: $Version"

# 确保 Go 在 PATH 中（兼容自定义安装路径）
$goPaths = @("D:\go\bin", "C:\Go\bin", "C:\Program Files\Go\bin")
foreach ($p in $goPaths) {
    if (Test-Path "$p\go.exe") {
        $env:Path = "$p;$env:Path"
        break
    }
}
$env:GOPROXY = "https://goproxy.cn,direct"

# 检查 Go 环境
try {
    $goVer = & go version 2>&1
    Write-Host "Go 版本: $goVer" -ForegroundColor Green
} catch {
    Write-Host "错误: 未找到 Go 编译器，请先安装 Go (https://go.dev/dl/)" -ForegroundColor Red
    Pop-Location
    exit 1
}

# 下载依赖
Write-Host "`n[1/2] 下载依赖..." -ForegroundColor Yellow
go mod tidy
if ($LASTEXITCODE -ne 0) {
    Write-Host "go mod tidy 失败" -ForegroundColor Red
    Pop-Location
    exit 1
}

# 构建
Write-Host "[2/2] 编译中..." -ForegroundColor Yellow

$outputName = "go-proxy"
if ($env:OS -match "Windows") {
    $outputName = "go-proxy.exe"
}

go build -ldflags "-s -w -X main.Version=$Version" -o $outputName ./cmd/proxy/
if ($LASTEXITCODE -ne 0) {
    Write-Host "构建失败" -ForegroundColor Red
    Pop-Location
    exit 1
}

$size = [math]::Round((Get-Item $outputName).Length / 1MB, 1)
Write-Host "`n构建成功!" -ForegroundColor Green
Write-Host "  文件: $PSScriptRoot\$outputName ($size MB)"
Write-Host "  版本: $Version"

Pop-Location

