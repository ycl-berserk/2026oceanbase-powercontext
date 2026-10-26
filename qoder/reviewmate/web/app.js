"use strict";

const SESSION_KEY = "reviewmate.session";
const EXAMPLES = [
  {
    label: "LRU / FIFO 与 Belady 异常",
    question: "LRU 和 FIFO 有什么区别？为什么 FIFO 会出现 Belady 异常？",
  },
  {
    label: "B+ 树与范围查询",
    question: "B+ 树为什么适合范围查询？聚簇索引和二级索引有什么区别？",
  },
  {
    label: "偏差-方差权衡",
    question: "偏差和方差如何权衡？正则化为什么能缓解过拟合？",
  },
  {
    label: "TCP 慢启动与快重传",
    question: "TCP 慢启动什么时候结束？快重传和超时重传有什么不同？",
  },
];

const KIND_LABELS = {
  "weak-point": "薄弱点",
  "study-note": "学习笔记",
  "study-progress": "进度",
};

const MODE_LABELS = {
  deepseek: ["DeepSeek 生成", ""],
  extractive: ["本地摘录", "warn"],
  "extractive-fallback": ["已降级 · 本地摘录", "off"],
  "no-evidence": ["没有找到依据", "neutral"],
  template: ["本地计划模板", "warn"],
  "template-fallback": ["已降级 · 本地模板", "off"],
};

const state = {
  sessionId: readSession(),
  course: "",
  documents: [],
  courses: [],
  health: null,
  lastQuestion: "",
  lastCitations: [],
  busy: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  sessionId: $("session-id"),
  newSession: $("new-session"),
  docCounter: $("doc-counter"),
  docList: $("doc-list"),
  courseFilter: $("course-filter"),
  courseSelect: $("course-select"),
  memoryCounter: $("memory-counter"),
  memoryScope: $("memory-scope"),
  memoryList: $("memory-list"),
  weakForm: $("weak-form"),
  weakTopic: $("weak-topic"),
  askForm: $("ask-form"),
  question: $("question"),
  askButton: $("ask-button"),
  examples: $("examples"),
  answerCard: $("answer-card"),
  answerEyebrow: $("answer-eyebrow"),
  answerQuestion: $("answer-question"),
  answerMode: $("answer-mode"),
  answerBody: $("answer-body"),
  evidenceSummary: $("evidence-summary"),
  evidenceList: $("evidence-list"),
  extraCandidates: $("extra-candidates"),
  extraSummary: $("extra-summary"),
  extraList: $("extra-list"),
  traceBody: $("trace-body"),
  markWeak: $("mark-weak"),
  makePlan: $("make-plan"),
  planCard: $("plan-card"),
  planMode: $("plan-mode"),
  planMemory: $("plan-memory"),
  planBody: $("plan-body"),
  toast: $("toast"),
  statusSeekdb: $("status-seekdb"),
  statusMemory: $("status-memory"),
  statusLlm: $("status-llm"),
};

/* ---------- helpers ---------- */

function readSession() {
  try {
    const saved = localStorage.getItem(SESSION_KEY);
    if (saved && /^[A-Za-z0-9_-]{1,64}$/.test(saved)) return saved;
  } catch {
    /* storage may be unavailable */
  }
  const id = newSessionId();
  try {
    localStorage.setItem(SESSION_KEY, id);
  } catch {
    /* ignore */
  }
  return id;
}

function newSessionId() {
  const raw =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().replace(/-/g, "")
      : Math.random().toString(36).slice(2);
  return `sess_${raw.slice(0, 10)}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
  });
}

function shorten(text, limit = 120) {
  const clean = String(text ?? "").replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit - 1)}…` : clean;
}

function num(value, digits = 0) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.detail || `请求失败（HTTP ${response.status}）`);
  }
  return data;
}

