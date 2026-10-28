const W = 960;
const H = 600;
const SERIF = '"Noto Serif SC","Songti SC","STSong","SimSun",serif';
const SANS = '"Noto Sans SC","Microsoft YaHei","PingFang SC","Segoe UI",sans-serif';

const canvas = document.getElementById("scene");
const ctx = canvas.getContext("2d");
ctx.scale(2, 2);

const $ = (id) => document.getElementById(id);
const stage = $("stage");
const tideValue = $("tideValue");
const tideFill = $("tideFill");
const tideMarker = $("tideMarker");
const turnCount = $("turnCount");
const clueRow = $("clueRow");
const promptEl = $("prompt");
const promptText = $("promptText");
const toastEl = $("toast");
const dialogue = $("dialogue");
const portrait = $("portrait");
const speaker = $("speaker");
const speakerRole = $("speakerRole");
const dialogueScroll = $("dialogueScroll");
const dialogueText = $("dialogueText");
const playerEcho = $("playerEcho");
const chipsEl = $("chips");
const askForm = $("askForm");
const askInput = $("askInput");
const sendBtn = $("sendBtn");
const closeBtn = $("closeBtn");
const titleScreen = $("title");
const prologue = $("prologue");
const prologueText = $("prologueText");
const prologueBtn = $("prologueBtn");
const endingScreen = $("ending");
const endingTitle = $("endingTitle");
const endingText = $("endingText");
const endingStats = $("endingStats");
const notebook = $("notebook");
const recordScreen = $("record");
const recordText = $("recordText");
const loading = $("loading");
const loadingText = $("loadingText");

const CLUES = [
  {
    key: "wall_height", mark: "墙顶", short: "墙顶", label: "墙顶不是地面",
    desc: "2.90 m 量的是城墙顶端；第 13 号片区的实际地面高程是 0.735 m。",
    hint: "问纪：铜牌上的 2.90 米，量的是哪一段？"
  },
  {
    key: "prefix_low", mark: "前缀", short: "前缀", label: "lo 是前缀",
    desc: "lo 只能放在词首，表示低地；放在词尾是不成立的词。",
    hint: "叶的录音里，旧路牌只念出了半个词。"
  },
  {
    key: "deleted_category", mark: "旧档", short: "旧档", label: "被删掉的分类",
    desc: "海关旧档的分类栏被整块裁走；最后调阅人是译名台复核员塞恩。",
    hint: "问纪：海关旧档的分类为什么不见了？"
  },
  {
    key: "roster", mark: "名册", short: "名册", label: "名册的缺口",
    desc: "撤离名册只有 18,000 个船位，低地实际居住约 24,000 人；第 13 号片区没有条目。",
    hint: "问纪：撤离名册里，第 13 号片区为什么不在？"
  }
];

const NPCS = [
  {
    id: "archivist",
    name: "纪",
    role: "档案馆值班员",
    portrait: "assets/ji.jpg",
    prefix: "档案员",
    color: "#7db7bb",
    x: 250, y: 338,
    anchor: { x: 250, y: 380 },
    radius: 92,
    greeting: "（她把手里的名册合上，抬眼看你。）说吧。",
    thinking: "（纪翻动档案，纸页很轻。）",
    prompt: "与纪交谈",
    questions: [
      "档案员，铜牌上的 2.90 米是什么高度？",
      "档案员，撤离名册里有多少人？",
      "档案员，海关旧档的分类为什么不见了？"
    ]
  },
  {
    id: "sean",
    name: "塞恩",
    role: "译名台复核员",
    portrait: "assets/sean.jpg",
    prefix: "塞恩",
    color: "#d5a15e",
    x: 750, y: 334,
    anchor: { x: 750, y: 376 },
    radius: 94,
    greeting: "（印章停在半空。他先看你，再看门口。）……译名官？这会儿还有手续？",
    thinking: "（塞恩把印章放下，又拿起来。）",
    prompt: "与塞恩交谈",
    questions: [
      "塞恩，名册为什么没有第 13 号片区？",
      "塞恩，旧档最后一页是你调阅的吗？",
      "塞恩，你改过这个名字吗？"
    ]
  },
  {
    id: "ye",
    name: "叶",
    role: "测绘员 · 手机录音",
    portrait: "assets/ye.jpg",
    prefix: "叶",
    color: "#79b9cf",
    x: 688, y: 492,
    anchor: { x: 735, y: 520 },
    radius: 96,
    greeting: "（储物柜上的手机亮了一下。录音自动播放。）……喂？还有人吗？",
    thinking: "（录音在缓冲，雨声先传了出来。）",
    prompt: "查看叶的手机",
    questions: [
      "叶，旧路牌上写的是什么？",
      "叶，地面高程是多少？",
      "叶，你还好吗？"
    ]
  }
];

const NPC_BY_ID = Object.fromEntries(NPCS.map((n) => [n.id, n]));
const ACTIONS = ["把片区改名为 lo-ul-dom", "指控塞恩"];
const META = ["状态", "任务"];

const SOLIDS = [
  { x: 120, y: 190, w: 250, h: 94 },
  { x: 600, y: 186, w: 290, h: 94 },
  { x: 70, y: 205, w: 48, h: 265 },
  { x: 700, y: 426, w: 118, h: 104 }
];
const NPC_SOLIDS = [
  { x: 250, y: 334, r: 17 },
  { x: 750, y: 330, r: 18 }
];
const BOUNDS = { x1: 72, y1: 198, x2: 888, y2: 564 };

const state = {
  started: false,
  over: false,
  busy: false,
  typing: false,
  dialogueOpen: false,
  activeNpc: null,
  nearId: null,
  notebookOpen: false,
  startFailed: false,
  conversationId: "",
  tide: 2.4,
  clues: { wall_height: false, prefix_low: false, deleted_category: false, roster: false },
  trust: { archivist: 0, sean: 0, ye: 0 },
  ending: "",
  actionCount: 0,
  yeContacted: false,
  lastQuery: ""
};

const player = { x: 480, y: 538, dir: "down", moving: false, anim: 0 };
const keys = new Set();

let typingTimer = null;
let typingFull = "";
let typingDone = null;
let typingProgress = 0;
let typingSpeed = 30;
let toastQueue = [];
let toastActive = false;
let toastTimer = null;

const clientId = (() => {
  try {
    const saved = localStorage.getItem("district13-client");
    if (saved) return saved;
    const id = (crypto.randomUUID && crypto.randomUUID()) ||
      ("rpg-" + Math.random().toString(36).slice(2) + Date.now().toString(36));
    localStorage.setItem("district13-client", id);
    return id;
  } catch (_) {
    return "rpg-" + Math.random().toString(36).slice(2);
  }
})();

/* ------------------------------------------------------------------ utils */

function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
function rand(n) {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}
function rr(x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}
function fillRect(x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
}
function line(x1, y1, x2, y2, color, width = 1) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}
function circle(x, y, r, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
}
function txt(s, x, y, size, color, align = "left", baseline = "middle", font = SERIF, weight = 400) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.font = weight + " " + size + "px " + font;
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
  ctx.fillText(s, x, y);
  ctx.restore();
}
function shadow(x, y, rx, ry) {
  ctx.save();
  ctx.fillStyle = "rgba(0,0,0,0.42)";
  ctx.beginPath();
  ctx.ellipse(x, y - 2, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}
function roundRectFill(x, y, w, h, r, color) {
  rr(x, y, w, h, r);
  ctx.fillStyle = color;
  ctx.fill();
}
function radial(x, y, r, color) {
  const g = ctx.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, color);
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
}

