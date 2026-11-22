"use strict";

const $ = (id) => document.getElementById(id);
const state = { token: "", canConnect: false, project: null, index: 0, take: null, frame: 0, first: 0, last: 0, busy: false };
const activeJobs = new Set(["queued", "preparing", "submitting", "running"]);
let toastTimer;
let frameTimer;
let confirmAction;

function notify(message, error = false) {
  const toast = $("toast");
  toast.classList.toggle("error", error);
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, error ? 8500 : 4000);
}

async function api(path, data) {
  const options = data === undefined ? {} : {
    method: "POST",
    headers: { "X-Muse-Review": state.token, "Content-Type": data instanceof File ? "application/octet-stream" : "application/json" },
    body: data instanceof File ? data : JSON.stringify(data),
  };
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作未完成。");
  return result;
}

function generationReady() {
  return state.canConnect && !state.project.requires_rebind && state.project.mode!=="demo" && (state.project.mode===state.provider || !state.project.segments.some(s=>s.job));
}
function providerName(){return state.provider==="api"?"自带 API":"星幕";}
function projectURL() { return `/api/projects/${state.project.id}`; }
function part() { return state.project.segments[state.index]; }
function following() { return state.project.segments[state.index + 1]; }
function previous() { return state.project.segments[state.index - 1]?.approval; }
function locked() { return state.project.segments.some((segment) => activeJobs.has(segment.job?.status)); }
function reviewed(segment) { return segment.approval && !segment.review; }
function previousReady() { return state.project.segments.slice(0, state.index).every(reviewed); }
function joinMode() { return following() ? document.querySelector('input[name="join"]:checked').value : "end"; }
function fps() {
  const [number, divisor = 1] = state.take.fps.split("/").map(Number);
  return number / divisor;
}
function takeURL() { return `${projectURL()}/segments/${state.index}/takes/${state.take.id}`; }

function setProjectPicker(projects) {
  const picker = $("projects");
  picker.replaceChildren();
  for (const item of projects) picker.add(new Option(item.title, item.id));
  picker.hidden = !projects.length;
}

async function loadProject(id) {
  const project = await api(`/api/projects/${id}`);
  $("reload-review").hidden = true;
  state.project = project;
  localStorage.setItem("muse-review-project", project.id);
  $("projects").value = project.id;
  $("workspace").hidden = false;
  $("welcome").hidden = true;
  selectSegment(0);
}

function statusOf(segment, index) {
  if (activeJobs.has(segment.job?.status)) return "生成中";
  if (segment.job?.status === "unknown") return "待查询";
  if (segment.review.startsWith("上游")) return "待复核接缝";
  if (segment.approval && segment.job?.status === "done" && segment.takes.at(-1)?.id !== segment.approval.take) return "有新版本待审核";
  if (segment.approval) return "已通过";
  if (segment.takes.length) return "待审核";
  if (segment.job?.status === "failed") return "生成未完成";
  if (index && !state.project.segments[index - 1].approval) return "等待上一段";
  return "待生成";
}

function showMedia(title, url, details = "", downloadName = "") {
  const video = $("dialog-player");
  $("media-title").textContent = title;
  $("media-caption").textContent = details;
  $("media-caption").hidden = !details;
  const link = $("media-download");
  link.hidden = !downloadName;
  link.href = url;
  link.download = downloadName;
  video.src = url;
  if (!$("media-dialog").open) $("media-dialog").showModal();
  soundDialog(url);
}