let toastTimer = null;
function toast(message, isError = false) {
  if (!els.toast) return;
  els.toast.textContent = message;
  els.toast.classList.toggle("error", Boolean(isError));
  els.toast.classList.add("show");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => els.toast.classList.remove("show"), 2800);
}

function setStatus(node, tone, text, title = "") {
  if (!node) return;
  node.className = `status ${tone}`;
  const label = node.querySelector("span");
  if (label) label.textContent = text;
  node.title = title;
}

/* ---------- boot ---------- */

function init() {
  els.sessionId.textContent = state.sessionId;
  renderExamples();
  bindEvents();
  loadHealth();
  loadInventory();
  loadMemory();
}

function renderExamples() {
  els.examples.innerHTML = EXAMPLES.map(
    (item) =>
      `<button type="button" class="example" data-question="${escapeHtml(item.question)}" title="${escapeHtml(
        item.question
      )}">${escapeHtml(item.label)}</button>`
  ).join("");
}

function bindEvents() {
  els.askForm.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(els.question.value);
  });

  els.question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      ask(els.question.value);
    }
  });

  els.examples.addEventListener("click", (event) => {
    const button = event.target.closest("[data-question]");
    if (!button) return;
    const question = button.dataset.question;
    els.question.value = question;
    ask(question);
  });

  els.courseSelect.addEventListener("change", () => {
    state.course = els.courseSelect.value;
    renderCourseFilter();
    renderDocuments();
  });

  els.courseFilter.addEventListener("click", (event) => {
    const button = event.target.closest("[data-course]");
    if (!button) return;
    state.course = button.dataset.course || "";
    els.courseSelect.value = state.course;
    renderCourseFilter();
    renderDocuments();
  });

  els.newSession.addEventListener("click", () => {
    state.sessionId = newSessionId();
    try {
      localStorage.setItem(SESSION_KEY, state.sessionId);
    } catch {
      /* ignore */
    }
    els.sessionId.textContent = state.sessionId;
    state.lastQuestion = "";
    state.lastCitations = [];
    els.answerCard.classList.add("hidden");
    els.planCard.classList.add("hidden");
    els.memoryList.innerHTML = '<li class="empty">正在读取新的学习记忆…</li>';
    loadMemory();
    toast("已切换到一个新的学习会话");
  });

  els.markWeak.addEventListener("click", () => {
    const cited = state.lastCitations.find((item) => item.used) || state.lastCitations[0];
    if (!cited && !state.lastQuestion) {
      toast("先提一个问题，再标记薄弱点", true);
      return;
    }
    const topic = cited ? `${cited.title} · ${cited.heading}` : state.lastQuestion;
    const detail = state.lastQuestion ? `来自问题：${state.lastQuestion}` : "来自检索片段";
    markWeakPoint(topic, detail, els.markWeak);
  });

  els.makePlan.addEventListener("click", () => {
    makePlan(els.makePlan);
  });

  els.weakForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const topic = els.weakTopic.value.trim();
    if (!topic) {
      toast("先写下要记住的知识点", true);
      return;
    }
    markWeakPoint(topic, "手动记录", els.weakForm.querySelector("button")).then((ok) => {
      if (ok) els.weakTopic.value = "";
    });
  });

  els.evidenceList.addEventListener("click", handleEvidenceClick);
  els.extraList.addEventListener("click", handleEvidenceClick);

  els.answerBody.addEventListener("click", (event) => {
    const cite = event.target.closest("[data-cite]");
    if (!cite) return;
    const target = document.getElementById(`ev-${cite.dataset.cite}`);
    if (!target) {
      els.extraCandidates.open = true;
      return;
    }
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("flash");
    void target.offsetWidth;
    target.classList.add("flash");
  });
}

function handleEvidenceClick(event) {
  const button = event.target.closest("[data-evidence-topic]");
  if (!button) return;
  markWeakPoint(button.dataset.evidenceTopic, "来自检索片段", button);
}

