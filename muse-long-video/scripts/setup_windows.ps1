# Windows x64 interactive installer. No generation or API payment.
param([ValidateSet('starcanvas','api','defer')][string]$Backend)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$skillSource = Split-Path -Parent $PSScriptRoot
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$destination = Join-Path $codexRoot 'skills\muse-long-video'
$config = Join-Path $codexRoot 'config.toml'
Write-Host 'Muse 长视频安装助手：星幕画布 / 自带 API（Windows）' -ForegroundColor Cyan
$savedSettings = Join-Path $codexRoot 'muse-long-video.local.json'
if (!$backend -and (Test-Path -LiteralPath $savedSettings)) {
    $saved = Get-Content -LiteralPath $savedSettings -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($saved.backend -in @('starcanvas','api')) {
        $backend = $saved.backend
        Write-Host ('沿用已有通道：' + $backend)
    }
}
if (!$backend) {
    $choice = Read-Host '请选择：1 星幕画布；2 自己的 API；3 仅安装，稍后选择'
    switch ($choice) { '1' {$backend='starcanvas'} '2' {$backend='api'} '3' {$backend='defer'} default {throw '请输入1、2或3后重新运行。'} }
}
Write-Host '本助手安装 Skill 和独立剪辑环境；仅星幕模式配置 MCP。不会生成视频或扣费。'
if ((Read-Host '输入 y 开始安装，其他输入退出 [y/N]') -notmatch '^[yY]$') { exit 0 }
Add-Type -AssemblyName System.Windows.Forms
if ($backend -eq 'starcanvas') {
    Write-Host '星幕下载：https://pan.quark.cn/s/cf3c1e40528d#/list/share'
    Write-Host '请使用自己星幕提供的本机配对信息；已有连接会复用。'
    $pick = New-Object System.Windows.Forms.OpenFileDialog
    $pick.Title = '选择已经安装好的 SynMewInfiniteCanvas.exe'
    $pick.Filter = 'SynMew executable|SynMewInfiniteCanvas.exe|Executable|*.exe'
    if ($pick.ShowDialog() -ne 'OK') { exit 0 }
    $exe = $pick.FileName
    $port = Read-Host '输入星幕提供的本机 MCP 端口（常见值18765）'
}
$folder = New-Object System.Windows.Forms.FolderBrowserDialog
$folder.Description = '选择媒体存储目录（新项目、中间文件、成片放在这里）'
if ($folder.ShowDialog() -ne 'OK') { exit 0 }
$workspace = $folder.SelectedPath
$python = Get-Command python -ErrorAction SilentlyContinue
if (!$python) { throw 'Install Python 3.10 or 3.11 x64 from https://www.python.org/downloads/windows/ and rerun.' }
$pythonExe = $python.Source
& $pythonExe -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
if ($LASTEXITCODE -ne 0) { throw 'A working Python 3.10+ is required.' }
$runtime = Join-Path $env:LOCALAPPDATA 'MuseLongVideo\venv'
$venvPython = Join-Path $runtime 'Scripts\python.exe'
if (!(Test-Path -LiteralPath $venvPython)) {
    & $pythonExe -m venv $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Could not create private Python environment.' }
}
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $skillSource 'assets\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; no MCP configuration changed.' }
# The Python helper validates existing configuration before any configuration write.
if ([IO.Path]::GetFullPath($skillSource) -ne [IO.Path]::GetFullPath($destination)) {
    if (Test-Path -LiteralPath $destination) {
        $backupRoot = Join-Path $codexRoot 'skill-backups'
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        $backup = Join-Path $backupRoot ('muse-long-video-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
        Copy-Item -LiteralPath $destination -Destination $backup -Recurse
    }
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    foreach ($name in @('SKILL.md','agents','assets','references','scripts')) {
        Copy-Item -LiteralPath (Join-Path $skillSource $name) -Destination $destination -Recurse -Force
    }
}
if ($backend -eq 'starcanvas') {
    & $venvPython (Join-Path $destination 'scripts\setup_synmew.py') --config $config --exe $exe --workspace $workspace --port $port --apply --check --probe
    if ($LASTEXITCODE -ne 0) { throw '连接检查未完成，请核对星幕运行状态及本机配对信息，不要直接生成。' }
    Write-Host '星幕连接检查通过，保持星幕运行。' -ForegroundColor Green
} else {
    & $venvPython (Join-Path $destination 'scripts\setup_backend.py') --config-dir $codexRoot --workspace $workspace --backend $backend --apply
    if ($LASTEXITCODE -ne 0) { throw '无法保存本机设置。' }
    Write-Host '共享文件安装完成。API地址、模型及兼容性还需在制作前核验；未配置星幕。' -ForegroundColor Green
}
Write-Host '把安装结果交给当前助手，继续所选通道的只读检查；客户端尚未发现新Skill/MCP时再重新加载。'
Read-Host '按回车结束'