function renderSidebar() {
  const accepted = state.project.segments.filter(reviewed).length;
  $("progress").textContent = `${accepted} / ${state.project.segments.length}`;
  $("segments").replaceChildren();
  state.project.segments.forEach((segment, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "segment";
    if (state.index === index) button.setAttribute("aria-current", "step");
    const number = document.createElement("span");
    number.className = "segment-num";
    number.textContent = String(index + 1).padStart(2, "0");
    const title = document.createElement("strong");
    title.textContent = `第 ${index + 1} 段`;
    const status = document.createElement("small");
    if (reviewed(segment)) status.className = "approved";
    status.textContent = statusOf(segment, index);
    button.append(number, title, status);
    button.addEventListener("click", () => { if (!state.busy) selectSegment(index); });
    $("segments").append(button);
  });
  $("outputs").replaceChildren();
  [...state.project.outputs].reverse().forEach((output, index) => {
    const button = document.createElement("button");
    const seconds = output.seconds.toFixed(2).replace(/0$/, "").replace(/\.0$/, "");
    button.className = "output-link";
    button.type = "button";
    button.textContent = `${output.audio_label || "合成版"} ${state.project.outputs.length - index} · ${seconds} 秒`;
    button.addEventListener("click", () => showMedia(button.textContent, `${projectURL()}/outputs/${output.id}`,
      `${output.frames} 帧 · ${output.output}`, `Muse-${output.id}.mp4`));
    $("outputs").append(button);
  });
  if (state.project.original) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "output-link";
    button.textContent = "历史成片 · 15.5 秒";
    button.addEventListener("click", () => showMedia(button.textContent, `${projectURL()}/original`));
    $("outputs").append(button);
  } else if (!state.project.outputs.length) {
    const note = document.createElement("p");
    note.className = "caption";
    note.textContent = "通过最后一段后合成";
    $("outputs").append(note);
  }
}

function renderNotice() {
  const notice = $("notice");
  const message = part().job?.status !== "done" ? part().job?.message : "";
  notice.textContent = part().review || message || "";
  notice.hidden = !notice.textContent;
}

function renderActions() {
  const live = generationReady();
  const next = following();
  const busy = state.busy || locked();
  const canQueueNext = live && next && next.prompt && !next.takes.length && next.job?.status !== "unknown";
  const approve = $("approve");
  approve.hidden = !state.take;
  approve.disabled = busy || !previousReady();
  approve.textContent = !next ? "通过并合成" : canQueueNext ? "通过并生成下一段" : "确认本段剪点";
  const generate = $("generate");
  generate.hidden = !live || part().job?.status === "unknown";
  generate.disabled = busy || !previousReady();
  generate.textContent = state.take ? "只重跑本段" : "生成本段";
  const check = $("check-job");
  const missingReceipt=Boolean(part().job?.missing_receipt);
  check.hidden = part().job?.status !== "unknown" || !part().job.card || missingReceipt;
  check.disabled = busy;
  for (const id of ["restore-receipt","confirm-not-submitted"]) {
    $(id).hidden=!missingReceipt; $(id).disabled=busy;
  }
  $("rebind-api").hidden=!state.project.requires_rebind;
  $("rebind-api").disabled=busy || state.project.segments.some(s=>s.job?.status==="unknown");
  $("save-prompt").disabled = busy;
  $("opening-file").disabled = busy;
  $("clear-opening").disabled = busy;
  $("seam").disabled = state.busy;
  $("projects").disabled = state.busy;
  $("new-project").disabled = state.busy;
  const hint = $("action-hint");
  hint.textContent = !previousReady() ? "请先确认前面的片段。" : state.take && state.frame !== state.last && !$("frame-image").hidden ?
    `当前结束帧是 ${state.last}。要用正在查看的帧，请点「设为结束帧」。` : state.project.requires_rebind ? "当前 API 配置已更换。请确认是否用于这个项目的后续生成。" : !live ? (state.project.mode==="demo"?"本地演练使用历史素材。":"请在组件设置中选回本项目的生成通道。") :
    next && !next.takes.length && !next.prompt ? "填好下一段提示词后即可生成。" : "";
  hint.hidden = !hint.textContent;
}

function renderPrompt() {
  showDubStatus();
  const open = state.project.mode !== "demo";
  $("prompt-panel").hidden = !open;
  $("prompt-panel").open = open && !part().takes.length;
  $("prompt").value = part().prompt;
  $("duration").value = part().duration || 10;
  const inherit = previous()?.mode === "continue";
  $("opening-panel").hidden = inherit;
  $("opening-help").textContent = state.index ? "切新镜头时，可以给本段单独指定开场参考图。" : "可以指定第一段的开场参考图。";
  $("opening-preview").hidden = !part().opening;
  if (part().opening) $("opening-preview").src = `${projectURL()}/segments/${state.index}/opening?rev=${state.project.rev}`;
  $("clear-opening").hidden = !part().opening;
}