/* ---------- health & inventory ---------- */

async function loadHealth() {
  try {
    const data = await api("/api/health");
    state.health = data;
    renderHealth(data);
  } catch (error) {
    state.health = null;
    setStatus(els.statusSeekdb, "off", "seekdb 不可用", error.message);
    setStatus(els.statusMemory, "off", "PowerContext 状态未知");
    setStatus(els.statusLlm, "off", "回答模式未知");
  }
}

function renderHealth(health) {
  const seekdb = health.seekdb || {};
  if (seekdb.ready) {
    setStatus(
      els.statusSeekdb,
      "ok",
      `seekdb · ${num(seekdb.documents)} 篇 / ${num(seekdb.chunks)} 段`,
      seekdb.db_path || ""
    );
  } else {
    setStatus(els.statusSeekdb, "off", "seekdb 不可用", seekdb.error || "");
  }

  const memory = health.powercontext || {};
  if (memory.available && memory.ready) {
    setStatus(els.statusMemory, "ok", "PowerContext 已记忆", memory.url || "");
  } else {
    setStatus(
      els.statusMemory,
      "off",
      "PowerContext 未连接",
      memory.error || "请先启动 PowerContext 服务"
    );
  }

  const llm = health.llm || {};
  if (llm.mode === "deepseek") {
    setStatus(els.statusLlm, "ok", `DeepSeek · ${llm.model || "已启用"}`, "回答由大模型基于检索片段生成");
  } else {
    setStatus(els.statusLlm, "warn", "本地摘录模式", "未配置 DEEPSEEK_API_KEY，回答直接摘录笔记原文");
  }
}

async function loadInventory() {
  try {
    const data = await api("/api/documents");
    state.documents = data.documents || [];
    state.courses = data.courses || [];
    if (state.course && !state.courses.includes(state.course)) state.course = "";
    renderCourseFilter();
    renderCourseOptions();
    renderDocuments();
    els.docCounter.textContent = `${state.documents.length} 篇`;
  } catch (error) {
    els.docList.innerHTML = `<li class="empty">无法读取知识库：${escapeHtml(error.message)}</li>`;
    els.docCounter.textContent = "—";
  }
}

function renderCourseFilter() {
  const counts = new Map();
  state.documents.forEach((doc) => counts.set(doc.course, (counts.get(doc.course) || 0) + 1));
  const chips = [`<button type="button" class="course-chip ${state.course ? "" : "active"}" data-course="">全部 ${state.documents.length}</button>`];
  state.courses.forEach((course) => {
    chips.push(
      `<button type="button" class="course-chip ${state.course === course ? "active" : ""}" data-course="${escapeHtml(
        course
      )}">${escapeHtml(course)} ${counts.get(course) || 0}</button>`
    );
  });
  els.courseFilter.innerHTML = chips.join("");
}

function renderCourseOptions() {
  els.courseSelect.innerHTML =
    '<option value="">全部课程</option>' +
    state.courses
      .map((course) => `<option value="${escapeHtml(course)}">${escapeHtml(course)}</option>`)
      .join("");
  els.courseSelect.value = state.course;
}

function renderDocuments() {
  const documents = state.course
    ? state.documents.filter((doc) => doc.course === state.course)
    : state.documents;
  if (!documents.length) {
    els.docList.innerHTML =
      '<li class="empty">还没有导入资料。运行 <code>make ingest</code> 导入 data/samples 中的课程笔记。</li>';
    return;
  }
  els.docList.innerHTML = documents
    .map(
      (doc) => `
      <li class="doc-item">
        <div class="doc-title">${escapeHtml(doc.title)}</div>
        <div class="doc-meta">
          <span class="tag">${escapeHtml(doc.course)}</span>
          <span>${num(doc.chunk_count)} 段</span>
          <span>${escapeHtml(doc.license || "")}</span>
        </div>
      </li>`
    )
    .join("");
}