/* --------------------------------------------------------------- ui state */

function buildHud() {
  clueRow.textContent = "";
  for (const d of CLUES) {
    const el = document.createElement("span");
    el.className = "clue-chip";
    el.dataset.key = d.key;
    el.title = d.label + "：" + d.desc;
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = "×";
    const label = document.createElement("span");
    label.textContent = d.short;
    el.append(mark, label);
    clueRow.append(el);
  }
}

function renderHud() {
  tideValue.textContent = state.tide.toFixed(2);
  const ratio = clamp((state.tide - 2.4) / 0.6, 0, 1);
  tideFill.style.width = (ratio * 100).toFixed(2) + "%";
  tideMarker.style.left = (ratio * 100).toFixed(2) + "%";
  tideValue.style.color = ratio > 0.82 ? "var(--danger)" : ratio > 0.55 ? "var(--amber)" : "var(--teal)";
  turnCount.textContent = "第 " + state.actionCount + " 次动作";

  for (const d of CLUES) {
    const el = clueRow.querySelector('[data-key="' + d.key + '"]');
    if (!el) continue;
    const found = !!state.clues[d.key];
    el.classList.toggle("found", found);
    el.querySelector(".mark").textContent = found ? "✓" : "×";
  }
  renderNotebook();
}

function renderNotebook() {
  const foundCount = CLUES.filter((d) => state.clues[d.key]).length;
  $("noteClueCount").textContent = foundCount + " / 4";
  $("noteTide").textContent = state.tide.toFixed(2) + " m";
  $("noteTurns").textContent = String(state.actionCount);
  $("noteYe").textContent = state.yeContacted ? "是" : "否";

  const list = $("noteClues");
  list.textContent = "";
  for (const d of CLUES) {
    const li = document.createElement("li");
    const found = !!state.clues[d.key];
    li.className = found ? "found" : "";
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = found ? "✓" : "×";
    const body = document.createElement("span");
    const name = document.createElement("span");
    name.className = "clue-name";
    name.textContent = found ? d.label : "尚未查明";
    const desc = document.createElement("span");
    desc.className = "clue-desc";
    desc.textContent = found ? d.desc : d.hint;
    body.append(name, desc);
    li.append(mark, body);
    list.append(li);
  }

  const trust = $("noteTrust");
  trust.textContent = "";
  const people = [
    ["纪", "archivist", "var(--teal)"],
    ["塞恩", "sean", "var(--amber)"],
    ["叶", "ye", "var(--teal)"]
  ];
  for (const [label, key, color] of people) {
    const row = document.createElement("div");
    row.className = "trust-row";
    const name = document.createElement("span");
    name.textContent = label;
    const bar = document.createElement("div");
    bar.className = "trust-bar";
    const v = state.trust[key] || 0;
    for (let i = 0; i < 3; i++) {
      const seg = document.createElement("i");
      if (i < v) seg.className = "on";
      bar.append(seg);
    }
    const val = document.createElement("b");
    val.textContent = String(v);
    val.style.color = color;
    row.append(name, bar, val);
    trust.append(row);
  }
}

function toast(msg) {
  toastQueue.push(msg);
  pumpToast();
}

function pumpToast() {
  if (toastActive || !toastQueue.length) return;
  toastActive = true;
  toastEl.textContent = toastQueue.shift();
  toastEl.classList.remove("is-hidden");
  toastTimer = setTimeout(() => {
    toastEl.classList.add("is-hidden");
    toastTimer = setTimeout(() => {
      toastActive = false;
      pumpToast();
    }, 180);
  }, 1900);
}

function showLoading(msg) {
  loadingText.textContent = msg || "译名台在等回声……";
  loading.classList.remove("is-hidden");
}
function hideLoading() { loading.classList.add("is-hidden"); }

function setPrompt(npc) {
  if (!npc) {
    promptEl.classList.add("is-hidden");
    return;
  }
  promptText.textContent = npc.prompt;
  promptEl.style.left = (npc.anchor.x / W) * 100 + "%";
  promptEl.style.top = ((npc.anchor.y - 24) / H) * 100 + "%";
  promptEl.classList.remove("is-hidden");
}

function updatePrompt() {
  const blocked = !state.started || state.over || state.dialogueOpen || state.notebookOpen ||
    !prologue.classList.contains("is-hidden") || !endingScreen.classList.contains("is-hidden");
  if (blocked) { setPrompt(null); state.nearId = null; return; }
  const near = nearestTarget();
  if (near) setPrompt(near);
  else setPrompt(null);
  state.nearId = near ? near.id : null;
}

/* --------------------------------------------------------------- dialogue */

function typewrite(text, speed, done) {
  stopTyping();
  typingFull = text;
  typingDone = done || null;
  typingSpeed = speed || 30;
  typingProgress = 0;
  state.typing = true;
  dialogueText.classList.remove("thinking");
  dialogueText.classList.add("typing");
  dialogueText.textContent = "";
  let last = performance.now();
  const tick = (now) => {
    const dt = Math.min((now - last) / 1000, 0.08);
    last = now;
    typingProgress += typingSpeed * dt;
    const n = Math.min(typingFull.length, Math.floor(typingProgress));
    dialogueText.textContent = typingFull.slice(0, n);
    scrollDialogue();
    if (n >= typingFull.length) {
      finishTyping();
      return;
    }
    typingTimer = requestAnimationFrame(tick);
  };
  typingTimer = requestAnimationFrame(tick);
}

function stopTyping() {
  if (typingTimer) {
    cancelAnimationFrame(typingTimer);
    typingTimer = null;
  }
  state.typing = false;
  dialogueText.classList.remove("typing");
}

function finishTyping() {
  if (!state.typing && dialogueText.textContent === typingFull) {
    if (typingDone) { const cb = typingDone; typingDone = null; cb(); }
    return;
  }
  if (typingTimer) { cancelAnimationFrame(typingTimer); typingTimer = null; }
  state.typing = false;
  dialogueText.classList.remove("typing");
  dialogueText.textContent = typingFull;
  scrollDialogue();
  const cb = typingDone;
  typingDone = null;
  if (cb) cb();
}

function scrollDialogue() {
  dialogueScroll.scrollTop = dialogueScroll.scrollHeight;
}

function openDialogue(npc) {
  if (!npc || state.over || state.busy) return;
  state.activeNpc = npc;
  state.dialogueOpen = true;
  state.nearId = null;
  keys.clear();
  player.moving = false;
  setPrompt(null);
  portrait.src = npc.portrait;
  portrait.alt = npc.name + "的立绘";
  speaker.textContent = npc.name;
  speakerRole.textContent = npc.role;
  playerEcho.classList.add("is-hidden");
  playerEcho.textContent = "";
  dialogue.classList.remove("is-hidden");
  renderChips();
  askInput.placeholder = "对" + npc.name + "说……";
  askInput.value = "";
  askInput.disabled = false;
  sendBtn.disabled = false;
  closeBtn.disabled = false;
  typewrite(npc.greeting, 28);
  setTimeout(() => askInput.focus(), 40);
}

