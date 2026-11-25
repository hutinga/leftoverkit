"use strict";

const copy = {
  zh: {
    title: ["AI 活干完了。", "临时文件留了一地。"],
    lede: "点一下，看哪些能清走，哪些会留下。",
    fixture: "可复现演示",
    fileLabel: "待清理的临时文件",
    before: "清理前",
    after: "清理后",
    working: "处理中",
    clean: "清理演示项目",
    undo: "撤回清理",
    workspace: "演示项目",
    cellLegend: "每格代表一个临时文件",
    worktrees: "个附加工作树",
    retained: "这些一直留在原处",
    guard: "清理完也照常使用。",
    fixtureNote: "这里回放一套真实 CLI 测试的结果。演示数据为合成数据，网页不会操作你的文件。",
    reproduce: "查看复现步骤 ↗",
    first: (n) => n + " 个文件可以清理，仍在使用的东西会留下。",
    cleaned: (n) => n + " 个文件和 1 个工作树已移入隔离区。",
    complete: (n) => n + " 个文件已清走",
    restored: (n) => "已恢复 " + n + " 个文件和原工作树。",
    unavailable: "演示数据未能加载。请下载完整项目后重新打开。",
    category: {
      screenshots: "截图", logs: "运行日志", reports: "测试报告",
      exports: "中间数据", scripts: "一次性脚本", patches: "补丁草稿",
    },
    keep: ["项目源码", "本机配置 .env", "验收交付物", "占用中的日志", "来源不明的 tmp", "未合并工作树"],
  },
  en: {
    title: ["AI finished the work.", "It left a mess."],
    lede: "Try one cleanup. See what moves and what stays.",
    fixture: "Reproducible demo",
    fileLabel: "temporary files ready to move",
    before: "Before",
    after: "After",
    working: "Working",
    clean: "Clean the demo project",
    undo: "Undo cleanup",
    workspace: "Demo project",
    cellLegend: "Each cell is one temporary file",
    worktrees: "linked worktrees",
    retained: "These stay put",
    guard: "They’re still there after cleanup.",
    fixtureNote: "This replays a verified CLI run in a synthetic repo. The page never touches your files.",
    reproduce: "Reproduce this run ↗",
    first: (n) => n + " files are ready. Anything still in use stays put.",
    cleaned: (n) => n + " files and 1 worktree moved to quarantine.",
    complete: (n) => n + " files cleared",
    restored: (n) => "Restored all " + n + " files and the original worktree.",
    unavailable: "The demo data could not load. Reopen it from the complete project.",
    category: {
      screenshots: "Screenshots", logs: "Run logs", reports: "Test reports",
      exports: "Data exports", scripts: "One-off scripts", patches: "Draft patches",
    },
    keep: ["Tracked source", "Local .env", "Acceptance evidence", "Open log", "Unknown tmp file", "Unmerged worktree"],
  },
};

const palette = {
  screenshots: "#6fc1ad", logs: "#bea678", reports: "#8ca9d0",
  exports: "#74a0a8", scripts: "#b294c9", patches: "#c69b93",
};
const canvas = document.querySelector("#cells");
const context = canvas.getContext("2d");
const action = document.querySelector("#action");
const language = document.querySelector("#language");
const feedback = document.querySelector("#feedback");
const panel = document.querySelector(".workspace");
const note = document.querySelector("#map-note");
const evidence = window.demoEvidence;
const total = evidence?.moved_files ?? 0;
const groups = Object.entries(evidence?.files ?? {});
const cells = groups.flatMap(([key, count]) => Array(count).fill(key));
const labels = new Map();
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const ready = (
  evidence?.synthetic && evidence.original_bytes_verified && total > 0
  && cells.length === total && evidence.restored_files === total
  && evidence.protected.length === 5 && Boolean(context)
);

const state = {
  lang: window.location.hash === "#en" ? "en" : "zh",
  mode: "before",
  fraction: 0,
  layout: [],
  viewport: { width: 0, height: 0 },
};

function localized() {
  return copy[state.lang];
}

function applyLanguage() {
  const t = localized();
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = total + (state.lang === "zh" ? " 个临时文件" : " temporary files") + " · LeftoverKit";
  language.textContent = state.lang === "zh" ? "EN" : "中文";
  language.setAttribute("aria-label", state.lang === "zh" ? "Switch to English" : "切换成中文");
  for (const element of document.querySelectorAll("[data-copy]")) {
    const value = t[element.dataset.copy];
    if (Array.isArray(value)) {
      element.replaceChildren(value[0], document.createElement("br"), value[1]);
    } else {
      element.textContent = value;
    }
  }
  for (const [key, ref] of labels) {
    ref.label.textContent = t.category[key];
  }
  document.querySelector("#groups").setAttribute("aria-label", state.lang === "zh" ? "文件类型" : "File types");
  if (ready) {
    const kept = t.keep.map((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      return item;
    });
    document.querySelector("#protected").replaceChildren(...kept);
  }
  updateStatus();
}

