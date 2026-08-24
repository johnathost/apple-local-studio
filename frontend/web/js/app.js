/**
 * Local Apple Studio — scene builder + compose preview + generate.
 */

const state = {
  schema: null,
  scene: {},
  engine: {},
  loras: [],
  catalog: [],
  prompt: "",
  tags: [],
  matched: [],
  manualScales: {}, // id -> scale override
  refImage: null, // { filename, url } identity / source
  poseImage: null, // { filename, url } pose/camera plate, edit only
  pollTimer: null,
  mode: "gen", // gen | edit
  editKind: null, // null | undress | pose
  systemPrompts: { gen: "", edit: "", undress: "", pose: "" },
  winner: null,
  blocked: {},
  dropped: [],
  undoStack: [], // previous refImage snapshots
  lastGenerate: null, // last POST /api/generate body
  lastResult: null, // { image_file, image_url }
  scenes: { extras: [], scenes: [] },
  studioSimple: true,
  showPrompt: false,
  undressFirst: false,
  twoTakes: false,
  shoot: null, // { identity, recipe, frames, selected, subjectIndex }
  jobStartedAt: null,
  elapsedTimer: null,
};

const GENITAL_EXTRAS = new Set();

const $ = (sel) => document.querySelector(sel);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function getSceneValue(groupId, fieldId) {
  return state.scene?.[groupId]?.[fieldId];
}

function catalogMode() {
  if (state.editKind === "undress" || state.editKind === "pose") return state.editKind;
  return state.mode;
}

function renderPoseGallery(wrap, field) {
  const cats = state.schema?.pose_categories || [];
  const current = getSceneValue("pose", "scene") || field.default;
  for (const cat of cats) {
    const section = document.createElement("div");
    section.className = "pose-cat";
    const heading = document.createElement("div");
    heading.className = "pose-cat-label";
    heading.textContent = cat.label || "Poses";
    section.appendChild(heading);
    const list = document.createElement("div");
    list.className = "pose-cat-list";
    for (const pose of cat.poses || []) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "pose-row" + (pose.id === current ? " active" : "");
      const title = document.createElement("span");
      title.className = "pose-row-title";
      title.textContent = pose.title || pose.id;
      const img = document.createElement("img");
      img.className = "pose-row-thumb";
      img.src = pose.image_url;
      img.alt = pose.title || "";
      row.appendChild(title);
      row.appendChild(img);
      row.addEventListener("click", () => {
        setSceneValue("pose", "scene", pose.id);
        list.querySelectorAll(".pose-row").forEach((r) => r.classList.remove("active"));
        row.classList.add("active");
      });
      list.appendChild(row);
    }
    section.appendChild(list);
    wrap.appendChild(section);
  }
}

function currentStudioScene() {
  const id = getSceneValue("pose", "scene");
  return (state.scenes.scenes || []).find((s) => s.id === id || s.plate === id) || null;
}

function optionLabel(groupId, fieldId, value) {
  const group = (state.schema?.groups || []).find((g) => g.id === groupId);
  const field = (group?.fields || []).find((f) => f.id === fieldId);
  const opt = (field?.options || []).find((o) => o.id === value);
  return opt?.label || value || "—";
}

function directorText() {
  const face = state.refImage ? "her" : "need a photo";
  const pose = optionLabel("position", "pose", getSceneValue("position", "pose"));
  const sex = optionLabel("sex", "category", getSceneValue("sex", "category"));
  return `${face} · ${pose} · ${sex}`;
}

function studioPlan() {
  const steps = [];
  if (state.undressFirst) steps.push("Undress");
  const pose = optionLabel("position", "pose", getSceneValue("position", "pose"));
  const sex = optionLabel("sex", "category", getSceneValue("sex", "category"));
  steps.push([pose, sex].filter(Boolean).join(" · ") || "Pose");
  return steps;
}

function fieldVisible(field) {
  const show = field?.show_if;
  if (!show) return true;
  return getSceneValue(show.group, show.field) === show.equals;
}

function groupedOptions(field) {
  const groups = [];
  const map = new Map();
  for (const opt of field.options || []) {
    const gid = opt.group || "_";
    if (!map.has(gid)) {
      const g = { id: gid, label: opt.group_label || field.label, options: [] };
      map.set(gid, g);
      groups.push(g);
    }
    map.get(gid).options.push(opt);
  }
  return groups;
}

function renderStudioField(group, field) {
  if (!fieldVisible(field)) return null;
  const wrap = document.createElement("div");
  wrap.className = "studio-section";
  const kicker = document.createElement("p");
  kicker.className = "studio-kicker";
  kicker.textContent = field.label || group.label;
  wrap.appendChild(kicker);

  const grouped = (field.options || []).some((o) => o.group);
  if (field.type === "choice" && grouped) {
    const cats = document.createElement("div");
    cats.className = "pose-cats";
    const current = getSceneValue(group.id, field.id);
    for (const g of groupedOptions(field)) {
      const cat = document.createElement("div");
      cat.className = "pose-cat";
      const heading = document.createElement("div");
      heading.className = "pose-cat-label";
      heading.textContent = g.label;
      cat.appendChild(heading);
      const grid = document.createElement("div");
      grid.className = "pose-grid";
      for (const opt of g.options) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "pose-pick" + (current === opt.id ? " active" : "");
        const title = document.createElement("span");
        title.className = "pose-pick-title";
        title.textContent = opt.label;
        btn.appendChild(title);
        if (opt.blurb) {
          const blurb = document.createElement("span");
          blurb.className = "pose-pick-blurb";
          blurb.textContent = opt.blurb;
          btn.appendChild(blurb);
        }
        btn.addEventListener("click", () => {
          setSceneValue(group.id, field.id, opt.id);
          renderSceneStudio();
        });
        grid.appendChild(btn);
      }
      cat.appendChild(grid);
      cats.appendChild(cat);
    }
    wrap.appendChild(cats);
    return wrap;
  }

  const chips = document.createElement("div");
  chips.className = "chips";
  if (field.type === "choice") {
    const current = getSceneValue(group.id, field.id);
    for (const opt of field.options || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip" + (current === opt.id ? " active" : "");
      btn.textContent = opt.label;
      if (optionBlocked(group.id, field.id, opt.id) && current !== opt.id) {
        btn.classList.add("conflict");
      }
      btn.addEventListener("click", () => {
        if (opt.id !== "keep" && current === opt.id && field.id === "face") {
          setSceneValue(group.id, field.id, "keep");
        } else {
          setSceneValue(group.id, field.id, opt.id);
        }
        renderSceneStudio();
      });
      chips.appendChild(btn);
    }
  } else if (field.type === "multi") {
    const selected = new Set(getSceneValue(group.id, field.id) || []);
    for (const opt of field.options || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip multi" + (selected.has(opt.id) ? " active" : "");
      btn.textContent = opt.label;
      btn.addEventListener("click", () => {
        const cur = new Set(getSceneValue(group.id, field.id) || []);
        if (cur.has(opt.id)) cur.delete(opt.id);
        else cur.add(opt.id);
        setSceneValue(group.id, field.id, [...cur]);
        renderSceneStudio();
      });
      chips.appendChild(btn);
    }
  }
  wrap.appendChild(chips);
  return wrap;
}

