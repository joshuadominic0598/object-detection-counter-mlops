'use strict';
const $ = id => document.getElementById(id);
const state = {provider: 'local', queue: [], selected: null, busy: false, stop: false, serverKey: false, connected: false, activeBox: null, batch: false, testing: false, cloudVerified: false, selectionVersion: 0};
const palette = ['#c298ff', '#6ee7b7', '#7dd3fc', '#fbbf72', '#f9a8d4', '#fde68a'];
const svgNS = 'http://www.w3.org/2000/svg';
const make = (tag, cls, text) => {const node = document.createElement(tag); if(cls) node.className = cls; if(text !== undefined) node.textContent = text; return node;};
const svg = (tag, attributes = {}) => {const node = document.createElementNS(svgNS, tag); Object.entries(attributes).forEach(([k,v]) => node.setAttribute(k, v)); return node;};
const integer = value => Number(value).toLocaleString();
function notify(message) {$('notice').textContent = message; $('notice').hidden = !message;}
async function jsonFetch(url, options = {}) {
  const response = await fetch(url, options);
  let body;
  try {body = await response.json();} catch {throw new Error('The app returned an unexpected response. Check that the API is running.');}
  if(!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`);
  return body;
}
function sessionKey() {return `counter.session.${state.provider}`;}
function readStorage(key) {try {return localStorage.getItem(key);} catch {return null;}}
function writeStorage(key, value) {try {localStorage.setItem(key, value);} catch { /* Sessions still work when storage is blocked. */ }}
function newSessionId() {return `${state.provider === 'local' ? 'local' : 'cloud'}-${crypto.randomUUID().slice(0, 8)}`;}
function validSession() {
  const value = $('session-id').value.trim();
  if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(value)) throw new Error('Session ID must contain 1–80 letters, numbers, underscores or hyphens.');
  return value;
}
function renderTotals(counts) {
  $('persistent-total').textContent = integer(Object.values(counts).reduce((a,b) => a+b, 0));
  const container = $('persistent-classes'); container.replaceChildren();
  Object.entries(counts).sort((a,b) => b[1]-a[1]).forEach(([label, number], index) => {
    const item = make('div','persistent-class'); item.style.borderColor = palette[index%palette.length];
    item.append(make('span','',label), make('strong','',integer(number))); container.append(item);
  });
  if(!Object.keys(counts).length) container.append(make('span','muted small','Run your first image to start counting.'));
}
async function loadSession() {
  const id = validSession();
  const result = await jsonFetch(`/api/sessions/${encodeURIComponent(id)}`);
  writeStorage(sessionKey(), id); renderTotals(result.total_counts);
}
function selectProvider(provider) {
  if(state.busy || state.testing) return;
  state.provider = provider;
  document.querySelectorAll('.provider-tab').forEach(tab => {const active = tab.dataset.provider === provider; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', active);});
  $('local-config').hidden = provider !== 'local'; $('roboflow-config').hidden = provider !== 'roboflow';
  $('provider-hint').textContent = provider === 'local' ? 'Private inference, running on your machine' : 'Bring your own deployment. Keep the same workflow.';
  $('session-id').value = readStorage(sessionKey()) || newSessionId();
  loadSession().catch(error => notify(error.message));
  renderQueue();
}
function updateButtons() {
  const pending = state.queue.filter(item => item.status === 'queued').length;
  const locked = state.busy || state.testing;
  $('run-button').disabled = locked || !pending || !state.connected || (state.provider === 'roboflow' && !state.cloudVerified);
  $('run-count').textContent = pending;
  $('run-label').textContent = state.batch ? 'Run batch' : 'Run detection';
  $('stop-button').hidden = !state.busy || !state.batch;
  $('clear-queue').disabled = locked || !state.queue.length;
  $('dropzone').disabled = locked;
  $('file-input').disabled = locked;
  $('file-input').multiple = state.batch;
  $('queue-panel').hidden = !state.batch;
  $('upload-heading').textContent = state.batch ? 'Add images to your batch' : 'Choose an image';
  $('dropzone-title').textContent = state.batch ? 'Drop images to add to queue' : 'Drop an image here';
  $('sample-heading').textContent = state.batch ? 'Add a sample to queue' : 'Try a sample';
  $('test-connection').disabled = locked || !state.connected;
  $('test-connection').textContent = state.testing ? 'Testing…' : 'Test connection';
  ['single-mode','batch-mode','threshold','persist-counts','session-id','load-session','new-session','roboflow-mode','api-key','workspace-name','workflow-id','model-id','output-path'].forEach(id => $(id).disabled = locked);
  document.querySelectorAll('.provider-tab,.sample').forEach(button => button.disabled = locked);
  document.querySelectorAll('.remove-image').forEach(button => button.disabled = locked);
  $('queue-count').textContent = `${state.queue.length} / ${state.batch ? 20 : 1}`;
}
function keepOnly(item) {
  state.queue.forEach(previous => {if(previous !== item && previous.preview.startsWith('blob:')) URL.revokeObjectURL(previous.preview);});
  state.queue = item ? [item] : [];
}
function resetCloudStatus() {
  state.cloudVerified = false;
  $('cloud-status').textContent = '○ Not tested · test connection to enable detection';
  $('cloud-status').classList.remove('connected');
  updateButtons();
}
async function testRoboflowConnection() {
  if(state.busy || state.testing) return;
  notify('');
  let fields;
  try {fields = roboflowFields();} catch(error) {resetCloudStatus(); notify(error.message); return;}
  state.testing = true; state.cloudVerified = false; updateButtons();
  $('cloud-status').classList.remove('connected');
  $('cloud-status').textContent = '○ Checking deployment access and detection output…';
  try {
    const form = new FormData(); Object.entries(fields).forEach(([key,value]) => form.set(key,value));
    const result = await jsonFetch('/api/roboflow/test-connection',{method:'POST',body:form});
    state.cloudVerified = true;
    $('cloud-status').textContent = `● Connected · ${result.mode === 'model' ? 'Model' : 'Workflow'} verified · ${integer(result.latency_ms)} ms`;
    $('cloud-status').classList.add('connected');
  } catch(error) {
    $('cloud-status').textContent = '○ Connection failed · check settings and retry';
    notify(error.message);
  } finally {state.testing = false; updateButtons();}
}

function renderQueue() {
  const container = $('queue'); container.replaceChildren();
  if(!state.queue.length) container.append(make('div','queue-empty','Your images will appear here. Each result is yours to inspect.'));
  state.queue.forEach(item => {
    const card = make('div',`queue-item ${item.status}${state.selected === item.id ? ' selected' : ''}`);
    const view = make('button'); view.type = 'button'; view.setAttribute('aria-label',`View ${item.name}`);
    const image = make('img'); image.src = item.preview; image.alt = '';
    view.append(image, make('span','queue-name',item.name));
    const labels = {queued:'Ready',running:'Processing…',done:`${item.result?.detection_count || 0} objects · ${item.result?.provider || ''}`,failed:'Failed · click to inspect'};
    view.append(make('span','queue-state',labels[item.status])); view.onclick = () => selectImage(item);
    card.append(view);
    const remove = make('button','remove-image','×'); remove.title = `Remove ${item.name}`; remove.disabled = state.busy; remove.onclick = () => removeImage(item.id); card.append(remove); container.append(card);
  });
  const done = state.queue.filter(item => item.status === 'done');
  const failed = state.queue.filter(item => item.status === 'failed');
  $('batch-metrics').hidden = !state.batch || (!done.length && !failed.length);
  if(done.length || failed.length) {
    const counts = {}; done.forEach(item => Object.entries(item.result.counts).forEach(([label,number]) => counts[label] = (counts[label] || 0) + number));
    const total = done.reduce((sum,item) => sum + item.result.detection_count,0);
    const latency = done.length ? Math.round(done.reduce((sum,item) => sum + item.result.latency_ms,0)/done.length) : 0;
    $('batch-metrics').textContent = `${done.length} succeeded · ${failed.length} failed · ${integer(total)} detections · ${latency} ms avg. latency${Object.keys(counts).length ? ' · ' + Object.entries(counts).map(([key,value]) => `${key}: ${integer(value)}`).join(' / ') : ''}`;
  }
  $('batch-summary').textContent = state.queue.length ? `${state.queue.length} image${state.queue.length === 1 ? '' : 's'} · ${done.length} completed` : 'Single image or a batch of up to 20';
  updateButtons();
}
function removeImage(id) {
  const item = state.queue.find(item => item.id === id); if(!item) return;
  if(item.preview.startsWith('blob:')) URL.revokeObjectURL(item.preview);
  state.queue = state.queue.filter(item => item.id !== id);
  if(state.selected === id) selectImage(state.queue[0] || null);
  renderQueue();
}
async function addFiles(files, selectionVersion = ++state.selectionVersion) {
  if(state.busy || state.testing) return;
  const errors = [];
  if(!state.batch && files.length > 1) {errors.push('Single-image mode accepts one image. Select Batch to add multiple images.'); files = files.slice(0,1);}
  for(const file of files) {
    if(state.batch && state.queue.length >= 20) {errors.push('Batch limit reached: up to 20 images. Clear the queue to start another batch.'); break;}
    if(file.size > 10*1024*1024) {errors.push(`${file.name}: exceeds 10 MB.`); continue;}
    if(!['image/jpeg','image/png'].includes(file.type)) {errors.push(`${file.name}: use JPEG or PNG.`); continue;}
    const preview = URL.createObjectURL(file);
    try {
      const img = new Image(); img.src = preview; await img.decode();
      if(Math.min(img.naturalWidth,img.naturalHeight) < 32 || Math.max(img.naturalWidth,img.naturalHeight) > 8192 || img.naturalWidth*img.naturalHeight > 16000000) throw new Error('must be 32 px min, 8192 px max per side and 16 MP max.');
      if(!state.batch && selectionVersion !== state.selectionVersion) {URL.revokeObjectURL(preview); continue;}
      if(state.busy || state.testing || (state.batch && state.queue.length >= 20)) {URL.revokeObjectURL(preview); errors.push('Queue is full or already processing. Add this image to the next batch.'); continue;}
      const item = {id: crypto.randomUUID(), name:file.name, file, preview, status:'queued'};
      if(state.batch) state.queue.push(item); else keepOnly(item);
      selectImage(item);
    } catch(error) {URL.revokeObjectURL(preview); errors.push(`${file.name}: ${error.message || 'could not open image.'}`);}
  }
  notify(errors.join('\n')); renderQueue();
  if(state.queue.some(item => item.status === 'queued')) $('run-progress').textContent = 'Ready when you are';
}
function selectImage(item) {
  state.selected = item?.id || null;
  $('canvas-empty').hidden = !!item; $('image-stage').hidden = !item;
  $('boxes').replaceChildren(); $('detection-list').replaceChildren(); state.activeBox = null;
  $('download-result').hidden = !item?.result?.annotated_url;
  ['metric-objects','metric-classes','metric-latency','metric-confidence'].forEach(id => $(id).textContent = '—');
  $('image-counts').replaceChildren(make('span','muted small','Per-image class counts appear after detection.'));
  $('canvas-badge').textContent = item?.result ? item.result.provider.toUpperCase() : 'PREVIEW';
  if(!item) {$('image-caption').textContent = 'Your next detection is one image away'; renderQueue(); return;}
  $('result-image').src = item.result?.image_url || item.preview;
  $('result-image').alt = `${item.name}${item.result ? ', with interactive object detections' : ', preview'}`;
  $('image-caption').textContent = item.name;
  if(item.error) notify(item.error);
  if(item.result) {
    const r = item.result;
    $('image-caption').textContent = `${item.name} · ${r.width} × ${r.height} px`;
    $('metric-objects').textContent = integer(r.detection_count); $('metric-classes').textContent = r.class_count;
    $('metric-latency').textContent = `${integer(r.latency_ms)} ms`;
    $('metric-confidence').textContent = r.mean_confidence === null ? '—' : `${(r.mean_confidence*100).toFixed(1)}%`;
    $('download-result').href = r.annotated_url;
    const counts = $('image-counts'); counts.replaceChildren();
    Object.entries(r.counts).forEach(([label,number]) => {const chip = make('span','class-chip',label); chip.append(make('strong','',integer(number))); counts.append(chip);});
    if(!r.detection_count) counts.append(make('span','muted small','No objects above this threshold. Try a lower threshold or an image containing the model’s trained classes.'));
    drawBoxes(r);
  }
  renderQueue();
}
function drawBoxes(result) {
  const layer = $('boxes'); layer.replaceChildren(); layer.setAttribute('viewBox', `0 0 ${result.width} ${result.height}`);
  const classes = Object.keys(result.counts); const displayScale = result.width / Math.max(1,$('result-image').clientWidth || 700);
  const fontSize = Math.max(11*displayScale, result.width/90);
  const defs = svg('defs'); const mask = svg('mask',{id:'focus-mask',maskUnits:'userSpaceOnUse',x:0,y:0,width:result.width,height:result.height});
  mask.append(svg('rect',{x:0,y:0,width:result.width,height:result.height,fill:'white'}));
  const cutout = svg('rect',{fill:'black'}); mask.append(cutout); defs.append(mask); layer.append(defs);
  const shade = svg('rect',{x:0,y:0,width:result.width,height:result.height,mask:'url(#focus-mask)',class:'focus-shade',visibility:'hidden'}); layer.append(shade);
  const labels = svg('g', {class:'box-label',visibility:'hidden'}); const labelBg = svg('rect',{rx:3*displayScale,fill:'#d3b3ff'});
  const labelText = svg('text',{fill:'#170d23','font-family':'system-ui,sans-serif','font-size':fontSize,'font-weight':700}); labels.append(labelBg,labelText);
  const rects = [], buttons = [];
  const activate = index => {
    state.activeBox = index;
    rects.forEach((rect,i) => {rect.setAttribute('stroke-width',i === index ? 3 : 1.5); rect.style.opacity = index === null || index === i ? '1' : '.2';});
    buttons.forEach((button,i) => button.classList.toggle('active',index === i));
    shade.setAttribute('visibility',index === null ? 'hidden' : 'visible'); labels.setAttribute('visibility',index === null ? 'hidden' : 'visible');
    if(index === null) return;
    const p = result.predictions[index], b = p.box;
    Object.entries({x:b.xmin,y:b.ymin,width:b.xmax-b.xmin,height:b.ymax-b.ymin}).forEach(([k,v]) => cutout.setAttribute(k,v));
    labelText.textContent = `${p.class_name}  ${(p.score*100).toFixed(1)}%`;
    const padding = 7*displayScale, labelHeight = fontSize+padding*2;
    const labelWidth = Math.min(result.width,labelText.getComputedTextLength()+padding*2);
    const x = Math.max(0,Math.min(b.xmin,result.width-labelWidth));
    const y = Math.min(result.height-labelHeight, Math.max(0,b.ymin-labelHeight-3*displayScale));
    labelBg.setAttribute('x',x); labelBg.setAttribute('y',y); labelBg.setAttribute('width',labelWidth); labelBg.setAttribute('height',labelHeight);
    labelText.setAttribute('x',x+padding); labelText.setAttribute('y',y+padding+fontSize*.8);
    layer.append(labels);
  };
  result.predictions.forEach((prediction,index) => {
    const box = prediction.box, color = palette[classes.indexOf(prediction.class_name)%palette.length];
    const rect = svg('rect',{x:box.xmin,y:box.ymin,width:box.xmax-box.xmin,height:box.ymax-box.ymin,stroke:color,fill:color,class:'bbox',tabindex:0,role:'button','aria-label':`${prediction.class_name}, ${(prediction.score*100).toFixed(1)}% confidence`});
    rect.addEventListener('pointerenter',() => activate(index)); rect.addEventListener('pointerleave',() => activate(null));
    rect.addEventListener('focus',() => activate(index)); rect.addEventListener('blur',() => activate(null));
    rect.addEventListener('click',() => activate(index));
    rect.addEventListener('keydown',event => {if(event.key === 'Enter' || event.key === ' ') {event.preventDefault(); activate(index);} if(event.key === 'Escape') activate(null);});
    layer.append(rect); rects.push(rect);
    const button = make('button','detection-item',`${prediction.class_name} · ${(prediction.score*100).toFixed(1)}%`);
    button.onpointerenter = () => activate(index); button.onpointerleave = () => activate(null); button.onfocus = () => activate(index); button.onblur = () => activate(null); button.onclick = () => activate(index);
    $('detection-list').append(button); buttons.push(button);
  });
  layer.append(labels);
}
function roboflowFields() {
  const mode = $('roboflow-mode').value;
  const values = {roboflow_mode:mode,api_key:$('api-key').value.trim(),workspace_name:$('workspace-name').value.trim(),workflow_id:$('workflow-id').value.trim(),model_id:$('model-id').value.trim(),output_path:$('output-path').value.trim()};
  if(!values.api_key && !state.serverKey) throw new Error('Enter your Roboflow API key before running detection.');
  if(mode === 'workflow' && (!values.workspace_name || !values.workflow_id || !values.output_path)) throw new Error('Enter the workspace slug, workflow slug and prediction output field.');
  if(mode === 'model' && !/^[A-Za-z0-9][A-Za-z0-9_-]*\/[1-9][0-9]*$/.test(values.model_id)) throw new Error('Model ID must be project-slug/version.');
  return values;
}
async function runDetection() {
  if(state.busy || state.testing) return;
  if(state.provider === 'roboflow' && !state.cloudVerified) {notify('Test the Roboflow connection before running detection.'); return;}
  notify('');
  let fields;
  try {fields = {session_id:validSession(),provider:state.provider,threshold:Number($('threshold').value)/100,counter:$('persist-counts').checked}; if(state.provider === 'roboflow') Object.assign(fields,roboflowFields());}
  catch(error) {notify(error.message); return;}
  writeStorage(sessionKey(),fields.session_id);
  state.busy = true; state.stop = false; updateButtons();
  const pending = state.queue.filter(item => item.status === 'queued'); let completed = 0;
  try {
    for(const item of pending) {
      if(state.stop) break;
      item.status = 'running'; renderQueue(); $('run-progress').textContent = `Processing ${completed+1} of ${pending.length}…`;
      try {
        const form = new FormData(); Object.entries(fields).forEach(([k,v]) => form.set(k,String(v))); form.set('file',item.file,item.name);
        item.result = await jsonFetch('/api/detect',{method:'POST',body:form}); item.status = 'done'; item.error = null;
        renderTotals(item.result.total_counts);
        if(state.provider === 'roboflow') {$('cloud-status').textContent = '● Roboflow connected · last request succeeded'; $('cloud-status').classList.add('connected');}
      } catch(error) {
        item.status = 'failed'; item.error = error.message; notify(`${item.name}: ${error.message}`);
        if(state.provider === 'roboflow') {state.cloudVerified = false; $('cloud-status').textContent = '○ Last request failed · test connection again'; $('cloud-status').classList.remove('connected');}
      }
      completed++; selectImage(item);
    }
  } finally {
    state.busy = false; renderQueue();
    $('run-progress').textContent = state.batch ? `${state.stop ? 'Stopped' : 'Batch complete'} · ${completed} processed${state.queue.some(item => item.status === 'queued') ? ' · remaining images are ready' : ''}. Failed images can be removed and added again.` : (state.queue[0]?.status === 'failed' ? 'Detection failed. Select an image to try again.' : 'Detection complete · 1 image processed. Select another image for the next run.');
  }
}
async function checkConnection() {
  try {
    const result = await jsonFetch('/api/status'); state.connected = true;
    if(state.serverKey !== result.server_key_available) resetCloudStatus();
    state.serverKey = result.server_key_available;
    $('local-model-name').textContent = result.local_model;
    $('api-status').classList.remove('offline'); $('api-status').replaceChildren(make('i'),document.createTextNode('API connected'));
    if(state.serverKey) {$('api-key').placeholder = 'Using server key · paste to override'; $('key-hint').textContent = 'A server key is configured. Leave blank to use it, or supply your own.';}
    else {$('api-key').placeholder = 'Paste your Roboflow API key'; $('key-hint').textContent = 'Sent securely to Roboflow through this backend.';}
  } catch {
    state.connected = false; resetCloudStatus(); $('api-status').classList.add('offline'); $('api-status').replaceChildren(make('i'),document.createTextNode('API offline'));
  }
  updateButtons();
}
async function init() {
  document.querySelectorAll('.provider-tab').forEach(button => button.onclick = () => selectProvider(button.dataset.provider));
  $('roboflow-mode').onchange = () => {$('workflow-fields').hidden = $('roboflow-mode').value !== 'workflow'; $('model-field').hidden = $('roboflow-mode').value !== 'model'; resetCloudStatus();};
  $('roboflow-mode').onchange();
  ['api-key','workspace-name','workflow-id','model-id','output-path'].forEach(id => $(id).addEventListener('input',resetCloudStatus));
  $('test-connection').onclick = testRoboflowConnection;
  const changeProcessingMode = () => {
    state.selectionVersion++; state.batch = $('batch-mode').checked;
    if(!state.batch) {const selected = state.queue.find(item => item.id === state.selected) || state.queue[0]; keepOnly(selected); selectImage(selected || null);}
    renderQueue();
  };
  $('batch-mode').onchange = changeProcessingMode;
  $('single-mode').onchange = changeProcessingMode;
  $('threshold').oninput = () => $('threshold-value').textContent = `${$('threshold').value}%`;
  $('dropzone').onclick = () => $('file-input').click();
  $('file-input').onchange = async () => {await addFiles(Array.from($('file-input').files)); $('file-input').value = '';};
  ['dragenter','dragover'].forEach(type => $('dropzone').addEventListener(type,event => {event.preventDefault(); if(!state.busy && !state.testing) $('dropzone').classList.add('dragging');}));
  ['dragleave','drop'].forEach(type => $('dropzone').addEventListener(type,event => {event.preventDefault(); $('dropzone').classList.remove('dragging');}));
  $('dropzone').addEventListener('drop',event => addFiles(Array.from(event.dataTransfer.files)));
  // Avoid accidentally navigating away from results when a file misses the drop target.
  window.addEventListener('dragover',event => event.preventDefault()); window.addEventListener('drop',event => event.preventDefault());
  $('run-button').onclick = runDetection; $('stop-button').onclick = () => {state.stop = true; $('stop-button').disabled = true; $('stop-button').textContent = 'Stopping after current image…';};
  $('run-button').addEventListener('click',() => {$('stop-button').disabled = false; $('stop-button').textContent = 'Stop after current image';});
  $('clear-queue').onclick = () => {state.queue.forEach(item => {if(item.preview.startsWith('blob:')) URL.revokeObjectURL(item.preview);}); state.queue = []; selectImage(null); $('run-progress').textContent = 'Add an image to get started'; notify('');};
  $('load-session').onclick = () => loadSession().then(() => notify('')).catch(error => notify(error.message));
  $('new-session').onclick = () => {$('session-id').value = newSessionId(); loadSession().catch(error => notify(error.message));};
  $('session-id').addEventListener('keydown',event => {if(event.key === 'Enter') $('load-session').click();});
  $('result-image').onload = () => {const item = state.queue.find(item => item.id === state.selected); if(item?.result) {$('detection-list').replaceChildren(); drawBoxes(item.result);}};
  await checkConnection(); selectProvider('local');
  try {
    const samples = await jsonFetch('/api/samples');
    samples.forEach(sample => {
      const button = make('button','sample'); button.title = `Use sample: ${sample.name}`; button.setAttribute('aria-label',`Use sample ${sample.name}`);
      const image = make('img'); image.src = sample.url; image.alt = sample.name; image.loading = 'lazy'; button.append(image);
      button.onclick = async () => {if(state.busy || state.testing) return; const selectionVersion = ++state.selectionVersion; button.disabled = true; try {const response = await fetch(sample.url); if(!response.ok) throw new Error('Sample unavailable.'); const blob = await response.blob(); if(!state.batch && selectionVersion !== state.selectionVersion) return; await addFiles([new File([blob],sample.id,{type:blob.type})],selectionVersion);} catch(error) {notify(error.message);} finally {updateButtons();}};
      $('samples').append(button);
    }); updateButtons();
  } catch(error) {notify(error.message);}
  setInterval(checkConnection,15000);
}
init();