function closeDialogue() {
  if (state.busy) return;
  if (state.ending) {
    const full = typingFull || dialogueText.textContent;
    stopTyping();
    showEnding(state.ending, full);
    return;
  }
  if (typingTimer) { cancelAnimationFrame(typingTimer); typingTimer = null; }
  state.typing = false;
  typingDone = null;
  typingFull = "";
  state.dialogueOpen = false;
  state.activeNpc = null;
  dialogue.classList.add("is-hidden");
  dialogueText.textContent = "";
  playerEcho.classList.add("is-hidden");
  playerEcho.textContent = "";
  keys.clear();
  updatePrompt();
  stage.focus();
}

function renderChips() {
  chipsEl.textContent = "";
  if (!state.activeNpc) return;
  const add = (label, query, cls) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (cls ? " " + cls : "");
    b.textContent = label;
    b.disabled = state.busy;
    b.addEventListener("click", () => {
      if (state.busy) return;
      if (state.typing) finishTyping();
      sendQuery(query, label);
    });
    chipsEl.append(b);
  };
  for (const q of state.activeNpc.questions) add(q, q);
  for (const q of ACTIONS) add(q, q, "action");
  for (const q of META) add(q, q, "meta");
}

function setBusy(busy) {
  state.busy = busy;
  askInput.disabled = busy || !!state.ending;
  sendBtn.disabled = busy || !!state.ending;
  closeBtn.disabled = busy;
  for (const b of chipsEl.querySelectorAll("button")) b.disabled = busy || !!state.ending;
  if (busy) {
    const who = state.activeNpc;
    speakerRole.textContent = "正在回应……";
    dialogueText.classList.add("thinking");
    dialogueText.textContent = who ? who.thinking : "（译名台在等回声。）";
    scrollDialogue();
  } else {
    if (state.activeNpc) speakerRole.textContent = state.activeNpc.role;
  }
}

/* ------------------------------------------------------------------- api */

function isMeta(q) {
  return /^(状态|任务|帮助|查看状态|查看任务|上次|重开|重来)/.test(q.trim());
}

function isAction(q) {
  return /(改名|改名为|指控)/.test(q);
}

function composeQuery(raw) {
  const q = raw.trim();
  if (!q) return "";
  if (isMeta(q) || isAction(q)) return q;
  if (/(纪|档案员|塞恩|叶)/.test(q)) return q;
  if (!state.activeNpc) return q;
  return "对" + state.activeNpc.prefix + "说：" + q;
}

async function postChat(query) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      conversation_id: state.conversationId,
      user: clientId
    })
  });
  let data = {};
  try { data = await res.json(); } catch (_) { data = {}; }
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  if (!data.answer) throw new Error("empty answer");
  return data;
}

function parseFooter(footer) {
  const out = { clues: {} };
  if (!footer) return out;
  const tide = footer.match(/潮时\s*([\d.]+)\s*m/);
  if (tide) out.tide = parseFloat(tide[1]);
  for (const d of CLUES) {
    const m = footer.match(new RegExp(d.mark + "\\s*([✓×])"));
    if (m) out.clues[d.key] = m[1] === "✓";
  }
  const trust = footer.match(/信任\s*纪\s*(\d+)\s*塞恩\s*(\d+)\s*叶\s*(\d+)/);
  if (trust) out.trust = { archivist: +trust[1], sean: +trust[2], ye: +trust[3] };
  return out;
}

function splitAnswer(answer) {
  const raw = String(answer || "").replace(/\r\n?/g, "\n");
  let footer = null;
  let ending = null;
  const em = raw.match(/【结局\s*·\s*([^】]+)】/);
  if (em) ending = em[1].trim();
  const kept = [];
  for (const line of raw.split("\n")) {
    const t = line.trim();
    if (/^潮时\s*[\d.]+\s*m\s*｜/.test(t)) { footer = t; continue; }
    if (/^结局：/.test(t)) {
      const e = t.replace(/^结局：/, "").split("｜")[0].trim();
      if (e) ending = e;
      continue;
    }
    if (t === "———") continue;
    if (/^【结局\s*·/.test(t)) continue;
    kept.push(line);
  }
  const text = kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  return { text, footer, ending };
}

function applyState(parsed, options = {}) {
  const silent = !!options.silent;
  const info = parseFooter(parsed.footer);
  const newClues = [];
  for (const d of CLUES) {
    if (info.clues[d.key] === true && !state.clues[d.key]) newClues.push(d);
    if (info.clues[d.key] === true) state.clues[d.key] = true;
  }
  if (Number.isFinite(info.tide)) state.tide = info.tide;
  if (info.trust) state.trust = info.trust;
  if (parsed.ending) state.ending = parsed.ending;
  renderHud();
  if (!silent) {
    for (const d of newClues) toast("获得线索 · " + d.label);
  }
}

async function sendQuery(raw, echoText) {
  if (state.busy || state.over || state.ending) return;
  const query = composeQuery(raw);
  if (!query) return;
  state.lastQuery = query;
  const meta = isMeta(query);
  if (!meta) {
    playerEcho.textContent = echoText || raw;
    playerEcho.classList.remove("is-hidden");
  } else {
    playerEcho.classList.add("is-hidden");
  }
  setBusy(true);
  try {
    const data = await postChat(query);
    state.conversationId = data.conversation_id || state.conversationId;
    const parsed = splitAnswer(data.answer);
    setBusy(false);
    if (!meta) state.actionCount += 1;
    if (state.activeNpc && state.activeNpc.id === "ye" && !meta) state.yeContacted = true;
    applyState(parsed);
    const text = parsed.text || "（档案里没有回应。）";
    const speed = parsed.ending ? 19 : 31;
    typewrite(text, speed, () => {
      if (parsed.ending) {
        setTimeout(() => showEnding(parsed.ending, text), 650);
      }
    });
    if (parsed.ending) {
      askInput.disabled = true;
      sendBtn.disabled = true;
      for (const b of chipsEl.querySelectorAll("button")) b.disabled = true;
    }
  } catch (err) {
    setBusy(false);
    applyState({ footer: null, ending: null }, { silent: true });
    dialogueText.classList.remove("thinking");
    dialogueText.textContent =
      "（译名台没有回应。）\n\n" +
      "检查本地游戏服务是否还在运行：python3 game/server.py\n" +
      "错误：" + (err && err.message ? err.message : "unknown");
    state.typing = false;
    dialogueText.classList.remove("typing");
    chipsEl.textContent = "";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "chip action";
    retry.textContent = "重试刚才的话";
    retry.addEventListener("click", () => sendQuery(state.lastQuery, state.lastQuery));
    chipsEl.append(retry);
  }
}

/* --------------------------------------------------------------- screens */

async function startNight() {
  if (state.busy) return;
  state.conversationId = "";
  state.busy = true;
  state.startFailed = false;
  titleScreen.classList.add("is-hidden");
  prologue.classList.add("is-hidden");
  endingScreen.classList.add("is-hidden");
  notebook.classList.remove("open");
  state.notebookOpen = false;
  setPrompt(null);
  showLoading("档案员在点灯……");
  try {
    const data = await postChat("开始调查");
    state.conversationId = data.conversation_id || "";
    const parsed = splitAnswer(data.answer);
    applyState(parsed, { silent: true });
    prologueText.textContent = parsed.text || "（档案馆里没有人回答。）";
    prologueBtn.textContent = "进入档案馆";
    prologue.classList.remove("is-hidden");
    hideLoading();
    state.started = false;
  } catch (err) {
    hideLoading();
    state.startFailed = true;
    prologueText.textContent =
      "档案室没有回应。\n\n" +
      "确认 Dify 与本地游戏服务都在运行：\n" +
      "  python3 game/server.py\n\n" +
      "错误：" + (err && err.message ? err.message : "unknown");
    prologueBtn.textContent = "重试";
    prologue.classList.remove("is-hidden");
  } finally {
    state.busy = false;
  }
}