function renderSceneStudio() {
  const root = $("#scene-studio");
  if (!root || state.editKind !== "pose" || !state.studioSimple) {
    root?.classList.add("hidden");
    return;
  }
  root.classList.remove("hidden");
  root.innerHTML = "";
  const dir = document.createElement("p");
  dir.className = "director-line";
  dir.innerHTML = directorText()
    .split(" · ")
    .map((bit) => {
      const i = bit.indexOf("=");
      if (i < 0) return escapeHtml(bit);
      return `<span>${escapeHtml(bit.slice(0, i + 1))}</span>${escapeHtml(bit.slice(i + 1))}`;
    })
    .join(" · ");
  root.appendChild(dir);

  const fields = [];
  for (const group of state.schema?.groups || []) {
    for (const field of group.fields || []) {
      if (field.type === "choice" || field.type === "multi") fields.push({ group, field });
    }
  }
  const skip = new Set();
  const pairWith = {
    "pussy.look": "asshole.look",
    "clothing.state": "clothing.heels",
  };
  for (let i = 0; i < fields.length; i++) {
    const key = `${fields[i].group.id}.${fields[i].field.id}`;
    if (skip.has(key)) continue;
    const mateId = pairWith[key];
    const node = renderStudioField(fields[i].group, fields[i].field);
    if (!node) continue;
    if (mateId) {
      const mate = fields.find((f) => `${f.group.id}.${f.field.id}` === mateId);
      const mateNode = mate ? renderStudioField(mate.group, mate.field) : null;
      if (mateNode) {
        skip.add(mateId);
        const split = document.createElement("div");
        split.className = "studio-split";
        split.appendChild(node);
        split.appendChild(mateNode);
        root.appendChild(split);
        continue;
      }
    }
    root.appendChild(node);
  }

  const foot = document.createElement("div");
  foot.className = "studio-foot";
  const undressRow = document.createElement("label");
  undressRow.className = "toggle";
  undressRow.innerHTML = `<input type="checkbox" id="studio-undress" ${state.undressFirst ? "checked" : ""} /> Undress first`;
  undressRow.querySelector("input").addEventListener("change", (e) => {
    state.undressFirst = e.target.checked;
    renderSceneStudio();
  });
  foot.appendChild(undressRow);
  const takesRow = document.createElement("label");
  takesRow.className = "toggle";
  takesRow.innerHTML = `<input type="checkbox" id="studio-takes" ${state.twoTakes ? "checked" : ""} /> Two takes`;
  takesRow.querySelector("input").addEventListener("change", (e) => {
    state.twoTakes = e.target.checked;
    renderSceneStudio();
  });
  foot.appendChild(takesRow);
  root.appendChild(foot);

  const loraK = document.createElement("p");
  loraK.className = "studio-kicker";
  loraK.textContent = "LoRAs";
  root.appendChild(loraK);
  const loraRow = document.createElement("div");
  loraRow.className = "studio-loras";
  const defChip = document.createElement("span");
  defChip.className = "chip locked";
  defChip.textContent = "SNOFS · default";
  loraRow.appendChild(defChip);
  for (const id of Object.keys(state.manualScales)) {
    if (id === "snofs") continue;
    const entry = (state.catalog || []).find((c) => c.id === id);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip active";
    chip.textContent = `${entry?.name || id} ×`;
    chip.addEventListener("click", () => {
      delete state.manualScales[id];
      renderSceneStudio();
      scheduleCompose();
    });
    loraRow.appendChild(chip);
  }
  const loraSel = document.createElement("select");
  loraSel.innerHTML = `<option value="">+ extra LoRA</option>`;
  const pinned = new Set(["snofs", ...Object.keys(state.manualScales)]);
  for (const entry of state.catalog || []) {
    if (!entry.id || pinned.has(entry.id) || entry.enabled === false) continue;
    const opt = document.createElement("option");
    opt.value = entry.id;
    const miss = entry.available ? "" : " (missing file)";
    opt.textContent = `${entry.name}${miss}`;
    loraSel.appendChild(opt);
  }
  loraSel.addEventListener("change", () => {
    const id = loraSel.value;
    if (!id) return;
    const entry = (state.catalog || []).find((c) => c.id === id);
    state.manualScales[id] = Number(entry?.default_scale ?? 0.8);
    renderSceneStudio();
    scheduleCompose();
  });
  loraRow.appendChild(loraSel);
  root.appendChild(loraRow);

  const plan = studioPlan();
  const planEl = document.createElement("p");
  planEl.className = "studio-plan";
  planEl.textContent = state.twoTakes
    ? `${plan.join(" → ")} · 2 takes`
    : plan.join(" → ");
  root.appendChild(planEl);
}

function setSceneValue(groupId, fieldId, value) {
  if (!state.scene[groupId]) state.scene[groupId] = {};
  state.scene[groupId][fieldId] = value;
  state.winner = `${groupId}.${fieldId}`;
  // Sync notes quick box into style.notes
  if (groupId === "style" && fieldId === "notes") {
    const nq = $("#notes-quick");
    if (nq && document.activeElement !== nq) nq.value = value || "";
  }
  scheduleCompose();
}

function openGroupIds() {
  return [...document.querySelectorAll("#builder-root details.group")]
    .filter((d) => d.open)
    .map((d) => d.dataset.group);
}

function optionBlocked(groupId, fieldId, optId) {
  const blocked = state.blocked[`${groupId}.${fieldId}`] || [];
  return blocked.includes(optId);
}

function renderBuilder() {
  const root = $("#builder-root");
  const keptOpen = new Set(openGroupIds());
  root.innerHTML = "";
  const defaultOpen = new Set([
    "sex",
    "position",
    "toys",
    "expression",
    "pussy",
    "asshole",
    "extras",
    "clothing",
    "subject",
    "body",
    "act",
    "camera",
  ]);
  for (const group of state.schema.groups || []) {
    const details = document.createElement("details");
    details.className =
      "group" + (group.id === "preset" || group.id === "pose" ? " preset-group" : "");
    details.dataset.group = group.id;
    details.open = keptOpen.size ? keptOpen.has(group.id) : defaultOpen.has(group.id);
    const summary = document.createElement("summary");
    summary.textContent = group.label;
    details.appendChild(summary);

    const body = document.createElement("div");
    body.className = "group-body";

    for (const field of group.fields || []) {
      const wrap = document.createElement("div");
      if (field.type !== "pose_gallery") {
        const label = document.createElement("div");
        label.className = "field-label";
        label.textContent = field.label;
        wrap.appendChild(label);
      }

      if (field.type === "pose_gallery") {
        renderPoseGallery(wrap, field);
      } else if (field.type === "choice") {
        const chips = document.createElement("div");
        chips.className = "chips";
        for (const opt of field.options || []) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "chip";
          btn.textContent = opt.label;
          btn.dataset.value = opt.id;
          const selected = getSceneValue(group.id, field.id) === opt.id;
          if (selected) btn.classList.add("active");
          else if (optionBlocked(group.id, field.id, opt.id)) {
            btn.classList.add("conflict");
            btn.title = "Conflicts with the current scene — click to switch";
          }
          btn.addEventListener("click", () => {
            setSceneValue(group.id, field.id, opt.id);
            chips.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
            btn.classList.add("active");
            btn.classList.remove("conflict");
          });
          chips.appendChild(btn);
        }
        wrap.appendChild(chips);
      } else if (field.type === "multi") {
        const chips = document.createElement("div");
        chips.className = "chips";
        const selected = new Set(getSceneValue(group.id, field.id) || []);
        for (const opt of field.options || []) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "chip multi";
          btn.textContent = opt.label;
          if (selected.has(opt.id)) btn.classList.add("active");
          else if (optionBlocked(group.id, field.id, opt.id)) {
            btn.classList.add("conflict");
            btn.title = "Conflicts with the current scene — click to switch";
          }
          btn.addEventListener("click", () => {
            const cur = new Set(getSceneValue(group.id, field.id) || []);
            if (opt.id === "none") {
              cur.clear();
            } else {
              cur.delete("none");
              if (cur.has(opt.id)) cur.delete(opt.id);
              else cur.add(opt.id);
            }
            setSceneValue(group.id, field.id, [...cur]);
            chips.querySelectorAll(".chip").forEach((c) => {
              const id = c.dataset.value;
              c.classList.toggle("active", cur.has(id));
              c.classList.toggle("conflict", !cur.has(id) && optionBlocked(group.id, field.id, id));
            });
          });
          btn.dataset.value = opt.id;
          chips.appendChild(btn);
        }
        wrap.appendChild(chips);
      } else if (field.type === "text") {
        const input = document.createElement("input");
        input.type = "text";
        input.placeholder = field.placeholder || "";
        input.value = getSceneValue(group.id, field.id) || "";
        input.addEventListener("input", () => setSceneValue(group.id, field.id, input.value));
        wrap.appendChild(input);
      }

      body.appendChild(wrap);
    }

    details.appendChild(body);
    root.appendChild(details);
  }
}

