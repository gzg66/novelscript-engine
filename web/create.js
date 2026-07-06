(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const form = $("#create-form");
  const dropZone = $("#drop-zone");
  const fileInput = $("#novel-file");
  const fileName = $("#file-name");
  const formError = $("#form-error");
  const submitBtn = $("#submit-btn");
  let selectedFile = null;

  function setFile(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".txt")) {
      showError("仅支持 .txt 格式的小说原文");
      return;
    }
    selectedFile = file;
    fileName.textContent = file.name + " · " + formatSize(file.size);
    dropZone.classList.add("drop-zone--ready");
    hideError();
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function showError(msg) {
    formError.hidden = false;
    formError.textContent = msg;
  }

  function hideError() {
    formError.hidden = true;
  }

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drop-zone--hover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drop-zone--hover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drop-zone--hover");
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  });

  function setUploadStep(step, msg) {
    const panel = $("#upload-progress");
    const actions = $("#form-actions");
    panel.hidden = false;
    actions.hidden = true;
    $("#upload-msg").textContent = msg;
    ["upload", "create", "index"].forEach((s) => {
      const el = $(`#step-${s}`);
      el.classList.remove("upload-step--active", "upload-step--done");
      if (s === step) el.classList.add("upload-step--active");
      const order = ["upload", "create", "index"];
      if (order.indexOf(s) < order.indexOf(step)) el.classList.add("upload-step--done");
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError();

    if (!selectedFile) {
      showError("请先选择小说 txt 文件");
      return;
    }
    if (!$("#rights-check").checked) {
      showError("请确认改编授权");
      return;
    }

    submitBtn.disabled = true;
    setUploadStep("upload", "正在上传小说原文…");

    const fd = new FormData();
    fd.append("file", selectedFile);
    fd.append("title", $("#project-title").value.trim());
    fd.append("mode", $("#project-mode").value);

    try {
      setUploadStep("create", "正在创建项目并写入原文…");
      const res = await fetch("/api/projects", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "创建失败");
      setUploadStep("index", `章节索引完成（${data.chapters || "—"} 章）· 正在进入项目页…`);
      await new Promise((r) => setTimeout(r, 600));
      const autostart = $("#autostart-check").checked;
      const base = data.redirect || "/project.html?slug=" + encodeURIComponent(data.slug);
      const sep = base.includes("?") ? "&" : "?";
      window.location.href = autostart ? base + sep + "autostart=1" : base;
    } catch (err) {
      $("#upload-progress").hidden = true;
      $("#form-actions").hidden = false;
      showError(err.message || "创建失败");
      submitBtn.disabled = false;
      submitBtn.textContent = "创建并开始精编";
    }
  });
})();
