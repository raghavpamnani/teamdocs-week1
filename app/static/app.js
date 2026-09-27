'use strict';
const $ = (id) => document.getElementById(id);
const state = { user: null, tenant: null, view: 'library', status: '', page: 1, auditPage: 1, rows: [], sequence: 0 };
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const initials = (name) => name.split(' ').map(x => x[0]).slice(0,2).join('');
const bytes = (n) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(1)} KB` : `${(n/1048576).toFixed(1)} MB`;
const date = (s) => new Date(s).toLocaleDateString(undefined,{month:'short',day:'numeric'});
const base = () => `/api/v1/workspaces/${encodeURIComponent(state.tenant.id)}`;
const admin = () => state.tenant?.role === 'admin';
let toastTimer;
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,4000); }
function errorMessage(error) { return error.message || 'Something went wrong. Please try again.'; }
async function api(path, options={}) {
  const headers = new Headers(options.headers || {});
  if (state.user?.csrf) headers.set('X-CSRF-Token',state.user.csrf);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  let response;
  try { response=await fetch(path,{...options,headers,credentials:'same-origin'}); }
  catch { throw new Error('Unable to reach TeamDocs. Check your connection and try again.'); }
  if (!response.ok) {
    const data=await response.json().catch(()=>({}));
    if (response.status===401 && state.user) showLogin();
    const error=new Error(data.error?.message || `Request failed (${response.status}).`);
    error.status=response.status; throw error;
  }
  if (response.status===204) return null;
  return response.json();
}
function showLogin() { state.user=null; state.tenant=null; state.sequence++; $('workspace-screen').hidden=true; $('login-screen').hidden=false; document.querySelectorAll('dialog[open]').forEach(d=>d.close()); }
async function signIn(email,password) {
  $('login-error').textContent=''; $('login-submit').disabled=true; document.querySelectorAll('[data-account]').forEach(x=>x.disabled=true);
  try { await api('/api/auth/login',{method:'POST',body:JSON.stringify({email,password})}); await loadUser(); }
  catch(error) { $('login-error').textContent=errorMessage(error); }
  finally { $('login-submit').disabled=false; document.querySelectorAll('[data-account]').forEach(x=>x.disabled=false); }
}
async function loadUser() {
  state.user=await api('/api/auth/me');
  if (!state.user.workspaces.length) { showLogin(); throw new Error('This account has no workspace membership.'); }
  state.tenant=state.user.workspaces[0];
  $('workspace-select').innerHTML=state.user.workspaces.map(w=>`<option value="${escapeHTML(w.id)}">${escapeHTML(w.name)}</option>`).join('');
  $('user-name').textContent=state.user.name;
  $('user-avatar').textContent=$('top-avatar').textContent=initials(state.user.name);
  $('login-screen').hidden=true; $('workspace-screen').hidden=false;
  applyWorkspace(); await setView('library');
}
function applyWorkspace() {
  $('workspace-mark').textContent=state.tenant.name[0];
  $('breadcrumb-workspace').textContent=$('sharing-workspace').textContent=state.tenant.name;
  $('user-role').textContent=state.tenant.role==='admin'?'Administrator':state.tenant.role;
  document.querySelectorAll('.admin-only').forEach(el=>el.hidden=!admin());
  document.querySelectorAll('.upload-permission,.export-permission').forEach(el=>el.hidden=state.tenant.role==='viewer');
}
async function setView(view) {
  if ((view==='team'||view==='activity')&&!admin()) view='library';
  state.view=view;state.page=1;state.auditPage=1;
  state.status=view==='review'?'review':'';
  $('search').value='';$('category').value='';
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  const info={library:['Document library','A shared home for the work that moves your team forward.'],review:['Needs review','Give the next good idea a second pair of eyes.'],team:['Team & access','The right access for every person in your workspace.'],activity:['Activity log','A clear record of who did what, and when.']}[view];
  $('page-title').textContent=info[0];const dot=document.createElement('span');dot.className='title-dot';dot.textContent='.';$('page-title').append(dot);
  $('breadcrumb-page').textContent=info[0];$('page-description').textContent=info[1];
  $('stats').hidden=$('document-actions').hidden=['team','activity'].includes(view);
  $('library-view').hidden=!['library','review'].includes(view);$('team-view').hidden=view!=='team';$('activity-view').hidden=view!=='activity';
  await refresh();
}
async function refresh() {
  $('page-error').hidden=true;
  const sequence=++state.sequence;
  try {
    if (['library','review'].includes(state.view)) {
      document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.status===state.status));
      const query=new URLSearchParams({q:$('search').value,category:$('category').value,status:state.status,page:state.page,limit:8});
      const [result,overview]=await Promise.all([api(`${base()}/documents?${query}`),api(`${base()}/overview`)]);
      if(sequence!==state.sequence)return;
      state.rows=result.items;
      $('stat-total').textContent=$('nav-count').textContent=overview.total;
      $('stat-approved').textContent=overview.approved;$('stat-review').textContent=$('review-count').textContent=overview.review;
      $('stat-storage').textContent=bytes(overview.bytes);$('workspace-member-count').textContent=`${overview.members} workspace members`;
      renderDocuments(result);
    } else if (state.view==='team') {
      const members=await api(`${base()}/members`);if(sequence!==state.sequence)return;
      $('member-rows').innerHTML=members.map(m=>`<tr><td><div class="owner-cell"><span class="avatar">${escapeHTML(initials(m.name))}</span><strong>${escapeHTML(m.name)}${m.id===state.user.id?' (you)':''}</strong></div></td><td>${escapeHTML(m.email)}</td><td><select class="role-select" data-member="${escapeHTML(m.id)}" aria-label="Role for ${escapeHTML(m.name)}">${['admin','member','viewer'].map(r=>`<option value="${r}" ${m.role===r?'selected':''}>${r==='admin'?'Administrator':r[0].toUpperCase()+r.slice(1)}</option>`).join('')}</select></td></tr>`).join('');
    } else {
      const [events,metrics]=await Promise.all([api(`${base()}/audit?page=${state.auditPage}`),api(`${base()}/metrics`)]);if(sequence!==state.sequence)return;
      $('activity-summary').textContent=`Application process · ${metrics.requests} requests · ${metrics.mean_duration_ms} ms mean response · ${metrics.errors} server errors`;
      const actions={'document.uploaded':'uploaded','document.imported':'imported','document.approved':'approved','document.downloaded':'downloaded','document.deleted':'deleted','register.exported':'exported','member.role_changed':'changed a role'};
      $('activity-list').innerHTML=events.items.length?events.items.map(e=>`<article class="activity-item"><span class="avatar">${escapeHTML(initials(e.actor))}</span><div><strong>${escapeHTML(e.actor)}</strong><p class="${e.outcome==='denied'?'outcome-denied':''}">${escapeHTML(e.outcome==='denied'?'was denied permission to '+e.action:actions[e.action]||e.action)} <b>${escapeHTML(e.target)}</b></p><small>Request ${escapeHTML(e.request_id)}</small></div><time datetime="${escapeHTML(e.created_at)}">${escapeHTML(date(e.created_at))} · ${escapeHTML(new Date(e.created_at).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}))}</time></article>`).join(''):'<div class="empty-state">No activity recorded yet.</div>';
      $('audit-count').textContent=`${events.total} recorded events`;$('audit-page').textContent=state.auditPage;$('audit-prev').disabled=state.auditPage===1;$('audit-next').disabled=state.auditPage*30>=events.total;
    }
  } catch(error) { if(sequence!==state.sequence)return; $('page-error').textContent=errorMessage(error);$('page-error').hidden=false; }
}
function renderDocuments(result) {
  $('document-rows').innerHTML=result.items.map(d=>{
    const ext=d.name.split('.').pop().toLowerCase();
    const canDelete=admin()||(state.tenant.role==='member'&&d.owner_id===state.user.id);
    return `<tr><td><div class="document-cell"><span class="file-icon ${escapeHTML(ext)}">${escapeHTML(ext.toUpperCase())}</span><div><span class="document-name">${escapeHTML(d.name)}</span><span class="document-meta">${bytes(d.size)}${d.source.startsWith('github:')?' · Imported from GitHub':''}</span></div></div></td><td><span class="category-label">${escapeHTML(d.category)}</span></td><td><span class="owner-cell"><span class="avatar">${escapeHTML(initials(d.owner))}</span>${escapeHTML(d.owner.split(' ')[0])}</span></td><td><span class="pill ${d.status}">${d.status==='approved'?'✓ Approved':'◷ In review'}</span></td><td>${escapeHTML(date(d.created_at))}</td><td><div class="row-actions">${admin()&&d.status==='review'?`<button class="icon-button approve-action" data-action="approve" data-id="${escapeHTML(d.id)}" title="Approve ${escapeHTML(d.name)}" aria-label="Approve ${escapeHTML(d.name)}">✓</button>`:''}<button class="icon-button" data-action="download" data-id="${escapeHTML(d.id)}" title="Download ${escapeHTML(d.name)}" aria-label="Download ${escapeHTML(d.name)}">↓</button>${canDelete?`<button class="icon-button" data-action="delete" data-id="${escapeHTML(d.id)}" title="Delete ${escapeHTML(d.name)}" aria-label="Delete ${escapeHTML(d.name)}">×</button>`:''}</div></td></tr>`;
  }).join('');
  $('empty-state').hidden=result.total>0;
  $('empty-copy').textContent=$('search').value||$('category').value||state.status?'Try a different search or filter.':'Upload your first document to get the conversation started.';
  $('results-label').textContent=result.total?`Showing ${(state.page-1)*8+1}–${Math.min(state.page*8,result.total)} of ${result.total} documents`:'0 documents';
  $('page-number').textContent=state.page;$('previous').disabled=state.page===1;$('next').disabled=state.page*8>=result.total;
}
async function download(path,name) {
  try {
    const response=await fetch(path,{credentials:'same-origin'});
    if(!response.ok){const data=await response.json();throw new Error(data.error?.message||'Download failed.');}
    const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Download ready.');
  }catch(e){toast(errorMessage(e));}
}
$('login-form').addEventListener('submit',e=>{e.preventDefault();signIn($('email').value,$('password').value);});
document.querySelectorAll('[data-account]').forEach(button=>button.addEventListener('click',()=>signIn(`${button.dataset.account}@teamdocs.demo`,'DemoPass123!')));
function logoutHandler() { return (async()=>{try{await api('/api/auth/logout',{method:'POST'});showLogin();}catch(e){toast(errorMessage(e));}})(); }
$('logout').addEventListener('click',logoutHandler);
$('mobile-logout').addEventListener('click',logoutHandler);
$('workspace-select').addEventListener('change',()=>{state.tenant=state.user.workspaces.find(w=>w.id===$('workspace-select').value);applyWorkspace();setView('library');});
document.querySelectorAll('[data-view]').forEach(x=>x.addEventListener('click',()=>setView(x.dataset.view)));
document.querySelectorAll('[data-status]').forEach(x=>x.addEventListener('click',()=>{state.status=x.dataset.status;state.page=1;refresh();}));
let debounce;
$('search').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(()=>{state.page=1;refresh();},220);});
$('category').addEventListener('change',()=>{state.page=1;refresh();});
$('previous').addEventListener('click',()=>{state.page--;refresh();});$('next').addEventListener('click',()=>{state.page++;refresh();});
$('audit-prev').addEventListener('click',()=>{state.auditPage--;refresh();});$('audit-next').addEventListener('click',()=>{state.auditPage++;refresh();});
$('export').addEventListener('click',()=>download(`${base()}/export`,'teamdocs-register.csv'));
$('upload-open').addEventListener('click',()=>{$('upload-form').reset();$('file-label').textContent='Choose a file or drop it here';$('upload-error').textContent='';$('upload-dialog').showModal();});
$('import-open').addEventListener('click',()=>{$('import-error').textContent='';$('import-dialog').showModal();});
document.querySelectorAll('.close-dialog').forEach(x=>x.addEventListener('click',()=>x.closest('dialog').close()));
function fileChanged(){const file=$('file-input').files[0];$('file-label').textContent=file?`${file.name} · ${bytes(file.size)}`:'Choose a file or drop it here';}
$('file-input').addEventListener('change',fileChanged);
['dragenter','dragover'].forEach(event=>$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.add('drag');}));
['dragleave','drop'].forEach(event=>$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.remove('drag');if(event==='drop'&&e.dataTransfer.files.length){$('file-input').files=e.dataTransfer.files;fileChanged();}}));
$('upload-form').addEventListener('submit',async e=>{e.preventDefault();$('upload-error').textContent='';const file=$('file-input').files[0];if(!file)return;if(file.size>5*1024*1024){$('upload-error').textContent='Files must be 5 MB or smaller.';return;}const form=new FormData();form.append('file',file);form.append('category',$('upload-category').value);$('upload-submit').disabled=true;$('upload-submit').textContent='Uploading…';try{await api(`${base()}/documents`,{method:'POST',body:form});$('upload-dialog').close();state.page=1;state.status='';$('search').value='';$('category').value='';toast('Document uploaded. Ready for review.');await refresh();}catch(error){$('upload-error').textContent=errorMessage(error);}finally{$('upload-submit').disabled=false;$('upload-submit').textContent='Upload document';}});
$('import-form').addEventListener('submit',async e=>{e.preventDefault();$('import-error').textContent='';$('import-submit').disabled=true;$('import-submit').textContent='Importing…';try{await api(`${base()}/imports/github`,{method:'POST',body:JSON.stringify({owner:$('github-owner').value.trim(),repo:$('github-repo').value.trim()})});$('import-dialog').close();state.page=1;state.status='';$('search').value='';$('category').value='';toast('README imported and ready for review.');await refresh();}catch(error){$('import-error').textContent=errorMessage(error);}finally{$('import-submit').disabled=false;$('import-submit').textContent='Import README ↗';}});
let deleteId;
$('document-rows').addEventListener('click',async e=>{const button=e.target.closest('[data-action]');if(!button)return;const doc=state.rows.find(d=>d.id===button.dataset.id);if(!doc)return;if(button.dataset.action==='download')return download(`${base()}/documents/${encodeURIComponent(doc.id)}/download`,doc.name);if(button.dataset.action==='delete'){deleteId=doc.id;$('confirm-copy').textContent=`“${doc.name}” will be permanently removed from this workspace. This action is recorded in the audit log.`;$('delete-error').textContent='';$('confirm-dialog').showModal();return;}button.disabled=true;try{await api(`${base()}/documents/${encodeURIComponent(doc.id)}/approve`,{method:'POST'});toast('Document approved.');await refresh();}catch(error){toast(errorMessage(error));button.disabled=false;}});
$('confirm-form').addEventListener('submit',async e=>{e.preventDefault();$('delete-submit').disabled=true;try{await api(`${base()}/documents/${encodeURIComponent(deleteId)}`,{method:'DELETE'});$('confirm-dialog').close();toast('Document deleted.');state.page=1;await refresh();}catch(error){$('delete-error').textContent=errorMessage(error);}finally{$('delete-submit').disabled=false;}});
$('member-rows').addEventListener('change',async e=>{if(!e.target.matches('[data-member]'))return;const select=e.target;select.disabled=true;try{await api(`${base()}/members/${encodeURIComponent(select.dataset.member)}`,{method:'PATCH',body:JSON.stringify({role:select.value})});toast('Role updated. Permissions take effect immediately.');state.user=await api('/api/auth/me');state.tenant=state.user.workspaces.find(w=>w.id===state.tenant.id);applyWorkspace();if(!admin())await setView('library');else await refresh();}catch(error){toast(errorMessage(error));await refresh();}});
async function boot(){try{const config=await api('/api/config');$('demo-login').hidden=$('demo-badge').hidden=!config.demo;try{await loadUser();}catch(e){showLogin();if(e.status!==401)$('login-error').textContent=errorMessage(e);}api('/health/ready').then(()=>$('health-status').textContent='Service ready').catch(()=>$('health-status').textContent='Service needs attention');}catch(e){showLogin();$('login-error').textContent=errorMessage(e);}finally{$('initial-loading').hidden=true;}}
boot();