function renderLoras() {
  const root = $("#lora-list");
  root.innerHTML = "";
  if (!state.matched.length) {
    root.innerHTML = `<div class="muted">No LoRAs matched. Adjust act / position / camera, or add files to <code>/opt/ivoai/lora</code>.</div>`;
    return;
  }
  for (const m of state.matched) {
    const card = document.createElement("div");
    card.className = "lora-card" + (m.available ? "" : " missing");
    const scale = state.manualScales[m.id] ?? m.scale;
    card.innerHTML = `
      <div class="row">
        <span class="name">${escapeHtml(m.name)}</span>
        <span class="pill ${m.available ? "ok" : "miss"}">${m.available ? "on disk" : "missing file"}</span>
      </div>
      <div class="meta">${escapeHtml(m.file || "(no filename)")} · score ${m.score}${m.auto ? " · auto" : " · manual"}</div>
      <div class="reasons">${(m.reasons || []).map(escapeHtml).join(" · ")}</div>
      <div class="scale-row">
        <span class="muted">scale</span>
        <input type="range" min="0.1" max="1.2" step="0.05" value="${scale}" data-id="${m.id}" />
        <span class="muted scale-val">${Number(scale).toFixed(2)}</span>
        ${m.auto ? "" : `<button type="button" class="ghost sm unpin" data-id="${m.id}">unpin</button>`}
      </div>
    `;
    const range = card.querySelector('input[type="range"]');
    const val = card.querySelector(".scale-val");
    range.addEventListener("input", () => {
      state.manualScales[m.id] = Number(range.value);
      val.textContent = Number(range.value).toFixed(2);
      scheduleCompose();
    });
    card.querySelector(".unpin")?.addEventListener("click", () => {
      delete state.manualScales[m.id];
      scheduleCompose();
    });
    root.appendChild(card);
  }
}

function renderTags() {
  const root = $("#tag-list");
  root.innerHTML = state.tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
}

function renderConstraintLine() {
  const el = $("#constraint-line");
  if (!el) return;
  if (!state.dropped.length) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.classList.remove("hidden");
  el.textContent = "Adjusted to keep the scene coherent: " + state.dropped.join(" · ");
}

function syncStrengthChrome() {
  const wrap = $("#strength-wrap");
  if (!wrap) return;
  const genRef = state.mode === "gen" && state.refImage;
  wrap.classList.toggle("hidden", !genRef);
  const label = wrap.querySelector("span, label") || wrap.childNodes[0];
  if (label && label.nodeType === Node.TEXT_NODE) {
    label.textContent = "Ref strength ";
  }
}

function setPoseChrome() {
  const wrap = $("#pose-wrap");
  const poseMode = state.editKind === "pose" && !state.studioSimple;
  wrap?.classList.toggle("hidden", !poseMode);
  const has = Boolean(state.poseImage);
  const label = $("#pose-label");
  if (label) label.textContent = has ? state.poseImage.filename : "";
  $("#btn-clear-pose")?.classList.toggle("hidden", !has || !poseMode);
  syncStrengthChrome();
}