function enterFromPrologue() {
  if (!prologue.classList.contains("is-hidden")) {
    if (state.startFailed) {
      startNight();
      return;
    }
    prologue.classList.add("is-hidden");
    state.started = true;
    keys.clear();
    stage.focus();
    toast("潮时 2.40 m ｜ 找到纪、塞恩和叶的手机");
  }
}

function showEnding(title, text) {
  state.over = true;
  state.dialogueOpen = false;
  state.activeNpc = null;
  dialogue.classList.add("is-hidden");
  setPrompt(null);
  const clean = String(text || "")
    .replace(/^《[^》]+》\s*\n?/, "")
    .replace(/【结局\s*·[^】]*】/g, "")
    .trim();
  endingTitle.textContent = title || state.ending || "这个夜晚结束了";
  endingText.textContent = clean || "潮水退去，档案里只剩下空白。";
  const found = CLUES.filter((d) => state.clues[d.key]).length;
  endingStats.textContent = "";
  const add = (label, value) => {
    const span = document.createElement("span");
    span.append(document.createTextNode(label + " "));
    const b = document.createElement("b");
    b.textContent = value;
    span.append(b);
    endingStats.append(span);
  };
  add("潮时", state.tide.toFixed(2) + " m");
  add("线索", found + " / 4");
  add("信任", "纪" + state.trust.archivist + " · 塞恩" + state.trust.sean + " · 叶" + state.trust.ye);
  add("动作", String(state.actionCount));
  endingScreen.classList.remove("is-hidden");
}

function resetState() {
  state.over = false;
  state.started = false;
  state.busy = false;
  state.typing = false;
  state.dialogueOpen = false;
  state.activeNpc = null;
  state.nearId = null;
  state.notebookOpen = false;
  state.startFailed = false;
  state.conversationId = "";
  state.tide = 2.4;
  state.clues = { wall_height: false, prefix_low: false, deleted_category: false, roster: false };
  state.trust = { archivist: 0, sean: 0, ye: 0 };
  state.ending = "";
  state.actionCount = 0;
  state.yeContacted = false;
  state.lastQuery = "";
  player.x = 480;
  player.y = 538;
  player.dir = "down";
  player.moving = false;
  player.anim = 0;
  keys.clear();
  playerEcho.textContent = "";
  playerEcho.classList.add("is-hidden");
  dialogue.classList.add("is-hidden");
  dialogueText.textContent = "";
  notebook.classList.remove("open");
  recordScreen.classList.add("is-hidden");
  endingScreen.classList.add("is-hidden");
  prologue.classList.add("is-hidden");
  setPrompt(null);
  renderHud();
}

async function restartGame() {
  if (state.busy) return;
  hideLoading();
  resetState();
  showLoading("夜色重新开始……");
  await startNight();
}

function toggleNotebook(force) {
  if (!state.started && !state.over) return;
  const open = typeof force === "boolean" ? force : !state.notebookOpen;
  state.notebookOpen = open;
  notebook.classList.toggle("open", open);
  if (open) {
    keys.clear();
    player.moving = false;
    setPrompt(null);
    renderNotebook();
  } else {
    updatePrompt();
  }
}

let recordBusy = false;

async function openRecord() {
  if (recordBusy) return;
  recordBusy = true;
  recordScreen.classList.remove("is-hidden");
  recordText.textContent = "正在调阅……";
  try {
    const data = await postChat("上次我们查到哪了？");
    state.conversationId = data.conversation_id || state.conversationId;
    const parsed = splitAnswer(data.answer);
    applyState(parsed, { silent: true });
    recordText.textContent = parsed.text || "（夜间记录是空的。）";
  } catch (err) {
    recordText.textContent = "调阅失败：" + (err && err.message ? err.message : "unknown");
  } finally {
    recordBusy = false;
  }
}

/* ----------------------------------------------------------------- input */

function nearestTarget() {
  let best = null;
  let bestD = Infinity;
  for (const npc of NPCS) {
    const d = Math.hypot(player.x - npc.anchor.x, player.y - npc.anchor.y);
    if (d < npc.radius && d < bestD) { best = npc; bestD = d; }
  }
  return best;
}

function blocked(x, y) {
  if (x < BOUNDS.x1 || x > BOUNDS.x2 || y < BOUNDS.y1 || y > BOUNDS.y2) return true;
  for (const r of SOLIDS) {
    if (x > r.x - 10 && x < r.x + r.w + 10 && y > r.y - 4 && y < r.y + r.h + 10) return true;
  }
  for (const s of NPC_SOLIDS) {
    const dx = x - s.x;
    const dy = y - s.y;
    if (dx * dx + dy * dy < (s.r + 8) * (s.r + 8)) return true;
  }
  return false;
}

function movePlayer(dt) {
  let mx = 0;
  let my = 0;
  if (keys.has("KeyA") || keys.has("ArrowLeft")) mx -= 1;
  if (keys.has("KeyD") || keys.has("ArrowRight")) mx += 1;
  if (keys.has("KeyW") || keys.has("ArrowUp")) my -= 1;
  if (keys.has("KeyS") || keys.has("ArrowDown")) my += 1;
  if (!mx && !my) {
    player.moving = false;
    player.anim += dt * 2.2;
    return;
  }
  const len = Math.hypot(mx, my);
  mx /= len;
  my /= len;
  const speed = 168;
  const nx = player.x + mx * speed * dt;
  if (!blocked(nx, player.y)) player.x = nx;
  const ny = player.y + my * speed * dt;
  if (!blocked(player.x, ny)) player.y = ny;
  if (Math.abs(mx) > Math.abs(my) + 0.01) player.dir = mx > 0 ? "right" : "left";
  else if (Math.abs(my) > Math.abs(mx) + 0.01) player.dir = my > 0 ? "down" : "up";
  else player.dir = my > 0 ? "down" : "up";
  player.moving = true;
  player.anim += dt * 11;
}

window.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName) || "";
  const inField = tag === "INPUT" || tag === "TEXTAREA";

  if (!titleScreen.classList.contains("is-hidden")) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      startNight();
    }
    return;
  }

  if (!prologue.classList.contains("is-hidden")) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      enterFromPrologue();
    }
    return;
  }

  if (e.key === "Escape") {
    if (!recordScreen.classList.contains("is-hidden")) { recordScreen.classList.add("is-hidden"); return; }
    if (state.notebookOpen) { toggleNotebook(false); return; }
    if (state.dialogueOpen && !state.busy) { closeDialogue(); return; }
    return;
  }

  if (inField) return;
  if (!recordScreen.classList.contains("is-hidden")) return;

  if ((e.key === "n" || e.key === "N" || e.key === "m" || e.key === "M") && !state.over && !state.dialogueOpen) {
    e.preventDefault();
    toggleNotebook();
    return;
  }

  if (state.typing && (e.key === " " || e.key === "Enter")) {
    e.preventDefault();
    finishTyping();
    return;
  }

  if (state.dialogueOpen) return;
  if (!state.started || state.over) return;

  if (e.key === "e" || e.key === "E" || e.key === "Enter" || e.key === " ") {
    const near = nearestTarget();
    if (near) {
      e.preventDefault();
      openDialogue(near);
    }
    return;
  }

  const moveKeys = ["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
  if (moveKeys.includes(e.code)) {
    e.preventDefault();
    keys.add(e.code);
  }
});

