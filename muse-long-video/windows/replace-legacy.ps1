param([string]$Prior,[int]$Port)
$ErrorActionPreference='Stop'
$base="http://127.0.0.1:$Port"
try {$catalog=Invoke-RestMethod "$base/api/projects" -TimeoutSec 2}catch{return}
if($catalog.service -ne 'muse-review' -or $catalog.provider){return}
$expected=Join-Path (Split-Path $Prior) 'server.py'
$listener=Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if(!$listener){return}
$process=Get-CimInstance Win32_Process -Filter "ProcessID=$($listener.OwningProcess)"
if(!$process.CommandLine -or !$process.CommandLine.Contains($expected)){return}
foreach($item in $catalog.projects){
 $p=Invoke-RestMethod "$base/api/projects/$($item.id)"
 if(@($p.segments|Where-Object {$_.job.status -in @('queued','preparing','submitting','running')}).Count){throw '旧版有任务在运行。请等任务完成后再打开新版工作台。'}
}
Stop-Process -Id $listener.OwningProcess