function renderLoraPicker() {
  const sel = $("#lora-add");
  if (!sel) return;
  const pinned = new Set(state.matched.map((m) => m.id));
  const current = sel.value;
  sel.innerHTML = `<option value="">Add from catalog…</option>`;
  for (const entry of state.catalog) {
    if (!entry.id || pinned.has(entry.id) || entry.enabled === false) continue;
    const opt = document.createElement("option");
    opt.value = entry.id;
    const miss = entry.available ? "" : " (missing file)";
    const auto = entry.auto === false ? " · manual" : "";
    opt.textContent = `${entry.name}${auto}${miss}`;
    sel.appendChild(opt);
  }
  sel.value = "";
  if (current && [...sel.options].some((o) => o.value === current)) sel.value = current;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

let composeTimer = null;
function scheduleCompose() {
  clearTimeout(composeTimer);
  composeTimer = setTimeout(runCompose, 120);
}

function syncQuickNotes() {
  const notesQuick = $("#notes-quick")?.value ?? "";
  if (state.mode === "edit") {
    if (!state.scene.instruction) state.scene.instruction = {};
    state.scene.instruction.text = notesQuick;
  } else {
    if (!state.scene.style) state.scene.style = {};
    state.scene.style.notes = notesQuick;
  }
}

async function runCompose() {
  syncQuickNotes();

  const includeTriggers = $("#include-triggers").checked;
  const maxLorasRaw = Number($("#eng-max-loras").value);
  const maxLoras = Number.isFinite(maxLorasRaw) ? maxLorasRaw : Number(state.engine.max_loras ?? 2);
  const manual = Object.entries(state.manualScales).map(([id, scale]) => ({ id, scale }));

  try {
    const data = await api("/api/compose", {
      method: "POST",
      body: JSON.stringify({
        scene: state.scene,
        include_triggers: includeTriggers,
        max_loras: maxLoras,
        manual_loras: manual,
        mode: catalogMode(),
        winner: state.winner,
        pose_ref: Boolean(state.poseImage) && state.editKind === "pose",
      }),
    });
    const prevScene = JSON.stringify(state.scene);
    state.prompt = data.prompt;
    state.tags = data.tags || [];
    state.matched = data.loras || [];
    state.dropped = data.dropped || [];
    state.blocked = data.blocked || {};
    state.scene = data.scene || state.scene;
    state.winner = null;

    const ta = $("#prompt-out");
    if (document.activeElement !== ta) ta.value = state.prompt;
    const focused = document.activeElement;
    const typing =
      focused &&
      (focused.tagName === "INPUT" || focused.tagName === "TEXTAREA") &&
      focused.id !== "prompt-out";
    if (JSON.stringify(state.scene) !== prevScene && !typing) {
      renderBuilder();
      renderSceneStudio();
    }
    renderLoras();
    renderLoraPicker();
    renderTags();
    renderConstraintLine();
    setPoseChrome();
  } catch (e) {
    console.error(e);
  }
}

function setEngineForm() {
  $("#eng-width").value = state.engine.width ?? 832;
  $("#eng-height").value = state.engine.height ?? 1248;
  $("#eng-steps").value = state.engine.steps ?? 4;
  $("#eng-guidance").value = state.engine.guidance ?? (state.mode === "edit" ? 2.0 : 1.4);
  $("#eng-seed").value = state.engine.seed ?? "";
  $("#eng-quant").value = state.engine.quantize ?? 4;
  $("#eng-max-loras").value = state.engine.max_loras ?? 2;
}

function appendMsg(html, cls = "") {
  const thread = $("#chat-thread");
  const empty = thread.querySelector(".empty-hint");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.innerHTML = html;
  thread.appendChild(div);
  thread.scrollTop = thread.scrollHeight;
  return div;
}

function ensureEmptyHint() {
  const thread = $("#chat-thread");
  if (!thread || thread.children.length) return;
  if (state.shoot?.frames?.length) return;
  const poseSimple = state.editKind === "pose" && state.studioSimple;
  thread.innerHTML = poseSimple
    ? `<div class="empty-hint">Drop her photo. Pick a scene. <strong>Make scene</strong> runs one Klein job per step — click a frame to keep going, retry that step if it’s wrong.</div>`
    : `<div class="empty-hint">Build a scene on the left. Prompt &amp; LoRAs update live on the right. Hit <strong>Generate</strong> when ready.</div>`;
}

function formatElapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function tickElapsed() {
  const el = $("#work-elapsed");
  if (!el || !state.jobStartedAt) return;
  el.textContent = formatElapsed(Date.now() - state.jobStartedAt);
}

function startElapsed() {
  state.jobStartedAt = Date.now();
  clearInterval(state.elapsedTimer);
  tickElapsed();
  state.elapsedTimer = setInterval(tickElapsed, 250);
}

function stopElapsed() {
  clearInterval(state.elapsedTimer);
  state.elapsedTimer = null;
  tickElapsed();
}

function showJobStatus(job) {
  const el = $("#job-status");
  const work = $("#work-status");
  const live = job && (job.status === "running" || job.status === "queued");
  const pct = Math.max(0, Math.min(100, Math.round((Number(job?.progress) || 0) * 100)));
  const stepBit =
    job?.step != null && job?.steps != null ? `${job.step}/${job.steps}` : "";

  if (el) {
    el.classList.remove("hidden", "error", "running", "done");
    if (!job) {
      el.classList.add("hidden");
    } else {
      el.classList.add(job.status === "error" ? "error" : job.status === "done" ? "done" : "running");
      el.innerHTML = `
        <div><strong>${escapeHtml(job.status)}</strong> — ${escapeHtml(job.message || "")}${
          live ? ` (${pct}%${stepBit ? ` · ${stepBit}` : ""})` : ""
        }</div>
        ${job.error ? `<div>${escapeHtml(job.error)}</div>` : ""}
        ${live ? `<div class="progress det"><i style="width:${pct}%"></i></div>` : ""}
      `;
    }
  }

  if (!work) return;
  if (!job) {
    work.classList.add("hidden");
    work.classList.remove("error", "running", "done");
    return;
  }
  work.classList.remove("hidden", "error", "running", "done", "as-hero");
  work.classList.add(job.status === "error" ? "error" : job.status === "done" ? "done" : "running");
  const gotFrame = (state.shoot?.frames || []).some((f) => f.image_url);
  work.classList.toggle("as-hero", Boolean(live && !gotFrame));
  const kicker = $("#work-status .work-kicker");
  const msg = $("#work-message");
  const stepEl = $("#work-step");
  const bar = $("#work-bar");
  if (kicker) {
    kicker.textContent =
      job.status === "done"
        ? "Done"
        : job.status === "error"
          ? "Failed"
          : "Editing in the background";
  }
  if (msg) msg.textContent = job.error || job.message || job.status || "";
  if (stepEl) stepEl.textContent = live && stepBit ? stepBit : live ? `${pct}%` : "";
  if (bar) {
    bar.style.width = `${pct}%`;
    bar.parentElement?.classList.toggle("indet", live && pct < 3);
    bar.parentElement?.classList.toggle("det", !(live && pct < 3));
  }
}

function setRefImage(data) {
  state.refImage = data;
  const label = $("#ref-label");
  if (label) label.textContent = data?.filename || "";
  $("#btn-clear-ref")?.classList.toggle("hidden", !data);
  syncStrengthChrome();
  updateSessionLine();
  renderSceneStudio();
}

function clearRefImage() {
  state.refImage = null;
  $("#ref-label").textContent = "";
  $("#btn-clear-ref")?.classList.add("hidden");
  const input = $("#ref-image");
  if (input) input.value = "";
  syncStrengthChrome();
  updateSessionLine();
  renderSceneStudio();
}

function updateSessionLine() {
  const line = $("#session-line");
  const undo = $("#btn-undo-session");
  if (!line) return;
  if (!state.refImage) {
    line.classList.add("hidden");
    line.textContent = "";
    undo?.classList.add("hidden");
    return;
  }
  line.classList.remove("hidden");
  const n = state.undoStack.length;
  line.textContent =
    n > 0
      ? `Subject: ${state.refImage.filename} (${n} earlier)`
      : `Subject: ${state.refImage.filename}`;
  undo?.classList.toggle("hidden", n === 0);
}

async function continueFromOutput(imageFile) {
  const data = await api("/api/promote-output", {
    method: "POST",
    body: JSON.stringify({ name: imageFile }),
  });
  if (state.refImage) {
    state.undoStack.push({ filename: state.refImage.filename, url: state.refImage.url });
  }
  setRefImage(data);
  return data;
}

function clearShoot() {
  state.shoot = null;
  renderFilmstrip();
}

function applyShootFromJob(job) {
  const steps = job?.result?.steps;
  if (Array.isArray(steps) && steps.length) {
    if (!state.shoot) {
      state.shoot = {
        identity: state.refImage ? { ...state.refImage } : null,
        recipe: state.lastGenerate?._recipe ? { ...state.lastGenerate } : null,
        frames: [],
        selected: null,
        subjectIndex: null,
      };
    }
    const prevByIndex = Object.fromEntries(
      (state.shoot.frames || []).map((f) => [f.index, f])
    );
    state.shoot.frames = steps.map((s, i) => {
      const index = s.index ?? i;
      const prev = prevByIndex[index] || {};
      const takes = Array.isArray(s.takes) ? s.takes : [];
      const picked = prev.picked || s.picked || null;
      const winner = picked ? takes.find((t) => t.id === picked) || prev : null;
      return {
        index,
        label: s.label || `Step ${i + 1}`,
        status: s.status || (s.image_url ? "done" : "queued"),
        image_file: winner?.image_file || s.image_file || null,
        image_url: winner?.image_url || s.image_url || null,
        seed: winner?.seed ?? s.seed ?? null,
        takes,
        pick_required: picked ? false : Boolean(s.pick_required),
        picked,
      };
    });
    const lastDone = [...state.shoot.frames].reverse().find((f) => f.image_url);
    const stillThere = state.shoot.frames.some((f) => f.index === state.shoot.selected);
    if (state.shoot.selected == null || !stillThere) {
      state.shoot.selected = lastDone ? lastDone.index : 0;
    }
    renderFilmstrip();
    return;
  }
  const file = job?.result?.image_file;
  const url = job?.result?.image_url;
  if (!file || !url) return;
  state.shoot = {
    identity: state.refImage ? { ...state.refImage } : null,
    recipe: null,
    frames: [
      {
        index: 0,
        label: state.editKind === "undress" ? "Undress" : state.editKind === "pose" ? "Pose" : "Result",
        status: "done",
        image_file: file,
        image_url: url,
      },
    ],
    selected: 0,
    subjectIndex: null,
  };
  renderFilmstrip();
}

function renderFilmstrip() {
  const strip = $("#filmstrip");
  const hero = $("#take-hero");
  if (!strip) return;
  const frames = state.shoot?.frames || [];
  if (!frames.length) {
    strip.classList.add("hidden");
    strip.innerHTML = "";
    hero?.classList.add("hidden");
    if (hero) hero.innerHTML = "";
    return;
  }
  strip.classList.remove("hidden");
  const selected =
    state.shoot.selected != null && frames.some((f) => f.index === state.shoot.selected)
      ? state.shoot.selected
      : ([...frames].reverse().find((f) => f.image_url) || frames[frames.length - 1]).index;
  state.shoot.selected = selected;
  strip.innerHTML = "";
  for (const frame of frames) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className =
      "filmstrip-frame" +
      (frame.index === selected ? " active" : "") +
      (frame.status === "running" ? " running" : "") +
      (frame.image_url ? "" : " queued") +
      (frame.takes?.length > 1 && !frame.picked ? " pick" : "");
    btn.dataset.frame = String(frame.index);
    if (frame.image_url) {
      const img = document.createElement("img");
      img.src = frame.image_url;
      img.alt = frame.label || "";
      btn.appendChild(img);
    } else {
      const ph = document.createElement("div");
      ph.className = "filmstrip-ph";
      btn.appendChild(ph);
    }
    const lbl = document.createElement("span");
    lbl.className = "lbl";
    const takeBit =
      frame.picked
        ? ` · ${frame.picked}`
        : frame.takes?.length > 1
          ? " · A|B"
          : "";
    lbl.textContent =
      frame.status === "running"
        ? `${frame.label}${takeBit}…`
        : frame.status === "queued"
          ? frame.label || "…"
          : `${frame.label || `Step ${frame.index + 1}`}${takeBit}`;
    btn.appendChild(lbl);
    strip.appendChild(btn);
  }

  const cur = frames.find((f) => f.index === selected);
  if (!hero) return;
  if (!cur?.image_url && !(cur?.takes || []).some((t) => t.image_url)) {
    hero.classList.add("hidden");
    hero.innerHTML = "";
    return;
  }
  hero.classList.remove("hidden");
  const canRetry = Boolean(state.shoot.recipe) || Boolean(state.lastGenerate);
  const takesReady =
    (cur.takes || []).length > 1 && (cur.takes || []).every((t) => t.image_url);
  const needPick = takesReady && !cur.picked;
  const takesHtml = (cur.takes || [])
    .map((t) => {
      if (!t.image_url) {
        return `<div class="take-choice queued"><div class="filmstrip-ph"></div><span class="lbl">Take ${escapeHtml(t.id || "")}…</span></div>`;
      }
      const on = cur.picked ? cur.picked === t.id : false;
      return `<button type="button" class="take-choice${on ? " active" : ""}" data-pick-take="${escapeHtml(t.id)}">
        <img src="${escapeHtml(t.image_url)}" alt="Take ${escapeHtml(t.id)}" />
        <span class="lbl">${needPick ? `Pick ${escapeHtml(t.id)}` : `Take ${escapeHtml(t.id)}`}</span>
      </button>`;
    })
    .join("");
  const mainImg = needPick || (cur.takes || []).length > 1
    ? `<div class="take-pair">${takesHtml}</div>
       ${needPick ? `<p class="muted">Pick the keeper. Then continue from it.</p>` : ""}`
    : `<img src="${escapeHtml(cur.image_url)}" alt="${escapeHtml(cur.label || "")}" />`;
  hero.innerHTML = `
    ${mainImg}
    <div class="actions">
      ${
        cur.image_file && !needPick
          ? `<button type="button" class="ghost sm" data-continue="${escapeHtml(cur.image_file)}">Use as subject</button>`
          : ""
      }
      ${
        canRetry
          ? `<button type="button" class="ghost sm" data-retry-step="${cur.index}">Retry this step</button>
             <button type="button" class="ghost sm" data-two-takes="${cur.index}">Two takes</button>`
          : ""
      }
      ${
        cur.image_url
          ? `<a class="file-btn" href="${escapeHtml(cur.image_url)}" download>Download</a>`
          : ""
      }
    </div>`;
}

