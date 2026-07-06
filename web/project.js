(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const slug = new URLSearchParams(location.search).get("slug");
  const autostart = new URLSearchParams(location.search).get("autostart") === "1";
  let manifest = null;
  let pollTimer = null;
  let pipelineRunning = false;
  let lastActivityKey = "";
  let autostartTriggered = false;
  let pendingGate = null;

  const PHASE_ORDER = ["index", "stage0", "S0", "S1", "S2", "S3", "S4/S5", "fidelity", "done"];

  const PHASE_LABELS = {
    idle: "等待启动",
    index: "章节索引",
    stage0: "上游准备",
    S0: "S0 故事引擎",
    S1: "S1 系列定位",
    S2: "S2 季图谱",
    S3: "S3 分集清单",
    "S4/S5": "S4/S5 剧本精编",
    fidelity: "忠实度审计",
    done: "全部完成",
  };

  const STAGE_STATUS_LABEL = {
    complete: "已完成",
    partial: "部分",
    pending: "待生成",
  };

  if (!slug) {
    window.location.href = "/";
    throw new Error("missing slug");
  }

  async function init() {
    $("#header-slug").textContent = slug;
    $("#footer-project").textContent = slug;

    try {
      manifest = await fetch(`/api/projects/${encodeURIComponent(slug)}/manifest`).then((r) => {
        if (!r.ok) throw new Error("项目不存在");
        return r.json();
      });
    } catch (e) {
      $("main").innerHTML =
        '<section class="fatal-error"><h2>项目未找到</h2>' +
        `<p>${slug}</p><a href="/">返回工作台</a></section>`;
      return;
    }

    renderAll();
    initFrostCanvas();
    bindToolbar();
    bindApproval();
    await refreshStatus(true);
    schedulePoll();

    if (autostart && !autostartTriggered && !pipelineRunning) {
      autostartTriggered = true;
      const clean = new URL(location.href);
      clean.searchParams.delete("autostart");
      history.replaceState(null, "", clean.pathname + clean.search);
      await runPipeline();
    }

    const firstDoc = manifest.stages.flatMap((s) => s.docs.map((d) => ({ ...d, stageId: s.id }))).find((d) => d.file);
    if (firstDoc) loadDocument(firstDoc.file, firstDoc.title, firstDoc.stageId);
  }

  function schedulePoll() {
    clearInterval(pollTimer);
    pollTimer = setInterval(() => refreshStatus(false), pipelineRunning ? 3000 : 8000);
  }

  function renderAll(activeStage) {
    renderHero();
    renderTriangle();
    renderPipeline(activeStage);
    renderEngines();
    renderSeasons();
    renderDocSidebar();
  }

  function phaseIndex(phase) {
    if (phase === "idle") return -1;
    const mapped = phase === "stage0" ? "stage0" : phase;
    return PHASE_ORDER.indexOf(mapped);
  }

  function manifestStageCounts() {
    if (!manifest?.stages) return { done: 0, total: 6 };
    const done = manifest.stages.filter((s) => s.status === "complete").length;
    return { done, total: manifest.stages.length };
  }

  function effectivePhase(status) {
    if (status?.pendingGate?.stageId) return status.pendingGate.stageId;
    if (status.running) return status.phase || "idle";
    if (status.phase && status.phase !== "idle") return status.phase;
    const { done } = manifestStageCounts();
    if (done === 0) return manifest?.project?.chapters ? "index" : "idle";
    const complete = manifest.stages.filter((s) => s.status === "complete");
    const last = complete[complete.length - 1]?.id;
    const map = { S0: "S0", S1: "S1", S2: "S2", S3: "S3", S4: "S4/S5", S5: "S4/S5" };
    return map[last] || "stage0";
  }

  function effectiveProgress(status) {
    if (status.running || status.phase === "done") return status.progress ?? 0;
    if ((status.progress ?? 0) > 0) return status.progress;
    const counts = manifestStageCounts();
    if (counts.done > 0) {
      const phase = effectivePhase(status);
      const map = { index: 5, stage0: 10, S0: 20, S1: 35, S2: 50, S3: 65, "S4/S5": 80, fidelity: 95, done: 100 };
      return map[phase] ?? Math.round((counts.done / counts.total) * 100);
    }
    return status.progress ?? 0;
  }

  function renderApprovalGate(status) {
    const panel = $("#approval-gate");
    if (!panel) return;
    const gate = status.pendingGate;
    pendingGate = gate || null;

    if (!gate) {
      panel.hidden = true;
      return;
    }

    panel.hidden = false;
    panel.dataset.gate = gate.gate;
    panel.dataset.stage = gate.stageId || "";
    panel.classList.toggle("approval-gate--warn", gate.passed === false);
    panel.classList.toggle("approval-gate--resume", !!gate.resumeOnly);

    const resumeOnly = !!gate.resumeOnly;
    $("#approval-eyebrow").textContent = resumeOnly ? `续跑闸 · ${gate.stageId}` : `审批闸 · ${gate.stageId}`;
    $("#approval-title").textContent = resumeOnly ? `${gate.label} · 待续跑` : `${gate.label}待审`;
    $("#approval-message").textContent = gate.message || "请审阅产物后批准继续";

    const issuesEl = $("#approval-issues");
    if (gate.issues?.length) {
      issuesEl.hidden = false;
      issuesEl.innerHTML = gate.issues
        .map((issue) => `<li>${escapeHtml(issue)}</li>`)
        .join("");
    } else {
      issuesEl.hidden = true;
      issuesEl.innerHTML = "";
    }

    const rerunBtn = $("#btn-approval-rerun");
    rerunBtn.dataset.stage = gate.stageId;
    rerunBtn.textContent =
      gate.gate === "s1_pilot" ? "重新生成分集清单" : `重新生成 ${gate.stageId}`;

    const passBtn = $("#btn-approval-pass");
    passBtn.disabled = false;
    passBtn.textContent = resumeOnly ? "继续精编" : "审核通过，继续精编";
  }

  function renderProgressPanel(status) {
    const panel = $("#progress-panel");
    const running = status.running && !status.pendingGate;
    const phase = status.pendingGate?.stageId || effectivePhase(status);
    const pct = status.pendingGate ? (status.progress ?? 50) : effectiveProgress(status);
    const counts = manifestStageCounts();
    const done = status.stagesComplete ?? counts.done;
    const total = status.stagesTotal ?? counts.total;

    panel.classList.toggle("progress-panel--running", running);
    panel.classList.toggle("progress-panel--done", phase === "done");
    panel.classList.toggle("progress-panel--blocked", !running && !!status.pendingGate);

    $("#progress-phase").textContent = running
      ? "精编运行中 · " + (PHASE_LABELS[phase] || phase)
      : phase === "done"
        ? "精编已完成"
        : done > 0 && done < total
          ? "精编进度 · " + (PHASE_LABELS[phase] || phase)
          : "项目已就绪";

    let message = status.message || "等待启动精编管线";
    if (!running && !status.pendingGate && phase === "idle") {
      const ch = manifest?.project?.chapters;
      message = ch
        ? `章节索引已完成（${ch} 章）· 点击「开始精编」启动 S0→S5 全流程`
        : "项目已创建 · 点击「开始精编」启动 S0→S5 全流程";
    }
    $("#progress-message").textContent = message;

    $("#progress-pct").textContent = pct + "%";
    $("#progress-stages").textContent = `${done}/${total} 阶段产物就绪`;

    const fill = $("#progress-fill");
    const needle = $("#progress-needle");
    const reel = $("#progress-reel");
    fill.style.width = pct + "%";
    needle.style.left = pct + "%";
    reel.setAttribute("aria-valuenow", String(pct));

    const currentIdx = phaseIndex(phase);
    const resumeIdx = running ? currentIdx : currentIdx >= 0 ? currentIdx : -1;
    $$("#progress-steps .progress-step").forEach((el) => {
      const p = el.dataset.phase;
      const idx = phaseIndex(p);
      el.classList.remove("is-active", "is-done", "is-pending");
      if (idx < 0) return;
      if (phase === "done") {
        el.classList.add("is-done");
      } else if (!running && resumeIdx >= 0 && idx <= resumeIdx) {
        el.classList.add("is-done");
      } else if (running && idx < resumeIdx) {
        el.classList.add("is-done");
      } else if (running && idx === resumeIdx) {
        el.classList.add("is-active");
      } else {
        el.classList.add("is-pending");
      }
    });

    const episodePanel = $("#progress-episode");
    const epDone = status.episodesDone ?? 0;
    const epTotal = status.episodesTotal ?? 0;
    if (running && phase === "S4/S5" && epTotal > 0) {
      episodePanel.hidden = false;
      $("#progress-episode-count").textContent = `${epDone} / ${epTotal} 集`;
      $("#progress-episode-fill").style.width = Math.round((epDone / epTotal) * 100) + "%";
    } else {
      episodePanel.hidden = true;
    }

    const elapsedEl = $("#progress-elapsed");
    if (running && status.startedAt) {
      elapsedEl.hidden = false;
      elapsedEl.textContent = "已运行 " + formatElapsed(status.startedAt);
    } else {
      elapsedEl.hidden = true;
    }

    const activityEl = $("#progress-activity");
    const items = status.activity?.length ? status.activity : running ? [message] : [];
    if (!items.length) {
      activityEl.innerHTML =
        '<p class="progress-activity-empty">启动精编后，这里会实时显示当前步骤，无需查看终端。</p>';
      return;
    }

    const key = items.join("|") + "|" + pct + "|" + phase;
    if (key === lastActivityKey) return;
    lastActivityKey = key;

    const displayItems = running ? items : items.slice(-3);

    activityEl.innerHTML = displayItems
      .map(
        (text, i) =>
          `<div class="progress-activity-item${i === displayItems.length - 1 && running ? " progress-activity-item--current" : ""}">${escapeHtml(text)}</div>`
      )
      .join("");
    if (running) activityEl.scrollTop = activityEl.scrollHeight;
  }

  function formatElapsed(startedAt) {
    const start = new Date(startedAt.replace(" ", "T"));
    if (Number.isNaN(start.getTime())) return "";
    const sec = Math.max(0, Math.floor((Date.now() - start.getTime()) / 1000));
    if (sec < 60) return sec + " 秒";
    const min = Math.floor(sec / 60);
    if (min < 60) return min + " 分 " + (sec % 60) + " 秒";
    const hr = Math.floor(min / 60);
    return hr + " 时 " + (min % 60) + " 分";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderHero(stageCounts) {
    const p = manifest.project;
    $("#project-title").textContent = p.title;
    $("#project-subtitle").textContent = p.subtitle || p.id;
    $("#project-meta").textContent = `${p.mode} 标准精编 · 竖屏 ${p.aspectRatio}`;

    const counts = stageCounts || manifestStageCounts();
    const done = counts.done;
    const total = counts.total;
    const logline =
      done > 0
        ? done >= total
          ? `全部 ${total} 个阶段已完成。可在管线中单独重跑某一阶段，或查看产物文档。`
          : `已完成 ${done}/${total} 个阶段。可继续全阶段精编，或在管线中单独重跑某一阶段。`
        : "项目已创建。点击上方「开始精编」启动 S0–S5 全阶段精编流程。";
    $("#project-logline").textContent = logline;

    const stats = [
      ["章节", p.chapters || "—"],
      ["季数", p.seasons || "—"],
      ["单季集数", p.episodesPerSeason || 30],
      ["画幅", p.aspectRatio],
      ["模式", p.mode],
    ];
    $("#hero-stats").innerHTML = stats
      .map(([label, val]) => `<span class="stat-chip"><strong>${val}</strong> ${label}</span>`)
      .join("");
  }

  function renderTriangle() {
    const chars = manifest.characters || [];
    const section = $("#triangle-section");
    const container = $("#character-triangle");
    if (!chars.length) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    container.innerHTML = "";

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "triangle-lines");
    svg.setAttribute("viewBox", "0 0 300 300");
    svg.innerHTML = `
      <line x1="150" y1="50" x2="50" y2="250" />
      <line x1="150" y1="50" x2="250" y2="250" />
      <line x1="50" y1="250" x2="250" y2="250" />
    `;
    container.appendChild(svg);

    const classes = ["char-node--freya", "char-node--desmond", "char-node--troy"];
    chars.slice(0, 3).forEach((c, i) => {
      const el = document.createElement("div");
      el.className = `char-node ${classes[i] || ""}`;
      el.innerHTML = `<p class="char-name">${c.name}</p><p class="char-role">${c.role || ""}</p>`;
      if (c.quote) el.title = c.quote;
      container.appendChild(el);
    });
  }

  function renderPipeline(activeStage) {
    $("#pipeline-track").innerHTML = manifest.stages
      .map(
        (s) => `
      <div class="stage-node stage-node--${s.status}${activeStage === s.id ? " stage-node--active" : ""} stage-node--${s.id}" data-stage="${s.id}">
        <div class="stage-dot"></div>
        <span class="stage-id">${s.id}</span>
        <span class="stage-label">${s.label}</span>
        <button type="button" class="stage-rerun" data-stage="${s.id}" ${pipelineRunning ? "disabled" : ""} aria-label="重跑 ${s.id}" title="重跑 ${s.id}">
          <svg class="stage-rerun-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
            <polyline points="21 3 21 9 15 9"/>
          </svg>
        </button>
      </div>`
      )
      .join("");

    $$(".stage-rerun").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        runStage(btn.dataset.stage, btn);
      });
    });
  }

  function renderEngines() {
    const grid = $("#engines-grid");
    if (!manifest.engines?.length) {
      grid.innerHTML = '<p class="section-empty">S0 故事引擎生成后将展示四台发动机</p>';
      return;
    }
    grid.innerHTML = manifest.engines
      .map(
        (e) => `
      <div class="engine-card">
        <span class="engine-symbol">${e.symbol}</span>
        <div>
          <p class="engine-id">发动机 ${e.id}</p>
          <p class="engine-name">${e.name}</p>
        </div>
      </div>`
      )
      .join("");
  }

  function renderSeasons() {
    const scroll = $("#seasons-scroll");
    const empty = $("#seasons-empty");
    const seasons = manifest.seasons || [];

    if (!seasons.length) {
      scroll.innerHTML = "";
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    scroll.innerHTML = seasons
      .map(
        (s) => `
      <article class="season-card" tabindex="0" data-season="${s.id}">
        <p class="season-num">SEASON ${String(s.id).padStart(2, "0")}</p>
        <h3 class="season-title">${s.title}</h3>
        ${s.chapters ? `<p class="season-chapters">Chapters ${s.chapters}</p>` : ""}
        ${s.arc ? `<p class="season-arc">${s.arc}</p>` : ""}
        ${s.hook ? `<p class="season-hook">「${s.hook}」</p>` : ""}
      </article>`
      )
      .join("");

    $$(".season-card").forEach((card) => {
      card.addEventListener("click", () => {
        const doc = manifest.stages.find((st) => st.id === "S2")?.docs[0];
        if (doc) loadDocument(doc.file, doc.title, "S2");
      });
    });
  }

  function renderDocSidebar() {
    $("#docs-sidebar").innerHTML = manifest.stages
      .map((stage) => {
        const statusClass = stage.status === "complete" ? "doc-group-status--complete" : "";
        const links =
          stage.docs.length > 0
            ? stage.docs
                .map(
                  (d) =>
                    `<button type="button" class="doc-link" data-file="${d.file}" data-title="${d.title}" data-stage="${stage.id}">${d.title}</button>`
                )
                .join("")
            : `<button type="button" class="doc-link doc-link--disabled" disabled>待生成</button>`;
        return `
          <div class="doc-stage-group doc-stage-group--${stage.id}${stage.status === "pending" ? " doc-stage-group--pending" : ""}">
            <div class="doc-group-header">
              <div class="doc-group-title">
                <span class="doc-stage-id">${stage.id}</span>
                <span class="doc-stage-name">${stage.label}</span>
              </div>
              <span class="doc-group-status ${statusClass}">${STAGE_STATUS_LABEL[stage.status] || stage.status}</span>
            </div>
            <div class="doc-group-links">${links}</div>
          </div>`;
      })
      .join("");

    $$(".doc-link:not(.doc-link--disabled)").forEach((btn) => {
      btn.addEventListener("click", () => loadDocument(btn.dataset.file, btn.dataset.title, btn.dataset.stage));
    });
  }

  /** Fix LLM markdown quirks (e.g. "## ## Title") before parsing. */
  function normalizeMarkdown(md) {
    let out = md.replace(/\r\n/g, "\n");
    out = out.replace(/^(\|.*\|)\s*$/gm, (line) => line.replace(/<br\s*\/?>/gi, " · "));
    let prev;
    do {
      prev = out;
      out = out.replace(/^(#{1,6})\s+\1\s+/gm, "$1 ");
    } while (out !== prev);
    return out;
  }

  function parseMarkdown(md) {
    const normalized = normalizeMarkdown(md);
    if (typeof marked !== "undefined" && marked.parse) {
      let html = marked.parse(normalized, { gfm: true, breaks: true });
      html = html.replace(
        /(<h[1-6][^>]*>)([\s\S]*?)(<\/h[1-6]>)/gi,
        (_, open, text, close) => {
          const cleaned = text.replace(/^(\s*(?:<[^>]+>\s*)*)#{1,6}\s+/, "$1");
          return open + cleaned + close;
        }
      );
      return html;
    }
    return `<pre>${normalized.replace(/</g, "&lt;")}</pre>`;
  }

  async function loadDocument(file, title, stageId) {
    $("#doc-title").textContent = title;
    const badge = $("#doc-stage");
    badge.textContent = `${stageId} · ${manifest.stages.find((s) => s.id === stageId)?.label || stageId}`;
    badge.className = `doc-stage-badge doc-stage-badge--${stageId}`;

    const content = $("#doc-content");
    content.innerHTML = '<p class="docs-loading">加载中…</p>';

    $$(".doc-link").forEach((btn) => {
      btn.classList.toggle("doc-link--active", btn.dataset.file === file);
    });

    try {
      const url = `/api/projects/${encodeURIComponent(slug)}/doc?file=${encodeURIComponent(file)}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error("加载失败");
      content.innerHTML = parseMarkdown(await res.text());
      content.scrollTop = 0;
    } catch {
      content.innerHTML = '<p class="docs-error">无法加载文档</p>';
    }
  }

  async function reloadManifest(activeStage) {
    manifest = await fetch(`/api/projects/${encodeURIComponent(slug)}/manifest`).then((r) => r.json());
    renderAll(activeStage);
  }

  function setRunningState(running) {
    pipelineRunning = running;
    const btn = $("#btn-run");
    btn.disabled = running;
    btn.textContent = running ? "精编运行中…" : "开始精编（S0→S5）";
    $$(".stage-rerun").forEach((b) => {
      b.disabled = running;
    });
  }

  function stageCountsFromStatus(status) {
    if (status?.stages && manifest) {
      manifest.stages = status.stages;
    }
    const local = manifestStageCounts();
    return {
      done: status?.stagesComplete ?? local.done,
      total: status?.stagesTotal ?? local.total,
    };
  }

  async function refreshStatus(forceReload) {
    try {
      const status = await fetch(`/api/projects/${encodeURIComponent(slug)}/status`).then((r) => r.json());
      const dot = $("#status-dot");
      const text = $("#status-text");
      const wasRunning = pipelineRunning;
      const stageCounts = stageCountsFromStatus(status);

      renderProgressPanel(status);
      renderApprovalGate(status);
      renderHero(stageCounts);

      if (status.running) {
        dot.className = "status-dot status-dot--running";
        text.textContent = status.message || "精编管线运行中…";
        setRunningState(true);
        renderPipeline(status.currentStage);
        renderDocSidebar();
        if (forceReload || !wasRunning) await reloadManifest(status.currentStage);
      } else if (status.pendingGate) {
        dot.className = "status-dot status-dot--blocked";
        text.textContent = `待审 · ${status.pendingGate.label}`;
        setRunningState(false);
        renderPipeline(status.pendingGate.stageId);
        renderDocSidebar();
        if (forceReload || wasRunning) await reloadManifest(status.pendingGate.stageId);
      } else {
        dot.className = "status-dot status-dot--idle";
        const phase = effectivePhase(status);
        text.textContent =
          phase === "done" && stageCounts.done >= stageCounts.total
            ? `已完成 · ${stageCounts.done}/${stageCounts.total} 阶段`
            : `就绪 · ${stageCounts.done}/${stageCounts.total} 阶段完成`;
        setRunningState(false);
        renderPipeline(null);
        renderDocSidebar();
        if (forceReload || wasRunning) await reloadManifest(null);
      }

      if (wasRunning !== pipelineRunning) schedulePoll();
    } catch {
      $("#status-text").textContent = "状态未知";
    }
  }

  async function approveGate() {
    if (!pendingGate || pipelineRunning) return;
    const btn = $("#btn-approval-pass");
    btn.disabled = true;
    btn.textContent = "正在批准…";
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(slug)}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gate: pendingGate.gate, resume: true }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "批准失败");
      $("#approval-gate").hidden = true;
      pendingGate = null;
      setRunningState(true);
      await refreshStatus(true);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "审核通过，继续精编";
      $("#status-text").textContent = err.message || "批准失败";
    }
  }

  async function runPipeline() {
    const btn = $("#btn-run");
    btn.disabled = true;
    btn.textContent = "启动中…";
    try {
      await fetch(`/api/projects/${encodeURIComponent(slug)}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ through: "S5", skip_llm: false }),
      });
      setRunningState(true);
      await refreshStatus(true);
    } catch {
      setRunningState(false);
    }
  }

  async function runStage(stageId, triggerBtn) {
    if (pipelineRunning) return;
    if (triggerBtn) {
      triggerBtn.disabled = true;
      triggerBtn.classList.add("stage-rerun--loading");
    }
    try {
      await fetch(`/api/projects/${encodeURIComponent(slug)}/run/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: stageId, skip_llm: false }),
      });
      setRunningState(true);
      await refreshStatus(true);
    } catch {
      if (triggerBtn) triggerBtn.classList.remove("stage-rerun--loading");
    }
  }

  function bindApproval() {
    $("#btn-approval-pass").addEventListener("click", approveGate);
    $("#btn-approval-preview").addEventListener("click", () => {
      if (!pendingGate?.docFile) return;
      const stage = manifest?.stages?.find((s) => s.id === pendingGate.stageId);
      const doc = stage?.docs?.find((d) => d.file === pendingGate.docFile) || {
        file: pendingGate.docFile,
        title: pendingGate.label,
      };
      loadDocument(doc.file, doc.title, pendingGate.stageId);
      document.getElementById("documents")?.scrollIntoView({ behavior: "smooth" });
    });
    $("#btn-approval-rerun").addEventListener("click", () => {
      if (!pendingGate) return;
      runStage(pendingGate.stageId, $("#btn-approval-rerun"));
    });
  }

  function bindToolbar() {
    $("#btn-refresh").addEventListener("click", () => refreshStatus(true));
    $("#btn-run").addEventListener("click", runPipeline);
  }

  function initFrostCanvas() {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const canvas = $("#frost-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let w, h, particles;

    function resize() {
      w = canvas.width = window.innerWidth;
      h = canvas.height = window.innerHeight;
    }
    function spawn() {
      particles = Array.from({ length: 40 }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        r: Math.random() * 1.5 + 0.5,
        vy: Math.random() * 0.3 + 0.1,
        vx: (Math.random() - 0.5) * 0.2,
        alpha: Math.random() * 0.4 + 0.1,
      }));
    }
    function tick() {
      ctx.clearRect(0, 0, w, h);
      particles.forEach((p) => {
        p.y += p.vy;
        p.x += p.vx;
        if (p.y > h) {
          p.y = -4;
          p.x = Math.random() * w;
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(126, 200, 227, ${p.alpha})`;
        ctx.fill();
      });
      requestAnimationFrame(tick);
    }
    resize();
    spawn();
    tick();
    window.addEventListener("resize", () => {
      resize();
      spawn();
    });
  }

  window.addEventListener("beforeunload", () => clearInterval(pollTimer));
  init();
})();
