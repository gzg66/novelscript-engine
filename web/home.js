(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

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

  async function loadProjects() {
    const grid = $("#projects-grid");
    try {
      const projects = await fetch("/api/projects").then((r) => {
        if (!r.ok) throw new Error("API 不可用");
        return r.json();
      });

      if (!projects.length) {
        grid.innerHTML =
          '<div class="projects-empty">' +
          "<p>还没有项目</p>" +
          '<a class="btn btn-primary" href="/create.html">上传第一本小说</a>' +
          "</div>";
        schedulePoll(false);
        return;
      }

      grid.innerHTML = projects
        .map((p) => {
          const pct = p.running
            ? p.progress ?? 0
            : Math.round((p.stagesComplete / p.stagesTotal) * 100);
          const runningBadge = p.running
            ? `<span class="project-card-running"><span class="status-dot status-dot--running"></span>${escapeHtml(p.message || PHASE_SHORT[p.phase] || "运行中")}</span>`
            : "";
          return `
        <a class="project-card${p.running ? " project-card--running" : ""}" href="/project.html?slug=${encodeURIComponent(p.slug)}">
          <p class="project-card-slug">${p.slug}</p>
          <h3 class="project-card-title">${escapeHtml(p.title)}</h3>
          <div class="project-card-meta">
            <span>${p.chapters || "—"} 章</span>
            <span>${p.mode}</span>
            <span>${p.stagesComplete}/${p.stagesTotal} 阶段</span>
          </div>
          ${runningBadge}
          <div class="project-card-bar">
            <span style="width:${pct}%"></span>
          </div>
        </a>
      `;
        })
        .join("");

      schedulePoll(projects.some((p) => p.running));
    } catch (e) {
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
    pollTimer = setInterval(loadProjects, anyRunning ? 4000 : 30000);
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

  loadProjects();
  initFrostCanvas();
  window.addEventListener("beforeunload", () => clearInterval(pollTimer));
})();
