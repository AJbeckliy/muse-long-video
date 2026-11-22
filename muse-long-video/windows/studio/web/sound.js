let soundEpoch = 0;
let dialogEpoch = 0;
let voiceContext = null;
const wantsClean = () => $("clean-sound").checked;
function soundTake() {
  const epoch = ++soundEpoch;
  const source = takeURL() + "/video";
  $("sound-status").textContent = wantsClean() ? "正在准备去配乐预览…" : "原声";
  if (!wantsClean() || (state.project.dub_ref && !state.canDub)) {
    $("sound-status").textContent = "原声";
    return;
  }
  api(projectURL() + "/audio-process", {kind:"take", id:state.take.id, mode:"clean"}).then(result => {
    if (epoch !== soundEpoch || !state.take || source !== takeURL()+"/video") return;
    const player = $("player");
    const time = player.currentTime;
    const playing = !player.paused;
    player.src = result.url;
    player.addEventListener("loadedmetadata", () => {
      if (epoch !== soundEpoch) return;
      player.currentTime = Math.min(time,player.duration);
      if (playing) player.play().catch(()=>{});
    }, {once:true});
    $("sound-status").textContent = state.project.dub_ref ? "参考音色重配 · 已对齐" : "去配乐预览";
  }).catch(e => { if (epoch === soundEpoch) $("sound-status").textContent = "当前播放原声 · " + e.message; });
}
$("clean-sound").onchange = () => {
  if (!state.take) return;
  $("player").src = takeURL()+"/video?track=source";
  soundTake();
};
async function soundDialog(url) {
  const epoch = ++dialogEpoch;
  const match = url.match(/^(.*)\/(outputs|seams)\/([a-f0-9]{16})$/);
  const output = state.project?.outputs.find(o=>o.id===match?.[3]);
  if (!match || !wantsClean() || output?.audio_label || (match[2]==="seams" && state.project.dub_ref)) return;
  $("media-caption").hidden=false;
  $("media-caption").textContent="正在准备去配乐版…";
  try {
    const processed = await api(match[1]+"/audio-process",{kind:output?"output":"seam",id:match[3],mode:"clean"});
    if (epoch!==dialogEpoch || !$("media-dialog").open) return;
    $("dialog-player").src=processed.url;
    $("media-caption").textContent="去配乐 · 保留对白和场景声";
    $("media-download").href=processed.url;
    if(output) {state.project=await api(match[1]); renderSidebar();}
  } catch(e) { if(epoch===dialogEpoch) $("media-caption").textContent="当前播放原声 · "+e.message; }
}
$("media-dialog").addEventListener("close",()=>{if(!$("media-dialog").open){dialogEpoch++;voiceContext=null;}});
async function configureDialogue(enabled) {
  await withBusy(async()=>{
    const project=projectURL(), revision=state.project.rev;
    let ref=null;
    if(enabled){
      const file=$("dub-reference").files[0];
      if(!file)throw new Error("请选择 WAV 或 MP3 参考人声。");
      ref=(await api(project+"/voice-reference",file)).ref;
    }
    $("dub-note").textContent=enabled?"正在生成对白并对齐现有分段…":"正在恢复…";
    try {
      state.project=await api(project+"/dialogue-track",{rev:revision,ref});
      selectSegment(state.index);
    } finally { showDubStatus(); }
  });
}
function showDubStatus(){
  const enabled=Boolean(state.project?.dub_ref);
  $("dub-settings").hidden=!state.canDub && !enabled;
  $("dub-reference").closest("label").hidden=!state.canDub;
  $("dub-on").hidden=!state.canDub;
  $("dub-note").textContent=enabled && !state.canDub ? "重配组件暂不可用，当前预览原声。恢复原对白后即可继续剪辑。" :
    enabled ? "已启用。连播和合成使用分段重配轨，取消去配乐勾选可对照原声。" : "选参考人声后，逐句重配并对齐到每段原视频。";
  $("dub-off").hidden=!state.project?.dub_ref;
}
$("dub-on").onclick=()=>configureDialogue(true);
$("dub-off").onclick=()=>configureDialogue(false);