/* ---------- memory ---------- */

async function loadMemory() {
  const sessionId = state.sessionId;
  try {
    const data = await api(`/api/memory?session_id=${encodeURIComponent(sessionId)}`);
    if (sessionId !== state.sessionId) return;
    renderMemory(data);
  } catch (error) {
    if (sessionId !== state.sessionId) return;
    els.memoryCounter.textContent = "—";
    els.memoryScope.textContent = "PowerContext 未连接";
    els.memoryList.innerHTML = `<li class="empty">${escapeHtml(error.message)}</li>`;
  }
}

function memoryText(entry) {
  const label = KIND_LABELS[entry.kind];
  const prefix = label ? `${label}：` : "";
  return prefix && entry.text.startsWith(prefix) ? entry.text.slice(prefix.length) : entry.text;
}

function renderMemory(data) {
  const entries = data.entries || [];
  els.memoryCounter.textContent = `${entries.length} 条`;
  if (!data.available) {
    els.memoryScope.textContent = "PowerContext 未连接";
    els.memoryList.innerHTML = `<li class="empty">${escapeHtml(
      data.error || "请先启动 PowerContext 服务，再刷新页面。"
    )}</li>`;
    return;
  }
  els.memoryScope.textContent = `scope ${data.scope_id || "—"}`;
  if (!entries.length) {
    els.memoryList.innerHTML =
      '<li class="empty">还没有记忆。提一个问题，或记下一个薄弱点。</li>';
    return;
  }
  const priority = { "weak-point": 0, "study-note": 1, "study-progress": 2 };
  const ordered = entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => {
      const diff = (priority[a.entry.kind] ?? 9) - (priority[b.entry.kind] ?? 9);
      return diff !== 0 ? diff : a.index - b.index;
    })
    .map((item) => item.entry)
    .slice(0, 12);
  els.memoryList.innerHTML = ordered
    .map(
      (entry) => `
      <li class="memory-item">
        <span class="memory-kind ${escapeHtml(entry.kind)}">${escapeHtml(
          KIND_LABELS[entry.kind] || entry.kind
        )}</span>
        <span class="memory-text">${escapeHtml(shorten(memoryText(entry), 96))}</span>
      </li>`
    )
    .join("");
}

/* ---------- ask ---------- */

function setBusy(busy) {
  state.busy = busy;
  els.askButton.disabled = busy;
  els.askButton.classList.toggle("is-loading", busy);
}

async function ask(rawQuestion) {
  const question = String(rawQuestion || "").trim();
  if (!question) {
    toast("先写下你的问题", true);
    els.question.focus();
    return;
  }
  if (state.busy) return;

  state.lastQuestion = question;
  state.lastCitations = [];
  setBusy(true);
  els.answerCard.classList.remove("hidden");
  els.planCard.classList.add("hidden");
  els.answerQuestion.textContent = question;
  els.answerEyebrow.textContent = `${state.course || "全部课程"} · ANSWER`;
  els.answerMode.textContent = "检索中";
  els.answerMode.className = "mode-badge neutral";
  els.answerBody.innerHTML =
    '<div class="skeleton"><span></span><span></span><span></span></div>';
  els.evidenceList.innerHTML = "";
  els.extraList.innerHTML = "";
  els.extraCandidates.classList.add("hidden");
  els.evidenceSummary.textContent = "";
  els.traceBody.innerHTML = "";
  els.answerCard.scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const data = await api("/api/ask", {
      method: "POST",
      body: JSON.stringify({
        question,
        session_id: state.sessionId,
        course: state.course || null,
      }),
    });
    renderAnswer(data);
    loadMemory();
    loadHealth();
  } catch (error) {
    els.answerMode.textContent = "请求失败";
    els.answerMode.className = "mode-badge off";
    els.answerBody.innerHTML = `<div class="error-box">${escapeHtml(error.message)}</div>`;
  } finally {
    setBusy(false);
  }
}