function selectSegment(index, preferredTake) {
  state.index = index;
  clearTimeout(frameTimer);
  $("project-title").textContent = state.project.title;
  $("segment-title").textContent = `第 ${index + 1} 段`;
  const versions = $("versions");
  versions.replaceChildren();
  for (const take of part().takes) versions.add(new Option(take.label, take.id));
  const chosen = part().takes.find((take) => take.id === (preferredTake || part().approval?.take)) || part().takes.at(-1) || null;
  // The historical edit is the starting point of the demo.
  const initial = state.project.mode === "demo" && !preferredTake && !part().approval ? part().takes[0] : chosen;
  loadTake(initial);
  renderPrompt();
  renderNotice();
  renderSidebar();
  renderActions();
}

function loadTake(take) {
  clearTimeout(frameTimer);
  state.take = take;
  for (const id of ["version-panel", "trim-panel", "timeline", "player"]) $(id).hidden = !take;
  $("join-panel").hidden = !take || !following();
  $("seam").hidden = !take || !previous();
  $("frame-image").hidden = true;
  $("back-to-video").hidden = true;
  $("empty").hidden = Boolean(take);
  const video = $("player");
  video.pause();
  if (!take) {
    video.removeAttribute("src");
    video.load();
    $("empty-title").textContent = statusOf(part(), state.index);
    $("empty-note").textContent = part().job?.message || "生成后，视频会出现在这里供你预览。";
    return;
  }
  $("versions").value = take.id;
  const saved = part().approval?.take === take.id ? part().approval : null;
  [state.first, state.last] = saved ? [saved.first, saved.last] : take.bounds;
  const mode = saved && saved.mode === "cut" ? "cut" : "continue";
  document.querySelector(`input[name="join"][value="${mode}"]`).checked = true;
  $("scrubber").max = $("frame-number").max = take.frames - 1;
  $("source-duration").textContent = `原片 ${(take.frames / fps()).toFixed(2)} 秒`;
  video.src = `${takeURL()}/video?track=source`;
  soundTake();
  setFrame(state.first, false);
  paintThumbnails();
  paintTrim();
}

function paintThumbnails() {
  const thumbnails = $("thumbnails");
  thumbnails.replaceChildren();
  const max = state.take.frames - 1;
  const points = [...new Set([0, Math.round(max / 4), Math.round(max / 2), Math.round(max * .75), max, state.last, state.first])].sort((a, b) => a - b);
  for (const frame of points) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "thumbnail";
    button.dataset.frame = frame;
    button.setAttribute("aria-pressed", String(frame === state.frame));
    const img = document.createElement("img");
    img.alt = `第 ${frame} 帧`;
    img.src = `${takeURL()}/frame?index=${frame}&size=thumb`;
    const label = document.createElement("span");
    label.textContent = `${(frame / fps()).toFixed(2)}s`;
    button.append(img, label);
    button.addEventListener("click", () => setFrame(frame));
    thumbnails.append(button);
  }
}

function setFrame(index, showImage = true) {
  if (!state.take) return;
  state.frame = Math.min(state.take.frames - 1, Math.max(0, Math.round(index)));
  $("scrubber").value = $("frame-number").value = state.frame;
  $("timecode").textContent = `${(state.frame / fps()).toFixed(3)} 秒`;
  $("frame-count").textContent = `帧 ${state.frame} / ${state.take.frames - 1}`;
  $("prev-frame").disabled = state.frame === 0;
  $("next-frame").disabled = state.frame === state.take.frames - 1;
  for (const button of $("thumbnails").children) button.setAttribute("aria-pressed", String(Number(button.dataset.frame) === state.frame));
  if (showImage) {
    $("player").pause();
    const target = `${takeURL()}/frame?index=${state.frame}`;
    clearTimeout(frameTimer);
    frameTimer = setTimeout(() => {
      const image = $("frame-image");
      image.onload = () => {
        if (image.getAttribute("src") !== target) return;
        image.hidden = false;
        $("player").hidden = true;
        $("back-to-video").hidden = false;
        renderActions();
      };
      image.onerror = () => notify("这帧暂时无法读取。", true);
      image.src = target;
      if (image.complete && image.naturalWidth) image.onload();
    }, 45);
  }
}

function paintTrim() {
  $("inpoint").textContent = `帧 ${state.first} · ${(state.first / fps()).toFixed(3)}s`;
  $("outpoint").textContent = `帧 ${state.last} · ${(state.last / fps()).toFixed(3)}s`;
  const frames = state.last - state.first + 1;
  $("retained").textContent = `保留 ${frames} 帧 · ${(frames / fps()).toFixed(3)} 秒`;
  $("trim-warning").hidden = frames !== 1;
  $("reset-trim").hidden = frames === state.take.frames;
  paintNextReference();
}