async function selectShootFrame(index) {
  if (!state.shoot?.frames) return;
  const frame = state.shoot.frames.find((f) => f.index === index);
  if (!frame) return;
  state.shoot.selected = index;
  renderFilmstrip();
  if (!frame.image_file) return;
  if (frame.takes?.length > 1 && !frame.picked) return;
  if (state.shoot.subjectIndex === index) return;
  state.shoot.subjectIndex = index;
  await continueFromOutput(frame.image_file);
}

async function pickTake(frameIndex, takeId) {
  const frame = state.shoot?.frames.find((f) => f.index === frameIndex);
  const take = frame?.takes?.find((t) => t.id === takeId);
  if (!frame || !take?.image_file) return;
  if (frame.takes?.length > 1 && frame.takes.some((t) => !t.image_file) && !frame.picked) {
    return;
  }
  frame.image_file = take.image_file;
  frame.image_url = take.image_url;
  frame.seed = take.seed;
  frame.picked = takeId;
  frame.pick_required = false;
  state.shoot.selected = frameIndex;
  state.shoot.subjectIndex = null;
  renderFilmstrip();
  await continueFromOutput(take.image_file);
  state.shoot.subjectIndex = frameIndex;
}

async function retryShootStep(index, { takes = 1 } = {}) {
  const shoot = state.shoot;
  if (!shoot) {
    await retryLast();
    return;
  }
  if (!shoot.recipe) {
    await retryLast();
    return;
  }
  const { _recipe, retry_step, keep_steps, ...base } = shoot.recipe;
  let identity;
  if (index <= 0) {
    identity = shoot.identity?.filename;
    if (!identity) {
      alert("Original photo is gone — drop it again.");
      return;
    }
  } else {
    const prev = shoot.frames.find((f) => f.index === index - 1);
    if (!prev?.image_file) {
      alert("Previous frame isn’t ready.");
      return;
    }
    const data = await continueFromOutput(prev.image_file);
    identity = data.filename;
    shoot.subjectIndex = index - 1;
  }
  const keep = shoot.frames
    .filter((f) => f.index < index && f.image_file)
    .map((f) => ({
      label: f.label,
      image_file: f.image_file,
      image_url: f.image_url,
      index: f.index,
    }));
  const body = {
    ...base,
    identity,
    retry_step: index,
    keep_steps: keep,
    seed: null,
    takes: takes > 1 ? 2 : 1,
    _recipe: true,
  };
  state.lastGenerate = body;
  shoot.selected = index;
  shoot.subjectIndex = null;
  setBusy(true);
  appendMsg(
    `<div class="muted">${takes > 1 ? "Two takes" : "Retry"} ${escapeHtml(shoot.frames.find((f) => f.index === index)?.label || "step")}</div>`,
    "user"
  );
  try {
    const { _recipe: _r, ...payload } = body;
    const job = await api("/api/recipe", { method: "POST", body: JSON.stringify(payload) });
    showJobStatus(job);
    applyShootFromJob(job);
    pollJob(job.id);
  } catch (e) {
    showJobStatus({ status: "error", message: "Failed", error: String(e.message || e) });
    appendMsg(`<div class="system">Error: ${escapeHtml(e.message || e)}</div>`, "system");
    setBusy(false);
  }
}