function renderAnswer(data) {
  state.lastCitations = data.citations || [];
  const [label, tone] = MODE_LABELS[data.answer_mode] || [data.answer_mode, "neutral"];
  els.answerMode.textContent = label;
  els.answerMode.className = `mode-badge ${tone}`.trim();
  els.answerEyebrow.textContent = `${data.course || "全部课程"} · ANSWER`;
  els.answerBody.innerHTML = renderMarkdown(data.answer);

  const citations = state.lastCitations;
  const used = citations.filter((item) => item.used);
  const unused = citations.filter((item) => !item.used);
  const visible = used.length ? used : citations.slice(0, 1);
  els.evidenceList.innerHTML = visible.map((item) => renderEvidence(item, true)).join("");

  if (unused.length) {
    els.extraCandidates.classList.remove("hidden");
    els.extraSummary.textContent = `其他检索候选（${unused.length} 条，未被直接引用）`;
    els.extraList.innerHTML = unused.map((item) => renderEvidence(item, false)).join("");
  } else {
    els.extraCandidates.classList.add("hidden");
  }

  const trace = data.trace || {};
  const retrieval = trace.retrieval || {};
  const channels = retrieval.channels || {};
  const retained = retrieval.retained || {};
  els.evidenceSummary.textContent = `${visible.length}/${citations.length} 条直接引用 · 全文 ${
    channels.fulltext ?? 0
  } / 向量 ${channels.vector ?? 0}`;
  els.traceBody.innerHTML = renderTrace(trace, data);
}

function renderEvidence(citation, used) {
  const badges = [];
  if (citation.fts_rank) {
    badges.push(`<span class="badge fts">全文 #${citation.fts_rank}</span>`);
  }
  if (citation.vector_rank) {
    badges.push(`<span class="badge vec">向量 #${citation.vector_rank}</span>`);
  }
  if (citation.distance != null) {
    badges.push(`<span class="badge page">L2 ${num(citation.distance, 3)}</span>`);
  }
  if (citation.page_no) {
    badges.push(`<span class="badge page">第 ${citation.page_no} 页</span>`);
  }
  return `
    <article class="evidence-item ${used ? "" : "unused"}" id="ev-${citation.index}">
      <span class="evidence-index">${citation.index}</span>
      <div>
        <div class="evidence-top">
          <span class="evidence-title">${escapeHtml(citation.title || citation.doc_id)}</span>
          <span class="evidence-path">${escapeHtml(citation.heading)} · ${escapeHtml(citation.course)}</span>
          ${badges.join("")}
        </div>
        <p class="evidence-snippet">${escapeHtml(shorten(citation.content, 180))}</p>
        <div class="evidence-tools">
          <button type="button" data-evidence-topic="${escapeHtml(
            `${citation.title} · ${citation.heading}`
          )}">标记为薄弱点</button>
        </div>
      </div>
    </article>`;
}

