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
};

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

function deepMergeScene(base, partial) {
  const out = structuredClone(base);
  for (const [k, v] of Object.entries(partial || {})) {
    if (v && typeof v === "object" && !Array.isArray(v) && typeof out[k] === "object") {
      out[k] = { ...out[k], ...v };
    } else {
      out[k] = v;
    }
  }
  return out;
}

function getSceneValue(groupId, fieldId) {
  return state.scene?.[groupId]?.[fieldId];
}

function catalogMode() {
  if (state.editKind === "undress" || state.editKind === "pose") return state.editKind;
  return state.mode;
}

function optionAllowed(opt) {
  if (!opt?.poses || !opt.poses.length) return true;
  return opt.poses.includes(getSceneValue("pose", "scene"));
}

function prunePoseFeatures() {
  const extras = getSceneValue("features", "extras");
  if (!Array.isArray(extras) || !extras.length) return;
  const allowed = new Set();
  for (const group of state.schema?.groups || []) {
    for (const field of group.fields || []) {
      if (group.id !== "features") continue;
      for (const opt of field.options || []) {
        if (optionAllowed(opt)) allowed.add(opt.id);
      }
    }
  }
  const next = extras.filter((id) => allowed.has(id));
  if (next.length !== extras.length) {
    if (!state.scene.features) state.scene.features = {};
    state.scene.features.extras = next;
  }
}

