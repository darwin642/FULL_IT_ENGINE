(() => {
"use strict";
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const state = { images: [], history: [], selected: new Set(), editing: null, pendingDelete: null };
const el = {
  rows: $("#oi-rows"), empty: $("#oi-empty"), count: $("#oi-row-count"),
  tabCount: $("#oi-tab-count"), bulk: $("#oi-bulk"), selectedCount: $("#oi-selected-count"),
  selectAll: $("#oi-select-all"), search: $("#oi-search"), os: $("#oi-os-filter"),
  status: $("#oi-status-filter"), sort: $("#oi-sort"), modal: $("#oi-modal"),
  modalTitle: $("#oi-modal-title"), modalBody: $("#oi-modal-body"),
  modalActions: $("#oi-modal-actions"), toast: $("#oi-toast")
};
let toastTimer;
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const dateLabel = value => {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
};
function notify(message) {
  el.toast.textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.toast.textContent = ""; }, 4200);
}
function log(action, detail) {
  state.history.unshift({id:uid(), action, detail, at:new Date().toISOString()});
  renderHistory();
}
function closeModal() { el.modal.hidden = true; }
function showModal(title, body, actions=[]) {
  el.modalTitle.textContent = title;
  el.modalBody.innerHTML = body;
  el.modalActions.replaceChildren();
  for (const item of actions) {
    const b = document.createElement("button");
    b.className = `oi-btn ${item.primary ? "oi-primary" : ""} ${item.danger ? "oi-danger-outline" : ""}`;
    b.textContent = item.label;
    b.addEventListener("click", item.run);
    el.modalActions.append(b);
  }
  el.modal.hidden = false;
}
function visibleImages() {
  const q = el.search.value.trim().toLowerCase();
  const os = el.os.value, status = el.status.value, sort = el.sort.value;
  const list = state.images.filter(x =>
    [x.name,x.os,x.version,x.addedBy].some(v => String(v || "").toLowerCase().includes(q)) &&
    (!os || x.os === os) &&
    (!status || (status === "official" ? x.official : !x.official))
  );
  list.sort((a,b) => {
    if (sort === "size") return (a.sizeBytes || 0) - (b.sizeBytes || 0);
    if (sort === "date") return new Date(b.addedAt) - new Date(a.addedAt);
    if (sort === "os") return a.os.localeCompare(b.os);
    if (sort === "version") return a.version.localeCompare(b.version);
    if (sort === "official") return Number(b.official) - Number(a.official);
    return a.name.localeCompare(b.name);
  });
  return list;
}
function statusMarkup(img) {
  return img.official
    ? '<span class="oi-status official">✓ Official</span>'
    : '<span class="oi-status unverified">✕ Unverified</span>';
}
function render() {
  const list = visibleImages();
  el.rows.replaceChildren();
  for (const img of list) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="oi-check"><input type="checkbox" data-select="${esc(img.id)}" aria-label="Select ${esc(img.name)}" ${state.selected.has(img.id)?"checked":""}></td>
      <td><div class="oi-image-name">${esc(img.name)}</div><div class="oi-file-sub">${esc(img.extension.toUpperCase())} image</div></td>
      <td>${esc(img.os)}</td><td>${esc(img.version || "—")}</td>
      <td>${img.sizeBytes ? (img.sizeBytes/1024**3).toFixed(2)+" GB" : "—"}</td>
      <td>${statusMarkup(img)}</td><td>${esc(img.addedBy || "Unknown")}</td>
      <td>${esc(dateLabel(img.addedAt))}</td>
      <td class="oi-action-cell">
        <button class="oi-dots" data-menu="${esc(img.id)}" aria-expanded="false" aria-label="Actions for ${esc(img.name)}">⋯</button>
        <div class="oi-row-menu" data-row-menu="${esc(img.id)}" hidden>
          <button data-action="details" data-id="${esc(img.id)}">◉ View Details</button>
          <button data-action="deploy" data-id="${esc(img.id)}">➤ Deploy</button>
          <button data-action="edit" data-id="${esc(img.id)}">✎ Edit</button>
          <button class="oi-menu-delete" data-action="delete" data-id="${esc(img.id)}">♲ Delete</button>
        </div>
      </td>`;
    el.rows.append(tr);
  }
  el.empty.hidden = list.length > 0;
  el.tabCount.textContent = state.images.length;
  el.count.textContent = `${list.length} of ${state.images.length} images`;
  const visibleIds = list.map(x => x.id);
  el.selectAll.checked = visibleIds.length > 0 && visibleIds.every(id => state.selected.has(id));
  el.selectAll.indeterminate = visibleIds.some(id => state.selected.has(id)) && !el.selectAll.checked;
  el.bulk.hidden = state.selected.size === 0;
  el.selectedCount.textContent = `${state.selected.size} image${state.selected.size===1?"":"s"} selected`;
}
function renderHistory() {
  const list = $("#oi-history-list"), empty = $("#oi-history-empty");
  list.replaceChildren();
  for (const item of state.history) {
    const row = document.createElement("div");
    row.className = "oi-history-item";
    row.innerHTML = `<span class="oi-history-dot"></span><div><strong>${esc(item.action)}</strong><p>${esc(item.detail)}</p></div><time>${esc(dateLabel(item.at))}</time>`;
    list.append(row);
  }
  empty.hidden = state.history.length > 0;
}
function openTab(tab) {
  $$(".oi-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  $("#oi-image-tools").hidden = tab !== "images";
  $("#oi-bulk").hidden = tab !== "images" || state.selected.size === 0;
  $("#oi-image-view").hidden = tab !== "images";
  $("#oi-history-view").hidden = tab !== "history";
}
function imageForm(img=null) {
  state.editing = img?.id || null;
  const isEdit = !!img;
  showModal(isEdit ? "Edit Image" : "Add Image Metadata", `
    <form class="oi-form" id="oi-image-form">
      <div class="oi-field full"><label for="oi-name">Image name</label><input id="oi-name" required maxlength="240" value="${esc(img?.name || "")}" ${isEdit?"":"readonly"}></div>
      <div class="oi-field"><label for="oi-form-os">Operating system</label><select id="oi-form-os"><option ${img?.os==="Windows"?"selected":""}>Windows</option><option ${img?.os==="Linux"?"selected":""}>Linux</option><option ${img?.os==="macOS"?"selected":""}>macOS</option><option ${img?.os==="Other"?"selected":""}>Other</option></select></div>
      <div class="oi-field"><label for="oi-version">Version</label><input id="oi-version" maxlength="80" value="${esc(img?.version || "")}" placeholder="e.g. 24H2"></div>
      <div class="oi-field full"><label for="oi-added-by">Added by</label><input id="oi-added-by" maxlength="120" value="${esc(img?.addedBy || "Administrator")}"></div>
      <div class="oi-field full"><label for="oi-source">Official source URL (optional)</label><input id="oi-source" type="url" value="${esc(img?.sourceUrl || "")}" placeholder="https://vendor.example/..."><small>Only mark Official after you have independently verified the source.</small></div>
      <div class="oi-field full"><label class="oi-checkline"><input id="oi-official" type="checkbox" ${img?.official?"checked":""}> I verified this image against the publisher's official source.</label></div>
      ${!isEdit ? '<div class="oi-field full"><small>Prototype note: this records metadata in the current page session. The file is not uploaded to a server yet.</small></div>' : ''}
    </form>`, [
      {label:"Cancel",run:closeModal},
      {label:isEdit?"Save changes":"Save metadata",primary:true,run:() => {
        const form = $("#oi-image-form");
        if (!form.reportValidity()) return;
        const old = img || {};
        const updated = {...old,
          name:$("#oi-name").value.trim(),
          os:$("#oi-form-os").value,
          version:$("#oi-version").value.trim(),
          addedBy:$("#oi-added-by").value.trim() || "Unknown",
          sourceUrl:$("#oi-source").value.trim(),
          official:$("#oi-official").checked
        };
        if (updated.official && !updated.sourceUrl) {
          notify("Add the official source URL before marking this image Official.");
          return;
        }
        if (isEdit) {
          Object.assign(img, updated);
          log("Image updated", img.name);
        } else {
          state.images.push(updated);
          log("Image metadata added", updated.name);
        }
        closeModal(); render();
      }}
    ]);
  if (!isEdit) $("#oi-name").readOnly = false;
}
function addFiles(files) {
  const accepted = [...files];
  if (!accepted.length) return;
  const bad = accepted.filter(f => !/\.(iso|dmg|app)$/i.test(f.name));
  if (bad.length) notify(`Unsupported file(s) skipped: ${bad.map(f=>f.name).join(", ")}. Only .iso, .dmg and .app are accepted.`);
  const good = accepted.filter(f => /\.(iso|dmg|app)$/i.test(f.name));
  if (!good.length) return;
  // Metadata-only preview: browser File objects are not uploaded or persisted.
  const f = good[0];
  const ext = f.name.split(".").pop().toLowerCase();
  const img = {
    id:uid(), name:f.name, extension:ext, sizeBytes:f.size,
    os:ext==="dmg"||ext==="app"?"macOS":"Other", version:"",
    addedBy:"Administrator", addedAt:new Date().toISOString(),
    official:false, sourceUrl:"", localOnly:true
  };
  state.images.push(img);
  log("Image selected (local preview)", `${f.name} — file not uploaded to backend`);
  render();
  imageForm(img);
  notify(`${f.name} selected. Metadata can be edited; server upload is not connected.`);
  if (good.length > 1) notify("For this preview, add metadata for the remaining files individually.");
}
function details(id) {
  const x = state.images.find(i=>i.id===id); if (!x) return;
  showModal("Image Details", `<div class="oi-detail-grid">
    <div class="oi-detail"><span>Image name</span><strong>${esc(x.name)}</strong></div>
    <div class="oi-detail"><span>Operating system</span><strong>${esc(x.os)}</strong></div>
    <div class="oi-detail"><span>Version</span><strong>${esc(x.version||"—")}</strong></div>
    <div class="oi-detail"><span>File size</span><strong>${x.sizeBytes?(x.sizeBytes/1024**3).toFixed(2)+" GB":"—"}</strong></div>
    <div class="oi-detail"><span>Originality</span><strong>${x.official?"✓ Official":"✕ Unverified"}</strong></div>
    <div class="oi-detail"><span>Added by</span><strong>${esc(x.addedBy||"Unknown")}</strong></div>
    <div class="oi-detail"><span>Date added</span><strong>${esc(dateLabel(x.addedAt))}</strong></div>
    <div class="oi-detail"><span>Source</span><strong>${x.sourceUrl?`<a href="${esc(x.sourceUrl)}" target="_blank" rel="noopener noreferrer">View source</a>`:"Not provided"}</strong></div>
  </div><p class="oi-disclaimer">Local preview record. The file itself is not stored on the server.</p>`, [{label:"Close",primary:true,run:closeModal}]);
}
function deploy(ids) {
  const items = state.images.filter(x=>ids.includes(x.id));
  if (!items.length) return;
  if (items.some(x=>x.os==="macOS")) {
    showModal("Deployment blocked", '<div class="oi-warning"><strong>PXE is NOT Supported on Mac devices.</strong><br>Remove macOS images from the selection before continuing with PXE deployment.</div>', [{label:"Close",primary:true,run:closeModal}]);
    return;
  }
  showModal("Deployment Preflight", `<div class="oi-warning">PXE and deployment services are not connected. No deployment will be started from this preview.</div>
    <p style="font-size:12px;line-height:1.7">Selected images: <strong>${items.map(x=>esc(x.name)).join(", ")}</strong></p>
    <ul style="font-size:12px;line-height:1.8"><li>Confirm target device and OS compatibility.</li><li>Verify DHCP/PXE services and network reachability. Routed networks may require DHCP relay/IP helper configuration.</li><li>Verify BIOS/UEFI and boot mode compatibility.</li><li>Confirm the target disk and destructive-operation warnings.</li></ul>`,
    [{label:"Cancel",run:closeModal},{label:"Record preflight attempt",primary:true,run:()=>{log("Deployment preflight opened",items.map(x=>x.name).join(", "));closeModal();notify("Preflight recorded in this session only. No deployment was executed.");}}]);
}
function deleteImages(ids) {
  const items = state.images.filter(x=>ids.includes(x.id));
  if (!items.length) return;
  showModal("Confirm deletion", `<div class="oi-warning">Delete ${items.length} selected image record${items.length===1?"":"s"} from this preview? This does not delete any server-side files.</div><p style="font-size:12px">${items.map(x=>esc(x.name)).join("<br>")}</p>`,
    [{label:"Cancel",run:closeModal},{label:"Delete",danger:true,run:()=> {
      state.images = state.images.filter(x=>!ids.includes(x.id));
      ids.forEach(id=>state.selected.delete(id));
      log("Image record(s) deleted",items.map(x=>x.name).join(", "));
      closeModal();render();notify("Preview records deleted.");
    }}]);
}
function exportJson() {
  const payload = {format:"cartman-os-image-metadata",version:1,exportedAt:new Date().toISOString(),images:state.images.map(({id,name,extension,sizeBytes,os,version,addedBy,addedAt,official,sourceUrl})=>({id,name,extension,sizeBytes,os,version,addedBy,addedAt,official,sourceUrl}))};
  const blob = new Blob([JSON.stringify(payload,null,2)],{type:"application/json"});
  const url = URL.createObjectURL(blob), a = document.createElement("a");
  a.href=url;a.download="cartman-os-images.json";a.click();URL.revokeObjectURL(url);
  log("JSON exported",`${state.images.length} image metadata record(s)`);
  notify("JSON metadata export created; image binaries are not included.");
}
async function importJson(file) {
  try {
    const data = JSON.parse(await file.text());
    const rows = Array.isArray(data) ? data : data.images;
    if (!Array.isArray(rows)) throw new Error("JSON must contain an images array.");
    const imported = rows.map(x=>{
      if (!x || typeof x.name!=="string" || !/\.(iso|dmg|app)$/i.test(x.name)) throw new Error("Every image needs a valid .iso, .dmg or .app filename.");
      return {id:uid(),name:x.name,extension:(x.extension||x.name.split(".").pop()).toLowerCase(),sizeBytes:Number(x.sizeBytes)||0,os:["Windows","Linux","macOS","Other"].includes(x.os)?x.os:"Other",version:String(x.version||""),addedBy:String(x.addedBy||"Imported"),addedAt:x.addedAt||new Date().toISOString(),official:false,sourceUrl:String(x.sourceUrl||""),localOnly:true};
    });
    state.images.push(...imported);
    log("JSON imported",`${imported.length} metadata record(s); authenticity reset to Unverified for review`);
    render();notify(`Imported ${imported.length} metadata record(s). Verify authenticity before marking Official.`);
  } catch (e) { notify(`Import failed: ${e.message}`); }
}
function closeImageRowMenus() {
  $$("[data-row-menu]").forEach(menu => {
    menu.hidden = true;
    menu.classList.remove("oi-menu-floating");
    menu.style.left = "";
    menu.style.top = "";
    menu.style.width = "";
    menu.style.maxHeight = "";

    if (menu._oiOriginalParent) {
      menu._oiOriginalParent.insertBefore(menu, menu._oiOriginalNext || null);
      delete menu._oiOriginalParent;
      delete menu._oiOriginalNext;
    }
  });

  $$("[data-menu]").forEach(button => button.setAttribute("aria-expanded", "false"));
}

function openImageRowMenu(button, menu) {
  closeImageRowMenus();

  menu._oiOriginalParent = menu.parentNode;
  menu._oiOriginalNext = menu.nextSibling;
  menu.hidden = false;
  menu.classList.add("oi-menu-floating");
  document.body.appendChild(menu);
  button.setAttribute("aria-expanded", "true");

  const rect = button.getBoundingClientRect();
  const gap = 6;
  const margin = 12;
  const width = Math.min(220, Math.max(165, rect.width + 135));

  menu.style.width = `${width}px`;
  menu.style.left = `${Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin))}px`;

  const menuHeight = menu.getBoundingClientRect().height;
  const spaceBelow = window.innerHeight - rect.bottom - margin;
  const spaceAbove = rect.top - margin;

  if (menuHeight <= spaceBelow || spaceBelow >= spaceAbove) {
    menu.style.top = `${rect.bottom + gap}px`;
    menu.style.maxHeight = `${Math.max(100, spaceBelow - gap)}px`;
  } else {
    menu.style.top = `${Math.max(margin, rect.top - Math.min(menuHeight, spaceAbove) - gap)}px`;
    menu.style.maxHeight = `${Math.max(100, spaceAbove - gap)}px`;
  }
}

document.addEventListener("click", event => {
  const menuButton = event.target.closest("[data-menu]");

  if (menuButton) {
    const id = menuButton.dataset.menu;
    const menu = $(`[data-row-menu="${CSS.escape(id)}"]`);
    const wasOpen = menu && !menu.hidden;

    closeImageRowMenus();

    if (menu && !wasOpen) openImageRowMenu(menuButton, menu);
    return;
  }

  const action = event.target.closest("[data-action]");

  if (action) {
    const id = action.dataset.id;
    closeImageRowMenus();

    const img = state.images.find(x => x.id === id);
    if (!img) return;

    if (action.dataset.action === "details") details(id);
    if (action.dataset.action === "edit") imageForm(img);
    if (action.dataset.action === "deploy") deploy([id]);
    if (action.dataset.action === "delete") deleteImages([id]);
    return;
  }

  if (!event.target.closest(".oi-menu-floating")) closeImageRowMenus();
});

window.addEventListener("resize", closeImageRowMenus);
window.addEventListener("scroll", closeImageRowMenus, true);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") closeImageRowMenus();
});
el.rows.addEventListener("change",event=>{
  const cb=event.target.closest("[data-select]"); if(!cb)return;
  cb.checked?state.selected.add(cb.dataset.select):state.selected.delete(cb.dataset.select);
  render();
});
el.selectAll.addEventListener("change",()=>{
  visibleImages().forEach(x=>el.selectAll.checked?state.selected.add(x.id):state.selected.delete(x.id));
  render();
});
[el.search,el.os,el.status,el.sort].forEach(x=>x.addEventListener(x===el.search?"input":"change",render));
$("#oi-add").addEventListener("click",()=>$("#oi-file-input").click());
$("#oi-empty-add").addEventListener("click",()=>$("#oi-file-input").click());
$("#oi-file-input").addEventListener("change",e=>{addFiles(e.target.files);e.target.value="";});
$("#oi-import").addEventListener("click",()=>$("#oi-json-input").click());
$("#oi-json-input").addEventListener("change",e=>{if(e.target.files[0])importJson(e.target.files[0]);e.target.value="";});
$("#oi-export").addEventListener("click",exportJson);
$("#oi-deploy-selected").addEventListener("click",()=>deploy([...state.selected]));
$("#oi-delete-selected").addEventListener("click",()=>deleteImages([...state.selected]));
$("#oi-clear-selection").addEventListener("click",()=>{state.selected.clear();render();});
$("#oi-modal-close").addEventListener("click",closeModal);
el.modal.addEventListener("click",e=>{if(e.target===el.modal)closeModal();});
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeModal();});
$$(".oi-tab").forEach(b=>b.addEventListener("click",()=>openTab(b.dataset.tab)));
$("#oi-clear-history").addEventListener("click",()=>{state.history=[];renderHistory();notify("Session history cleared.");});
render();renderHistory();
})();