function renderTrace(trace, data) {
  const retrieval = trace.retrieval || {};
  const channels = retrieval.channels || {};
  const retained = retrieval.retained || {};
  const timing = trace.timing_ms || {};
  const memory = trace.powercontext || {};
  const memoryText = memory.available
    ? `scope ${memory.scope_id} · 命中 ${memory.hits ?? 0} 条 · 写入${
        memory.recorded ? "成功" : "未完成"
      }`
    : `未连接：${memory.error || "未知错误"}`;
  const rows = [
    [
      "检索通道",
      `全文 ${channels.fulltext ?? 0} 条 · 向量 ${channels.vector ?? 0} 条（保留 ${
        retained.fulltext ?? 0
      } / ${retained.vector ?? 0}）`,
    ],
    ["融合策略", `RRF（k=60）· top_k=${trace.top_k ?? "—"} · 课程 ${trace.course || "全部"}`],
    [
      "耗时",
      `embedding ${timing.embed ?? 0} ms · 检索 ${timing.retrieval ?? 0} ms · 记忆 ${
        timing.memory ?? 0
      } ms · 回答 ${timing.answer ?? 0} ms`,
    ],
    ["向量模型", `${trace.embedding_model || "—"}（${trace.embedding_dim || "—"} 维）`],
    ["PowerContext", memoryText],
    ["回答模式", `${(trace.llm || {}).mode || data.answer_mode}${(trace.llm || {}).warning ? " · " + trace.llm.warning : ""}`],
    ["QA 记录", trace.qa_id || data.qa_id || "—"],
  ];
  const rowsHtml = rows
    .map(
      ([key, value]) =>
        `<div class="trace-row"><span class="trace-key">${escapeHtml(key)}</span><span class="trace-val">${escapeHtml(
          value
        )}</span></div>`
    )
    .join("");
  const sql = `MATCH(content) AGAINST(?)
UNION ALL
SELECT ... ORDER BY l2_distance(embedding, ?) APPROXIMATE`;
  return `${rowsHtml}<div class="trace-row"><span class="trace-key">seekdb SQL</span><pre class="trace-sql">${escapeHtml(
    sql
  )}</pre></div>`;
}

/* ---------- actions ---------- */

async function markWeakPoint(topic, detail, trigger) {
  if (!topic) return false;
  if (trigger) trigger.disabled = true;
  try {
    await api("/api/memory/weak", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        topic,
        detail,
      }),
    });
    toast("已写入 PowerContext 学习记忆");
    await loadMemory();
    return true;
  } catch (error) {
    toast(error.message, true);
    return false;
  } finally {
    if (trigger) trigger.disabled = false;
  }
}

async function makePlan(trigger) {
  if (trigger) {
    trigger.disabled = true;
    trigger.textContent = "生成中…";
  }
  try {
    const data = await api("/api/review-plan", {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId, course: state.course || null }),
    });
    const [label, tone] = MODE_LABELS[data.mode] || [data.mode, "neutral"];
    els.planMode.textContent = label;
    els.planMode.className = `mode-badge ${tone}`.trim();
    const weakCount = (data.weak_points || []).length;
    const docCount = (data.documents || []).length;
    const memoryNote = data.powercontext && data.powercontext.available
      ? `取用了 ${weakCount} 条薄弱点，覆盖 ${docCount} 篇笔记。`
      : `PowerContext 未连接，计划仅基于 ${docCount} 篇笔记（${data.powercontext?.error || "无记忆"}）。`;
    els.planMemory.textContent = memoryNote;
    els.planBody.innerHTML = renderMarkdown(data.plan);
    els.planCard.classList.remove("hidden");
    els.planCard.scrollIntoView({ behavior: "smooth", block: "start" });
    toast("复习计划已生成");
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (trigger) {
      trigger.disabled = false;
      trigger.textContent = "生成复习计划";
    }
  }
}

/* ---------- markdown-lite ---------- */

function renderMarkdown(text) {
  const lines = escapeHtml(text || "").split("\n");
  let html = "";
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const heading = trimmed.match(/^#{3}\s+(.*)$/);
    if (heading) {
      html += `<p class="md-heading">${inlineMarkup(heading[1])}</p>`;
      continue;
    }
    const step = trimmed.match(/^(\d+)[.、]\s+(.*)$/);
    if (step) {
      html += `<p class="md-step"><span class="md-num">${step[1]}</span><span>${inlineMarkup(
        step[2]
      )}</span></p>`;
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      html += `<p class="md-bullet">${inlineMarkup(bullet[1])}</p>`;
      continue;
    }
    html += `<p>${inlineMarkup(trimmed)}</p>`;
  }
  return html || "<p>没有生成内容。</p>";
}

function inlineMarkup(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(\d+)\]/g, '<button type="button" class="cite" data-cite="$1">[$1]</button>');
}

init();