function paintNextReference() {
  const show = state.take && joinMode() === "continue";
  $("next-reference").hidden = !show;
  if (show) {
    $("next-reference-img").src = `${takeURL()}/frame?index=${state.last}&size=thumb`;
    $("next-reference-label").textContent = `下一段参考 · 帧 ${state.last}`;
  }
}

function chooseBoundary(boundary) {
  if (boundary === "first" && state.frame > state.last || boundary === "last" && state.frame < state.first) {
    notify("入点需要在结束帧之前或同一帧。", true);
    return;
  }
  state[boundary] = state.frame;
  paintTrim();
  paintThumbnails();
  renderActions();
}

function draft() {
  return { take: state.take.id, first: state.first, last: state.last, mode: joinMode() };
}

async function withBusy(callback) {
  if (state.busy) return;
  state.busy = true;
  if (state.project) renderActions();
  try { await callback(); }
  catch (error) { notify(error.message, true); }
  finally {
    state.busy = false;
    if (state.project) renderActions();
  }
}

async function update(action, fields = {}) {
  state.project = await api(`${projectURL()}/review`, { rev: state.project.rev, index: state.index, action, selection:state.selection, ...fields });
}

function ask(title, detail, reference, action) {
  $("confirm-title").textContent = title;
  $("confirm-text").textContent = detail;
  $("confirm-reference").textContent = reference;
  $("confirm-yes").textContent="确认提交"+providerName();
  confirmAction = action;
  $("confirm-dialog").showModal();
}

function approveCurrent(confirmed) {
  return withBusy(async () => {
    const lastSegment = !following();
    const index = state.index;
    await update("approve", { ...draft(), confirmed });
    if (lastSegment) {
      selectSegment(index);
      const output = state.project.outputs.at(-1);
      showMedia(`合成完成 · ${output.seconds.toFixed(2)} 秒`, `${projectURL()}/outputs/${output.id}`,
        `${output.frames} 帧 · ${output.output}`, `Muse-${output.id}.mp4`);
      return;
    }
    selectSegment(index + 1);
    notify(confirmed ? "接点已确认，正在检查下一段的生成条件。" : "本段剪点已保存。");
  });
}

async function poll() {
  if (!state.project || state.busy) return;
  const id = state.project.id;
  try {
    const update = await api(projectURL());
    if (state.project.id !== id || state.busy || update.rev <= state.project.rev) return;
    const old = part();
    const nextPart = update.segments[state.index];
    const changed = JSON.stringify(old.approval) !== JSON.stringify(nextPart.approval)
      || old.review !== nextPart.review || old.prompt !== nextPart.prompt || old.duration !== nextPart.duration
      || old.opening !== nextPart.opening || state.project.dub_ref !== update.dub_ref;
    if (changed) {
      const bounds = old.approval?.take === state.take?.id && old.approval ? [old.approval.first, old.approval.last] : state.take?.bounds;
      const dirty = (bounds && (bounds[0] !== state.first || bounds[1] !== state.last))
        || (old.approval && state.take && (old.approval.take !== state.take.id || old.approval.mode !== joinMode()))
        || $("prompt").value !== old.prompt || Number($("duration").value) !== (old.duration || 10);
      if (dirty) {
        // Keep the old revision: the server will reject writes based on this draft.
        $("reload-review").hidden = false;
        return;
      }
      state.project = update;
      $("reload-review").hidden = true;
      selectSegment(state.index);
      return;
    }
    state.project = update;
    if (part().takes.length !== old.takes.length) selectSegment(state.index, part().takes.at(-1).id);
    else if (!state.take) selectSegment(state.index);
    else { renderSidebar(); renderNotice(); renderActions(); }
  } catch (error) { notify(error.message, true); }
}
$("reload-review").onclick = () => withBusy(async () => {
  const index = state.index;
  await loadProject(state.project.id);
  selectSegment(index);
});

