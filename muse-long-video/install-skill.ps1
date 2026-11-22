param([switch]$NoOpen)
$ErrorActionPreference='Stop'
$homeDir=[IO.Path]::GetFullPath($(if($env:CODEX_HOME){$env:CODEX_HOME}else{Join-Path $env:USERPROFILE '.codex'}))
$src=(Resolve-Path -LiteralPath $PSScriptRoot).ProviderPath
$dst=[IO.Path]::GetFullPath((Join-Path $homeDir 'skills\muse-long-video'))
$pref=Join-Path $homeDir 'muse-long-video.local.json'
$local=Join-Path $dst 'windows\studio\settings.local.json'
$shortcut=Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Muse Review Studio.lnk'
$backupRoot=[IO.Path]::GetFullPath((Join-Path $homeDir 'skill-backups'))
$stagingRoot=[IO.Path]::GetFullPath((Join-Path $homeDir 'skill-staging'))
$tag=[guid]::NewGuid().ToString('N')
$stage=Join-Path $stagingRoot "muse-$tag"
$backup=Join-Path $backupRoot "muse-long-video-$tag"
$newPlaced=$false
$activationStarted=$false
$stopped=$null

function Restore-File([string]$File,[string]$Bytes) {
 if($null -ne $Bytes -and $Bytes.Length){[IO.File]::WriteAllBytes($File,[Convert]::FromBase64String($Bytes))}
 elseif([IO.File]::Exists($File)){[IO.File]::Delete($File)}
}
function Find-Studio {
 $studioDirs=@((Join-Path $dst 'windows\studio'))
 if($oldEntry){$studioDirs+=Split-Path ([IO.Path]::GetFullPath($oldEntry))}
 $found=@()
 foreach($proc in (Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")){
  if(!$proc.CommandLine){continue}
  foreach($dir in ($studioDirs|Select-Object -Unique)){
   $server=Join-Path $dir 'server.py'
   if($proc.CommandLine -notmatch ('(?:^|[\s"])'+[Regex]::Escape($server)+'(?:$|[\s"])')){continue}
   $listener=@(Get-NetTCPConnection -OwningProcess $proc.ProcessId -State Listen -ErrorAction SilentlyContinue|Where-Object LocalAddress -eq '127.0.0.1')
   if($listener.Count -ne 1){throw '工作台正在启动或退出，请稍后再安装。'}
   $port=$listener[0].LocalPort;$base="http://127.0.0.1:$port"
   $cat=Invoke-RestMethod "$base/api/projects" -TimeoutSec 3
   if($cat.service -ne 'muse-review'){throw '当前工作台身份无法核对，请关闭工作台后再安装。'}
   foreach($item in $cat.projects){
    $project=Invoke-RestMethod "$base/api/projects/$($item.id)" -TimeoutSec 3
    if(@($project.segments|Where-Object {$_.job.status -in @('queued','preparing','submitting','running')}).Count){throw '有视频生成任务正在运行，请等完成后再安装。'}
   }
   if(@(Get-NetTCPConnection -OwningProcess $proc.ProcessId -State Established -ErrorAction SilentlyContinue).Count){throw '工作台仍在处理请求，请等导出、配音或导入完成后再安装。'}
   $found+=[PSCustomObject]@{Id=$proc.ProcessId;Port=$port;Dir=$dir;Python=$proc.ExecutablePath}
   break
  }
 }
 if($found.Count -gt 1){throw '检测到多个工作台服务，请先关闭多余实例后再安装。'}
 if($found.Count){return $found[0]}
}
function Start-Studio([string]$Python,[string]$Dir,[int]$Port,[bool]$Show=$false) {
 $before=$env:MUSE_STUDIO_PORT
 try{
  $env:MUSE_STUDIO_PORT="$Port"
  $argsList=@('-B',(Join-Path $Dir 'launch.py'))
  if(!$Show){$argsList+='--no-browser'}
  & $Python @argsList
  if($LASTEXITCODE){throw '工作台恢复启动失败。'}
 }finally{$env:MUSE_STUDIO_PORT=$before}
}

[IO.Directory]::CreateDirectory($homeDir)|Out-Null
try{
 $guard=[IO.File]::Open((Join-Path $homeDir 'muse-long-video.install.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::Write,[IO.FileShare]::None)
}catch{throw '另一个安装程序正在运行，或当前用户没有写入权限。'}
try{
 $same=$src -eq $dst
 $prefBefore=if([IO.File]::Exists($pref)){[Convert]::ToBase64String([IO.File]::ReadAllBytes($pref))}
 $oldEntry=if($prefBefore){([IO.File]::ReadAllText($pref)|ConvertFrom-Json).review_studio}
 $localBefore=if([IO.File]::Exists($local)){[Convert]::ToBase64String([IO.File]::ReadAllBytes($local))}
 $shortcutBefore=if([IO.File]::Exists($shortcut)){[Convert]::ToBase64String([IO.File]::ReadAllBytes($shortcut))}
 $replacing=(!$same -and [IO.Directory]::Exists($dst)) -or ($oldEntry -and [IO.Path]::GetFullPath($oldEntry) -ne (Join-Path $dst 'windows\studio\Open-Muse-Review.cmd'))
 if($replacing){$null=Find-Studio}
 if(!$same){
  [IO.Directory]::CreateDirectory($stage)|Out-Null
  [IO.Directory]::CreateDirectory((Split-Path $dst))|Out-Null
  foreach($name in @('SKILL.md','scripts','references','assets','agents','windows','安装Skill.cmd','install-skill.ps1')){
   Copy-Item -LiteralPath (Join-Path $src $name) -Destination $stage -Recurse
  }
  if($localBefore){[IO.File]::WriteAllBytes((Join-Path $stage 'windows\studio\settings.local.json'),[Convert]::FromBase64String($localBefore))}
  & "$stage\windows\runtime\python.exe" -B "$stage\windows\base_install.py"
  if($LASTEXITCODE){throw "基础组件准备失败；旧 Skill 保持可用。"}
  & "$stage\windows\runtime\python.exe" -B -c "import av,PIL.Image,imageio_ffmpeg,subprocess;subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-version'],stdout=subprocess.DEVNULL,check=True)"
  if($LASTEXITCODE){throw '新安装包的视频组件校验失败。'}
 }
 # Work out whether an existing process needs replacement before changing its files or preferences.
 if($replacing){
  $running=Find-Studio
  if($running){
   Stop-Process -Id $running.Id -ErrorAction Stop
   Wait-Process -Id $running.Id -Timeout 12 -ErrorAction SilentlyContinue
   if(Get-Process -Id $running.Id -ErrorAction SilentlyContinue){throw '工作台仍在运行，请稍后重试。'}
   $stopped=$running
  }
 }
 if(!$same){
  if([IO.Directory]::Exists($dst)){
   [IO.Directory]::CreateDirectory($backupRoot)|Out-Null
   [IO.Directory]::Move($dst,$backup)
  }
  [IO.Directory]::Move($stage,$dst);$newPlaced=$true
 }
 $activationStarted=$true
 & "$dst\windows\runtime\python.exe" -B "$dst\windows\activate.py" --no-open
 if($LASTEXITCODE){throw '工作台激活失败，正在恢复之前的安装。'}
 if($stopped){Start-Studio "$dst\windows\runtime\python.exe" "$dst\windows\studio" $stopped.Port (!$NoOpen)}
 elseif(!$NoOpen){& "$dst\windows\runtime\python.exe" -B "$dst\windows\studio\launch.py";if($LASTEXITCODE){throw '工作台启动失败。'}}
}catch{
 $failure=$_
 if($newPlaced -and [IO.Directory]::Exists($dst)){[IO.Directory]::Move($dst,(Join-Path $stagingRoot "failed-$tag"))}
 if([IO.Directory]::Exists($backup)){[IO.Directory]::Move($backup,$dst)}
 if($activationStarted){
  Restore-File $pref $prefBefore
  if($same){Restore-File $local $localBefore}
  if($env:MUSE_NO_SHORTCUT -ne '1'){Restore-File $shortcut $shortcutBefore}
 }
 if($stopped){Start-Studio $stopped.Python $stopped.Dir $stopped.Port}
 throw $failure
}finally{$guard.Dispose()}
