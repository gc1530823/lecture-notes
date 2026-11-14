# 쫑긋 강의노트 서버 (Windows): 필요한 프로그램을 winget 으로 설치하고 run.py 를 실행한다.
# 설치하는 것: Python 3.12, Node.js LTS, FFmpeg, cloudflared, Tailscale (이미 있으면 건너뜀)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Has($cmd) {
  $c = Get-Command $cmd -ErrorAction SilentlyContinue
  # Microsoft Store 의 가짜 python(설치 안내만 띄우는 것)은 없는 것으로 친다
  return ($null -ne $c) -and ($c.Source -notlike "*WindowsApps*")
}

function Ensure($cmd, $id, $label) {
  if (Has $cmd) { return }
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "[!] $label 이(가) 없어요. winget 이 없어 자동 설치를 못 해요. 직접 설치한 뒤 다시 실행해 주세요." -ForegroundColor Yellow
    exit 1
  }
  Write-Host "$label 설치 중… (처음 한 번)" -ForegroundColor Cyan
  winget install -e --id $id --silent --accept-source-agreements --accept-package-agreements | Out-Host
  Refresh-Path
  if (-not (Has $cmd)) {
    Write-Host "[!] $label 을(를) 설치했지만 아직 찾을 수 없어요. 이 창을 닫고 다시 실행해 주세요." -ForegroundColor Yellow
    exit 1
  }
}

Ensure "python" "Python.Python.3.12" "Python 3.12"
Ensure "node" "OpenJS.NodeJS.LTS" "Node.js"
Ensure "ffmpeg" "Gyan.FFmpeg" "FFmpeg"
Ensure "cloudflared" "Cloudflare.cloudflared" "cloudflared (무료 터널)"
# Tailscale: 바뀌지 않는 무료 주소. 설치가 안 돼도 임시 주소(cloudflared)로 켜지므로 멈추지 않는다
if (-not (Has "tailscale") -and -not (Test-Path "C:\Program Files\Tailscale\tailscale.exe") -and (Get-Command winget -ErrorAction SilentlyContinue)) {
  Write-Host "Tailscale 설치 중… (바뀌지 않는 무료 주소, 처음 한 번)" -ForegroundColor Cyan
  winget install -e --id Tailscale.Tailscale --silent --accept-source-agreements --accept-package-agreements | Out-Host
  Refresh-Path
}

# 우리 AI 파일(deploy\model)을 넣어 두었으면 Ollama 도 설치 (우리 AI 를 돌리는 프로그램)
if ((Test-Path "$PSScriptRoot\model\lecture-notes.gguf.part00") -and -not (Has "ollama") -and (Get-Command winget -ErrorAction SilentlyContinue)) {
  Write-Host "Ollama 설치 중… (우리 AI 를 돌리는 프로그램, 처음 한 번)" -ForegroundColor Cyan
  winget install -e --id Ollama.Ollama --silent --accept-source-agreements --accept-package-agreements | Out-Host
  Refresh-Path
}

& python "$PSScriptRoot\run.py" @args
