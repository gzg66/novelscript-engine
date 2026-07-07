(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const BUILD = "20260706k";

  const PHASE_SHORT = {
    index: "索引",
    stage0: "准备",
    S0: "S0",
    S1: "S1",
    S2: "S2",
    S3: "S3",
    "S4/S5": "S4/5",
    fidelity: "审计",
    done: "完成",
  };

  let pollTimer = null;

  async function deleteProject(slug, title, btn) {
    const label = title || slug;
    if (
      !confirm(
        `确定删除项目「${label}」？\n\n将永久删除 meta、原文、索引、运行记录等全部数据，且不可恢复。`
      )
    ) {
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = "删除中…";
    }
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(slug)}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "删除失败");
      await loadProjects();
    } catch (err) {
      alert(err.message || "删除失败");
      if (btn) {
        btn.disabled = false;
        btn.textContent = "删除";
      }
    }
  }

  async function cancelProject(slug, btn) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "停止中…";
    }
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(slug)}/cancel`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "停止失败");
      if (data.status === "stopped") {
        await loadProjects();
        return;
      }
      await loadProjects();
    } catch (err) {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "停止精编";
      }
      console.error(err);
    }
  }

  function bindProjectCards() {
    const grid = $("#projects-grid");
    if (!grid || grid.dataset.bound === "1") return;
    grid.dataset.bound = "1";

    grid.addEventListener("click", (e) => {
      const stopBtn = e.target.closest(".btn-stop");
      if (stopBtn) {
        e.preventDefault();
        e.stopPropagation();
        cancelProject(stopBtn.dataset.slug, stopBtn);
        return;
      }
      const deleteBtn = e.target.closest(".btn-delete");
      if (deleteBtn) {
        e.preventDefault();
        e.stopPropagation();
        deleteProject(deleteBtn.dataset.slug, deleteBtn.dataset.title, deleteBtn);
        return;
      }
      const card = e.target.closest(".project-card");
      if (!card?.dataset.href) return;
      window.location.href = card.dataset.href;
    });

    grid.addEventListener("keydown", (e) => {
      if (e.target.closest(".btn-stop") || e.target.closest(".btn-delete")) return;
      const card = e.target.closest(".project-card");
      if (!card?.dataset.href) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        window.location.href = card.dataset.href;
      }
    });
  }

  function renderRunningBanner(runningProjects) {
    const banner = $("#running-banner");
    if (!banner) return;

    if (!runningProjects.length) {
      banner.hidden = true;
      banner.innerHTML = "";
      return;
    }

    banner.hidden = false;
    banner.innerHTML = `
      <div class="running-banner-inner">
        <div class="running-banner-head">
          <span class="status-dot status-dot--running"></span>
          <strong>${runningProjects.length} 个项目正在精编</strong>
          <span class="running-banner-hint">LLM 调用中 · 可随时停止</span>
        </div>
        <ul class="running-banner-list">
          ${runningProjects
            .map((p) => {
              const pct = p.progress ?? 0;
              const phase = PHASE_SHORT[p.phase] || p.phase || "运行中";
              return `<li class="running-banner-item">
                <a class="running-banner-link" href="/project.html?slug=${encodeURIComponent(p.slug)}">
                  <span class="running-banner-title">${escapeHtml(p.title)}</span>
                  <span class="running-banner-meta">${escapeHtml(p.message || phase)}${pct > 0 ? ` · ${pct}%` : ""}</span>
                </a>
                <button type="button" class="btn btn-sm btn-stop" data-slug="${escapeHtml(p.slug)}">停止精编</button>
              </li>`;
            })
            .join("")}
        </ul>
      </div>`;
  }

  async function loadProjects() {
    const grid = $("#projects-grid");
    try {
      const projects = await fetch("/api/projects").then((r) => {
        if (!r.ok) throw new Error("API 不可用");
        return r.json();
      });

      if (!projects.length) {
        renderRunningBanner([]);
        grid.innerHTML =
          '<div class="projects-empty">' +
          "<p>还没有项目</p>" +
          '<a class="btn btn-primary" href="/create.html">上传第一本小说</a>' +
          "</div>";
        schedulePoll(false);
        return;
      }

      const runningProjects = projects.filter((p) => p.running);
      const runningCount = runningProjects.length;
      renderRunningBanner(runningProjects);

      const sorted = [...projects].sort((a, b) => Number(b.running) - Number(a.running));

      grid.innerHTML = sorted
        .map((p) => {
          const pct = p.running
            ? p.progress ?? 0
            : Math.round((p.stagesComplete / p.stagesTotal) * 100);
          const phaseLabel = PHASE_SHORT[p.phase] || p.phase || "运行中";
          const runningRow = p.running
            ? `<div class="project-card-running-row">
                <span class="project-card-running">
                  <span class="status-dot status-dot--running"></span>
                  <strong>精编中</strong> · ${escapeHtml(p.message || phaseLabel)}${pct > 0 ? ` · ${pct}%` : ""}
                </span>
                <button type="button" class="btn btn-sm btn-stop" data-slug="${escapeHtml(p.slug)}">停止精编</button>
              </div>`
            : "";
          return `
        <article class="project-card${p.running ? " project-card--running" : ""}" data-href="/project.html?slug=${encodeURIComponent(p.slug)}" tabindex="0" role="link" aria-label="打开项目 ${escapeHtml(p.title)}">
          ${p.running ? '<span class="project-card-live" aria-hidden="true">LIVE</span>' : ""}
          <p class="project-card-slug">${escapeHtml(p.slug)}</p>
          <h3 class="project-card-title">${escapeHtml(p.title)}</h3>
          <div class="project-card-meta">
            <span>${p.chapters || "—"} 章</span>
            <span>${p.mode}</span>
            <span>${p.stagesComplete}/${p.stagesTotal} 阶段</span>
          </div>
          ${runningRow}
          <div class="project-card-bar">
            <span style="width:${pct}%"></span>
          </div>
          <div class="project-card-actions">
            <button type="button" class="btn btn-sm btn-delete" data-slug="${escapeHtml(p.slug)}" data-title="${escapeHtml(p.title)}">删除</button>
          </div>
        </article>
      `;
        })
        .join("");

      const head = document.querySelector("#projects .section-head p");
      if (head) {
        head.textContent =
          runningCount > 0
            ? `${runningCount} 个项目正在调用 LLM · 可在上方横幅或卡片上直接停止`
            : "选择项目进入解析与产物阅读";
      }

      bindProjectCards();
      schedulePoll(runningCount > 0);
    } catch (e) {
      renderRunningBanner([]);
      grid.innerHTML =
        '<div class="projects-empty">' +
        "<p>无法连接后端服务</p>" +
        "<p class='drop-hint'>请运行 <code>web\\serve.ps1</code> 后刷新</p>" +
        "</div>";
      schedulePoll(false);
    }
  }

  function schedulePoll(anyRunning) {
    clearInterval(pollTimer);
    pollTimer = setInterval(loadProjects, anyRunning ? 2000 : 30000);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
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
      particles = Array.from({ length: 30 }, () => ({
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

  document.documentElement.dataset.portalBuild = BUILD;
  loadProjects();
  initFrostCanvas();
  window.addEventListener("beforeunload", () => clearInterval(pollTimer));
})();