function updateStatus() {
  const t = localized();
  const after = state.mode === "after";
  const working = state.mode === "cleaning" || state.mode === "restoring";
  const restoring = after || state.mode === "restoring";
  panel.dataset.stage = after ? "after" : "before";
  action.disabled = working || !ready;
  panel.setAttribute("aria-busy", String(working));
  document.querySelector("#action-label").textContent = restoring ? t.undo : t.clean;
  document.querySelector("#action-icon").textContent = restoring ? "↶" : "↘";
  document.querySelector("#command").textContent = restoring ? "leftoverkit undo" : "leftoverkit clean";
  document.querySelector("#phase").textContent = working ? t.working : (after ? t.after : t.before);
  document.querySelector("#worktrees").textContent = ready
    ? String(evidence.untouched_worktrees + (after ? 0 : evidence.moved_worktrees)) : "—";
  note.hidden = !after;
  note.textContent = after ? t.complete(total) : "";
  feedback.textContent = !ready ? t.unavailable
    : working ? t.working
      : after ? t.cleaned(total)
        : state.mode === "restored" ? t.restored(total) : t.first(total);
}

function setupLegend() {
  const list = document.querySelector("#groups");
  for (const [key] of groups) {
    const row = document.createElement("li");
    const marker = document.createElement("i");
    const label = document.createElement("span");
    const count = document.createElement("b");
    marker.setAttribute("aria-hidden", "true");
    row.style.setProperty("--group", palette[key]);
    row.append(marker, label, count);
    list.append(row);
    labels.set(key, { label, count });
  }
}

function resize() {
  if (!ready) return;
  const { width, height } = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  state.viewport = { width, height };
  const padding = width < 420 ? 12 : 19;
  const availableWidth = width - 2 * padding;
  const availableHeight = height - 2 * padding;
  const cols = Math.ceil(Math.sqrt(total * availableWidth / availableHeight));
  const rows = Math.ceil(total / cols);
  const stepX = availableWidth / cols;
  const stepY = availableHeight / rows;
  const size = Math.max(2, Math.min(stepX, stepY) - (width < 420 ? 2.25 : 3.1));
  state.layout = cells.map((group, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    return {
      group, size, x: padding + stepX * (col + .5) - size / 2,
      y: padding + stepY * (row + .5) - size / 2,
      key: col + row * .64 + ((index * 37) % 71) / 120,
      intensity: .72 + ((index * 29) % 17) / 63,
    };
  }).sort((a, b) => a.key - b.key);
  draw();
}

function draw() {
  const { width, height } = state.viewport;
  const moved = Math.round(state.fraction * total);
  context.clearRect(0, 0, width, height);
  const perGroup = Object.fromEntries(groups.map(([key]) => [key, 0]));
  state.layout.forEach(({ x, y, size, group, intensity }, index) => {
    const filled = index >= moved;
    context.fillStyle = filled ? palette[group] : "#25312d";
    context.globalAlpha = filled ? intensity : .66;
    if (filled) perGroup[group]++;
    context.beginPath();
    context.roundRect(x, y, size, size, Math.min(2, size / 3));
    context.fill();
  });
  context.globalAlpha = 1;
  document.querySelector("#count").textContent = String(total - moved);
  for (const [key, ref] of labels) ref.count.textContent = String(perGroup[key]);
}

function transition(restore) {
  const from = restore ? 1 : 0;
  const to = 1 - from;
  const duration = reducedMotion.matches ? 0 : (restore ? 420 : 760);
  state.mode = restore ? "restoring" : "cleaning";
  updateStatus();
  const start = performance.now();
  function tick(now) {
    const t = duration ? Math.min((now - start) / duration, 1) : 1;
    const eased = 1 - (1 - t) ** 3;
    state.fraction = from + (to - from) * eased;
    draw();
    if (t < 1) {
      window.requestAnimationFrame(tick);
    } else {
      state.mode = restore ? "restored" : "after";
      updateStatus();
      action.focus({ preventScroll: true });
    }
  }
  window.requestAnimationFrame(tick);
}

language.addEventListener("click", () => {
  state.lang = state.lang === "zh" ? "en" : "zh";
  window.history.replaceState(null, "", state.lang === "en" ? "#en" : "#zh");
  applyLanguage();
});
action.addEventListener("click", () => transition(state.mode === "after"));
if (ready) {
  setupLegend();
  new ResizeObserver(resize).observe(canvas);
  resize();
}
applyLanguage();