window.addEventListener("keyup", (e) => {
  keys.delete(e.code);
});
window.addEventListener("blur", () => keys.clear());

stage.addEventListener("pointerdown", () => {
  if (state.started && !state.dialogueOpen && !state.notebookOpen && !state.over) stage.focus();
});

askForm.addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.busy || state.over) return;
  const raw = askInput.value.trim();
  if (!raw) return;
  askInput.value = "";
  if (state.typing) finishTyping();
  sendQuery(raw, raw);
});

dialogueScroll.addEventListener("pointerdown", () => {
  if (state.typing) finishTyping();
});

closeBtn.addEventListener("click", closeDialogue);
$("startBtn").addEventListener("click", startNight);
prologueBtn.addEventListener("click", enterFromPrologue);
$("restartBtn").addEventListener("click", restartGame);
$("notebookBtn").addEventListener("click", () => toggleNotebook(true));
$("missionBtn").addEventListener("click", () => toggleNotebook(true));
$("notebookClose").addEventListener("click", () => toggleNotebook(false));
$("notebookDone").addEventListener("click", () => toggleNotebook(false));
$("recordBtn").addEventListener("click", openRecord);
$("recordClose").addEventListener("click", () => recordScreen.classList.add("is-hidden"));
$("endingNoteBtn").addEventListener("click", () => toggleNotebook(true));

/* ---------------------------------------------------------------- drawing */

function drawRoom(t) {
  fillRect(0, 0, W, H, "#080d13");

  const wallGrad = ctx.createLinearGradient(0, 0, 0, 200);
  wallGrad.addColorStop(0, "#0a121a");
  wallGrad.addColorStop(0.7, "#101b25");
  wallGrad.addColorStop(1, "#0d161f");
  ctx.fillStyle = wallGrad;
  ctx.fillRect(0, 0, W, 194);

  for (let x = 20; x < W; x += 78) {
    line(x, 0, x, 188, "rgba(0,0,0,0.22)", 1);
  }
  line(0, 188, W, 188, "rgba(198,154,88,0.18)", 1);

  fillRect(0, 194, 64, 372, "#0a1118");
  fillRect(896, 194, 64, 372, "#0a1118");
  line(64, 194, 64, 566, "rgba(198,154,88,0.12)");
  line(896, 194, 896, 566, "rgba(198,154,88,0.12)");

  // floor planks
  const floorTop = 194;
  const floorBottom = 566;
  fillRect(64, floorTop, 832, floorBottom - floorTop, "#18130f");
  const plankH = 30;
  let row = 0;
  for (let y = floorTop; y < floorBottom; y += plankH, row++) {
    ctx.fillStyle = row % 2 ? "rgba(255,255,255,0.018)" : "rgba(0,0,0,0.06)";
    ctx.fillRect(64, y, 832, plankH - 1);
    line(64, y + plankH - 1, 896, y + plankH - 1, "rgba(0,0,0,0.38)", 1);
    const offset = (row % 3) * 92;
    for (let x = 64 + offset; x < 896; x += 184) {
      line(x, y + 2, x, y + plankH - 3, "rgba(0,0,0,0.22)", 1);
    }
    for (let i = 0; i < 2; i++) {
      const gy = y + 6 + rand(row * 9 + i) * (plankH - 12);
      line(64 + rand(row * 5 + i) * 500, gy, 64 + 300 + rand(row * 7 + i) * 520, gy,
        "rgba(255,220,170,0.022)", 1);
    }
  }
  const sheen = ctx.createLinearGradient(0, floorTop, 0, floorTop + 150);
  sheen.addColorStop(0, "rgba(93,140,150,0.12)");
  sheen.addColorStop(1, "rgba(93,140,150,0)");
  ctx.fillStyle = sheen;
  ctx.fillRect(64, floorTop, 832, 150);

  // rug
  fillRect(330, 362, 300, 146, "#341a17");
  ctx.save();
  ctx.strokeStyle = "rgba(198,154,88,0.28)";
  ctx.lineWidth = 2;
  ctx.strokeRect(338, 370, 284, 130);
  ctx.strokeStyle = "rgba(198,154,88,0.12)";
  ctx.lineWidth = 1;
  ctx.strokeRect(348, 380, 264, 110);
  for (let i = 0; i < 5; i++) {
    const x = 392 + i * 44;
    line(x, 392, x + 22, 435, "rgba(198,154,88,0.09)", 1);
    line(x + 22, 435, x, 478, "rgba(198,154,88,0.09)", 1);
  }
  ctx.restore();

  // baseboard
  fillRect(64, 188, 832, 7, "#241b13");
  line(64, 188, 896, 188, "rgba(198,154,88,0.16)");

  // bottom wall + door
  fillRect(0, 566, W, 34, "#080d13");
  fillRect(426, 536, 108, 64, "#160f0b");
  fillRect(434, 544, 92, 56, "#2a1b12");
  ctx.strokeStyle = "rgba(198,154,88,0.2)";
  ctx.strokeRect(442, 552, 76, 38);
  circle(512, 584, 2.5, "rgba(198,154,88,0.75)");
  txt("出口", 480, 528, 9, "rgba(198,154,88,0.55)", "center");

  // windows
  drawWindow(148, 82, 196, 98, t, 0);
  drawWindow(378, 82, 178, 98, t, 1);
  drawPlaque();
  drawClock();

  // shelves
  drawShelves();
}

function drawWindow(x, y, w, h, t, seed) {
  fillRect(x - 7, y - 7, w + 14, h + 14, "#070b0f");
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, "#071521");
  g.addColorStop(0.55, "#0d2430");
  g.addColorStop(1, "#102c37");
  ctx.fillStyle = g;
  ctx.fillRect(x, y, w, h);

  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();

  // distant city
  for (let i = 0; i < 16; i++) {
    const bx = x + rand(seed * 31 + i) * w;
    const bw = 8 + rand(seed * 17 + i) * 18;
    const bh = 12 + rand(seed * 7 + i) * 28;
    ctx.fillStyle = "rgba(4,10,14,0.72)";
    ctx.fillRect(bx, y + h - 20 - bh, bw, bh);
    if (rand(seed * 53 + i) > 0.55) {
      ctx.fillStyle = "rgba(224,164,92,0.4)";
      ctx.fillRect(bx + 2, y + h - 22 - bh, 2, 2);
    }
  }
  // waterline
  const waterH = 9 + (state.tide - 2.4) * 26;
  const wy = y + h - waterH;
  const wg = ctx.createLinearGradient(0, wy, 0, y + h);
  wg.addColorStop(0, "rgba(74,126,136,0.42)");
  wg.addColorStop(1, "rgba(8,20,26,0.85)");
  ctx.fillStyle = wg;
  ctx.fillRect(x, wy, w, waterH);
  for (let i = 0; i < 6; i++) {
    const wx = x + ((t * 9 + i * 37) % w);
    line(wx, wy + 2 + (i % 2), wx + 9, wy + 2 + (i % 2), "rgba(160,210,210,0.18)", 1);
  }

  // rain
  for (let i = 0; i < 26; i++) {
    const rx = x + rand(seed * 101 + i) * w;
    const ry = y + ((t * (70 + rand(i) * 50) + rand(seed * 13 + i) * h * 3) % h);
    line(rx, ry, rx - 2, ry + 8 + rand(i + 3) * 7, "rgba(150,195,205,0.16)", 1);
  }
  ctx.restore();

  ctx.strokeStyle = "rgba(198,154,88,0.32)";
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, w, h);
  line(x + w / 2, y, x + w / 2, y + h, "rgba(198,154,88,0.26)", 2);
  line(x, y + h * 0.46, x + w, y + h * 0.46, "rgba(198,154,88,0.26)", 2);
  ctx.strokeStyle = "rgba(0,0,0,0.55)";
  ctx.lineWidth = 1;
  ctx.strokeRect(x - 3, y - 3, w + 6, h + 6);
}

