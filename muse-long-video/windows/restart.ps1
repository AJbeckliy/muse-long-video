$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath "$PSScriptRoot\studio\settings.local.json" -Raw -Encoding UTF8|ConvertFrom-Json
$port=if($env:MUSE_STUDIO_PORT){[int]$env:MUSE_STUDIO_PORT}elseif($cfg.port){[int]$cfg.port}else{8786}
$l=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if(!$l){exit 0}
$p=Get-CimInstance Win32_Process -Filter "ProcessID=$($l.OwningProcess)"
$source=Join-Path $PSScriptRoot 'studio\server.py'
if(!$p.CommandLine.Contains($source)){throw '端口由其他程序占用，请先关闭原实例。'}
$u="http://127.0.0.1:$port";$catalog=Invoke-RestMethod "$u/api/projects"
if($catalog.service -ne 'muse-review'){throw '无法确认工作台身份'}
foreach($item in $catalog.projects){
 $project=Invoke-RestMethod "$u/api/projects/$($item.id)"
 if(@($project.segments|Where-Object {$_.job.status -in @('queued','preparing','submitting','running')}).Count){throw '有生成任务正在运行，请完成后重启。'}
}
Write-Host '请在所有导出、上传和配音完成后重启。'
if((Read-Host '现在重启工作台？ y/N') -ne 'y'){exit 1}
Stop-Process -Id $l.OwningProcess
