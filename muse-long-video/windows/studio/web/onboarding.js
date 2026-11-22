function revealProtocol() {
  $("api-fields").hidden=$("backend-choice").value!=="api";
  $("ark-fields").hidden=$("api-protocol").value!=="ark";
  $("profile-field").hidden=!$("ark-fields").hidden;
}
function openOnboarding(){
  $("backend-choice").value=state.provider==="api"?"api":"starcanvas";
  $("api-base").value="";
  $("api-model").value="";
  $("api-profile").value="";
  $("api-secret").value="";
  $("onboard-status").textContent="";
  $("audio-choice").value="";
  revealProtocol();
  if(!$("components-dialog").open)$("components-dialog").showModal();
}
$("backend-choice").onchange=revealProtocol;
$("api-protocol").onchange=revealProtocol;
$("onboard").onsubmit=async(event)=>{
  event.preventDefault();
  const button=event.target.querySelector('button[type="submit"]');
  button.disabled=true;
  try{
    const provider=$("backend-choice").value;
    const data={provider,audio:$("audio-choice").value};
    if(provider==="api"){
      data.key=$("api-secret").value;
      data.protocol=$("api-protocol").value;
      // Saved API credentials stay in Windows. Keep them when only changing audio.
      if(!data.key && state.savedApi && !$("api-base").value && !$("api-model").value && !$("api-profile").files.length)data.reuse=true;
      else if(data.protocol==="ark"){data.base=$("api-base").value;data.model=$("api-model").value;}
      else {const file=$("api-profile").files[0];if(!file)throw new Error("请选择接口配置 JSON。");data.profile=JSON.parse(await file.text());}
    }
    $("onboard-status").textContent="正在保存设置…";
    const result=await api("/api/provider",data);
    state.provider=result.provider;state.selection=result.selection;state.canConnect=result.can_generate;state.savedApi=result.saved_api;
    $("api-secret").value="";$("components-dialog").close();
    if(state.project){state.project=await api(projectURL());selectSegment(state.index);}
    notify(result.message || "设置已保存。");
    refreshConnection(false).catch(()=>{});
  }catch(e){$("onboard-status").textContent=e.message;}
  finally{button.disabled=false;}
};
document.querySelectorAll('[data-close="components-dialog"]').forEach(button=>{
  button.addEventListener("click",()=>api("/api/onboard-dismiss",{}).catch(e=>notify(e.message,true)));
});
