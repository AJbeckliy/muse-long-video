param([ValidateSet('none','clean','dub')][string]$Sound='none',[int]$Pairing=0)
$ErrorActionPreference='Stop'
try {
 if($Pairing){& "$PSScriptRoot\pair.ps1"}
 if($Sound -ne 'none'){
  $argsList=@('-B',"$PSScriptRoot\audio-setup.py")
  if($Sound -eq 'dub'){$argsList+='--full'}
  & "$PSScriptRoot\runtime\python.exe" @argsList
  if($LASTEXITCODE){throw '声音组件安装未完成，可以保留基础审片并稍后重试。'}
  & "$PSScriptRoot\Restart-Studio.cmd"
 }
}catch{Write-Host $_;Read-Host '按回车关闭';exit 1}