$("projects").addEventListener("change", () => withBusy(() => loadProject($("projects").value)));
$("import-video").onchange = () => withBusy(async () => {
  const file=$("import-video").files[0];
  if (!file) return;
  try {
    state.project=await api(projectURL()+"/segments/"+state.index+"/import?rev="+state.project.rev,file);
    selectSegment(state.index,part().takes.at(-1).id);
    notify("视频已导入，可以选帧。");
  } finally { $("import-video").value=""; }
});
$("new-project").addEventListener("click", () => $("project-dialog").showModal());
$("create-project").addEventListener("submit", (event) => {
  event.preventDefault();
  withBusy(async () => {
    const count = Number($("new-count").value);
    const pieces = $("new-prompts").value.split(/^\s*---\s*$/m);
    if (pieces.length > count) throw new Error("分段提示词数量超过设定段数。");
    const result = await api("/api/projects", { title: $("new-title").value, ratio: $("new-ratio").value,
      prompts: Array.from({ length: count }, (_, i) => pieces[i] || "") });
    const list = await api("/api/projects");
    setProjectPicker(list.projects);
    $("project-dialog").close();
    $("create-project").reset();
    await loadProject(result.id);
  });
});
async function refreshConnection(showMessage) {
  const status = await api("/api/connection");
  $("connection").classList.toggle("ready", status.ready);
  $("connection").textContent = status.ready ? providerName()+"已配置" : "本地审片";
  if (showMessage) notify(status.message, state.canConnect && !status.ready);
}

$("connection").addEventListener("click", () => withBusy(() => refreshConnection(true)));
$("versions").addEventListener("change", () => { loadTake(part().takes.find((take) => take.id === $("versions").value)); renderActions(); });
$("scrubber").addEventListener("input", () => setFrame(Number($("scrubber").value)));
$("frame-number").addEventListener("change", () => setFrame(Number($("frame-number").value)));
$("prev-frame").addEventListener("click", () => setFrame(state.frame - 1));
$("next-frame").addEventListener("click", () => setFrame(state.frame + 1));
$("grab-frame").addEventListener("click", () => {
  const video = $("player");
  if (video.hidden) { $("back-to-video").click(); return; }
  setFrame(Math.floor(video.currentTime * fps() + 0.0001));
});
$("back-to-video").addEventListener("click", () => {
  const video = $("player");
  clearTimeout(frameTimer);
  $("frame-image").onload = null;
  $("frame-image").hidden = true;
  $("back-to-video").hidden = true;
  video.hidden = false;
  if (video.readyState) video.currentTime = state.frame / fps();
  renderActions();
});
$("set-in").addEventListener("click", () => chooseBoundary("first"));
$("set-out").addEventListener("click", () => chooseBoundary("last"));
$("reset-trim").addEventListener("click", () => {
  state.first = 0;
  state.last = state.take.frames - 1;
  setFrame(0);
  paintTrim();
  paintThumbnails();
  renderActions();
});
document.querySelectorAll('input[name="join"]').forEach((radio) => radio.addEventListener("change", paintNextReference));
$("seam").addEventListener("click", () => withBusy(async () => {
  notify("正在生成接缝预览…");
  const result = await api(`${projectURL()}/seam`, { ...draft(), index: state.index });
  showMedia(`第 ${state.index} 段 → 第 ${state.index + 1} 段`, `${projectURL()}/seams/${result.id}`, "播放上一段结尾和当前段开头，可同时检查声音。");
}));
$("approve").addEventListener("click", () => {
  if (generationReady() && following()?.prompt && !following().takes.length && following().job?.status !== "unknown") {
    const reference = joinMode() === "continue" ? `使用当前版本第 ${state.last} 帧作为续拍参考。` : "下一段独立生成，使用它单独设置的参考图（如有）。";
    ask("通过并生成下一段", `将提交第 ${state.index + 2} 段的一次视频生成，目标 ${following().duration || 10} 秒，按${providerName()}账户计费。`, reference, () => approveCurrent(true));
  } else approveCurrent(false);
});
$("generate").addEventListener("click", () => {
  const rerun = Boolean(state.take);
  const reference = previous()?.mode === "continue" ? `沿用上一段已确认的第 ${previous().last} 帧。` : "使用本段单独设置的参考图（如有）。";
  const duration = Number($("duration").value);
  if (!Number.isInteger(duration) || duration < 2 || duration > 10) { notify("单段目标时长请选择 2–10 秒。", true); return; }
  ask(rerun ? "只重跑本段" : "生成本段", `本次仅提交第 ${state.index + 1} 段的一次视频生成，目标 ${duration} 秒，按${providerName()}账户计费。`, reference, () => withBusy(async () => {
    if ($("prompt").value.trim() !== part().prompt || duration !== part().duration) {
      await update("save-prompt", { prompt: $("prompt").value, duration });
    }
    await update("generate", { confirmed: true });
    renderSidebar(); renderNotice();
  }));
});
$("check-job").addEventListener("click", () => withBusy(async () => {
  await update("check-job"); renderSidebar(); renderNotice();
}));
for(const action of ["restore-receipt","confirm-not-submitted","rebind-api"]){
  $(action).addEventListener("click",()=>withBusy(async()=>{
    let taskId="";
    if(action==="restore-receipt"){
      taskId=window.prompt("从供应商后台复制本段的原任务号。系统将查询并收集这次任务。")?.trim();
      if(!taskId)return;
    }else if(!window.confirm(action==="rebind-api"?"后续生成将使用当前保存的 API 账号和模型，确认更换？":"请先在供应商后台核对。如果已受理，请填写原任务号。确认这次请求未被受理？"))return;
    await update(action,{confirmed:true,task_id:taskId});renderSidebar();renderNotice();
  }));
}
$("confirm-yes").addEventListener("click", () => { $("confirm-dialog").close(); confirmAction?.(); });
$("save-prompt").addEventListener("click", () => withBusy(async () => {
  await update("save-prompt", { prompt: $("prompt").value, duration: Number($("duration").value) });
  notify("本段设置已保存。");
}));
$("opening-file").addEventListener("change", () => {
  const file = $("opening-file").files[0];
  if (!file) return;
  withBusy(async () => {
    state.project = await api(`${projectURL()}/segments/${state.index}/opening?rev=${state.project.rev}`, file);
    renderPrompt();
    $("prompt-panel").open = true;
    $("opening-file").value = "";
    notify("参考图已保存到本机。");
  });
});
$("clear-opening").addEventListener("click", () => withBusy(async () => {
  await update("clear-opening"); renderPrompt(); $("prompt-panel").open = true;
}));
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
$("media-dialog").addEventListener("close", () => {
  if ($("media-dialog").open) return;
  const player = $("dialog-player");
  player.pause(); player.removeAttribute("src"); player.load();
});
$("player").addEventListener("error", () => { if (state.take && $("player").currentSrc) notify("这段视频无法在当前浏览器播放。", true); });
document.addEventListener("keydown", (event) => {
  if (!state.take || ["INPUT", "TEXTAREA", "SELECT", "VIDEO", "BUTTON"].includes(event.target.tagName) || document.querySelector("dialog[open]")) return;
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  setFrame(state.frame + (event.key === "ArrowLeft" ? -1 : 1));
});