function undoSession() {
  const prev = state.undoStack.pop();
  if (prev) setRefImage(prev);
  else clearRefImage();
}

async function retryLast() {
  if (state.shoot?.recipe && state.shoot.selected != null) {
    await retryShootStep(state.shoot.selected);
    return;
  }
  if (!state.lastGenerate) {
    alert("Nothing to retry yet.");
    return;
  }
  setBusy(true);
  appendMsg(`<div class="muted">Retry last step</div>`, "user");
  const path = state.lastGenerate._recipe ? "/api/recipe" : "/api/generate";
  try {
    const { _recipe, ...payload } = state.lastGenerate;
    const job = await api(path, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showJobStatus(job);
    pollJob(job.id);
  } catch (e) {
    showJobStatus({ status: "error", message: "Failed", error: String(e.message || e) });
    appendMsg(`<div class="system">Error: ${escapeHtml(e.message || e)}</div>`, "system");
    setBusy(false);
  }
}

function applyModeChrome() {
  const edit = state.mode === "edit";
  const kind = state.editKind;
  const run = $("#btn-generate");
  if (run) {
    run.textContent =
      kind === "undress"
        ? "Undress"
        : kind === "pose" && state.studioSimple
          ? "Make scene"
          : kind === "pose"
            ? "Apply pose"
            : "Generate";
  }
  const wrap = $("#ref-wrap");
  if (wrap) {
    wrap.classList.toggle("required", edit);
    const label = wrap.childNodes[0];
    if (label && label.nodeType === Node.TEXT_NODE) {
      label.textContent = edit ? "Source image " : "Optional reference ";
    }
  }
  const sys = $("#system-line");
  if (sys) {
    sys.textContent =
      (kind === "pose" && state.systemPrompts.lora) ||
      state.systemPrompts[kind || state.mode] ||
      "";
  }
  const title = $("#builder-title");
  if (title) {
    title.textContent =
      kind === "undress"
        ? "Undress"
        : kind === "pose" && state.studioSimple
          ? "Studio"
          : kind === "pose"
            ? "Pose"
            : edit
              ? "Edit"
              : "Scene";
  }
  const notes = $("#notes-quick");
  if (notes) {
    notes.placeholder =
      kind === "undress"
        ? "Optional notes (outfit details, jewelry to keep)…"
        : kind === "pose"
          ? "Optional notes for the new pose…"
          : "Optional free-text notes / override lines…";
  }
  const sub = document.querySelector(".sub");
  if (sub) {
    sub.textContent =
      kind === "undress"
        ? "Undress → same person, same pose"
        : kind === "pose"
          ? "Your photo. Pick a pose and extras."
          : "Scene composer → mflux · private local gen";
  }
  const sl = $("#eng-strength");
  if (sl && state.mode === "gen") sl.value = "0.55";
  setPoseChrome();
  $("#aspect-row")?.classList.toggle("hidden", edit);
  $("#btn-edit-kinds")?.classList.toggle("hidden", !edit || !kind);
  $("#btn-reset-scene")?.classList.toggle("hidden", edit && !kind);
  const poseSimple = kind === "pose" && state.studioSimple;
  $("#btn-studio-advanced")?.classList.toggle("hidden", kind !== "pose");
  const adv = $("#btn-studio-advanced");
  if (adv) adv.textContent = state.studioSimple ? "Advanced" : "Simple";
  $("#btn-toggle-prompt")?.classList.toggle("hidden", !poseSimple);
  $("#scene-studio")?.classList.toggle("hidden", !poseSimple);
  $("#builder-root")?.classList.toggle("hidden", poseSimple || (edit && !kind));
  const layout = $("#studio");
  layout?.classList.toggle("simple-studio", poseSimple);
  layout?.classList.toggle("show-prompt", poseSimple && state.showPrompt);
  if (poseSimple) renderSceneStudio();
}

function showHome() {
  $("#home")?.classList.remove("hidden");
  $("#studio")?.classList.add("hidden");
  $("#studio")?.classList.remove("simple-studio", "show-prompt");
  $("#btn-home")?.classList.add("hidden");
  state.editKind = null;
  $("#edit-picker")?.classList.add("hidden");
  $("#scene-studio")?.classList.add("hidden");
  $("#builder-root")?.classList.remove("hidden");
}

function showEditPicker() {
  state.editKind = null;
  $("#edit-picker")?.classList.remove("hidden");
  $("#builder-root")?.classList.add("hidden");
  $("#btn-edit-kinds")?.classList.add("hidden");
  $("#btn-reset-scene")?.classList.add("hidden");
  const title = $("#builder-title");
  if (title) title.textContent = "Edit";
  setPoseChrome();
}

async function enterEditKind(kind) {
  const next = kind === "undress" ? "undress" : "pose";
  state.editKind = next;
  state.mode = "edit";
  const [schema, defaults] = await Promise.all([
    api(`/api/schema?mode=${next}`),
    api(`/api/defaults?mode=${next}`),
  ]);
  if (!schema || !schema.groups) {
    throw new Error("Schema did not load. Rebuild the frontend image.");
  }
  state.schema = schema;
  state.scene = defaults.scene || {};
  state.engine = defaults.engine || {};
  state.systemPrompts = { ...state.systemPrompts, ...(defaults.system_prompts || {}) };
  state.manualScales = {};
  state.winner = null;
  state.studioSimple = next === "pose";
  state.showPrompt = false;
  if (next === "pose") {
    state.scenes = await api("/api/scenes").catch(() => ({ extras: [], scenes: [] }));
  }
  if (next !== "pose") {
    state.poseImage = null;
    const poseInput = $("#pose-image");
    if (poseInput) poseInput.value = "";
  }
  setEngineForm();
  $("#edit-picker")?.classList.add("hidden");
  $("#builder-root")?.classList.remove("hidden");
  applyModeChrome();
  renderBuilder();
  renderSceneStudio();
  await runCompose();
}

async function enterStudio(mode) {
  const next = mode === "edit" ? "edit" : "gen";
  const card = document.querySelector(`[data-enter="${next}"]`);
  card?.classList.add("busy");
  try {
    state.mode = next;
    state.editKind = null;
    state.catalog = await api("/api/loras").catch(() => []);
    state.manualScales = {};
    state.winner = null;
    state.blocked = {};
    state.dropped = [];
    state.poseImage = null;
    const poseInput = $("#pose-image");
    if (poseInput) poseInput.value = "";
    if (next === "edit") {
      state.schema = { groups: [] };
      state.scene = {};
      const defaults = await api("/api/defaults?mode=pose").catch(() => ({}));
      state.engine = defaults.engine || {};
      state.systemPrompts = { ...state.systemPrompts, ...(defaults.system_prompts || {}) };
      setEngineForm();
      applyModeChrome();
      showEditPicker();
      $("#builder-root").innerHTML = "";
    } else {
      const [schema, defaults] = await Promise.all([
        api(`/api/schema?mode=${state.mode}`),
        api(`/api/defaults?mode=${state.mode}`),
      ]);
      if (!schema || !schema.groups) {
        throw new Error("Schema did not load. Rebuild the frontend image.");
      }
      state.schema = schema;
      state.scene = defaults.scene || {};
      state.engine = defaults.engine || {};
      state.systemPrompts = { ...state.systemPrompts, ...(defaults.system_prompts || {}) };
      $("#edit-picker")?.classList.add("hidden");
      $("#builder-root")?.classList.remove("hidden");
      setEngineForm();
      applyModeChrome();
      renderBuilder();
    }
    $("#home")?.classList.add("hidden");
    $("#studio")?.classList.remove("hidden");
    $("#btn-home")?.classList.remove("hidden");
    const notes = $("#notes-quick");
    if (notes) notes.value = "";
    if (next !== "edit") await runCompose();
  } catch (e) {
    console.error(e);
    alert(`Could not open ${next}: ${e.message || e}`);
  } finally {
    card?.classList.remove("busy");
  }
}

function setBusy(busy) {
  const run = $("#btn-generate");
  if (run) run.disabled = busy;
  if (busy) {
    startElapsed();
    showJobStatus({ status: "queued", message: "Queued", progress: 0 });
  } else {
    stopElapsed();
  }
}

async function generateRecipe() {
  if (!state.refImage) {
    alert("Need a source photo.");
    return;
  }
  const plan = studioPlan();
  const body = {
    identity: state.refImage.filename,
    undress: !!state.undressFirst,
    scene: state.scene || {},
    width: Number($("#eng-width").value) || 1024,
    height: Number($("#eng-height").value) || 576,
    steps: Number($("#eng-steps").value) || 4,
    guidance: Number($("#eng-guidance")?.value || 2.0),
    quantize: Number($("#eng-quant").value) || 4,
    seed: $("#eng-seed").value === "" ? null : Number($("#eng-seed").value),
    max_loras: Number($("#eng-max-loras").value) || 2,
    manual_loras: Object.entries(state.manualScales).map(([id, scale]) => ({ id, scale })),
    notes: $("#notes-quick")?.value || null,
    takes: state.twoTakes ? 2 : 1,
    _recipe: true,
  };
  state.lastGenerate = body;
  state.shoot = {
    identity: { filename: state.refImage.filename, url: state.refImage.url },
    recipe: { ...body },
    frames: plan.map((label, i) => ({
      index: i,
      label,
      status: "queued",
      image_file: null,
      image_url: null,
    })),
    selected: 0,
    subjectIndex: null,
  };
  renderFilmstrip();
  setBusy(true);
  appendMsg(
    `<div class="prompt">${escapeHtml(plan.join(" → "))}</div>
     <div class="muted">recipe · ${plan.length} step${plan.length === 1 ? "" : "s"}${
       state.twoTakes ? " · 2 takes on last step" : ""
     }</div>`,
    "user"
  );
  try {
    const { _recipe, ...payload } = body;
    const job = await api("/api/recipe", { method: "POST", body: JSON.stringify(payload) });
    showJobStatus(job);
    applyShootFromJob(job);
    pollJob(job.id);
  } catch (e) {
    showJobStatus({ status: "error", message: "Failed", error: String(e.message || e) });
    appendMsg(`<div class="system">Error: ${escapeHtml(e.message || e)}</div>`, "system");
    setBusy(false);
  }
}

async function generate() {
  if (state.mode === "edit" && !state.editKind) {
    alert("Pick Undress or Pose edit on the left first.");
    return;
  }
  if (state.mode === "edit" && !state.refImage) {
    alert("Edit image needs a source photo. Choose an image first.");
    return;
  }
  if (state.editKind === "pose" && state.studioSimple) {
    await generateRecipe();
    return;
  }

  await runCompose();
  const prompt = $("#prompt-out").value.trim();
  if (!prompt) {
    alert("Prompt is empty");
    return;
  }

  setBusy(true);

  const manual = state.matched.map((m) => ({
    id: m.id,
    scale: state.manualScales[m.id] ?? m.scale,
  }));

  const seedVal = $("#eng-seed").value;
  const body = {
    scene: state.scene,
    prompt,
    include_triggers: $("#include-triggers").checked,
    max_loras: Number.isFinite(Number($("#eng-max-loras").value))
      ? Number($("#eng-max-loras").value)
      : 2,
    manual_loras: manual,
    width: Number($("#eng-width").value),
    height: Number($("#eng-height").value),
    steps: Number($("#eng-steps").value),
    guidance: Number(
      $("#eng-guidance")?.value || (state.editKind === "undress" ? 1.0 : state.mode === "edit" ? 2.0 : 1.4)
    ),
    quantize: Number($("#eng-quant").value),
    seed: seedVal === "" ? null : Number(seedVal),
    mode: catalogMode(),
    winner: state.winner,
    image_paths: state.refImage ? [state.refImage.filename] : [],
    pose_path: null,
    image_strength:
      state.mode === "gen" && state.refImage
        ? Number($("#eng-strength")?.value || 0.55)
        : null,
  };

  state.lastGenerate = body;

  const poseBit = state.poseImage ? ` · pose ${state.poseImage.filename}` : "";
  appendMsg(
    `<div class="prompt">${escapeHtml(prompt)}</div>
     <div class="muted">${state.editKind || (state.mode === "edit" ? "edit" : "generate")}${poseBit} · ${
       state.matched
         .filter((m) => m.available)
         .map((m) => escapeHtml(m.name))
         .join(" · ") || "no LoRAs"
     }</div>`,
    "user"
  );

  try {
    const job = await api("/api/generate", { method: "POST", body: JSON.stringify(body) });
    showJobStatus(job);
    pollJob(job.id);
  } catch (e) {
    showJobStatus({ status: "error", message: "Failed", error: String(e.message || e) });
    appendMsg(`<div class="system">Error: ${escapeHtml(e.message || e)}</div>`, "system");
    setBusy(false);
  }
}

function pollJob(id) {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const job = await api(`/api/jobs/${id}`);
      showJobStatus(job);
      if (job.result) applyShootFromJob(job);
      if (job.status === "done") {
        clearInterval(state.pollTimer);
        setBusy(false);
        showJobStatus(job);
        const url = job.result?.image_url;
        const file = job.result?.image_file || "";
        state.lastResult = { image_file: file, image_url: url };
        const n = (job.result?.steps || state.shoot?.frames || []).filter((s) => s.image_url).length;
        const loras = (job.result?.loras || []).map((l) => l.name).join(", ");
        const elapsed = state.jobStartedAt
          ? formatElapsed(Date.now() - state.jobStartedAt)
          : "";
        appendMsg(
          `<div class="muted">Take ready${n ? ` · ${n} frame${n === 1 ? "" : "s"}` : ""}${
            elapsed ? ` · ${elapsed}` : ""
          }</div>
           ${loras ? `<div class="muted">${escapeHtml(loras)}</div>` : ""}`,
          "assistant"
        );
        const lastDone = [...(state.shoot?.frames || [])].reverse().find((f) => f.image_file);
        if (lastDone) {
          state.shoot.selected = lastDone.index;
          renderFilmstrip();
          const waitPick = lastDone.takes?.length > 1 && !lastDone.picked;
          if (!waitPick) selectShootFrame(lastDone.index).catch(() => {});
        }
      } else if (job.status === "error") {
        clearInterval(state.pollTimer);
        setBusy(false);
        showJobStatus(job);
        appendMsg(`<div class="system">Generation failed: ${escapeHtml(job.error || "unknown")}</div>`, "system");
      }
    } catch (e) {
      clearInterval(state.pollTimer);
      setBusy(false);
      showJobStatus({ status: "error", message: "Poll failed", error: String(e.message || e) });
    }
  }, 400);
}