function drawPlaque() {
  const x = 602, y = 108, w = 130, h = 54;
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.6)";
  ctx.shadowBlur = 10;
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, "#8a6a3b");
  g.addColorStop(0.45, "#c69a58");
  g.addColorStop(1, "#6e512b");
  rr(x, y, w, h, 3);
  ctx.fillStyle = g;
  ctx.fill();
  ctx.restore();
  ctx.strokeStyle = "rgba(20,14,8,0.65)";
  ctx.lineWidth = 2;
  rr(x + 3, y + 3, w - 6, h - 6, 2);
  ctx.stroke();
  for (const [sx, sy] of [[x + 7, y + 7], [x + w - 7, y + 7], [x + 7, y + h - 7], [x + w - 7, y + h - 7]]) {
    circle(sx, sy, 1.7, "rgba(30,20,10,0.7)");
  }
  txt("潮位基准", x + w / 2, y + 15, 9, "rgba(32,22,10,0.75)", "center");
  txt("2.90 m", x + w / 2, y + 35, 21, "#23180b", "center", "middle", SERIF, 600);
}

function drawClock() {
  const cx = 810, cy = 132, r = 30;
  circle(cx, cy, r + 4, "#070b0f");
  circle(cx, cy, r, "#b9a77f");
  circle(cx, cy, r - 3, "#d8c9a7");
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2 - Math.PI / 2;
    const x1 = cx + Math.cos(a) * (r - 7);
    const y1 = cy + Math.sin(a) * (r - 7);
    const x2 = cx + Math.cos(a) * (r - 4);
    const y2 = cy + Math.sin(a) * (r - 4);
    line(x1, y1, x2, y2, "rgba(40,30,18,0.55)", 1);
  }
  const minutes = (10 + state.actionCount * 3 + Math.floor(state.tide * 10) % 3) % 60;
  const minuteA = (minutes / 60) * Math.PI * 2 - Math.PI / 2;
  const hourA = (((23 % 12) + minutes / 60) / 12) * Math.PI * 2 - Math.PI / 2;
  line(cx, cy, cx + Math.cos(hourA) * 13, cy + Math.sin(hourA) * 13, "#2c2115", 2.5);
  line(cx, cy, cx + Math.cos(minuteA) * 20, cy + Math.sin(minuteA) * 20, "#2c2115", 1.5);
  circle(cx, cy, 2.2, "#7b3b2a");
}

function drawShelves() {
  const x = 72, y = 208, w = 46, h = 258;
  fillRect(x - 4, y - 4, w + 8, h + 8, "#1a120c");
  fillRect(x, y, w, h, "#0f0c09");
  const rows = 4;
  for (let r = 0; r < rows; r++) {
    const sy = y + 8 + r * (h - 16) / rows;
    const sh = (h - 16) / rows - 6;
    let bx = x + 4;
    let i = 0;
    while (bx < x + w - 5) {
      const bw = 3 + rand(r * 31 + i) * 5;
      const bh = sh * (0.62 + rand(r * 17 + i) * 0.3);
      const colors = ["#5b3428", "#3d514a", "#6b5730", "#41394d", "#4a2a2d", "#2c4351"];
      fillRect(bx, sy + sh - bh, bw, bh, colors[Math.floor(rand(r * 7 + i) * colors.length)]);
      line(bx, sy + sh - bh + 3, bx + bw, sy + sh - bh + 3, "rgba(198,154,88,0.18)", 1);
      bx += bw + 1.5;
      i++;
    }
    fillRect(x, sy + sh, w, 3, "#24170f");
  }
  ctx.strokeStyle = "rgba(198,154,88,0.18)";
  ctx.strokeRect(x, y, w, h);
}

function drawDeskJi() {
  const x = 120, y = 208, w = 250, h = 72;
  fillRect(x + 7, y + 9, w, h, "rgba(0,0,0,0.35)");
  fillRect(x, y, w, h, "#3a2719");
  fillRect(x, y, w, 9, "#543a24");
  fillRect(x, y + h - 16, w, 16, "#2a1b11");
  line(x + 4, y + h - 16, x + w - 4, y + h - 16, "rgba(198,154,88,0.18)");
  // ledger + folders
  ctx.save();
  ctx.translate(x + 58, y + 34);
  ctx.rotate(-0.05);
  fillRect(-30, -18, 60, 36, "#cbbd9d");
  fillRect(-30, -18, 60, 3, "#8f8065");
  for (let i = 0; i < 5; i++) line(-22, -10 + i * 6, 20, -10 + i * 6, "rgba(60,48,32,0.35)", 1);
  ctx.restore();
  ctx.save();
  ctx.translate(x + 116, y + 31);
  ctx.rotate(0.08);
  fillRect(-26, -16, 52, 32, "#b9a985");
  fillRect(-26, -16, 52, 2, "#7b6c51");
  ctx.restore();
  // paper stack
  for (let i = 0; i < 4; i++) {
    fillRect(x + 176 + i, y + 20 + i * 2, 38, 26, i === 3 ? "#d3c5a5" : "#bcae8e");
  }
  // ink pot
  circle(x + 224, y + 58, 6, "#14100c");
  circle(x + 224, y + 56, 4, "#2b241c");
  // plaque
  fillRect(x + 154, y + 58, 44, 10, "#7b5a30");
  txt("档案", x + 176, y + 63, 6, "rgba(25,16,8,0.8)", "center");
  drawLamp(x + 222, y + 12, 0.85);
}

function drawDeskSean() {
  const x = 600, y = 204, w = 290, h = 72;
  fillRect(x + 7, y + 9, w, h, "rgba(0,0,0,0.35)");
  fillRect(x, y, w, h, "#3b281a");
  fillRect(x, y, w, 9, "#563b25");
  fillRect(x, y + h - 16, w, 16, "#291a10");
  line(x + 4, y + h - 16, x + w - 4, y + h - 16, "rgba(198,154,88,0.18)");
  for (let s = 0; s < 3; s++) {
    for (let i = 0; i < 6; i++) {
      fillRect(x + 24 + s * 42 + i, y + 26 - s * 4 + i * 1.5, 36, 22, i === 5 ? "#d0c1a0" : "#b3a585");
    }
  }
  // stamp and pad
  fillRect(x + 196, y + 40, 20, 12, "#211a15");
  fillRect(x + 200, y + 30, 12, 12, "#3a2b20");
  circle(x + 206, y + 27, 5, "#54382a");
  fillRect(x + 172, y + 52, 18, 10, "#5d2f2a");
  // form tray
  fillRect(x + 226, y + 44, 46, 18, "#1d1712");
  fillRect(x + 230, y + 48, 38, 10, "#c8b997");
  drawLamp(x + 256, y + 10, 0.75);
}