function setSceneValue(groupId, fieldId, value) {
  if (!state.scene[groupId]) state.scene[groupId] = {};
  state.scene[groupId][fieldId] = value;
  state.winner = `${groupId}.${fieldId}`;
  if (groupId === "pose" && fieldId === "scene") {
    prunePoseFeatures();
    renderBuilder();
  }
  if (
    groupId !== "preset" &&
    groupId !== "pose" &&
    ["position", "act", "camera", "partners"].includes(groupId) &&
    state.scene.preset?.scene &&
    state.scene.preset.scene !== "none"
  ) {
    state.scene.preset.scene = "none";
  }
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
    "pose",
    "features",
    "clothing",
    "preset",
    "subject",
    "keep",
    "body",
    "position",
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
      const label = document.createElement("div");
      label.className = "field-label";
      label.textContent = field.label;
      wrap.appendChild(label);

      if (field.type === "choice") {
        const chips = document.createElement("div");
        chips.className = "chips";
        for (const opt of field.options || []) {
          if (!optionAllowed(opt)) continue;
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
          if (!optionAllowed(opt)) continue;
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
  const poseOn = Boolean(state.poseImage && state.editKind === "pose");
  const genRef = state.mode === "gen" && state.refImage;
  wrap.classList.toggle("hidden", !(poseOn || genRef));
  const label = wrap.querySelector("span, label") || wrap.childNodes[0];
  if (label && label.nodeType === Node.TEXT_NODE) {
    label.textContent = poseOn ? "Restage " : "Ref strength ";
  }
}

function setPoseChrome() {
  const wrap = $("#pose-wrap");
  const poseMode = state.editKind === "pose";
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
  if (!thread.children.length) {
    thread.innerHTML = `<div class="empty-hint">Build a scene on the left. Prompt &amp; LoRAs update live on the right. Hit <strong>Generate</strong> when ready.</div>`;
  }
}

function showJobStatus(job) {
  const el = $("#job-status");
  el.classList.remove("hidden", "error", "running", "done");
  if (!job) {
    el.classList.add("hidden");
    return;
  }
  el.classList.add(job.status === "error" ? "error" : job.status === "done" ? "done" : "running");
  const pct = Math.max(0, Math.min(100, Math.round((Number(job.progress) || 0) * 100)));
  const stepBit =
    job.step != null && job.steps != null ? ` · ${job.step}/${job.steps}` : "";
  const live = job.status === "running" || job.status === "queued";
  el.innerHTML = `
    <div><strong>${escapeHtml(job.status)}</strong> — ${escapeHtml(job.message || "")}${live ? ` (${pct}%${stepBit})` : ""}</div>
    ${job.error ? `<div>${escapeHtml(job.error)}</div>` : ""}
    ${live ? `<div class="progress det"><i style="width:${pct}%"></i></div>` : ""}
  `;
}

function applyModeChrome() {
  const edit = state.mode === "edit";
  const kind = state.editKind;
  const run = $("#btn-generate");
  if (run) {
    run.textContent = kind === "undress" ? "Undress" : kind === "pose" ? "Apply pose" : "Generate";
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
  if (sys) sys.textContent = state.systemPrompts[kind || state.mode] || "";
  const title = $("#builder-title");
  if (title) {
    title.textContent = kind === "undress" ? "Undress" : kind === "pose" ? "Pose" : edit ? "Edit" : "Scene";
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
          ? "Pose edit → restage, keep identity"
          : "Scene composer → mflux · private local gen";
  }
  const sl = $("#eng-strength");
  if (sl && !state.poseImage) sl.value = kind === "pose" ? "0.75" : "0.55";
  setPoseChrome();
  $("#aspect-row")?.classList.toggle("hidden", edit);
  $("#btn-edit-kinds")?.classList.toggle("hidden", !edit || !kind);
  $("#btn-reset-scene")?.classList.toggle("hidden", edit && !kind);
}

function showHome() {
  $("#home")?.classList.remove("hidden");
  $("#studio")?.classList.add("hidden");
  $("#btn-home")?.classList.add("hidden");
  state.editKind = null;
  $("#edit-picker")?.classList.add("hidden");
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
  $("#mode-gen") && ($("#mode-gen").disabled = busy);
  $("#mode-edit") && ($("#mode-edit").disabled = busy);
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
    pose_path: state.editKind === "pose" && state.poseImage ? state.poseImage.filename : null,
    image_strength:
      state.editKind === "pose" && state.poseImage
        ? Number($("#eng-strength")?.value || 0.75)
        : state.mode === "gen" && state.refImage
            ? Number($("#eng-strength")?.value || 0.55)
            : null,
  };

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
      if (job.status === "done") {
        clearInterval(state.pollTimer);
        setBusy(false);
        const url = job.result?.image_url;
        const loras = (job.result?.loras || []).map((l) => l.name).join(", ");
        appendMsg(
          `${url ? `<img src="${url}" alt="result" />` : ""}
           <div class="actions">
             <a class="file-btn" href="${url}" download>Download</a>
             <button type="button" class="ghost sm remix">Remix scene</button>
           </div>
           <div class="muted" style="margin-top:6px">${escapeHtml(loras)}</div>`,
          "assistant"
        );
      } else if (job.status === "error") {
        clearInterval(state.pollTimer);
        setBusy(false);
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
  $("#enter-gen")?.addEventListener("click", () => enterStudio("gen"));
  $("#enter-edit")?.addEventListener("click", () => enterStudio("edit"));
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
    state.refImage = null;
    $("#ref-label").textContent = "";
    $("#btn-clear-ref").classList.add("hidden");
    const input = $("#ref-image");
    if (input) input.value = "";
    syncStrengthChrome();
  });
  $("#btn-reset-scene").addEventListener("click", async () => {
    const defaults = await api(`/api/defaults?mode=${catalogMode()}`);
    state.scene = defaults.scene || {};
    state.manualScales = {};
    $("#notes-quick").value = "";
    renderBuilder();
    await runCompose();
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
      state.refImage = data;
      $("#ref-label").textContent = data.filename;
      $("#btn-clear-ref").classList.remove("hidden");
      syncStrengthChrome();
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
      const sl = $("#eng-strength");
      if (sl) sl.value = "0.75";
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

document.getElementById("home-cards")?.addEventListener("click", (e) => {
  const card = e.target.closest("[data-enter]");
  if (card) enterStudio(card.dataset.enter);
});

init().catch((e) => {
  console.error(e);
});
