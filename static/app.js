const $ = id => document.getElementById(id);
const labels = {idle:'等待继续',queued:'排队中',running:'处理中',complete:'处理完成',error:'需要处理',interrupted:'上次处理已中断'};
let current = null, rows = [], dirty = false, onlyFlagged = false, loading = false, saving = false, playingEnd = null;
let toastTimer;
let dependencyBusy = false;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 6500); }
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-ASMR-Client':'webui'}, body:JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '请求失败');
  return value;
}
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
function markDirty() { dirty = true; $('save-state').textContent = '有未保存修改 · 保存后更新导出文件'; $('save-state').classList.add('dirty'); $('downloads').replaceChildren(); updateCounts(); }
function updateCounts() { $('count').textContent = rows.length; $('review-count').textContent = rows.filter(r => !r.reviewed).length; }
function rowButton(label, action) { const el = node('button', label); el.type = 'button'; el.onclick = action; return el; }
function renderRows() {
  updateCounts();
  const query = $('search').value.toLowerCase();
  const visible = rows.map((r,i) => [r,i]).filter(([r]) => (!onlyFlagged || !r.reviewed) && (r.source + r.translation).toLowerCase().includes(query));
  const list = $('subtitles'); list.replaceChildren();
  if (!visible.length) {
    const empty = node('div', undefined, 'empty');
    empty.append(node('div','〰','empty-icon'), node('h3',rows.length ? '没有符合条件的字幕' : '等待字幕生成'), node('p',rows.length ? '试试其他关键词，或切回全部字幕。' : '先完成原文识别。若没有检测到人声，可关闭过滤无声片段后新建任务。'));
    list.append(empty); return;
  }
  const fragment = document.createDocumentFragment();
  for (const [row,index] of visible) {
    const el = node('article', undefined, 'subtitle-row' + (!row.reviewed ? ' needs-review' : ''));
    const times = node('div',undefined,'time-fields');
    times.append(node('span',String(index+1).padStart(3,'0'),'row-id'));
    for (const key of ['start','end']) {
      const input = node('input'); input.type = 'number'; input.step = '.001'; input.min = '0'; input.value = row[key].toFixed(3);
      input.setAttribute('aria-label', `第 ${index+1} 条${key === 'start' ? '开始' : '结束'}秒数`);
      input.oninput = () => { row[key] = input.value === '' ? NaN : Number(input.value); row.reviewed = false; review.checked = false; el.classList.add('needs-review'); markDirty(); };
      input.disabled = !!current?.active || saving; times.append(input);
    }
    const actions = node('div',undefined,'row-actions');
    actions.append(rowButton('试听', () => { const audio = $('audio'); if (!audio.getAttribute('src')) return toast('音轨尚未生成'); if (!Number.isFinite(row.start) || !Number.isFinite(row.end)) return toast('请先填写有效时间'); audio.currentTime = row.start; playingEnd = row.end; audio.play().catch(e => toast('无法播放：' + e.message)); }));
    const text = node('div',undefined,'subtitle-text');
    const areas = {};
    for (const key of ['source','translation']) {
      const area = node('textarea'); area.rows = 2; area.value = row[key]; area.placeholder = key === 'translation' ? '等待翻译，也可手动输入中文' : '原文';
      area.setAttribute('aria-label',`第 ${index+1} 条${key === 'source' ? '原文' : '译文'}`);
      area.oninput = () => { row[key] = area.value; row.reviewed = false; markDirty(); review.checked = false; el.classList.add('needs-review'); };
      area.disabled = !!current?.active || saving; areas[key] = area; text.append(area);
    }
    if (row.original && row.original !== row.source) text.append(node('div','原始识别：' + row.original,'original'));
    if (row.flags?.length) text.append(node('div', row.flags.join(' · '),'flags'));
    const split = rowButton('切分', () => {
      const cutSource = areas.source.selectionStart;
      const cutTranslation = areas.translation.selectionStart;
      if (cutSource <= 0 || cutSource >= row.source.length || (row.translation && (cutTranslation <= 0 || cutTranslation >= row.translation.length))) return toast('先在原文和译文中分别放置切分光标，再点击切分。空译文无需放光标。');
      const midpoint = row.start + (row.end - row.start) * cutSource / row.source.length;
      if (!Number.isFinite(midpoint) || midpoint <= row.start || midpoint >= row.end) return toast('请先修正开始和结束时间');
      const second = {...row, start:midpoint, source:row.source.slice(cutSource).trim(), translation:row.translation.slice(cutTranslation).trim(), reviewed:false, flags:[...(row.flags || []), '手动切分：时间按比例估算，请试听调整']};
      row.end = midpoint; row.source = row.source.slice(0,cutSource).trim(); row.translation = row.translation.slice(0,cutTranslation).trim(); row.reviewed = false; row.flags = [...second.flags];
      rows.splice(index+1,0,second); markDirty(); renderRows();
    });
    const remove = rowButton('删除', () => { if (!confirm('删除这条字幕？保存前刷新页面可恢复。')) return; rows.splice(index,1); markDirty(); renderRows(); });
    split.disabled = remove.disabled = !!current?.active || saving; actions.append(split,remove); times.append(actions);
    const reviewLabel = node('label',undefined,'row-review'); const review = node('input'); review.type = 'checkbox'; review.checked = !!row.reviewed; review.disabled = !!current?.active || saving; review.setAttribute('aria-label',`第 ${index+1} 条已听音确认`);
    review.onchange = () => { row.reviewed = review.checked; markDirty(); el.classList.toggle('needs-review',!review.checked); if (onlyFlagged) renderRows(); };
    reviewLabel.append(review,node('span','已确认')); el.append(times,text,reviewLabel); fragment.append(el);
  }
  list.append(fragment);
}
function renderJob(job, replaceRows=true) {
  current = job; $('job-title').textContent = job.name; $('job-status').textContent = labels[job.state] || job.state;
  $('job-error').hidden = !job.error; $('job-error').textContent = job.error;
  document.querySelectorAll('#steps li').forEach(el => { el.classList.toggle('done',job.done.includes(el.dataset.stage)); el.classList.toggle('running',job.active && job.stage === el.dataset.stage); });
  $('logs').textContent = job.logs.join('\n') || '等待处理。';
  $('transport').hidden = false;
  const audioURL = `/files/${job.id}/audio.wav`;
  if (job.files.includes('audio.wav') && $('audio').getAttribute('src') !== audioURL) $('audio').src = audioURL;
  if (!job.files.includes('audio.wav')) $('audio').removeAttribute('src');
  $('continue').disabled = !!job.active || saving; $('continue').textContent = job.active ? '处理中…' : '继续全流程';
  $('metadata-box').hidden = !Object.keys(job.metadata).length;
  $('metadata-text').textContent = [job.metadata.title,job.metadata.uploader,job.metadata.description,job.metadata.warning].filter(Boolean).join('\n\n');
  $('save').disabled = !!job.active || saving || !job.files.includes('segments.json');
  if (replaceRows) { rows = job.segments; dirty = false; renderRows(); $('save-state').textContent = '已载入最新字幕 · 时间单位为秒'; $('save-state').classList.remove('dirty'); }
  if (!dirty) {
    const downloads = $('downloads'); downloads.replaceChildren();
    for (const [file,label] of [['source.srt','原文 SRT'],['translation.srt','中文 SRT'],['bilingual.srt','双语 SRT'],['review.json','复核清单']]) {
      if (job.files.includes(file)) { const link = node('a',label); link.href = `/files/${job.id}/${file}`; link.download = file; downloads.append(link); }
    }
  }
}
async function refreshJobs() {
  const jobs = await api('/api/jobs');
  const list = $('jobs'); list.replaceChildren();
  if (!jobs.length) list.append(node('p','还没有任务，从原片开始吧。','hint'));
  for (const job of jobs) {
    const el = node('button',undefined,'job-item' + (job.id === current?.id ? ' active' : '')); el.type = 'button';
    el.append(node('strong',job.name),node('small',`${labels[job.state] || job.state} · ${new Date(job.created*1000).toLocaleString('zh-CN')}`));
    el.onclick = async () => { if (saving) return toast('正在保存，请稍候'); if (dirty && !confirm('当前修改尚未保存，确定切换任务吗？')) return; try { renderJob(await api('/api/jobs/'+job.id)); await refreshJobs(); } catch(e) { toast(e.message); } };
    list.append(el);
  }
}
$('create-form').onsubmit = async event => {
  event.preventDefault();
  if (saving) return toast('正在保存，请稍候');
  if (dirty && !confirm('当前字幕修改尚未保存，确定新建任务吗？')) return;
  $('start').disabled = true;
  try {
    const config = Object.fromEntries(new FormData(event.target)); config.vad = $('vad').checked;
    const until = $('until').value;
    if (until !== 'metadata' && !window.dependencyState?.ffmpeg.ready) throw new Error('请先下载 FFmpeg');
    if (!['metadata','audio'].includes(until) && !window.dependencyState?.model.ready && config.model === 'small') throw new Error('请先下载识别模型');
    if (until === 'export' && config.translation_backend === 'codex' && !window.codexAvailable) throw new Error('请先安装并登录本机 Codex CLI');
    if (until === 'export' && config.translation_backend === 'api' && !config.translation_model) throw new Error('请填写翻译模型名称');
    const job = await api('/api/jobs',config);
    renderJob(await api('/api/jobs/'+job.id));
    await api(`/api/jobs/${job.id}/run`,{until:$('until').value});
    renderJob(await api('/api/jobs/'+job.id)); await refreshJobs(); toast('任务已开始');
  } catch(e) { toast(e.message); } finally { $('start').disabled = false; }
};
$('upload').onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  $('start').disabled = true; $('upload-label').textContent = '正在复制到本地工作目录…';
  try {
    const response = await fetch('/api/upload',{method:'POST',headers:{'X-ASMR-Client':'webui','X-Filename':encodeURIComponent(file.name)},body:file});
    const value = await response.json(); if (!response.ok) throw new Error(value.error);
    $('source').value = value.source; $('upload-label').textContent = file.name + ' · 已导入';
  } catch(e) { toast(e.message); $('upload-label').textContent = '上传失败，可直接填写文件路径'; } finally { $('start').disabled = false; }
};
$('save').onclick = async () => {
  if (!current || saving) return; saving = true; $('save').disabled = true; $('continue').disabled = true; renderRows();
  try { await api(`/api/jobs/${current.id}/save`,{segments:rows}); renderJob(await api('/api/jobs/'+current.id)); toast('已保存，字幕和复核清单已更新'); }
  catch(e) { toast(e.message); } finally { saving = false; $('save').disabled = !!current?.active; $('continue').disabled = !!current?.active; renderRows(); }
};
$('continue').onclick = async () => {
  if (!current || saving) return;
  if (dirty) return toast('请先保存字幕修改，再继续处理');
  try { await api(`/api/jobs/${current.id}/run`,{until:'export'}); renderJob(await api('/api/jobs/'+current.id)); await refreshJobs(); } catch(e) { toast(e.message); }
};
$('all').onclick = () => { onlyFlagged = false; $('all').classList.add('selected'); $('flagged').classList.remove('selected'); renderRows(); };
$('flagged').onclick = () => { onlyFlagged = true; $('flagged').classList.add('selected'); $('all').classList.remove('selected'); renderRows(); };
$('search').oninput = renderRows;
$('refresh').onclick = () => refreshJobs().catch(e => toast(e.message));
$('audio').ontimeupdate = () => { if (playingEnd !== null && $('audio').currentTime >= playingEnd) { $('audio').pause(); playingEnd = null; } };
window.addEventListener('beforeunload',e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
async function init() {
  try {
    const env = await api('/api/environment');
    window.studioHome = env.app_home;
    $('model').value = env.model; $('api-base').value = env.api_base; $('translation-model').value = env.translation_model;
    window.apiKeyReady = env.api_key;
    window.codexAvailable = env.codex_available;
    syncTranslationBackend();
    await refreshDependencies();
    await refreshJobs();
    const onboarding = await api('/api/onboarding');
    if (!onboarding.completed) openTutorial();
  } catch(e) { $('health').textContent = '连接失败'; toast(e.message); }
}
function syncTranslationBackend() {
  const apiMode = $('translation-backend').value === 'api';
  $('api-settings').hidden = !apiMode;
  $('codex-hint').hidden = apiMode;
  if (window.dependencyState) refreshDependencies();
}
$('translation-backend').onchange = syncTranslationBackend;
setInterval(async () => {
  if (!current || loading || saving) return;
  loading = true;
  const id = current.id;
  try {
    const job = await api('/api/jobs/'+id);
    if (current?.id !== id || saving) return;
    const wasActive = current.active;
    renderJob(job,!dirty && (job.active || wasActive));
    if (wasActive && !job.active) await refreshJobs();
  } catch(e) { $('health').textContent = '连接中断 · 请检查本地服务'; } finally { loading = false; }
},2500);
init();

async function refreshDependencies() {
  if (dependencyBusy) return;
  dependencyBusy = true;
  try {
    const state = await api('/api/dependencies'); window.dependencyState = state;
    for (const kind of ['ffmpeg','model']) {
      const item = state[kind], button = $(kind+'-download'), message = $(kind+'-state');
      $(kind+'-link').href = item.url;
      const working = ['queued','downloading'].includes(item.state);
      button.disabled = working || item.ready;
      button.textContent = working ? '下载中…' : item.ready ? '已就绪' : item.state === 'error' ? '重试下载' : '下载并安装';
      const progress = item.total ? ` ${Math.round(item.downloaded/item.total*100)}%` : '';
      message.textContent = working ? (item.message + progress) : item.state === 'error' ? ('失败：'+item.message) : item.ready ? '已就绪，可离线使用' : '尚未安装';
    }
    if (state.model.ready && $('model').value === 'small') {
      const env = await api('/api/environment'); $('model').value = env.model;
    }
    const missing = [!state.ffmpeg.ready && 'FFmpeg', !state.model.ready && '识别模型'].filter(Boolean);
    $('health').textContent = missing.length ? '待下载：'+missing.join('、') : '● 本地识别已就绪';
    if (!window.codexAvailable && $('translation-backend').value === 'codex') $('health').textContent += ' · 未找到 Codex CLI';
  } catch(e) { $('health').textContent = '组件状态获取失败'; } finally { dependencyBusy = false; }
}
for (const kind of ['ffmpeg','model']) $(kind+'-download').onclick = async () => {
  try { await api('/api/dependencies/'+kind,{}); toast('已开始下载，请保持程序运行'); await refreshDependencies(); }
  catch(e) { toast(e.message); }
};
setInterval(refreshDependencies,2500);

let tutorialStep = 0;
const tutorialSteps = [
  {title:'01 · 导入原片和发布信息', text:'选择本地视频或音频，也可以直接粘贴文件完整路径。大文件推荐用路径，避免复制。原发布链接用于提取简介、人物名和术语；抓取失败时，可在简介补充栏手动填写。', hint:'原文件始终保持不变，处理结果单独保存。'},
  {title:'02 · 下载运行组件', text:'安装包不包含 FFmpeg 和语音模型。首次使用前，在首页“运行组件”分别点击“下载并安装”；也可以打开旁边的官方下载链接。下载完成后可离线识别。', hint:'FFmpeg 下载约 109 MB，small 模型约 500 MB；下载时请保持程序运行。'},
  {title:'03 · 使用本机 Codex 翻译', text:'默认调用本机已登录的 Codex CLI。若未安装，请先安装并运行 codex login；然后在“识别与翻译设置”选择本机 Codex。也可切换至自定义翻译 API。', hint:'翻译会发送字幕与简介给所选服务，可能消耗账户用量；音频在本地识别。已识别的旧任务可在更新后继续翻译。'},
  {title:'04 · 试听校对，然后导出', text:'逐句试听，修改原文、译文和时间。切分时先在两种语言中分别放置光标，再点“切分”，并试听调整时间。确认后勾选复核，点击“保存并导出”下载 SRT。', hint:'自动字幕都需要听音复核。任务失败可继续运行；本教程随时可从页面右上角重新打开。'}
];
function renderTutorial() {
  const step = tutorialSteps[tutorialStep];
  $('tutorial-content').replaceChildren(node('h3',step.title),node('p',step.text),node('div',step.hint,'tutorial-note'));
  if (tutorialStep === 2 && window.studioHome) $('tutorial-content').append(node('p','用户数据目录：' + window.studioHome,'tutorial-path'));
  $('tutorial-progress').textContent = `${tutorialStep+1} / ${tutorialSteps.length}`;
  $('tutorial-back').disabled = tutorialStep === 0;
  $('tutorial-next').textContent = tutorialStep === tutorialSteps.length-1 ? '开始听译' : '下一步';
}
function openTutorial() { tutorialStep = 0; renderTutorial(); if (!$('tutorial').open) $('tutorial').showModal(); }
$('help').onclick = openTutorial;
$('tutorial-later').onclick = () => $('tutorial').close();
$('tutorial-back').onclick = () => { if (tutorialStep > 0) tutorialStep--; renderTutorial(); };
$('tutorial-next').onclick = async () => {
  if (tutorialStep < tutorialSteps.length-1) { tutorialStep++; renderTutorial(); return; }
  $('tutorial-next').disabled = true;
  try { await api('/api/onboarding',{}); $('tutorial').close(); }
  catch(e) { toast('教程状态保存失败：' + e.message); }
  finally { $('tutorial-next').disabled = false; }
};