function drawLamp(x, y, scale) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(scale, scale);
  fillRect(-3, 6, 6, 26, "#2b2119");
  ctx.fillStyle = "#4b3825";
  ctx.beginPath();
  ctx.moveTo(-16, 6);
  ctx.lineTo(16, 6);
  ctx.lineTo(11, -4);
  ctx.lineTo(-11, -4);
  ctx.closePath();
  ctx.fill();
  fillRect(-12, 5, 24, 3, "#c69a58");
  ctx.restore();
}

function drawLocker() {
  const x = 700, y = 426, w = 118, h = 104;
  fillRect(x + 7, y + 9, w, h, "rgba(0,0,0,0.4)");
  fillRect(x, y, w, h, "#26332f");
  fillRect(x + 3, y + 3, w - 6, h - 6, "#2f403a");
  line(x + w / 2, y + 6, x + w / 2, y + h - 6, "rgba(0,0,0,0.35)", 2);
  for (let i = 0; i < 5; i++) {
    fillRect(x + 10, y + 14 + i * 5, 36, 2, "rgba(0,0,0,0.28)");
    fillRect(x + 72, y + 14 + i * 5, 36, 2, "rgba(0,0,0,0.28)");
  }
  fillRect(x + 48, y + 52, 5, 12, "#b7a273");
  fillRect(x + 65, y + 52, 5, 12, "#b7a273");
  ctx.strokeStyle = "rgba(198,154,88,0.22)";
  ctx.strokeRect(x, y, w, h);
  // sticky note
  ctx.save();
  ctx.translate(x + 92, y + 76);
  ctx.rotate(0.08);
  fillRect(-13, -8, 26, 16, "#c9b98f");
  txt("旧桥", 0, 0, 6, "rgba(40,30,18,0.8)", "center");
  ctx.restore();
  // phone on top
  const px = x + 62, py = y - 8;
  ctx.save();
  ctx.translate(px, py);
  ctx.rotate(-0.16);
  fillRect(-9, -14, 18, 28, "#101418");
  fillRect(-7, -12, 14, 24, "#17363e");
  ctx.fillStyle = "rgba(121,185,207,0.55)";
  ctx.fillRect(-7, -12, 14, 24);
  fillRect(-7, -12, 14, 3, "rgba(255,255,255,0.15)");
  ctx.restore();
}

function drawNameTag(label, x, y, color) {
  ctx.save();
  ctx.font = "10px " + SANS;
  const w = ctx.measureText(label).width + 14;
  roundRectFill(x - w / 2, y - 9, w, 18, 3, "rgba(4,8,12,0.7)");
  ctx.strokeStyle = "rgba(198,154,88,0.22)";
  ctx.lineWidth = 1;
  rr(x - w / 2, y - 9, w, 18, 3);
  ctx.stroke();
  txt(label, x, y + 0.5, 10, color, "center", "middle", SANS);
  ctx.restore();
}

function drawJi(t) {
  const x = 250;
  const y = 338 + Math.sin(t * 1.6) * 1.2;
  shadow(x, 338, 20, 6);
  // legs
  fillRect(x - 10, y - 20, 7, 20, "#0d151b");
  fillRect(x + 3, y - 20, 7, 20, "#0d151b");
  // coat
  roundRectFill(x - 16, y - 62, 32, 44, 7, "#17343b");
  roundRectFill(x - 13, y - 58, 26, 36, 5, "#1d4149");
  line(x, y - 56, x, y - 24, "rgba(0,0,0,0.28)", 1);
  // arms folded
  roundRectFill(x - 18, y - 48, 8, 24, 4, "#142c32");
  roundRectFill(x + 10, y - 48, 8, 24, 4, "#142c32");
  // folder
  ctx.save();
  ctx.translate(x + 1, y - 43);
  ctx.rotate(-0.08);
  fillRect(-15, -10, 30, 20, "#cbbd9d");
  fillRect(-15, -10, 30, 2, "#8f8065");
  line(-10, -4, 9, -4, "rgba(60,48,32,0.3)", 1);
  line(-10, 1, 9, 1, "rgba(60,48,32,0.3)", 1);
  ctx.restore();
  // head
  circle(x, y - 71, 10, "#d7ad88");
  // hair
  ctx.fillStyle = "#171313";
  ctx.beginPath();
  ctx.arc(x, y - 74, 10.5, Math.PI * 0.95, Math.PI * 2.02);
  ctx.fill();
  fillRect(x - 10, y - 75, 5, 10, "#171313");
  // face
  fillRect(x - 5, y - 72, 2, 2, "#2a1d16");
  fillRect(x + 3, y - 72, 2, 2, "#2a1d16");
  line(x - 2, y - 66, x + 2, y - 66, "rgba(90,50,40,0.6)", 1);
  // collar + pin
  fillRect(x - 3, y - 63, 6, 3, "#0f2429");
  circle(x + 6, y - 56, 1.6, "#c69a58");
  drawNameTag("纪", x, y - 92, "#a7d1d4");
}

function drawSean(t) {
  const x = 750;
  const y = 334 + Math.sin(t * 1.1 + 1) * 1.1;
  shadow(x, 334, 23, 7);
  fillRect(x - 12, y - 21, 9, 21, "#1a120d");
  fillRect(x + 3, y - 21, 9, 21, "#1a120d");
  roundRectFill(x - 19, y - 65, 38, 46, 8, "#4a3527");
  roundRectFill(x - 15, y - 60, 30, 36, 5, "#5a4230");
  // shirt + tie
  fillRect(x - 7, y - 60, 14, 20, "#c9bda3");
  ctx.fillStyle = "#2f2a25";
  ctx.beginPath();
  ctx.moveTo(x, y - 58);
  ctx.lineTo(x + 4, y - 50);
  ctx.lineTo(x, y - 34);
  ctx.lineTo(x - 4, y - 50);
  ctx.closePath();
  ctx.fill();
  // arms
  roundRectFill(x - 22, y - 52, 8, 26, 4, "#43301f");
  roundRectFill(x + 14, y - 52, 8, 26, 4, "#43301f");
  // stamp in right hand
  fillRect(x + 17, y - 31, 7, 10, "#231b15");
  fillRect(x + 15, y - 35, 11, 5, "#4b3526");
  // head
  circle(x, y - 74, 11, "#cfa77f");
  // hair
  ctx.fillStyle = "#1a1512";
  ctx.beginPath();
  ctx.arc(x, y - 77, 11.3, Math.PI * 0.92, Math.PI * 2.05);
  ctx.fill();
  fillRect(x - 11, y - 78, 5, 9, "#1a1512");
  fillRect(x + 7, y - 78, 4, 9, "#1a1512");
  // glasses
  ctx.strokeStyle = "rgba(220,210,180,0.75)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.arc(x - 4.5, y - 75, 3.4, 0, Math.PI * 2);
  ctx.arc(x + 5, y - 75, 3.4, 0, Math.PI * 2);
  ctx.stroke();
  line(x - 1, y - 75, x + 1.5, y - 75, "rgba(220,210,180,0.65)", 1);
  fillRect(x - 5.5, y - 76, 1.6, 1.6, "#2a1d16");
  fillRect(x + 4, y - 76, 1.6, 1.6, "#2a1d16");
  line(x - 3, y - 67, x + 3, y - 67, "rgba(80,45,35,0.55)", 1);
  // brass button
  circle(x + 11, y - 48, 1.5, "#b98d4d");
  drawNameTag("塞恩", x, y - 96, "#e2b87c");
}