async function init() {
  const list = await api("/api/projects");
  state.token = list.token;
  state.provider=list.provider; state.selection=list.selection; state.canConnect=list.can_generate;state.savedApi=list.saved_api;
  $("components").hidden=!list.service;
  $("new-project").hidden = false;
  $("clean-sound").checked = Boolean(list.audio);
  $("clean-sound").disabled = !list.audio;
  state.canDub = Boolean(list.dub);
  if (!list.audio) $("clean-sound").title="可在安装目录按需安装声音组件";
  setProjectPicker(list.projects);
  if(list.sound_question && list.setup_available) openOnboarding();
  setInterval(poll, 2400);
  if (state.canConnect) refreshConnection(false).catch(() => {});
  if (!list.projects.length) { $("welcome").hidden = false; return; }
  const requested = new URLSearchParams(location.search).get("project");
  const linked = list.projects.find((item) => item.id === requested);
  const last = list.projects.find((item) => item.id === localStorage.getItem("muse-review-project"));
  await loadProject(linked?.id || last?.id || list.projects[0].id);
}

$("components").onclick=()=>openOnboarding();
document.querySelectorAll("[data-component]").forEach(button=>button.onclick=async()=>{
  try {await api("/api/setup",{component:button.dataset.component});$("components-dialog").close();notify("请在安装窗口中继续。");}
  catch(e){notify(e.message,true);}
});
window.addEventListener("DOMContentLoaded", () => {
  if (location.protocol === "file:") {
    location.replace("http://127.0.0.1:8786/" + location.search);
    return;
  }
  init().catch((error) => notify(error.message, true));
});