async function refreshEngineBadge() {
  try {
    const h = await api("/api/health");
    const badge = $("#engine-badge");
    const eng = h.engine || {};
    if (eng.mode === "remote") {
      if (eng.reachable && eng.mflux_available) {
        badge.textContent = eng.loaded_mode
          ? `remote · ${eng.loaded_mode}`
          : "remote backend ready";
        badge.className = "badge ok";
      } else if (eng.reachable) {
        badge.textContent = "backend up · mflux missing";
        badge.className = "badge warn";
      } else {
        badge.textContent = "backend offline";
        badge.className = "badge warn";
      }
    } else if (eng.mflux_available) {
      badge.textContent = eng.loaded_mode
        ? `local · ${eng.loaded_mode}`
        : "local mflux ready";
      badge.className = "badge ok";
    } else {
      badge.textContent = "mflux missing (UI only)";
      badge.className = "badge warn";
    }
  } catch {
    $("#engine-badge").textContent = "server offline";
    $("#engine-badge").className = "badge warn";
  }
}

async function init() {
  const defaults = await api("/api/defaults?mode=gen").catch(() => ({}));
  state.systemPrompts = defaults.system_prompts || state.systemPrompts;
  state.engine = defaults.engine || {};
  showHome();
  ensureEmptyHint();
  await refreshEngineBadge();
  setInterval(refreshEngineBadge, 15000);

  $("#home-cards")?.addEventListener("click", (e) => {
    const card = e.target.closest("[data-enter]");
    if (card) enterStudio(card.dataset.enter);
  });
  $("#btn-home")?.addEventListener("click", showHome);
  $("#aspect-row")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".aspect-btn");
    if (!btn) return;
    $("#eng-width").value = btn.dataset.w;
    $("#eng-height").value = btn.dataset.h;
    document.querySelectorAll(".aspect-btn").forEach((b) => b.classList.toggle("active", b === btn));
  });
  $("#btn-generate")?.addEventListener("click", generate);
  $("#btn-clear-ref").addEventListener("click", () => {
    state.undoStack = [];
    clearRefImage();
  });
  $("#btn-undo-session")?.addEventListener("click", undoSession);
  $("#chat-thread")?.addEventListener("click", (e) => {
    const cont = e.target.closest("[data-continue]");
    if (cont) {
      continueFromOutput(cont.dataset.continue).catch((err) =>
        alert(err.message || "Could not use that result as the subject")
      );
      return;
    }
    if (e.target.closest("[data-retry]")) retryLast();
  });
  $("#filmstrip")?.addEventListener("click", (e) => {
    const frame = e.target.closest("[data-frame]");
    if (!frame) return;
    selectShootFrame(Number(frame.dataset.frame)).catch((err) =>
      alert(err.message || "Could not use that frame as the subject")
    );
  });
  $("#take-hero")?.addEventListener("click", (e) => {
    const pick = e.target.closest("[data-pick-take]");
    if (pick) {
      pickTake(state.shoot?.selected, pick.dataset.pickTake).catch((err) =>
        alert(err.message || "Could not use that take")
      );
      return;
    }
    const two = e.target.closest("[data-two-takes]");
    if (two) {
      retryShootStep(Number(two.dataset.twoTakes), { takes: 2 }).catch((err) =>
        alert(err.message || "Two takes failed")
      );
      return;
    }
    const retry = e.target.closest("[data-retry-step]");
    if (retry) {
      retryShootStep(Number(retry.dataset.retryStep)).catch((err) =>
        alert(err.message || "Retry failed")
      );
      return;
    }
    const cont = e.target.closest("[data-continue]");
    if (cont) {
      if (state.shoot) state.shoot.subjectIndex = null;
      continueFromOutput(cont.dataset.continue).catch((err) =>
        alert(err.message || "Could not use that result as the subject")
      );
    }
  });
  $("#btn-reset-scene").addEventListener("click", async () => {
    const defaults = await api(`/api/defaults?mode=${catalogMode()}`);
    state.scene = defaults.scene || {};
    state.manualScales = {};
    $("#notes-quick").value = "";
    renderBuilder();
    renderSceneStudio();
    await runCompose();
  });
  $("#btn-studio-advanced")?.addEventListener("click", () => {
    if (state.editKind !== "pose") return;
    state.studioSimple = !state.studioSimple;
    applyModeChrome();
    renderBuilder();
    renderSceneStudio();
  });
  $("#btn-toggle-prompt")?.addEventListener("click", () => {
    state.showPrompt = !state.showPrompt;
    applyModeChrome();
  });
  $("#btn-edit-kinds")?.addEventListener("click", () => {
    showEditPicker();
    applyModeChrome();
  });
  $("#edit-picker")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-edit-kind]");
    if (!btn) return;
    enterEditKind(btn.dataset.editKind).catch((err) => {
      console.error(err);
      alert(`Could not open ${btn.dataset.editKind}: ${err.message || err}`);
    });
  });
  $("#btn-clear-chat").addEventListener("click", () => {
    $("#chat-thread").innerHTML = "";
    clearShoot();
    ensureEmptyHint();
  });
  $("#include-triggers").addEventListener("change", scheduleCompose);
  $("#eng-max-loras").addEventListener("change", scheduleCompose);
  $("#lora-add")?.addEventListener("change", () => {
    const id = $("#lora-add").value;
    if (!id) return;
    if (state.manualScales[id] == null) {
      const entry = state.catalog.find((l) => l.id === id);
      state.manualScales[id] = Number(entry?.default_scale ?? 0.8);
    }
    $("#lora-add").value = "";
    scheduleCompose();
  });
  $("#notes-quick").addEventListener("input", () => {
    syncQuickNotes();
    scheduleCompose();
  });
  $("#eng-strength")?.addEventListener("input", () => {
    syncStrengthChrome();
  });
  $("#prompt-out").addEventListener("input", () => {
    state.prompt = $("#prompt-out").value;
  });
  $("#btn-unload").addEventListener("click", async () => {
    await api("/api/engine/unload", { method: "POST" });
    refreshEngineBadge();
  });

  async function uploadToStudio(file) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    if (!res.ok) throw new Error("Upload failed");
    return res.json();
  }

  $("#ref-image").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const data = await uploadToStudio(file);
      state.undoStack = [];
      setRefImage(data);
    } catch (err) {
      alert(err.message || "Upload failed");
    }
  });
  $("#pose-image")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const data = await uploadToStudio(file);
      state.poseImage = data;
      setPoseChrome();
      scheduleCompose();
    } catch (err) {
      alert(err.message || "Upload failed");
    }
  });
  $("#btn-clear-pose")?.addEventListener("click", () => {
    state.poseImage = null;
    const input = $("#pose-image");
    if (input) input.value = "";
    setPoseChrome();
    scheduleCompose();
  });
}

init().catch((e) => {
  console.error(e);
});