function drawYe(t) {
  const x = 688;
  const baseY = 492;
  const pulse = 0.36 + 0.08 * Math.sin(t * 2.1);
  ctx.save();
  ctx.globalAlpha = pulse;
  ctx.globalCompositeOperation = "lighter";
  radial(x, baseY - 34, 54, "rgba(80,170,190,0.22)");
  ctx.globalCompositeOperation = "source-over";
  // kneeling silhouette
  ctx.fillStyle = "rgba(110,190,205,0.65)";
  ctx.beginPath();
  ctx.ellipse(x, baseY - 14, 18, 9, 0, 0, Math.PI * 2);
  ctx.fill();
  roundRectFill(x - 12, baseY - 46, 24, 30, 7, "rgba(110,190,205,0.6)");
  circle(x, baseY - 56, 9, "rgba(130,205,215,0.72)");
  ctx.strokeStyle = "rgba(150,225,235,0.65)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(x, baseY - 56, 9.5, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();

  // scanline shimmer
  ctx.save();
  ctx.globalAlpha = 0.18 + 0.08 * Math.sin(t * 4);
  for (let i = 0; i < 5; i++) {
    const yy = baseY - 68 + ((t * 16 + i * 13) % 62);
    line(x - 15, yy, x + 15, yy, "rgba(121,185,207,0.5)", 1);
  }
  ctx.restore();
  drawNameTag("叶（录音）", x, baseY - 82, "#9ed5e2");
}

function drawPlayer(t) {
  const x = player.x;
  const y = player.y + (player.moving ? Math.abs(Math.sin(player.anim)) * 1.4 : Math.sin(t * 1.6) * 0.7);
  shadow(x, player.y, 14, 5);
  const swing = player.moving ? Math.sin(player.anim) * 4 : 0;
  // legs
  fillRect(x - 8, y - 22 + Math.max(0, swing), 6, 21, "#111821");
  fillRect(x + 2, y - 22 + Math.max(0, -swing), 6, 21, "#111821");
  fillRect(x - 9, y - 3 + Math.max(0, swing), 7, 4, "#090d12");
  fillRect(x + 2, y - 3 + Math.max(0, -swing), 7, 4, "#090d12");
  // coat
  roundRectFill(x - 13, y - 55, 26, 35, 5, "#25323f");
  roundRectFill(x - 10, y - 51, 20, 28, 4, "#2d3c4b");
  // satchel
  fillRect(x + 9, y - 40, 9, 13, "#5f4229");
  line(x + 4, y - 50, x + 13, y - 38, "rgba(198,154,88,0.6)", 1.5);
  // arms
  roundRectFill(x - 16, y - 50 + swing * 0.4, 6, 20, 3, "#20303c");
  roundRectFill(x + 10, y - 50 - swing * 0.4, 6, 20, 3, "#20303c");
  // scarf
  roundRectFill(x - 9, y - 62, 18, 7, 3, "#b5763d");
  fillRect(x - 2, y - 56, 5, 14, "#9a5f33");
  // head
  circle(x, y - 69, 9.5, "#d8b08c");
  // hair
  ctx.fillStyle = "#171313";
  if (player.dir === "up") {
    ctx.beginPath();
    ctx.arc(x, y - 71, 10, 0, Math.PI * 2);
    ctx.fill();
  } else {
    ctx.beginPath();
    ctx.arc(x, y - 72, 10, Math.PI * 0.92, Math.PI * 2.08);
    ctx.fill();
    if (player.dir === "left") fillRect(x - 10, y - 74, 6, 11, "#171313");
    else if (player.dir === "right") fillRect(x + 4, y - 74, 6, 11, "#171313");
    else {
      fillRect(x - 10, y - 74, 4, 10, "#171313");
      fillRect(x + 6, y - 74, 4, 10, "#171313");
    }
  }
  // face
  if (player.dir === "down") {
    fillRect(x - 4, y - 69, 2, 2, "#2a1d16");
    fillRect(x + 3, y - 69, 2, 2, "#2a1d16");
  } else if (player.dir === "left") {
    fillRect(x - 6, y - 69, 2, 2, "#2a1d16");
  } else if (player.dir === "right") {
    fillRect(x + 4, y - 69, 2, 2, "#2a1d16");
  }
  // badge
  circle(x - 6, y - 44, 1.6, "#c69a58");
}

function drawGlows(t) {
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  const flick = 0.82 + 0.18 * Math.sin(t * 7.3) * Math.sin(t * 2.1);
  radial(342, 222, 92, "rgba(224,164,92," + (0.14 * flick).toFixed(3) + ")");
  radial(856, 218, 86, "rgba(224,164,92," + (0.12 * flick).toFixed(3) + ")");
  radial(762, 418, 58, "rgba(90,190,210," + (0.16 + 0.04 * Math.sin(t * 3)).toFixed(3) + ")");
  radial(688, 452, 70, "rgba(80,170,190,0.07)");
  ctx.restore();
}

function drawDust(t) {
  ctx.save();
  for (let i = 0; i < 22; i++) {
    const x = 150 + rand(i * 7) * 660 + Math.sin(t * 0.25 + i) * 12;
    const y = 210 + ((rand(i * 13) * 320 + t * 5) % 310);
    const a = 0.05 + 0.05 * rand(i * 3);
    circle(x, y, 0.8 + rand(i) * 1.1, "rgba(230,210,170," + a.toFixed(3) + ")");
  }
  ctx.restore();
}

function drawVignette() {
  const g = ctx.createRadialGradient(480, 300, 220, 480, 300, 620);
  g.addColorStop(0, "rgba(0,0,0,0)");
  g.addColorStop(0.72, "rgba(0,0,0,0.16)");
  g.addColorStop(1, "rgba(0,0,0,0.62)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  const top = ctx.createLinearGradient(0, 0, 0, 120);
  top.addColorStop(0, "rgba(0,0,0,0.45)");
  top.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = top;
  ctx.fillRect(0, 0, W, 120);
}

function drawNearHighlight(t) {
  if (!state.nearId) return;
  const npc = NPC_BY_ID[state.nearId];
  if (!npc) return;
  const a = 0.35 + 0.2 * Math.sin(t * 4);
  ctx.save();
  ctx.strokeStyle = "rgba(224,164,92," + a.toFixed(3) + ")";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.ellipse(npc.x, npc.y - 2, 24, 9, 0, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function render(t) {
  ctx.clearRect(0, 0, W, H);
  drawRoom(t);
  drawDeskJi();
  drawDeskSean();
  drawLocker();
  drawJi(t);
  drawSean(t);
  drawYe(t);
  drawPlayer(t);
  drawNearHighlight(t);
  drawGlows(t);
  drawDust(t);
  drawVignette();
}

/* ------------------------------------------------------------------ loop */

let last = performance.now();
function loop(now) {
  const dt = Math.min((now - last) / 1000, 0.05);
  last = now;
  const t = now / 1000;

  const canMove = state.started && !state.dialogueOpen && !state.over &&
    !state.notebookOpen && prologue.classList.contains("is-hidden") &&
    endingScreen.classList.contains("is-hidden");
  if (canMove) movePlayer(dt);
  else player.moving = false;

  updatePrompt();
  render(t);
  requestAnimationFrame(loop);
}

buildHud();
renderHud();
requestAnimationFrame(loop);
