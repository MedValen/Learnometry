/* Learnometry - front end.

   Two design rules run through all of this:

   1. Nothing the student needs is ever off-screen. Instructions, premises, and
      the task itself are restated in the item. Immediate verbal registration is
      often the narrow channel, so "remember what I said a second ago" is a
      trap.

   2. Scoring is three-way, not two-way. "Correct", "correct but needed the cue"
      and "wrong" are different events for a profile with slow lexical retrieval
      and intact reasoning. Collapsing the middle one into "wrong" would
      systematically under-report what you know.
*/

const $  = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const body = await res.json().catch(() => ({ detail: "Server sent a non-JSON response." }));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
};

const state = {
  sources: [],       // {sha, name, kind, ...}
  analysis: null,
  questions: [],
  idx: 0,
  answers: [],       // {qid, given, correct, usedCue, skipped}
  usedCue: false,
  selected: null,
  answered: false,
  // --- persistence wiring ---
  storedIds: {},     // local question id -> durable bank id
  sessionId: null,
  confidence: "unsure",
  shownAt: 0,        // for rt_ms: recorded, never scored (see mastery.py)
};

/* ============================ navigation ==============================
   Five destinations, each holding the screens that belong to one job. The
   sixteen views underneath are unchanged: this table says where each one
   lives, and everything else - the bar, the sub-bar, the page header, the
   account menu, the URL - is rendered from it. Adding a screen means adding
   a row here, not another button in a drawer. */

const NAV = [
  { id: "home", label: "Home", views: [["today", "Home"]] },
  { id: "study", label: "Study", views: [
    ["quiz", "Practice"],
    ["drills", "Drills"],
    ["sheet", "Study sheet"],
    ["resources", "Find videos"],
  ] },
  { id: "library", label: "Library", views: [
    ["material", "All materials"],
    ["vault", "Images & captures"],
    ["board", "Pinboard"],
  ] },
  { id: "mastery", label: "Mastery", views: [
    ["map", "Overview"],
    ["topics", "Topics"],
    ["weak", "Weaknesses"],
    ["analytics", "Learning patterns"],
  ] },
  { id: "plan", label: "Plan", views: [["plan", "Exams & plan"]] },
];

/* Account-shaped screens. These are jobs you do once and leave, so they get
   the account menu rather than a permanent seat in the navigation. */
const MENU_VIEWS = [
  ["profile", "Profile"],
  ["progress", "Progress & achievements"],
  ["screener", "Screener"],
  ["help", "Help & support"],
];

/* One header per screen. The long explanations that used to open every page
   are kept - they move behind the info toggle, so they are available on the
   first visit and silent on the fiftieth. */
const PAGES = {
  today: { title: "Home", sub: "What to study next, and where you stand." },

  quiz: { title: "Practice",
    sub: "The engine picks the questions. You pick how long.",
    detail: "Weak concepts first, then high-yield gaps, then whatever is due " +
            "for review. Everything below the fold is optional - the default " +
            "is a sensible session." },
  drills: { title: "Drills",
    sub: "Four short games built from your own concepts.",
    detail: "Aimed at the specific pattern in your assessment. They run " +
            "offline, so they need no API key." },
  sheet: { title: "Study sheet",
    sub: "One page, tables and arrows only.",
    detail: "Externalized working memory for a topic - keep it open beside " +
            "the questions rather than trying to hold it in your head." },
  resources: { title: "Find videos",
    sub: "Outside material, ranked for how it carries information.",
    detail: "Two axes: what students actually rate highly, and whether the " +
            "format is visual. A five-star audio-only resource is still the " +
            "wrong resource for a low auditory working memory." },

  material: { title: "Library",
    sub: "Everything you have uploaded, kept on this machine.",
    detail: "Files stay here across restarts - nothing is thrown away when " +
            "the app closes. What leaves this machine is only the material " +
            "you deliberately send to Claude." },
  vault: { title: "Images & captures",
    sub: "Whiteboards, handouts and exam questions - kept, captioned, findable.",
    detail: "A brain dump is a retrieval attempt you already performed, so " +
            "the app can read it and tell you what is <em>missing</em> - " +
            "which is the half worth knowing." },
  board: { title: "Pinboard",
    sub: "Yours, not the app's.",
    detail: "Nothing here is generated, scored or scheduled. Everywhere else " +
            "the engine decides what you study; this is the one surface " +
            "where you do." },

  topics: { title: "Topics",
    sub: "Every system, down to the concept.",
    detail: "A topic with nothing answered under it is reported as unassessed " +
            "rather than given a number. Unknown and weak are different " +
            "things and the interface has to be able to say which." },
  weak: { title: "Weaknesses",
    sub: "What is costing you the most, in order.",
    detail: "Ranked by weakness \u00d7 yield \u00d7 forgetting risk, so a " +
            "badly-known footnote sits below a shakily-known essential. Only " +
            "concepts you have actually answered can appear here." },

  map: { title: "Mastery",
    sub: "What you know, and what needs attention.",
    detail: "Red demands attention. Everything fades toward green as you go " +
            "- and fades back if you leave it alone, because mastery decays. " +
            "A topic with no attempts behind it is reported as unassessed " +
            "rather than given a number." },
  analytics: { title: "Learning patterns",
    sub: "Only what the data supports.",
    detail: "Everything else is listed as pending, with what it is still " +
            "waiting for. Nothing here is asserted from a handful of " +
            "answers." },

  plan: { title: "Plan",
    action: null,
    sub: "Terms, exams, and what matters before each one.",
    detail: "Terms and courses are your filing system. They sit alongside " +
            "the First Aid taxonomy rather than replacing it, so a concept " +
            "drilled for a midterm keeps its whole history when it turns up " +
            "again on the final." },

  progress: { title: "Progress",
    sub: "Bars fill; nothing here drains.",
    detail: "Streaks count correct answers, not consecutive days - a rest " +
            "day should never cost you three weeks of work." },
  profile: { title: "Profile",
    sub: "What the app knows about how you learn." },
  screener: { title: "Set up your profile",
    sub: "A short set of tasks, so the app can calibrate itself to you." },
  help: { title: "Help & support",
    sub: "Setting up, getting assessed, and supporting the project." },
};

const DEST_OF = {};
NAV.forEach((d) => d.views.forEach(([v]) => { DEST_OF[v] = d.id; }));

/* Rendered before any of the wiring below runs, so the rest of the file can
   go on assuming the buttons are in the document. */
function renderDests() {
  const bar = document.getElementById("dests");
  if (!bar) return;
  bar.innerHTML = NAV.map((d) =>
    `<button class="tab dest" data-dest="${d.id}" data-view="${d.views[0][0]}">` +
    `${d.label}</button>`).join("");
}
renderDests();

function renderSubnav(dest, view) {
  const bar = document.getElementById("subbar");
  const d = NAV.find((x) => x.id === dest);
  if (!bar) return;
  if (!d || d.views.length < 2) {
    bar.hidden = true;
    document.getElementById("subnav").innerHTML = "";
    return;
  }
  document.getElementById("subnav").innerHTML = d.views.map(([v, label]) =>
    `<button class="subtab${v === view ? " active" : ""}" data-view="${v}">` +
    `${label}</button>`).join("");
  bar.hidden = false;
}

function renderPageHead(view) {
  const head = document.getElementById("pageHead");
  const pg = PAGES[view];
  if (!head) return;
  if (!pg) { head.hidden = true; return; }
  document.getElementById("phTitle").textContent = pg.title;
  const sub = document.getElementById("phSub");
  sub.textContent = pg.sub || "";
  sub.hidden = !pg.sub;
  const det = document.getElementById("phDetail");
  det.innerHTML = pg.detail ? `<p>${pg.detail}</p>` : "";
  det.hidden = true;
  document.getElementById("phInfo").hidden = !pg.detail;
  document.getElementById("phInfo").classList.remove("on");
  head.hidden = false;
}

/* Work a screen needs on arrival. This used to be three more passes of
   `querySelectorAll(".tab")`, which silently stopped covering anything the
   nav rendered later. */
const ENTER = {
  today: () => loadDashboard(),
  progress: () => loadProgress(),
  analytics: () => loadAnalytics(),
  map: () => loadMap(),
  plan: () => openNextExam(),
  topics: () => loadTopics(),
  weak: () => { loadWeak(); loadAnkiSelections(); },
  profile: () => { loadAccount(); loadKeys(); },
  material: () => loadLibrary(),
  // Mid-session this must NOT reset - you may be checking the mastery map
  // between questions and would lose your place.
  quiz: () => {
    const done = document.getElementById("quizDone");
    if (done && !done.hidden) backToLauncher();
  },
};

/* Screens register their own arrival work, from wherever they are defined.
   Composing onto the table means a screen added at the bottom of this file is
   wired as reliably as one added at the top. */
function onEnter(view, fn) {
  const prev = ENTER[view];
  ENTER[view] = prev ? () => { prev(); fn(); } : fn;
}

function navigate(view) {
  if (!view) return;
  show(view);
  const f = ENTER[view];
  if (f) { try { f(); } catch (e) { /* a screen still opens if its data fails */ } }
}

document.addEventListener("click", (e) => {
  // Buttons only, and only ones that actually name a view. A bare
  // [data-view] selector is too broad to be safe on a document listener.
  const el = e.target.closest ? e.target.closest("button[data-view]") : null;
  if (!el || !el.dataset.view) return;
  navigate(el.dataset.view);
});

/* Deep links and the back button. The hash is the view, so "#map" opens the
   mastery overview from a bookmark and Back leaves it again. */
window.addEventListener("hashchange", () => {
  const v = location.hash.slice(1);
  if (v && document.getElementById(`view-${v}`)) navigate(v);
});

/* ===================== tiny markdown renderer =====================
   Deliberately small and dependency-free. It covers exactly what the
   generator is instructed to emit: tables, arrow chains in code blocks,
   headings, lists, bold/italic/code, and links. */

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,
             '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
}

function md(src) {
  if (!src) return "";
  const lines = String(src).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;

  const isDivider = (l) => /^\s*\|?[\s:-]*-{2,}[\s|:-]*\|?\s*$/.test(l) && l.includes("-");
  const cells = (l) => l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());

  while (i < lines.length) {
    const line = lines[i];

    // fenced code
    if (/^\s*```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }

    // table: header row followed by a divider row
    if (line.includes("|") && i + 1 < lines.length && isDivider(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const body = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        body.push(cells(lines[i++]));
      }
      out.push(
        "<table><thead><tr>" +
        head.map((h) => `<th>${inline(h)}</th>`).join("") +
        "</tr></thead><tbody>" +
        body.map((r) =>
          "<tr>" + head.map((_, n) => `<td>${inline(r[n] ?? "")}</td>`).join("") + "</tr>"
        ).join("") +
        "</tbody></table>"
      );
      continue;
    }

    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }

    if (/^\s*(---|___|\*\*\*)\s*$/.test(line)) { out.push("<hr>"); i++; continue; }

    if (/^\s*>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${inline(buf.join(" "))}</blockquote>`);
      continue;
    }

    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i++].replace(/^\s*([-*+]|\d+\.)\s+/, ""));
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map((t) => `<li>${inline(t)}</li>`).join("")}</${tag}>`);
      continue;
    }

    if (!line.trim()) { i++; continue; }

    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(#|>|```|[-*+]\s|\d+\.\s)/.test(lines[i])
           && !(lines[i].includes("|") && isDivider(lines[i + 1] || ""))) {
      buf.push(lines[i++]);
    }
    out.push(`<p>${inline(buf.join("\n")).replace(/\n/g, "<br>")}</p>`);
  }
  return out.join("");
}

/* ============================ chrome ============================ */

function toast(msg, isErr = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.hidden = true; }, isErr ? 9000 : 3500);
}

function show(view) {
  if (!view) return;
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === `view-${view}`));

  // A screen reached from the account menu belongs to no destination, so
  // nothing in the bar lights up - which is correct: you are off to one side.
  const dest = DEST_OF[view] || null;
  document.querySelectorAll(".dest").forEach((b) =>
    b.classList.toggle("active", b.dataset.dest === dest));

  renderSubnav(dest, view);
  renderPageHead(view);
  // NOT `data-view`: the delegated navigation handler below matches the
  // closest [data-view] ancestor, and putting that attribute on <body> made
  // every click anywhere in the app re-navigate to the current screen - which
  // re-ran its arrival work and, on Practice, threw away the session summary
  // the moment you clicked "End & review".
  document.body.dataset.screen = view;

  if (location.hash.slice(1) !== view) {
    history.replaceState(null, "", `#${view}`);
  }
  window.scrollTo({ top: 0 });
}

async function checkHealth() {
  const el = $("status");
  try {
    const h = await api("/api/health");
    el.className = "status " + (h.ok ? "ok" : "bad");
    $("statusText").textContent = h.ok ? h.model : "no API key";
    if (!h.ok) toast(h.detail, true);
  } catch (e) {
    el.className = "status bad";
    $("statusText").textContent = "offline";
  }
}

/* ============================= files ============================= */

const drop = $("drop");
const fileInput = $("fileInput");

drop.addEventListener("click", () => fileInput.click());
["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));
fileInput.addEventListener("change", () => upload(fileInput.files));

/* A visible queue rather than a frozen screen. Adding forty lectures at the
   start of a block should not stop you practising the ones already in. */
const upq = new Map();          // name -> "waiting" | "adding" | "done" | "err"

function renderQueue() {
  const box = $("upQueue");
  if (!upq.size) { box.hidden = true; return; }
  box.hidden = false;
  const LABEL = { waiting: "waiting", adding: "adding\u2026",
                  done: "added", err: "failed" };
  $("uqList").innerHTML = [...upq.entries()].map(([name, st]) => `
    <div class="uqrow ${st === "done" ? "done" : st === "err" ? "err" : ""}">
      <span>${esc(name)}</span>
      <span class="uqstate">${LABEL[st] || st}</span>
    </div>`).join("");
}

async function upload(fileList) {
  const files = [...fileList];
  if (!files.length) return;

  const fd = new FormData();
  files.forEach((f) => { fd.append("files", f); upq.set(f.name, "adding"); });
  renderQueue();
  renderFiles(files.map((f) => ({ name: f.name, pending: true })));

  try {
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    state.sources.push(...body.sources);
    files.forEach((f) => upq.set(f.name, "done"));
    (body.errors || []).forEach((e) => {
      toast(e, true);
      // The message names the file it rejected, so mark that one rather than
      // reporting the whole batch as fine.
      for (const name of upq.keys()) if (e.includes(name)) upq.set(name, "err");
    });
    renderFiles();
    $("analyzeRow").hidden = state.sources.length === 0;
    if (typeof loadLibrary === "function") loadLibrary();
  } catch (e) {
    files.forEach((f) => upq.set(f.name, "err"));
    renderFiles();
    toast(e.message, true);
  }
  renderQueue();
  // Successful rows clear themselves; failures stay until dismissed.
  setTimeout(() => {
    [...upq.entries()].forEach(([n, st]) => { if (st === "done") upq.delete(n); });
    renderQueue();
  }, 6000);
  fileInput.value = "";
}

function renderFiles(pending = []) {
  const el = $("fileList");
  const rows = [
    ...state.sources.map((s) => {
      const meta = s.kind === "pdf"
        ? `PDF${s.pages ? ` · ${s.pages} pages` : ""} · sent whole, diagrams intact`
        : s.kind === "image" ? "image"
        : `${s.chars.toLocaleString()} characters extracted`;
      return `<div class="fileitem"><span class="fname">${esc(s.name)}</span>
              <span class="fmeta">${meta}</span>
              <button class="x" data-sha="${s.sha}" title="Remove">×</button></div>`;
    }),
    ...pending.map((p) => `<div class="fileitem"><span class="fname">${esc(p.name)}</span>
              <span class="fmeta">reading…</span></div>`),
  ];
  el.innerHTML = rows.join("");
  el.querySelectorAll(".x").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/sources/${b.dataset.sha}`, { method: "DELETE" });
      state.sources = state.sources.filter((s) => s.sha !== b.dataset.sha);
      renderFiles();
      $("analyzeRow").hidden = state.sources.length === 0;
    }));
}

/* =========================== analysis =========================== */

$("analyzeBtn").addEventListener("click", async () => {
  const btn = $("analyzeBtn");
  btn.disabled = true;
  btn.textContent = "Reading… (this one takes a minute)";
  try {
    const a = await api("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ shas: state.sources.map((s) => s.sha) }),
    });
    state.analysis = a;
    renderAnalysis(a);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Read the material";
  }
});

function renderAnalysis(a) {
  $("analysis").hidden = false;
  $("anTitle").textContent = a.title;
  $("anSubject").textContent = a.subject_area;
  $("anOverview").innerHTML = md(a.overview);
  $("anTable").innerHTML = md(a.orientation_table);

  $("flagCard").hidden = !(a.flags && a.flags.length);
  $("anFlags").innerHTML = (a.flags || []).map((f) => `<li>${esc(f)}</li>`).join("");

  const pc = a.planned_counts;
  $("countTotal").textContent = pc.total;
  $("countBreakdown").textContent = pc.breakdown;
  $("countRationale").textContent = a.count_rationale;
  $("countOverride").value = pc.total;

  $("conceptCount").textContent = a.concepts.length;
  $("conceptList").innerHTML = a.concepts.map((c) => `
    <div class="concept ${c.yield}">
      <div class="cname">${esc(c.name)} <span class="pill">${c.yield}</span></div>
      <div class="cone">${esc(c.one_line)}</div>
      <div class="cmeta"><b>Load:</b> ${esc(c.load_risk)}<br>
      <b>Mixed up with:</b> ${esc(c.confusable_with)}</div>
    </div>`).join("");

  $("genHint").textContent = `${a.concepts.length} concepts across ${state.sources.length} file(s).`;
  window.scrollTo({ top: $("analysis").offsetTop - 20, behavior: "smooth" });
}

/* ========================= generation ========================== */

$("genBtn").addEventListener("click", async () => {
  const total = parseInt($("countOverride").value, 10) || state.analysis.planned_counts.total;
  const btn = $("genBtn");
  btn.disabled = true;
  $("genProgress").hidden = false;

  try {
    const { batches } = await api("/api/plan", {
      method: "POST",
      body: JSON.stringify({ concepts: state.analysis.concepts, total }),
    });

    const shas = state.sources.map((s) => s.sha);
    const collected = [];
    const failed = [];
    for (let n = 0; n < batches.length; n++) {
      btn.textContent = `Writing questions… ${n + 1} of ${batches.length}`;
      $("genBar").style.width = `${(n / batches.length) * 100}%`;

      // One flaky batch used to abort this loop and throw away every question
      // already generated - a 32-concept lecture is seven batches, so a single
      // transient failure on batch five discarded four batches you had already
      // paid for and showed your nothing at all. Retry first, and if a batch
      // still won't come back, keep what worked and name what didn't.
      let got = null;
      for (let attempt = 0; attempt < 3 && !got; attempt++) {
        try {
          got = await api("/api/questions", {
            method: "POST",
            body: JSON.stringify({
              shas, concepts: batches[n].concepts, budget: batches[n].budget,
            }),
          });
        } catch (e) {
          if (attempt === 2) {
            failed.push(...batches[n].concepts.map((c) => c.name));
            console.warn(`batch ${n + 1} failed after 3 attempts: ${e.message}`);
          } else {
            btn.textContent = `Retrying batch ${n + 1}…`;
            await new Promise((r) => setTimeout(r, 800 * (attempt + 1)));
          }
        }
      }
      if (got) collected.push(...got.questions);
    }
    $("genBar").style.width = "100%";

    if (!collected.length) {
      throw new Error(
        failed.length
          ? `Every batch failed. Nothing was generated, so nothing was charged for a set you can use. Last covered: ${failed.length} concepts.`
          : "No questions came back. Try again.");
    }

    // Persist into the durable bank before starting, so the work survives the
    // session and every answer below has a stable concept to attach to.
    btn.textContent = "Saving to your bank…";
    try {
      const saved = await api("/api/bank/save", {
        method: "POST",
        body: JSON.stringify({
          analysis: state.analysis,
          questions: collected,
          source_ref: {
            label: state.sources.map((s) => s.name).join(", ") || state.analysis.title,
            kind: "lecture",
          },
        }),
      });
      state.storedIds = saved.ids || {};
      toast(`${collected.length} questions ready · ${saved.concepts} concepts tracked.`);
      if (failed.length) {
        toast(`${failed.length} concept(s) got no questions: ${
          failed.slice(0, 3).join(", ")}${failed.length > 3 ? "…" : ""}. `
          + "Generate again to cover them.", true);
      }
    } catch (e) {
      // A bank failure must not cost you the questions you just paid to generate.
      state.storedIds = {};
      toast(`Questions ready, but not saved: ${e.message}`, true);
    }

    startQuiz(collected);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Build the question set";
    setTimeout(() => { $("genProgress").hidden = true; $("genBar").style.width = "0"; }, 600);
  }
});

/* ============================= quiz ============================= */

const INSTRUCTIONS = {
  recognition:    "Pick the one right answer.",
  cued_recall:    "Type the answer. If the word won't come, open the cue — that's not cheating, it's the point.",
  discrimination: "Two of these look alike. Pick the one that fits the description.",
  application:    "Read the case, then pick the answer. Everything you need is on this screen.",
  visual_map:     "Fill in the missing piece of the table.",
};

async function startQuiz(questions, mode = "mixed") {
  state.questions = questions;
  state.idx = 0;
  state.answers = [];
  state.sessionId = null;
  $("quizEmpty").hidden = true;
  $("quizDone").hidden = true;
  $("quizRunner").hidden = false;
  $("reviewCard").hidden = true;
  show("quiz");
  renderQuestion();

  // Non-blocking: a session id is nice for grouping attempts, but not having
  // one must never stop you from answering.
  try {
    const s = await api("/api/session/start", {
      method: "POST",
      body: JSON.stringify({ mode, planned: questions.length }),
    });
    state.sessionId = s.session_id;
  } catch { /* attempts still record, just ungrouped */ }
}

function renderQuestion() {
  const q = state.questions[state.idx];
  state.usedCue = false;
  state.selected = null;
  state.answered = false;

  $("qFill").style.width = `${(state.idx / state.questions.length) * 100}%`;
  $("qCounter").textContent = `${state.idx + 1} of ${state.questions.length}`;
  $("qType").textContent = q.type.replace("_", " ");
  $("qConcept").textContent = q.concept_id;
  $("qInstruction").textContent = INSTRUCTIONS[q.type] || INSTRUCTIONS.recognition;

  $("qStem").innerHTML = md(q.stem);

  // Premises live on the page, never in your head.
  $("qPremise").hidden = !q.premise_table;
  $("qPremise").innerHTML = q.premise_table ? md(q.premise_table) : "";

  const isTyped = !q.options || q.options.length === 0;
  $("qOptions").hidden = isTyped;
  $("qTyped").hidden = !isTyped;
  $("qInput").value = "";

  if (!isTyped) {
    $("qOptions").innerHTML = q.options.map((o, i) => `
      <button class="opt" data-label="${esc(o.label)}">
        <span class="lab">${esc(o.label)}</span>
        <span class="otext">${inline(o.text)}</span>
        <span class="keycap">${i + 1}</span>
      </button>`).join("");
    $("qOptions").querySelectorAll(".opt").forEach((b) =>
      b.addEventListener("click", () => {
        if (state.answered) return;
        $("qOptions").querySelectorAll(".opt").forEach((x) => x.classList.remove("sel"));
        b.classList.add("sel");
        state.selected = b.dataset.label;
      }));
  } else {
    setTimeout(() => $("qInput").focus(), 50);
  }

  $("qCue").hidden = true;
  $("qCue").innerHTML = "";
  $("cueBtn").hidden = !q.cue;
  $("cueBtn").disabled = false;
  $("cueBtn").textContent = "Need a cue?";
  $("qExplain").hidden = true;
  $("qMomentum").hidden = true;
  $("submitBtn").hidden = false;
  $("skipBtn").hidden = false;
  $("confidence").hidden = false;
  setConfidence("unsure");
  $("qDissect").hidden = true;
  $("dissectBtn").disabled = false;
  state.shownAt = performance.now();
  startTimer();
  window.scrollTo({ top: 0 });
}

/* Confidence is captured BEFORE feedback. Asked afterwards it would just be
   hindsight, and "incorrect + confident" - the misconception signal, the most
   valuable thing this input produces - would never fire. */
function setConfidence(value) {
  state.confidence = value;
  $("confidence").querySelectorAll(".chip").forEach((c) =>
    c.classList.toggle("active", c.dataset.conf === value));
}

$("confidence").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (chip && !state.answered) setConfidence(chip.dataset.conf);
});

$("cueBtn").addEventListener("click", () => {
  const q = state.questions[state.idx];
  state.usedCue = true;
  $("qCue").hidden = false;
  $("qCue").innerHTML = inline(q.cue);
  $("cueBtn").disabled = true;
  $("cueBtn").textContent = "Cue shown";
});

/* Generous matching. Word-finding speed is measured at the 5th percentile here;
   it is explicitly not the skill under test, so spelling slips, synonyms, and
   partial answers all count. */
function normalize(s) {
  return String(s || "").toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ").replace(/\s+/g, " ").trim();
}

function editDistance(a, b) {
  const m = a.length, n = b.length;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1,
                        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[n];
}

function matches(given, q) {
  const g = normalize(given);
  if (!g) return false;
  const targets = [q.answer_text, ...(q.accepted_answers || [])].filter(Boolean).map(normalize);
  for (const t of targets) {
    if (!t) continue;
    if (g === t) return true;
    if (t.length > 6 && (g.includes(t) || t.includes(g)) && g.length >= t.length - 3) return true;
    const tol = t.length > 12 ? 3 : t.length > 7 ? 2 : 1;
    if (editDistance(g, t) <= tol) return true;
  }
  return false;
}

$("submitBtn").addEventListener("click", () => grade(false));
$("skipBtn").addEventListener("click", () => grade(true));
$("qInput").addEventListener("keydown", (e) => { if (e.key === "Enter") grade(false); });

function grade(skipped) {
  if (state.answered) return;
  const q = state.questions[state.idx];
  const isTyped = !q.options || q.options.length === 0;
  const given = skipped ? "" : (isTyped ? $("qInput").value : state.selected);

  if (!skipped && !given) { toast("Pick an answer, or hit Skip."); return; }

  const correct = skipped ? false
    : isTyped ? matches(given, q)
    : !!(q.options.find((o) => o.label === given) || {}).correct;

  state.answered = true;
  const rtMs = state.shownAt ? Math.round(performance.now() - state.shownAt) : null;

  state.answers.push({
    qid: q.id, concept_id: q.concept_id, type: q.type, difficulty: q.difficulty,
    stem: q.stem, given: given || "(skipped)", correct, usedCue: state.usedCue, skipped,
    confidence: state.confidence,
  });

  $("confidence").hidden = true;
  stopTimer();
  recordAttempt(q, { correct, given, skipped, rtMs });

  if (!isTyped) {
    $("qOptions").querySelectorAll(".opt").forEach((b) => {
      const o = q.options.find((x) => x.label === b.dataset.label);
      b.classList.remove("sel");
      if (o && o.correct) b.classList.add("right");
      else if (b.dataset.label === given) b.classList.add("wrong");
    });
  }

  const v = $("qVerdict");
  if (correct && state.usedCue) {
    v.className = "verdict close";
    v.textContent = "Right — and you got there with the cue. You know this. The word was just slow to arrive.";
  } else if (correct) {
    v.className = "verdict right";
    v.textContent = "Right.";
  } else if (skipped) {
    v.className = "verdict wrong";
    v.textContent = "Skipped — here it is.";
  } else {
    v.className = "verdict wrong";
    const shown = isTyped ? q.answer_text
      : (q.options.find((o) => o.correct) || {}).text;
    v.textContent = `Not this one. The answer is: ${shown}`;
  }

  $("eWhy").innerHTML = md(q.why_right);
  $("eVisual").innerHTML = md(q.visual);
  $("eDerive").innerHTML = md(q.derive_from);
  $("eHook").innerHTML = md(q.memory_hook);
  $("eClue").innerHTML = md(q.key_clue || "—");
  $("eSource").textContent = q.source_ref ? `From: ${q.source_ref}` : "";
  loadWhereTo(q, correct);

  $("eOptions").innerHTML = (q.options || []).map((o) => `
    <div class="optwhy ${o.correct ? "correct" : ""}">
      <b>${esc(o.label)}. ${esc(o.text)}</b>
      <p>${inline(o.why)}</p>
    </div>`).join("") || `<p class="hint">Accepted answers: ${
      [q.answer_text, ...(q.accepted_answers || [])].filter(Boolean).map(esc).join(", ")}</p>`;

  $("submitBtn").hidden = true;
  $("skipBtn").hidden = true;
  $("qExplain").hidden = false;
  $("nextBtn").textContent = state.idx + 1 >= state.questions.length
    ? "Finish" : "Next question";
  $("nextBtn").scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/* Fire-and-forget: the answer is already graded on screen. If the write fails,
   you keep studying and finds out at the end, rather than mid-flow. */
async function recordAttempt(q, { correct, given, skipped, rtMs }) {
  const questionId = state.storedIds[q.id];
  if (!questionId) return;   // generated but never banked

  try {
    const res = await api("/api/attempt", {
      method: "POST",
      body: JSON.stringify({
        question_id: questionId,
        correct,
        given: given || "",
        confidence: state.confidence,
        used_cue: state.usedCue,
        error_type: skipped ? "skipped" : null,
        rt_ms: rtMs,
        session_id: state.sessionId,
      }),
    });
    renderMomentum(res.concepts && res.concepts[0], res);
  } catch (e) {
    state.saveFailed = e.message;
  }
}

const BAND_LABEL = {
  red: "weak", orange: "developing", yellow: "inconsistent",
  light_green: "strong", dark_green: "mastered",
};

/* The "one more question" line. Fills only - nothing here counts down or
   drains, because extended time is an accommodation and a decaying clock would
   turn a support into a stressor. */
function renderMomentum(c, res) {
  if (!c) return;
  const el = $("qMomentum");
  const pct = Math.round(c.after * 100);
  const bits = [];

  if (res && res.xp) {
    bits.push(`<span class="xpchip">+${res.xp.gained} XP</span>`);
    if (res.xp.levelled_up) {
      bits.push(`<span class="bandmove">Level ${res.xp.level.level}</span>`);
    }
  }

  if (c.band !== c.band_before) {
    bits.push(`<span class="bandmove">${esc(c.name)} moved to
      <span class="bandchip band-${c.band}">${BAND_LABEL[c.band] || c.band}</span></span>`);
  } else if (c.to_next_band) {
    bits.push(`<span><b>${c.to_next_band.questions}</b> more to ${
      nextBandPhrase(c.band, c.to_next_band.band)} on ${esc(c.name)}</span>`);
  } else {
    bits.push(`<span>${esc(c.name)} —
      <span class="bandchip band-${c.band}">${BAND_LABEL[c.band] || c.band}</span></span>`);
  }

  const run = res && res.streak ? res.streak.streak : c.streak;
  if (run >= 3) bits.push(`<span>\u{1F525} <b>${run}</b> in a row</span>`);
  if (res && res.unlocked) {
    res.unlocked.forEach((a) => toast(`Achievement unlocked: ${a.name}`));
  }
  bits.push(`<span class="mbar"><span class="mfill" style="width:${pct}%"></span></span>`);

  el.innerHTML = bits.join("");
  el.hidden = false;
}

$("nextBtn").addEventListener("click", () => {
  state.idx++;
  if (state.idx >= state.questions.length) finish();
  else renderQuestion();
});

$("quitBtn").addEventListener("click", () => {
  if (state.answers.length === 0) { toast("Nothing answered yet."); return; }
  finish();
});

async function finish() {
  $("quizRunner").hidden = true;
  $("quizDone").hidden = false;

  const knew   = state.answers.filter((a) => a.correct && !a.usedCue).length;
  const word   = state.answers.filter((a) => a.correct && a.usedCue).length;
  const missed = state.answers.filter((a) => !a.correct).length;

  $("scoreKnew").textContent = knew;
  $("scoreWord").textContent = word;
  $("scoreMissed").textContent = missed;
  window.scrollTo({ top: 0 });

  if (state.saveFailed) {
    toast(`Some answers weren't saved: ${state.saveFailed}`, true);
    state.saveFailed = null;
  }
  if (!state.sessionId) return;

  try {
    const s = await api("/api/session/end", {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    renderMastered(s);
  } catch { /* the score above is already on screen */ }
}

/* What actually moved this session - the useful half of a summary screen. */
function renderMastered(s) {
  const box = $("sessionMoves");
  if (!box) return;
  const row = (m, cls) => `<div class="moveitem ${cls}">
      <span class="mname">${esc(m.name)}</span>
      <span class="mdelta">${m.delta > 0 ? "+" : ""}${Math.round(m.delta * 100)}%</span>
    </div>`;

  const parts = [];
  if (s.improved && s.improved.length) {
    parts.push("<h4>Improved</h4>" + s.improved.map((m) => row(m, "up")).join(""));
  }
  if (s.needs_work && s.needs_work.length) {
    parts.push("<h4>Needs work</h4>" + s.needs_work.map((m) => row(m, "down")).join(""));
  }
  box.innerHTML = parts.join("");
  box.hidden = !parts.length;
}

$("reviewBtn").addEventListener("click", async () => {
  const btn = $("reviewBtn");
  btn.disabled = true; btn.textContent = "Looking at the pattern…";
  try {
    const r = await api("/api/review", {
      method: "POST",
      body: JSON.stringify({
        results: state.answers.map((a) => ({
          concept_id: a.concept_id, type: a.type, difficulty: a.difficulty,
          stem: a.stem, correct: a.correct, given: a.given, used_cue: a.usedCue,
        })),
      }),
    });
    $("reviewCard").hidden = false;
    $("revVerdict").textContent = r.verdict;
    $("revPatterns").innerHTML = r.patterns.map((p) => `
      <div class="optwhy"><b>${esc(p.pattern)}</b>
        <p>${esc(p.evidence)}</p>
        <p><b>Fix:</b> ${esc(p.fix)}</p></div>`).join("");
    $("revTable").innerHTML = md(r.repair_table);
    $("revNext").textContent = r.next_session;
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = "What should I do next?";
  }
});

$("retryBtn").addEventListener("click", () => {
  const missedIds = new Set(state.answers.filter((a) => !a.correct).map((a) => a.qid));
  const again = state.questions.filter((q) => missedIds.has(q.id));
  if (!again.length) { toast("Nothing missed. Nothing to redo."); return; }
  startQuiz(again);
});

$("saveBtn").addEventListener("click", async () => {
  try {
    await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({
        title: (state.analysis && state.analysis.title) || "Session",
        questions: state.questions,
        answers: state.answers,
        score: `${state.answers.filter((a) => a.correct).length}/${state.answers.length}`,
      }),
    });
    toast("Saved.");
    loadSaved();
  } catch (e) { toast(e.message, true); }
});

async function loadSaved() {
  try {
    const { sessions } = await api("/api/sessions");
    $("savedList").innerHTML = sessions.length
      ? `<h4>Saved sessions</h4>` + sessions.map((s) => `
          <button class="saveditem" data-id="${esc(s.id)}">
            <span class="st">${esc(s.title)}</span>
            <span class="fmeta">${s.count} questions${s.score ? ` · ${esc(s.score)}` : ""}</span>
          </button>`).join("")
      : "";
    $("savedList").querySelectorAll(".saveditem").forEach((b) =>
      b.addEventListener("click", async () => {
        const s = await api(`/api/sessions/${b.dataset.id}`);
        startQuiz(s.questions);
      }));
  } catch { /* first run, no sessions dir yet */ }
}

/* =========================== study sheet ======================== */

$("sheetBtn").addEventListener("click", async () => {
  if (!state.sources.length) { toast("Drop a course file first.", true); return; }
  const btn = $("sheetBtn");
  btn.disabled = true; btn.textContent = "Building…";
  try {
    const r = await api("/api/sheet", {
      method: "POST",
      body: JSON.stringify({
        shas: state.sources.map((s) => s.sha),
        focus: $("sheetFocus").value.trim(),
      }),
    });
    $("sheetOut").hidden = false;
    $("sheetOut").innerHTML = md(r.markdown);
    $("sheetPrint").hidden = false;
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Build sheet"; }
});
$("sheetPrint").addEventListener("click", () => window.print());

/* ============================ resources ========================= */

$("resBtn").addEventListener("click", async () => {
  const topic = $("resTopic").value.trim();
  if (!topic) { toast("Type a topic first."); return; }
  const btn = $("resBtn");
  btn.disabled = true; btn.textContent = "Searching…";
  try {
    const r = await api("/api/resources", {
      method: "POST",
      body: JSON.stringify({
        topic,
        context: (state.analysis && state.analysis.subject_area) || "",
      }),
    });
    $("resOut").hidden = false;
    $("resOut").innerHTML = md(r.markdown);
    $("resSources").hidden = !(r.sources || []).length;
    $("resSourceList").innerHTML = (r.sources || []).map((s) =>
      `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a></li>`
    ).join("");
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Search"; }
});
$("resTopic").addEventListener("keydown", (e) => { if (e.key === "Enter") $("resBtn").click(); });

/* ============================= profile ========================== */

async function loadProfile() {
  try {
    const p = await api("/api/profile");

    // The lever table lives in the identity card now, so there is one place
    // that says what the app is doing and why, rather than two that can drift.
    $("profileLeverList").innerHTML = p.levers.map((l) => `
      <div class="lever">
        <div class="lf">${esc(l.finding)}</div>
        <div class="ls">${esc(l.score)}</div>
        <div class="lr">${esc(l.rule)}</div>
      </div>`).join("");

    const all = { ...p.indexes, ...p.subtests };
    const scores = $("scoresCard") || $("profileScores").closest(".card");
    if (scores) scores.hidden = !Object.keys(all).length;
    $("scoresHead").textContent = p.name ? `${p.name}'s scores` : "Scores";
    $("profileCaveatScores").textContent = p.caveat || "";

    $("profileScores").innerHTML = Object.entries(all).map(([k, v]) => {
      const isIndex = k in p.indexes;
      const n = Number(v);
      // An index is normed to mean 100, a subtest to mean 10. Reading one on
      // the other's scale would paint every subtest score bright red.
      const low = isIndex ? n < 85 : n <= 6;
      const strong = isIndex ? n >= 100 : n >= 10;
      return `<div class="score ${low ? "low" : strong ? "strong" : ""}">
                <div class="sv">${esc(String(v))}</div><div class="sn">${esc(k)}</div></div>`;
    }).join("");
  } catch (e) { /* the app works without a profile; it just works generically */ }
}

checkHealth();
loadProfile();
loadSaved();
loadTimerOptions();

/* ====================== phase 2: adaptive launcher ====================== */

const BANDS = [
  ["red", "weak"], ["orange", "developing"], ["yellow", "inconsistent"],
  ["light_green", "strong"], ["dark_green", "mastered"],
];

/* "Reach inconsistent" is not a goal anyone wants. Yellow reads fine as a
   status and badly as a rung, so the middle bands are phrased as leaving where
   you are, and only the two green bands are phrased as arriving somewhere. */
function nextBandPhrase(from, to) {
  if (to === "dark_green") return "reach <b>mastered</b>";
  if (to === "light_green") return "reach <b>strong</b>";
  return `move out of <b>${BAND_LABEL[from] || from}</b>`;
}

let sessionLength = 10;
let sessionMode = "mixed";

$("lengths").addEventListener("click", (e) => {
  const b = e.target.closest(".len");
  if (!b) return;
  sessionLength = parseInt(b.dataset.n, 10);
  $("lengths").querySelectorAll(".len").forEach((x) => x.classList.toggle("active", x === b));
});

$("modes").addEventListener("click", (e) => {
  const b = e.target.closest(".mode");
  if (!b) return;
  sessionMode = b.dataset.mode;
  $("modes").querySelectorAll(".mode").forEach((x) => x.classList.toggle("active", x === b));
});

/* One start path, two entrances: the recommendation and the manual pickers.
   Having them share this means the recommended session is a real session with
   a real mode, not a separate code path that could drift. */
async function beginSession(n, mode, btn, restore) {
  btn.disabled = true;
  btn.textContent = "Picking your questions\u2026";
  try {
    const r = await api("/api/select", {
      method: "POST",
      body: JSON.stringify({ n, mode, scope: currentScope() }),
    });
    // Adaptive questions come from the bank, so they already carry durable ids.
    state.storedIds = Object.fromEntries(r.questions.map((q) => [q.id, q.id]));
    await startQuiz(r.questions, mode);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = restore;
  }
}

$("startAdaptive").addEventListener("click", () =>
  beginSession(sessionLength, sessionMode, $("startAdaptive"), "Start studying"));

/* ------------------------- the recommendation ------------------------- */

const rec = { mode: "mixed", n: 10 };

const REC_LENGTHS = [[5, "5"], [10, "10"], [20, "20"], [40, "Endless"]];

function renderRecLengths() {
  $("recLengths").innerHTML = REC_LENGTHS.map(([n, label]) =>
    `<button class="len${n === rec.n ? " active" : ""}" data-recn="${n}">${label}</button>`
  ).join("");
  $("recLengths").querySelectorAll("[data-recn]").forEach((b) =>
    b.addEventListener("click", () => {
      rec.n = Number(b.dataset.recn);
      renderRecLengths();
    }));
}

$("recStart").addEventListener("click", () =>
  beginSession(rec.n, rec.mode, $("recStart"), "Start"));

async function refreshLauncher() {
  renderRecLengths();
  try {
    const r = await api("/api/select/modes");
    $("dueCount").textContent = r.due_now;
    $("poolHint").textContent = r.available_concepts
      ? `${r.available_concepts} concepts in your bank.`
      : "Nothing banked yet \u2014 add material and build a question set first.";
    $("startAdaptive").disabled = !r.available_concepts;
    $("recStart").disabled = !r.available_concepts;
  } catch { /* server may not be up yet */ }

  try {
    const g = await api("/api/select/recommend");
    rec.mode = g.mode;
    $("recTitle").textContent = g.title;
    // The recommendation names the mode it chose, so nothing here is a black
    // box: whatever it suggests, you could have picked yourself below.
    const named = (MODE_NAMES[g.mode] || g.mode);
    $("recWhy").textContent = g.available
      ? `${g.why} \u00b7 this runs as "${named}".`
      : g.why;
    $("recStart").disabled = !g.available;
    // Keep the manual pickers honest: they open on what was recommended.
    setMode(g.mode);
  } catch { /* the manual pickers still work */ }
}

const MODE_NAMES = {
  mixed: "Mixed review", weak_areas: "Weak areas", high_yield: "High yield",
  spaced: "Due for review", exam_cram: "Exam cram", new_material: "New material",
};

function setMode(mode) {
  sessionMode = mode;
  document.querySelectorAll("#modes .mode").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
}

/* ========================= phase 2: mastery map ======================== */

function pct(x) { return x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`; }

/* One fetch feeds Overview, Topics and Weaknesses. Switching between them is
   a filter on data already held, not three round trips. */
const mastery = { map: null, weak: null, at: 0 };

async function masteryData(force = false) {
  if (!force && mastery.map && Date.now() - mastery.at < 20000) return mastery;
  const [map, weak] = await Promise.all([
    api("/api/mastery/map"),
    api("/api/mastery/weakest?limit=40"),
  ]);
  mastery.map = map;
  mastery.weak = weak;
  mastery.at = Date.now();
  return mastery;
}

const bandName = (b) => (BANDS.find((x) => x[0] === b) || [, b])[1];

/* UNKNOWN and WEAK are not the same thing, and the interface has to be able to
   say which. A topic nobody has answered reports no number at all rather than
   the prior dressed up as a measurement - which is how every unopened subject
   used to read 35%. */
function scoreCell(t) {
  if (t.evidence === "none") {
    return `<span class="hpct none">Not assessed</span>`;
  }
  if (t.evidence === "thin") {
    return `<span class="hpct thin" title="${t.assessed} of ${t.concepts} concepts answered">
      \u2248${Math.round(t.effective * 100)}%<em>estimate</em></span>`;
  }
  return `<span class="hpct">${Math.round(t.effective * 100)}%</span>`;
}

function topicBar(t) {
  if (t.evidence === "none") {
    return `<span class="hbar"><span class="hempty"></span></span>`;
  }
  return `<span class="hbar"><span class="hfill fill-${t.band}${
    t.evidence === "thin" ? " thin" : ""}"
    style="width:${Math.max(3, (t.effective || 0) * 100)}%"></span></span>`;
}

function coverText(t) {
  return t.concepts
    ? `${t.assessed} of ${t.concepts} answered`
    : "no concepts";
}

async function loadMap() {
  $("legend").innerHTML = BANDS.map(([b, label]) =>
    `<span class="li"><span class="sw fill-${b}"></span>${label}</span>`).join("")
    + `<span class="li"><span class="sw swnone"></span>Not assessed</span>`;

  let d;
  try { d = await masteryData(); }
  catch (e) { toast(e.message, true); return; }

  const systems = d.map.topics.filter((t) => t.depth === 0);
  const totC = systems.reduce((n, t) => n + t.concepts, 0);
  const totA = systems.reduce((n, t) => n + t.assessed, 0);
  $("mapCoverage").textContent = totC
    ? `${totA} of ${totC} concepts answered`
    : "";

  $("heatmap").innerHTML = systems.length
    ? systems.map((t) => `
      <button class="hrow" data-topic="${esc(t.id)}">
        <span class="hname">${esc(t.name)}
          <span class="hcount">${coverText(t)}</span></span>
        ${topicBar(t)}
        ${scoreCell(t)}
      </button>`).join("")
    : `<p class="hint">Nothing here yet. Add material and answer some questions
         and this fills in.</p>`;

  $("heatmap").querySelectorAll(".hrow").forEach((r) =>
    r.addEventListener("click", () => { navigate("topics"); openTopic(r.dataset.topic); }));

  $("mapWeak").innerHTML = d.weak.weakest.length
    ? d.weak.weakest.slice(0, 5).map((w, i) => weakRow(w, i)).join("")
    : `<p class="hint">No measured weaknesses yet \u2014 that needs a few
         answered questions. An untouched concept is not a weakness.</p>`;
  $("mapWeak").querySelectorAll(".weakrow").forEach((r) =>
    r.addEventListener("click", () => showConcept(r.dataset.concept)));
}

function weakRow(w, i) {
  return `
    <button class="weakrow" data-concept="${esc(w.concept_id)}">
      <span class="rank">${i + 1}</span>
      <span class="wname">${esc(w.name)}
        <span class="wtopic">${esc(w.topic)} \u00b7 ${
          esc(w.hy_tier.replace("_", " "))} yield</span></span>
      <span class="bandchip band-${w.band}">${bandName(w.band)}</span>
      <span class="wpct">${pct(w.effective)}</span>
    </button>`;
}

async function loadWeak() {
  let d;
  try { d = await masteryData(); }
  catch (e) { toast(e.message, true); return; }

  $("weakList").innerHTML = d.weak.weakest.length
    ? d.weak.weakest.map((w, i) => weakRow(w, i)).join("")
    : `<p class="hint">Nothing to rank yet. A concept has to be answered before
         it can be called weak \u2014 until then it is simply unknown, which is
         a different problem with a different fix.</p>`;
  $("weakList").querySelectorAll(".weakrow").forEach((r) =>
    r.addEventListener("click", () => showConcept(r.dataset.concept)));
}

/* -------------------------- the topic explorer ------------------------ */

const topicOpen = new Set();

async function loadTopics() {
  let d;
  try { d = await masteryData(); }
  catch (e) { toast(e.message, true); return; }
  renderTopicTree();
}

function renderTopicTree() {
  const d = mastery.map;
  if (!d) return;
  const filter = ($("topicFilter").value || "").trim().toLowerCase();
  const byParent = {};
  d.topics.forEach((t) => {
    (byParent[t.parent_id || ""] = byParent[t.parent_id || ""] || []).push(t);
  });

  const conceptsOf = (tid) => d.concepts.filter((c) => c.topic_id === tid);
  const hit = (text) => !filter || text.toLowerCase().includes(filter);

  // A filter that matched only topic names would hide the concept you typed.
  const keep = (t) => {
    if (hit(t.name)) return true;
    if (conceptsOf(t.id).some((c) => hit(c.name))) return true;
    return (byParent[t.id] || []).some(keep);
  };

  const node = (t, depth) => {
    if (filter && !keep(t)) return "";
    const kids = byParent[t.id] || [];
    const own = conceptsOf(t.id).filter((c) => hit(c.name));
    const open = filter ? true : topicOpen.has(t.id);
    return `
      <div class="tnode d${depth}">
        <button class="trow${open ? " open" : ""}" data-topic="${esc(t.id)}">
          <span class="tcaret">${kids.length || own.length ? "\u25b8" : ""}</span>
          <span class="tlabel">${esc(t.name)}
            <span class="hcount">${coverText(t)}</span></span>
          ${topicBar(t)}
          ${scoreCell(t)}
        </button>
        ${open ? `<div class="tkids">
          ${kids.map((k) => node(k, depth + 1)).join("")}
          ${own.map((c) => conceptRow(c)).join("")}
        </div>` : ""}
      </div>`;
  };

  const roots = (byParent[""] || []).concat(
    d.topics.filter((t) => t.parent_id && !d.topics.some((x) => x.id === t.parent_id)));

  const html = roots.map((t) => node(t, 0)).join("");
  $("topicTree").innerHTML = html.trim()
    ? html
    : `<p class="hint">${filter ? "Nothing matches that." :
        "No topics yet \u2014 add material and this fills in."}</p>`;

  $("topicTree").querySelectorAll(".trow").forEach((r) =>
    r.addEventListener("click", () => {
      const id = r.dataset.topic;
      if (topicOpen.has(id)) topicOpen.delete(id); else topicOpen.add(id);
      renderTopicTree();
    }));
  $("topicTree").querySelectorAll("[data-concept]").forEach((r) =>
    r.addEventListener("click", (e) => {
      e.stopPropagation();
      showConcept(r.dataset.concept);
    }));
}

function conceptRow(c) {
  const seen = c.attempts > 0;
  return `
    <button class="crow" data-concept="${esc(c.id)}">
      <span class="cdot band-${seen ? c.band : "untouched"}"></span>
      <span class="clabel">${esc(c.name)}</span>
      <span class="hy hy-${esc(c.hy_tier)}">${esc(c.hy_tier.replace("_", " "))}</span>
      <span class="cscore">${seen ? pct(c.effective)
        : `<span class="none">not assessed</span>`}</span>
    </button>`;
}

$("topicFilter").addEventListener("input", () => {
  clearTimeout($("topicFilter")._t);
  $("topicFilter")._t = setTimeout(renderTopicTree, 160);
});

function openTopic(tid) {
  const d = mastery.map;
  if (d) {
    // Open it and every ancestor, so a click from the overview lands on
    // something visible rather than a collapsed row.
    let cur = d.topics.find((t) => t.id === tid);
    while (cur) {
      topicOpen.add(cur.id);
      cur = d.topics.find((t) => t.id === cur.parent_id);
    }
  }
  renderTopicTree();
  const row = $("topicTree").querySelector(`[data-topic="${CSS.escape(tid)}"]`);
  if (row) row.scrollIntoView({ behavior: "smooth", block: "center" });
}

/* The three numbers, never collapsed into one percentage. */
async function showConcept(cid) {
  show("topics");
  try {
    const d = await api(`/api/mastery/concept/${cid}`);
    const m = d.mastery;
    const box = $("conceptDetail");
    box.hidden = false;
    $("cdName").textContent = d.concept.name;
    $("cdTopic").textContent = `${d.concept.topic_id.replace(/\./g, " / ")} · ${
      d.concept.hy_tier.replace("_", " ")} yield`;

    $("cdNums").innerHTML = `
      <div class="tnum"><div class="tv">${pct(m.mastery)}</div>
        <div class="tl">Mastery</div><div class="th">How well you know it</div></div>
      <div class="tnum"><div class="tv">${pct(m.retention)}</div>
        <div class="tl">Retention</div><div class="th">How likely that's still true</div></div>
      <div class="tnum"><div class="tv">${pct(m.est_confidence)}</div>
        <div class="tl">Confidence in the estimate</div>
        <div class="th">How much evidence there is</div></div>`;

    const rows = [];
    rows.push(`<h4>Status</h4><p><span class="bandchip band-${m.band}">${
      (BANDS.find((b) => b[0] === m.band) || [, m.band])[1]}</span>
      &nbsp;${m.attempts} attempts · ${m.correct} correct · streak ${m.streak}</p>`);

    if (m.difficulty_gap > 0.15) {
      rows.push(`<h4>Recall vs. application</h4>
        <p>You're ${Math.round(m.difficulty_gap * 100)}% better on the facts than on
        applying them. That's the gap worth closing.</p>`);
    }
    if (m.to_next_band) {
      const kind = m.to_next_band.needs_harder
        ? " — but they have to be harder ones. Recall questions alone can't get you there."
        : ".";
      rows.push(`<h4>Next</h4><p>About <b>${m.to_next_band.questions}</b> more correct
        answers to ${nextBandPhrase(m.band, m.to_next_band.band)}${kind}</p>`);
    }
    if (d.related.length) {
      rows.push(`<h4>Mixed up with</h4><p>${
        d.related.map((r) => esc(r.name)).join(", ")}</p>`);
    }
    // Reported as a trend against your own baseline only - never scored.
    if (m.avg_rt_ms) {
      rows.push(`<h4>Pace</h4><p class="hint">Average ${
        (m.avg_rt_ms / 1000).toFixed(1)}s. Recorded for your own reference —
        speed never affects your mastery score.</p>`);
    }
    $("cdExtra").innerHTML = rows.join("");
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    toast(e.message, true);
  }
}

// Refresh the map and launcher whenever those tabs are opened.
refreshLauncher();

/* Opening Practice re-reads the recommendation: what is due changes as you
   answer things, and a stale suggestion is worse than none. */
onEnter("quiz", refreshLauncher);

/* ===================== phase 3: organisation, vault, board ==============
   Terms and exams are your filing system; the mastery map is the app's.
   Keeping them separate is what lets a concept drilled for a midterm carry
   its history into the final instead of starting over under a new heading. */

const org = {
  terms: [], exams: [], selectedExam: null,
  chatId: null, plan: null, pins: [], assets: [],
};

/* --------------------------- a small modal ---------------------------- */

function modal(title, fields, onSave) {
  const m = $("modal");
  $("modalTitle").textContent = title;
  $("modalBody").innerHTML = fields.map((f) => {
    const id = `mf_${f.name}`;
    if (f.type === "textarea") {
      return `<label><span>${esc(f.label)}</span>
        <textarea id="${id}" placeholder="${esc(f.placeholder || "")}">${esc(f.value || "")}</textarea></label>`;
    }
    if (f.type === "select") {
      return `<label><span>${esc(f.label)}</span><select id="${id}">${
        f.options.map((o) => `<option value="${esc(o.value)}"${
          o.value === f.value ? " selected" : ""}>${esc(o.label)}</option>`).join("")
      }</select></label>`;
    }
    return `<label><span>${esc(f.label)}</span>
      <input type="${f.type || "text"}" id="${id}" value="${esc(f.value || "")}"
        placeholder="${esc(f.placeholder || "")}"></label>`;
  }).join("");
  m.hidden = false;

  const first = $("modalBody").querySelector("input, textarea, select");
  if (first) setTimeout(() => first.focus(), 40);

  const close = () => {
    m.hidden = true;
    $("modalOk").onclick = null;
    $("modalCancel").onclick = null;
  };
  $("modalCancel").onclick = close;
  $("modalOk").onclick = async () => {
    const values = {};
    fields.forEach((f) => { values[f.name] = $(`mf_${f.name}`).value.trim(); });
    try {
      await onSave(values);
      close();
    } catch (e) { toast(e.message, true); }
  };
}
$("modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") $("modal").hidden = true;
});

const todayISO = () => new Date().toISOString().slice(0, 10);

function countdownClass(days) {
  if (days === null || days === undefined) return "";
  if (days < 0) return "past";
  if (days <= 3) return "urgent";
  if (days <= 10) return "soon";
  return "";
}

function countdownText(days) {
  if (days === null || days === undefined) return "no date";
  if (days < 0) return `${Math.abs(days)}d ago`;
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `${days} days`;
}

/* ------------------------------- terms -------------------------------- */

async function loadOrg() {
  try {
    const [t, e] = await Promise.all([api("/api/terms"), api("/api/exams")]);
    org.terms = t.terms;
    org.exams = e.exams;
    renderTerms();
    renderExams();
    fillExamPickers();
  } catch (err) { toast(err.message, true); }
}

function renderTerms() {
  $("termList").innerHTML = org.terms.length
    ? org.terms.map((t) => `
      <button class="termrow ${t.active ? "on" : ""}" data-term="${esc(t.id)}">
        <span class="tname">${esc(t.name)}</span>
        <span class="fmeta">${t.course_count} course${t.course_count === 1 ? "" : "s"} ·
          ${t.exam_count} exam${t.exam_count === 1 ? "" : "s"}</span>
        ${t.active ? '<span class="bandchip band-dark_green">active</span>' : ""}
      </button>`).join("")
    : `<p class="hint">No terms yet. Add one to start organising by term and course.</p>`;

  $("termList").querySelectorAll(".termrow").forEach((r) =>
    r.addEventListener("click", async () => {
      await api(`/api/terms/${r.dataset.term}/active`, { method: "POST" });
      loadOrg();
    }));
}

$("newTermBtn").addEventListener("click", () => {
  modal("New term", [
    { name: "name", label: "Name", placeholder: "Term 4" },
    { name: "starts", label: "Starts", type: "date" },
    { name: "ends", label: "Ends", type: "date" },
  ], async (v) => {
    if (!v.name) throw new Error("Give the term a name.");
    await api("/api/terms", { method: "POST", body: JSON.stringify(v) });
    loadOrg();
  });
});

/* ------------------------------- exams -------------------------------- */

function renderExams() {
  $("examList").innerHTML = org.exams.length
    ? org.exams.map((e) => `
      <button class="examrow ${org.selectedExam === e.id ? "sel" : ""}" data-exam="${esc(e.id)}">
        <span class="ename">${esc(e.name)}
          <span class="esub">${esc(e.kind)}${e.course ? " · " + esc(e.course) : ""} · ${esc(e.date)}</span>
        </span>
        <span class="countdown ${countdownClass(e.days_left)}">${countdownText(e.days_left)}</span>
      </button>`).join("")
    : `<p class="hint">No exams yet. Adding one immediately changes what the practice engine serves — exam proximity is part of the priority formula.</p>`;

  $("examList").querySelectorAll(".examrow").forEach((r) =>
    r.addEventListener("click", () => selectExam(r.dataset.exam)));
}

$("newExamBtn").addEventListener("click", () => {
  modal("Add exam", [
    { name: "name", label: "Name", placeholder: "Renal Midterm" },
    { name: "date", label: "Date", type: "date", value: todayISO() },
    { name: "kind", label: "Kind", type: "select", value: "midterm",
      options: ["quiz", "midterm", "final", "nbme", "shelf", "practical", "other"]
        .map((k) => ({ value: k, label: k })) },
    { name: "term_id", label: "Term", type: "select",
      options: [{ value: "", label: "—" }].concat(
        org.terms.map((t) => ({ value: t.id, label: t.name }))) },
  ], async (v) => {
    if (!v.name || !v.date) throw new Error("An exam needs a name and a date.");
    const created = await api("/api/exams", { method: "POST", body: JSON.stringify(v) });
    await loadOrg();
    selectExam(created.id);
  });
});

async function selectExam(eid) {
  org.selectedExam = eid;
  org.chatId = null;
  org.plan = null;
  renderExams();
  $("examDetail").hidden = false;
  $("planOut").hidden = true;
  $("planStrategy").hidden = true;

  const e = org.exams.find((x) => x.id === eid);
  if (e) {
    $("edName").textContent = e.name;
    $("edMeta").textContent = `${e.kind}${e.course ? " · " + e.course : ""} · ${e.date}`;
    $("edCountdown").textContent = countdownText(e.days_left);
    $("edCountdown").className = `countdown ${countdownClass(e.days_left)}`;
  }
  await Promise.all([loadReadiness(eid), loadEmphasis(eid), loadChat(eid)]);
  $("examDetail").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadReadiness(eid) {
  try {
    const r = await api(`/api/exams/${eid}/readiness`);
    if (r.empty) {
      $("edReadiness").innerHTML = `<p class="hint">${esc(r.message)}</p>`;
      $("edCovers").innerHTML = "";
      return;
    }
    const strip = Object.entries(r.band_counts)
      .filter(([, n]) => n > 0)
      .map(([b, n]) => `<span class="fill-${b}" style="flex:${n}"></span>`).join("");

    $("edReadiness").innerHTML = `
      <div class="rtop">
        <span class="rnum">${Math.round(r.readiness * 100)}%</span>
        <span class="rlabel">readiness · ${r.concepts_total} concepts mapped
          ${r.concepts_untested ? `· ${r.concepts_untested} never practised` : ""}</span>
      </div>
      <span class="rbar"><span class="rfill" style="width:${r.readiness * 100}%"></span></span>
      <div class="bandstrip">${strip}</div>
      <p class="caveat">${esc(r.caveat)}</p>
      <h4>Highest risk</h4>
      <div class="weaklist">${r.high_risk.map((c) => `
        <button class="weakrow" data-concept="${esc(c.concept_id)}">
          <span class="rank"></span>
          <span class="wname">${esc(c.name)}<span class="wtopic">${esc(c.topic)}${
            c.emphasis_boost > 0 ? " · emphasised" : ""}</span></span>
          <span class="bandchip band-${c.band}">${
            (BANDS.find((b) => b[0] === c.band) || [, c.band])[1]}</span>
          <span class="wpct">${Math.round(c.effective * 100)}%</span>
        </button>`).join("")}</div>
      ${r.likely_secure.length ? `<h4>Likely secure</h4><p class="hint">${
        r.likely_secure.map((c) => esc(c.name)).join(", ")}</p>` : ""}`;

    $("edReadiness").querySelectorAll(".weakrow").forEach((b) =>
      b.addEventListener("click", () => { showConcept(b.dataset.concept); }));

    const cs = await api(`/api/exams/${eid}/concepts`);
    $("edCovers").innerHTML = cs.concepts.map((c) =>
      `<span class="chipx">${esc(c.name)}</span>`).join("")
      || `<span class="hint">Nothing mapped yet.</span>`;
  } catch (e) { toast(e.message, true); }
}

/* The page used to open on a list and wait. The reason to be here is almost
   always the next paper, so that is what it opens on. */
async function openNextExam() {
  await loadOrg();
  const upcoming = (org.exams || [])
    .filter((e) => e.days_left !== null && e.days_left >= 0)
    .sort((a, b) => a.days_left - b.days_left);
  const none = !(org.exams || []).length;
  $("planEmpty").hidden = !none;
  if (none) { $("examDetail").hidden = true; return; }
  const pick = upcoming[0] || org.exams[org.exams.length - 1];
  if (pick && $("examDetail").hidden) selectExam(pick.id);
}

if ($("planAddExam")) {
  $("planAddExam").addEventListener("click", () => $("newExamBtn").click());
}

/* Turns the exam into a session rather than describing one. */
$("edStudy").addEventListener("click", () => {
  if (!org.selectedExam) { toast("Pick an exam first."); return; }
  scopeState.exam_ids = [org.selectedExam];
  scopeState.upload_ids = [];
  scopeState.include_unmapped = false;
  navigate("quiz");
  if (typeof refreshScopeCount === "function") refreshScopeCount();
  if (typeof renderScopeMaterial === "function") renderScopeMaterial();
  toast("Practice is now scoped to this exam.");
});

/* Attach topics/concepts to an exam. */
let suggestTimer = null;
$("edTopicSearch").addEventListener("input", () => {
  clearTimeout(suggestTimer);
  const q = $("edTopicSearch").value.trim();
  if (q.length < 2) { $("edSuggest").hidden = true; return; }
  suggestTimer = setTimeout(async () => {
    try {
      const r = await api(`/api/topic-search?q=${encodeURIComponent(q)}`);
      $("edSuggest").hidden = !r.results.length;
      $("edSuggest").innerHTML = r.results.map((x) =>
        `<button data-kind="${esc(x.kind)}" data-id="${esc(x.id)}">
          <span class="skind">${esc(x.kind)}</span>${esc(x.label)}</button>`).join("");
      $("edSuggest").querySelectorAll("button").forEach((b) =>
        b.addEventListener("click", () => addCoverage(b.dataset.kind, b.dataset.id)));
    } catch { /* search is a convenience */ }
  }, 220);
});

async function addCoverage(kind, id) {
  const eid = org.selectedExam;
  const exam = await api(`/api/exams/${eid}`);
  const key = kind === "topic" ? "topic_ids" : "concept_ids";
  const next = [...new Set([...(exam[key] || []), id])];
  await api(`/api/exams/${eid}`, {
    method: "PATCH", body: JSON.stringify({ [key]: next }),
  });
  $("edTopicSearch").value = "";
  $("edSuggest").hidden = true;
  loadReadiness(eid);
  toast("Added to this exam.");
}

/* ------------------------------ emphasis ------------------------------ */

async function loadEmphasis(eid) {
  try {
    const r = await api(`/api/emphasis?exam_id=${eid}`);
    if (!$("emphWho").options.length) {
      $("emphWho").innerHTML = r.said_by.map((s) =>
        `<option value="${esc(s)}">${esc(s)}</option>`).join("");
      $("emphStrength").innerHTML = r.strengths.map((s) =>
        `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    }
    renderEmphasis(r.notes);
  } catch (e) { toast(e.message, true); }
}

function renderEmphasis(notes) {
  $("emphList").innerHTML = notes.length ? notes.map((n) => `
    <div class="emph ${n.applied ? "applied" : ""}">
      <div class="etext">${esc(n.text)}</div>
      <div class="emeta">${esc(n.said_by)} · ${esc(n.strength)}${
        n.concepts.length ? " · " + n.concepts.map((c) => esc(c.name)).join(", ")
                          : " · no concepts matched yet"}</div>
      <div class="eacts">
        ${n.concepts.length ? `<button class="btn small ${n.applied ? "ghost" : ""}"
          data-apply="${esc(n.id)}" data-on="${n.applied ? "0" : "1"}">${
          n.applied ? `Undo +${n.proposed_boost} priority` : `Apply +${n.proposed_boost} priority`
        }</button>` : `<button class="btn small ghost" data-link="${esc(n.id)}">Find concepts</button>`}
        <button class="btn small ghost" data-del="${esc(n.id)}">Delete</button>
      </div>
    </div>`).join("")
    : `<p class="hint">Nothing recorded yet. Write down what a professor stressed and it becomes part of what the engine prioritises — once you confirm it.</p>`;

  $("emphList").querySelectorAll("[data-apply]").forEach((b) =>
    b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        await api(`/api/emphasis/${b.dataset.apply}/apply`, {
          method: "POST", body: JSON.stringify({ apply: b.dataset.on === "1" }),
        });
        await loadEmphasis(org.selectedExam);
        loadReadiness(org.selectedExam);
      } catch (e) { toast(e.message, true); b.disabled = false; }
    }));

  $("emphList").querySelectorAll("[data-link]").forEach((b) =>
    b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "Looking…";
      try {
        await api(`/api/emphasis/${b.dataset.link}/link`, { method: "POST" });
        loadEmphasis(org.selectedExam);
      } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = "Find concepts"; }
    }));

  $("emphList").querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/emphasis/${b.dataset.del}`, { method: "DELETE" });
      loadEmphasis(org.selectedExam);
      loadReadiness(org.selectedExam);
    }));
}

$("emphAdd").addEventListener("click", async () => {
  const text = $("emphText").value.trim();
  if (!text) { toast("Write down what you were told first."); return; }
  const btn = $("emphAdd");
  btn.disabled = true; btn.textContent = "Saving…";
  try {
    await api("/api/emphasis", {
      method: "POST",
      body: JSON.stringify({
        text, exam_id: org.selectedExam,
        said_by: $("emphWho").value, strength: $("emphStrength").value,
      }),
    });
    $("emphText").value = "";
    loadEmphasis(org.selectedExam);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Save"; }
});
$("emphText").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("emphAdd").click();
});

/* -------------------------------- chat -------------------------------- */

async function loadChat(eid) {
  try {
    const r = await api(`/api/chats?exam_id=${eid}`);
    if (r.chats.length) {
      const c = await api(`/api/chats/${r.chats[0].id}`);
      org.chatId = c.id;
      renderChat(c.messages);
    } else {
      org.chatId = null;
      renderChat([]);
    }
  } catch (e) { renderChat([]); }
}

function renderChat(messages) {
  $("chatLog").innerHTML = messages.length
    ? messages.map((m) => `<div class="msg ${esc(m.role)}">${
        m.role === "assistant" ? md(m.content) : esc(m.content)}</div>`).join("")
    : `<div class="chatempty">Ask about this exam. It already knows your mastery data
        and everything you've recorded about what was emphasised.</div>`;
  $("chatLog").scrollTop = $("chatLog").scrollHeight;
}

$("chatSend").addEventListener("click", async () => {
  const text = $("chatInput").value.trim();
  if (!text) return;
  if (!org.selectedExam) { toast("Pick an exam first."); return; }

  const btn = $("chatSend");
  btn.disabled = true;
  $("chatInput").value = "";
  $("chatLog").insertAdjacentHTML("beforeend",
    `<div class="msg user">${esc(text)}</div>
     <div class="msg assistant" id="pending">…</div>`);
  $("chatLog").scrollTop = $("chatLog").scrollHeight;

  try {
    if (!org.chatId) {
      const c = await api("/api/chats", {
        method: "POST", body: JSON.stringify({ exam_id: org.selectedExam }),
      });
      org.chatId = c.id;
    }
    const c = await api(`/api/chats/${org.chatId}/send`, {
      method: "POST", body: JSON.stringify({ text }),
    });
    renderChat(c.messages);
  } catch (e) {
    const p = $("pending");
    if (p) { p.textContent = e.message; p.style.color = "var(--bad)"; }
    toast(e.message, true);
  } finally { btn.disabled = false; }
});
$("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("chatSend").click();
});

/* ------------------------------ study plan ---------------------------- */

$("planBuild").addEventListener("click", async () => {
  if (!org.selectedExam) { toast("Pick an exam first."); return; }
  const btn = $("planBuild");
  btn.disabled = true; btn.textContent = "Building…";
  try {
    const plan = await api("/api/plan/build", {
      method: "POST",
      body: JSON.stringify({
        exam_id: org.selectedExam,
        minutes_per_day: parseInt($("planMinutes").value, 10) || 60,
      }),
    });
    org.plan = plan;
    renderPlan(plan);
    $("planStrategy").hidden = false;
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Build plan"; }
});

function renderPlan(p) {
  const out = $("planOut");
  out.hidden = false;
  out.innerHTML = `
    <div class="planhead">
      <div class="planstat"><div class="pv">${p.days_left}</div><div class="pl">days left</div></div>
      <div class="planstat"><div class="pv">${p.study_days}</div><div class="pl">study days</div></div>
      <div class="planstat"><div class="pv">${p.scheduled_questions}</div><div class="pl">questions</div></div>
      <div class="planstat"><div class="pv">${p.concepts_covered}</div><div class="pl">concepts covered</div></div>
    </div>
    ${p.warnings.map((w) => `<div class="warnbox">${esc(w)}</div>`).join("")}
    ${p.concepts_dropped.length ? `<h4>Didn't fit</h4>
      <p class="hint">${p.concepts_dropped.map((c) => esc(c.name)).join(", ")}</p>` : ""}
    <div id="planStrategyOut"></div>
    <h4>Day by day</h4>
    ${p.days.map((d) => `
      <div class="planday ${d.is_exam_eve ? "eve" : ""}">
        <div class="pdhead">
          <span class="pddate">${esc(d.weekday)} ${esc(d.date.slice(5))}</span>
          ${d.is_exam_eve ? '<span class="bandchip band-dark_green">exam eve</span>' : ""}
          <span class="pdmeta">${d.minutes} min · ${d.questions} q</span>
        </div>
        ${d.blocks.map((b) => `
          <div class="planblock ${b.kind === "review" ? "review" : ""}">
            <span class="pbmin">${b.minutes}m</span>
            <span class="pblabel">${esc(b.label)}${
              b.note ? `<br><span class="hint">${esc(b.note)}</span>` : ""}</span>
          </div>`).join("") || '<p class="hint">Rest day.</p>'}
      </div>`).join("")}`;
}

$("planStrategy").addEventListener("click", async () => {
  if (!org.plan) return;
  const btn = $("planStrategy");
  btn.disabled = true; btn.textContent = "Thinking…";
  try {
    const s = await api("/api/plan/strategy", {
      method: "POST", body: JSON.stringify({ plan: org.plan }),
    });
    $("planStrategyOut").innerHTML = `
      <div class="ecard">
        <h4>How to work this plan</h4>
        <p><b>${esc(s.headline)}</b></p>
        <div>${md(s.approach)}</div>
        <h4>Every day</h4><p>${esc(s.per_day_tip)}</p>
        <h4>Watch out for</h4><p>${esc(s.watch_out)}</p>
        <div class="md">${md(s.table)}</div>
      </div>`;
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "How should I work it?"; }
});

/* -------------------------------- vault ------------------------------- */

const VAULT_KINDS = [
  ["photo", "Photo"], ["whiteboard", "Whiteboard brain dump"],
  ["question", "Exam question"], ["handout", "Handout"], ["note", "Note"],
];

function fillExamPickers() {
  const opts = [`<option value="">Not linked to an exam</option>`].concat(
    org.exams.map((e) => `<option value="${esc(e.id)}">${esc(e.name)}</option>`)).join("");
  if ($("vaultExam")) $("vaultExam").innerHTML = opts;
  if ($("vaultKind") && !$("vaultKind").options.length) {
    $("vaultKind").innerHTML = VAULT_KINDS.map(([v, l]) =>
      `<option value="${v}">${l}</option>`).join("");
  }
  if ($("vaultFilter") && !$("vaultFilter").options.length) {
    $("vaultFilter").innerHTML = [`<option value="">Everything</option>`].concat(
      VAULT_KINDS.map(([v, l]) => `<option value="${v}">${l}</option>`)).join("");
  }
}

const vDrop = $("vaultDrop");
vDrop.addEventListener("click", () => $("vaultInput").click());
["dragenter", "dragover"].forEach((ev) =>
  vDrop.addEventListener(ev, (e) => { e.preventDefault(); vDrop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) =>
  vDrop.addEventListener(ev, (e) => { e.preventDefault(); vDrop.classList.remove("over"); }));
vDrop.addEventListener("drop", (e) => vaultUpload(e.dataTransfer.files));
$("vaultInput").addEventListener("change", () => vaultUpload($("vaultInput").files));

async function vaultUpload(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  fd.append("kind", $("vaultKind").value);
  fd.append("caption", $("vaultCaption").value);
  if ($("vaultExam").value) {
    fd.append("link_kind", "exam");
    fd.append("link_target", $("vaultExam").value);
  }
  try {
    const res = await fetch("/api/vault/upload", { method: "POST", body: fd });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    (body.errors || []).forEach((e) => toast(e, true));
    $("vaultCaption").value = "";
    loadVault();
    toast(`${body.assets.length} file(s) saved.`);
  } catch (e) { toast(e.message, true); }
  $("vaultInput").value = "";
}

async function loadVault() {
  try {
    const kind = $("vaultFilter").value;
    const r = await api(`/api/vault${kind ? `?kind=${kind}` : ""}`);
    org.assets = r.assets;
    renderVault();
  } catch (e) { toast(e.message, true); }
}
$("vaultFilter").addEventListener("change", loadVault);

function renderVault() {
  $("vaultGrid").innerHTML = org.assets.length ? org.assets.map((a) => `
    <div class="vitem">
      ${a.is_image
        ? `<img src="/api/vault/${esc(a.id)}/file" alt="${esc(a.caption || a.filename)}"
             data-open="${esc(a.id)}">`
        : `<div class="vdoc">▤</div>`}
      <div class="vbody">
        <div class="vcap">${esc(a.caption || a.filename)}</div>
        <div class="vmeta">${esc(a.kind)} · ${new Date(a.added_at * 1000).toLocaleDateString()}</div>
        <div class="vacts">
          ${a.is_image ? `<button class="btn small" data-analyse="${esc(a.id)}">${
            a.analysis ? "Re-read" : "Read it"}</button>` : ""}
          <button class="btn small ghost" data-vdel="${esc(a.id)}">Delete</button>
        </div>
      </div>
      ${a.analysis ? renderAnalysis(a.analysis) : ""}
    </div>`).join("")
    : `<p class="hint">Nothing saved yet. Photograph a whiteboard, a question you got wrong, or a handout.</p>`;

  $("vaultGrid").querySelectorAll("[data-open]").forEach((i) =>
    i.addEventListener("click", () =>
      window.open(`/api/vault/${i.dataset.open}/file`, "_blank")));

  $("vaultGrid").querySelectorAll("[data-analyse]").forEach((b) =>
    b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "Reading…";
      try {
        await api(`/api/vault/${b.dataset.analyse}/analyse`, { method: "POST" });
        loadVault();
      } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = "Read it"; }
    }));

  $("vaultGrid").querySelectorAll("[data-vdel]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/vault/${b.dataset.vdel}`, { method: "DELETE" });
      loadVault();
    }));
}

/* The gaps are the point: what a complete answer would contain that you didn't write down. */
function renderAnalysis(a) {
  return `<div class="vanalysis">
    <h5>What this is</h5><p>${esc(a.summary)}</p>
    ${a.recalled && a.recalled.length ? `<h5 class="got">You had</h5>
      <p class="got">${a.recalled.map(esc).join(" · ")}</p>` : ""}
    ${a.missing && a.missing.length ? `<h5 class="gap">Missing</h5><ul>${
      a.missing.map((m) => `<li class="gap"><b>${esc(m.name)}</b> — ${
        esc(m.why_it_matters)}</li>`).join("")}</ul>` : ""}
    ${a.errors && a.errors.length ? `<h5>Corrections</h5><ul>${
      a.errors.map((e) => `<li><s>${esc(e.wrote)}</s> → ${esc(e.correction)}</li>`).join("")
    }</ul>` : ""}
    ${a.legibility ? `<h5>Legibility</h5><p class="hint">${esc(a.legibility)}</p>` : ""}
  </div>`;
}

/* ------------------------------- pinboard ----------------------------- */

const PIN_KINDS = [["note", "Note"], ["mnemonic", "Mnemonic"], ["topic", "Topic"],
                   ["question", "Question"], ["image", "Image"], ["link", "Link"]];

async function loadPins(tag) {
  try {
    const r = await api(`/api/pins${tag ? `?tag=${encodeURIComponent(tag)}` : ""}`);
    org.pins = r.pins;
    $("pinTags").innerHTML = r.tags.map((t) =>
      `<span class="chipx clickable ${tag === t.tag ? "on" : ""}" data-tag="${esc(t.tag)}">${
        esc(t.tag)} <b>${t.count}</b></span>`).join("");
    $("pinTags").querySelectorAll("[data-tag]").forEach((c) =>
      c.addEventListener("click", () =>
        loadPins(tag === c.dataset.tag ? null : c.dataset.tag)));
    renderPins();
  } catch (e) { toast(e.message, true); }
}

function renderPins() {
  $("pinGrid").innerHTML = org.pins.length ? org.pins.map((p) => `
    <div class="pin k-${esc(p.kind)} ${p.starred ? "starred" : ""}">
      <div class="ptitle">${esc(p.title)}</div>
      ${p.asset_id ? `<img src="/api/vault/${esc(p.asset_id)}/file" alt="">` : ""}
      ${p.body ? `<div class="pbody">${esc(p.body)}</div>` : ""}
      <div class="pfoot">
        <span class="pkind">${esc(p.kind)}</span>
        ${p.tags.map((t) => `<span class="chipx">${esc(t)}</span>`).join("")}
        ${p.exam_name ? `<span class="chipx">${esc(p.exam_name)}</span>` : ""}
        <button class="btn small ghost" data-star="${esc(p.id)}" data-on="${p.starred ? "0" : "1"}">${
          p.starred ? "Unstar" : "Star"}</button>
        <button class="btn small ghost" data-pdel="${esc(p.id)}">Delete</button>
      </div>
    </div>`).join("")
    : `<p class="hint">Nothing pinned yet.</p>`;

  $("pinGrid").querySelectorAll("[data-star]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/pins/${b.dataset.star}`, {
        method: "PATCH", body: JSON.stringify({ starred: b.dataset.on === "1" }),
      });
      loadPins();
    }));
  $("pinGrid").querySelectorAll("[data-pdel]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/pins/${b.dataset.pdel}`, { method: "DELETE" });
      loadPins();
    }));
}

$("newPinBtn").addEventListener("click", () => {
  modal("New pin", [
    { name: "title", label: "Title", placeholder: "Winter's formula" },
    { name: "kind", label: "Kind", type: "select", value: "note",
      options: PIN_KINDS.map(([v, l]) => ({ value: v, label: l })) },
    { name: "body", label: "Body", type: "textarea",
      placeholder: "expected pCO2 = 1.5 x HCO3 + 8 (+/- 2)" },
    { name: "tags", label: "Tags (comma separated)", placeholder: "renal, formula" },
    { name: "exam_id", label: "Exam", type: "select",
      options: [{ value: "", label: "—" }].concat(
        org.exams.map((e) => ({ value: e.id, label: e.name }))) },
  ], async (v) => {
    if (!v.title) throw new Error("A pin needs a title.");
    await api("/api/pins", {
      method: "POST",
      body: JSON.stringify({
        ...v, tags: v.tags ? v.tags.split(",").map((t) => t.trim()) : [],
      }),
    });
    loadPins();
  });
});

/* ------------------------------ tab wiring ---------------------------- */

onEnter("vault", () => { fillExamPickers(); loadVault(); });
onEnter("board", () => loadPins());

loadOrg();

/* =================== phase 4: scope filter + skill drills ===============
   Scope decides what the engine is allowed to serve. Drills are short games
   built from your own concepts, aimed at the specific subtest pattern - and
   framed honestly about what they can and cannot do. */

const scopeState = {
  term_id: null, course_id: null, exam_ids: [],
  exclude_past: false, include_unmapped: true,
  options: null,
};

function currentScope() {
  return {
    term_id: scopeState.term_id,
    course_id: scopeState.course_id,
    exam_ids: scopeState.exam_ids,
    exclude_past: scopeState.exclude_past,
    include_unmapped: scopeState.include_unmapped,
  };
}

$("scopeToggle").addEventListener("click", () => {
  const panel = $("scopePanel");
  panel.hidden = !panel.hidden;
  $("scopeToggle").classList.toggle("open", !panel.hidden);
  if (!panel.hidden && !scopeState.options) loadScopeOptions();
  // Presets render inside loadScopeOptions, which is skipped when options are
  // already cached - and the library tab caches them. Render them here too so
  // opening the panel always fills the row.
  if (!panel.hidden) {
    const box = $("scopePresets");
    if (box && !box.children.length) renderScopePresets(box, applyScopePreset);
  }
});

async function loadScopeOptions() {
  try {
    const o = await api("/api/scope/options");
    scopeState.options = o;

    $("scopeTerm").innerHTML = [`<option value="">Any term</option>`].concat(
      o.terms.map((t) => `<option value="${esc(t.id)}"${
        t.active ? " data-active=1" : ""}>${esc(t.name)}${
        t.active ? " (current)" : ""}</option>`)).join("");
    renderScopeChildren();

    if ($("scopePresets")) {
      renderScopePresets($("scopePresets"), applyScopePreset);
    }

    // If you have past exams, that filter is the one you probably wants.
    if (o.has_past_exams && !scopeState.exclude_past) {
      $("scopeExcludePast").parentElement.classList.add("suggested");
    }
    refreshScopeCount();
  } catch (e) { toast(e.message, true); }
}

function renderScopeChildren() {
  const o = scopeState.options;
  if (!o) return;
  const courses = o.courses.filter(
    (c) => !scopeState.term_id || c.term_id === scopeState.term_id);
  $("scopeCourse").innerHTML = [`<option value="">Any course</option>`].concat(
    courses.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`)).join("");

  const exams = o.exams.filter((e) =>
    (!scopeState.term_id || e.term_id === scopeState.term_id) &&
    (!scopeState.course_id || e.course_id === scopeState.course_id));
  $("scopeExam").innerHTML = [`<option value="">Any exam</option>`].concat(
    exams.map((e) => `<option value="${esc(e.id)}">${esc(e.name)}${
      e.past ? " (sat)" : ""} · ${e.concepts} concepts</option>`)).join("");
}

async function refreshScopeCount() {
  try {
    const d = await api("/api/scope/describe", {
      method: "POST", body: JSON.stringify({ scope: currentScope() }),
    });
    $("scopeSummary").textContent = d.summary;
    $("scopeCount").textContent = `${d.concepts} of ${d.total} concepts in scope`;
    $("scopeWarn").hidden = !d.warning;
    $("scopeWarn").textContent = d.warning || "";
    $("startAdaptive").disabled = d.concepts === 0;
  } catch (e) { /* the picker still works without a live count */ }
}

$("scopeTerm").addEventListener("change", () => {
  scopeState.term_id = $("scopeTerm").value || null;
  scopeState.course_id = null;
  scopeState.exam_ids = [];
  renderScopeChildren();
  refreshScopeCount();
});
$("scopeCourse").addEventListener("change", () => {
  scopeState.course_id = $("scopeCourse").value || null;
  scopeState.exam_ids = [];
  renderScopeChildren();
  refreshScopeCount();
});
$("scopeExam").addEventListener("change", () => {
  scopeState.exam_ids = $("scopeExam").value ? [$("scopeExam").value] : [];
  refreshScopeCount();
});
$("scopeExcludePast").addEventListener("change", () => {
  scopeState.exclude_past = $("scopeExcludePast").checked;
  refreshScopeCount();
});
$("scopeUnmapped").addEventListener("change", () => {
  scopeState.include_unmapped = $("scopeUnmapped").checked;
  refreshScopeCount();
});
$("scopeReset").addEventListener("click", () => {
  Object.assign(scopeState, {
    term_id: null, course_id: null, exam_ids: [],
    exclude_past: false, include_unmapped: true,
  });
  $("scopeTerm").value = "";
  $("scopeCourse").value = "";
  $("scopeExam").value = "";
  $("scopeExcludePast").checked = false;
  $("scopeUnmapped").checked = true;
  renderScopeChildren();
  refreshScopeCount();
});

/* ================================ drills ============================== */

const drill = { def: null, data: null, round: 0, correct: 0, span: 3,
                picks: [], buckets: [], startedAt: 0 };

async function loadDrills() {
  try {
    const [av, hist] = await Promise.all([
      api("/api/drills", { method: "POST", body: JSON.stringify({ scope: currentScope() }) }),
      api("/api/drills/history"),
    ]);
    $("drillHonesty").textContent = av.honesty;
    $("drillPicker").innerHTML = av.drills.map((d) => {
      const b = hist.best[d.id] || {};
      return `<button class="drillcard" data-drill="${esc(d.id)}"${
        d.available ? "" : " disabled"}>
        <span class="dname">${esc(d.name)}</span>
        <span class="dtag">${esc(d.tagline)}</span>
        <span class="dtargets">${esc(d.targets)}</span>
        <span class="dwhy">${esc(d.why)}</span>
        ${d.available
          ? `<span class="dbest">${b.sessions
              ? `${b.sessions} run${b.sessions === 1 ? "" : "s"}${
                  b.best_span ? ` · best span ${b.best_span}` : ""}`
              : "not tried yet"}</span>`
          : `<span class="dblocked">${esc(d.reason || "")}</span>`}
      </button>`;
    }).join("");

    $("drillPicker").querySelectorAll("[data-drill]").forEach((b) =>
      b.addEventListener("click", () => startDrill(b.dataset.drill)));

    renderDrillHistory(hist);
  } catch (e) { toast(e.message, true); }
}

function renderDrillHistory(hist) {
  if (!hist.runs.length) { $("drillHistory").hidden = true; return; }
  $("drillHistory").hidden = false;
  $("dhBody").innerHTML = `
    ${hist.trend ? `<p class="trendline">Your last three sequence runs averaged
      <b>${hist.trend.recent}</b> items, against <b>${hist.trend.earlier}</b>
      earlier. That's a comparison with yourself only — there's no norm here.</p>` : ""}
    <div class="runlist">${hist.runs.slice(0, 12).map((r) => `
      <div class="runrow">
        <span class="rdate">${new Date(r.ts * 1000).toLocaleDateString()}</span>
        <span>${esc(r.drill)}</span>
        <span class="rscore">${r.correct}/${r.rounds}</span>
        <span class="rscore">${r.span ? `span ${r.span}` : ""}</span>
      </div>`).join("")}</div>`;
}

async function startDrill(id) {
  const av = await api("/api/drills", {
    method: "POST", body: JSON.stringify({ scope: currentScope() }),
  });
  drill.def = av.drills.find((d) => d.id === id);
  drill.round = 0;
  drill.correct = 0;
  drill.picks = [];
  drill.startedAt = performance.now();

  try {
    drill.data = await api("/api/drills/build", {
      method: "POST",
      body: JSON.stringify({ drill: id, rounds: 6, span: drill.span,
                             scope: currentScope() }),
    });
  } catch (e) { toast(e.message, true); return; }

  $("drillPicker").hidden = true;
  $("drillStage").hidden = false;
  $("dsName").textContent = drill.def.name;
  $("dsInstruction").textContent = drill.data.instruction || "";
  $("dsFeedback").innerHTML = "";
  runRound();
}

$("dsQuit").addEventListener("click", endDrill);

async function endDrill(save = true) {
  const rounds = drill.data && drill.data.rounds ? drill.data.rounds.length : 1;
  if (save && drill.round > 0) {
    try {
      await api("/api/drills/result", {
        method: "POST",
        body: JSON.stringify({
          drill: drill.def.id,
          score: drill.round ? drill.correct / drill.round : 0,
          rounds: drill.round, correct: drill.correct,
          span: drill.def.id === "sequence" ? drill.span : null,
          ms: Math.round(performance.now() - drill.startedAt),
        }),
      });
    } catch { /* a lost drill score is not worth an error toast */ }
  }
  $("drillStage").hidden = true;
  $("drillPicker").hidden = false;
  loadDrills();
}

function drillProgress() {
  const total = drill.data.rounds ? drill.data.rounds.length : 1;
  return `<div class="drillmeta">
    <span>round ${Math.min(drill.round + 1, total)} / ${total}</span>
    <span>${drill.correct} right</span>
    ${drill.def.id === "sequence" ? `<span>span ${drill.span}</span>` : ""}
  </div>`;
}

function runRound() {
  const kind = drill.def.id;
  if (kind === "sequence") return roundSequence();
  if (kind === "oddone") return roundOddOne();
  if (kind === "name") return roundName();
  if (kind === "chunk") return roundChunk();
}

/* --- Sequence: watch the run, play it back ---------------------------- */

async function roundSequence() {
  const r = drill.data.rounds[drill.round];
  if (!r) return finishDrill();
  drill.picks = [];

  $("dsBody").innerHTML = drillProgress() + `
    <div class="seqorder" id="seqOrder"></div>
    <div class="seqgrid" id="seqGrid">${r.grid.map((g) =>
      `<button class="seqtile" data-id="${esc(g.id)}" disabled>${esc(g.name)}</button>`
    ).join("")}</div>`;
  $("dsFeedback").innerHTML = "";

  const tiles = [...$("seqGrid").querySelectorAll(".seqtile")];
  const byId = Object.fromEntries(tiles.map((t) => [t.dataset.id, t]));

  // Show the run. Unhurried on purpose - this is not a speed task.
  await new Promise((res) => setTimeout(res, 500));
  for (const id of r.sequence) {
    byId[id].classList.add("lit");
    await new Promise((res) => setTimeout(res, 750));
    byId[id].classList.remove("lit");
    await new Promise((res) => setTimeout(res, 260));
  }

  tiles.forEach((t) => {
    t.disabled = false;
    t.addEventListener("click", () => {
      if (drill.picks.includes(t.dataset.id)) return;
      drill.picks.push(t.dataset.id);
      t.classList.add("picked");
      $("seqOrder").innerHTML = drill.picks.map((id, i) =>
        `<span class="slot">${i + 1}. ${esc(byId[id].textContent)}</span>`).join("");
      if (drill.picks.length === r.sequence.length) gradeSequence(r, byId, tiles);
    });
  });
}

function gradeSequence(r, byId, tiles) {
  tiles.forEach((t) => { t.disabled = true; });
  let hits = 0;
  r.sequence.forEach((id, i) => {
    const ok = drill.picks[i] === id;
    if (ok) hits++;
    byId[id].classList.remove("picked");
    byId[id].classList.add(ok ? "right" : "wrong");
  });
  const perfect = hits === r.sequence.length;
  if (perfect) drill.correct++;

  $("dsFeedback").innerHTML = `
    <div class="drillverdict ${perfect ? "right" : "wrong"}">
      ${perfect ? `All ${hits} in order.`
                : `${hits} of ${r.sequence.length} in the right place.`}
    </div>
    <p class="hint">Correct order: ${r.sequence.map((id) =>
      esc(byId[id].textContent)).join(" → ")}</p>
    <button class="btn primary" id="dsNext">Next round</button>`;

  // Adapt to sit at your edge rather than march a fixed ladder.
  drill.span = perfect ? Math.min(7, drill.span + 1)
             : hits / r.sequence.length < 0.5 ? Math.max(2, drill.span - 1)
             : drill.span;

  $("dsNext").addEventListener("click", async () => {
    drill.round++;
    if (drill.round >= drill.data.rounds.length) return finishDrill();
    // Rebuild so the next run uses the adapted span.
    drill.data = await api("/api/drills/build", {
      method: "POST",
      body: JSON.stringify({ drill: "sequence",
                             rounds: drill.data.rounds.length - drill.round,
                             span: drill.span, scope: currentScope() }),
    });
    drill.round = 0;
    drill.data.rounds = drill.data.rounds.slice(0, 1);
    roundSequence();
  }, { once: true });
}

/* --- Odd one out: the rule flips every round -------------------------- */

function roundOddOne() {
  const r = drill.data.rounds[drill.round];
  if (!r) return finishDrill();
  const switched = drill.round > 0 &&
                   drill.data.rounds[drill.round - 1].rule !== r.rule;

  $("dsBody").innerHTML = drillProgress() + `
    <div class="rulebar ${switched ? "switched" : ""}">
      ${switched ? "⇄ The rule just changed — " : ""}${esc(r.prompt)}
    </div>
    <div class="oddgrid">${r.options.map((o) => `
      <button class="oddopt" data-id="${esc(o.id)}">
        <span class="oname">${esc(o.name)}</span>
        ${o.hint ? `<span class="ohint">${esc(o.hint)}</span>` : ""}
      </button>`).join("")}</div>`;
  $("dsFeedback").innerHTML = "";

  $("dsBody").querySelectorAll(".oddopt").forEach((b) =>
    b.addEventListener("click", () => {
      const ok = b.dataset.id === r.answer;
      if (ok) drill.correct++;
      $("dsBody").querySelectorAll(".oddopt").forEach((x) => {
        x.disabled = true;
        if (x.dataset.id === r.answer) x.classList.add("right");
        else if (x === b) x.classList.add("wrong");
      });
      $("dsFeedback").innerHTML = `
        <div class="drillverdict ${ok ? "right" : "wrong"}">
          ${ok ? "Right." : "Not that one."}
        </div>
        <p class="hint">${esc(r.because)}</p>
        <button class="btn primary" id="dsNext">Next round</button>`;
      $("dsNext").addEventListener("click", () => {
        drill.round++;
        drill.round >= drill.data.rounds.length ? finishDrill() : roundOddOne();
      }, { once: true });
    }));
}

/* --- Name it: untimed, generous, cue on request ----------------------- */

function roundName() {
  const r = drill.data.rounds[drill.round];
  if (!r) return finishDrill();
  let usedCue = false;

  $("dsBody").innerHTML = drillProgress() + `
    <div class="namecard">
      <div class="nameclue">${esc(r.clue)}</div>
      <input type="text" class="namein" id="nameIn" placeholder="Type the term…"
             autocomplete="off" spellcheck="false">
      <div class="row">
        <button class="btn primary" id="nameGo">Check</button>
        <button class="btn ghost small" id="nameCue">Need a cue?</button>
      </div>
      <div class="cue" id="nameCueBox" hidden></div>
    </div>`;
  $("dsFeedback").innerHTML = "";
  setTimeout(() => $("nameIn").focus(), 40);

  $("nameCue").addEventListener("click", () => {
    usedCue = true;
    $("nameCueBox").hidden = false;
    $("nameCueBox").textContent = r.cue;
    $("nameCue").disabled = true;
  });

  const submit = () => {
    const given = $("nameIn").value;
    // Same generous matcher as practice: word-finding speed is never the test.
    const ok = matches(given, { answer_text: r.answer, accepted_answers: r.accepted });
    if (ok) drill.correct++;
    $("dsFeedback").innerHTML = `
      <div class="drillverdict ${ok ? (usedCue ? "neutral" : "right") : "wrong"}">
        ${ok ? (usedCue
                ? "Right — with the cue. You knew it; the word was just slow."
                : "Right.")
             : `The term is: ${esc(r.answer)}`}
      </div>
      <button class="btn primary" id="dsNext">Next</button>`;
    $("dsNext").addEventListener("click", () => {
      drill.round++;
      drill.round >= drill.data.rounds.length ? finishDrill() : roundName();
    }, { once: true });
  };
  $("nameGo").addEventListener("click", submit, { once: true });
  $("nameIn").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("nameGo").click();
  });
}

/* --- Chunk it: group a long list, name the groups --------------------- */

function roundChunk() {
  const d = drill.data;
  drill.buckets = Array.from({ length: d.buckets }, () => ({ name: "", items: [] }));
  let active = 0;

  const draw = () => {
    const placed = new Set(drill.buckets.flatMap((b) => b.items.map((i) => i.id)));
    $("dsBody").innerHTML = `
      <p class="hint">${esc(d.note)}</p>
      <div class="chunkpool">${d.items.map((i) => `
        <button class="chunkitem ${placed.has(i.id) ? "used" : ""}"
                data-id="${esc(i.id)}"${placed.has(i.id) ? " disabled" : ""}>
          ${esc(i.name)}</button>`).join("")}</div>
      <div class="buckets">${drill.buckets.map((b, n) => `
        <div class="bucket ${n === active ? "active" : ""}" data-b="${n}">
          <input type="text" placeholder="Group ${n + 1} name…"
                 value="${esc(b.name)}" data-name="${n}">
          <div class="bitems">${b.items.map((i) => `
            <span class="bitem">${esc(i.name)}
              <button data-remove="${esc(i.id)}" data-from="${n}">×</button></span>`
          ).join("")}</div>
        </div>`).join("")}</div>
      <button class="btn primary" id="chunkDone"${
        placed.size === d.items.length ? "" : " disabled"}>
        ${placed.size === d.items.length ? "Done" : `${
          d.items.length - placed.size} left to place`}</button>`;

    $("dsBody").querySelectorAll(".bucket").forEach((el) =>
      el.addEventListener("click", (e) => {
        if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
        active = parseInt(el.dataset.b, 10);
        draw();
      }));
    $("dsBody").querySelectorAll("[data-name]").forEach((el) =>
      el.addEventListener("input", () => {
        drill.buckets[parseInt(el.dataset.name, 10)].name = el.value;
      }));
    $("dsBody").querySelectorAll(".chunkitem:not([disabled])").forEach((b) =>
      b.addEventListener("click", () => {
        const item = d.items.find((i) => i.id === b.dataset.id);
        drill.buckets[active].items.push(item);
        draw();
      }));
    $("dsBody").querySelectorAll("[data-remove]").forEach((b) =>
      b.addEventListener("click", () => {
        const n = parseInt(b.dataset.from, 10);
        drill.buckets[n].items = drill.buckets[n].items.filter(
          (i) => i.id !== b.dataset.remove);
        draw();
      }));
    const done = $("chunkDone");
    if (done) done.addEventListener("click", gradeChunk);
  };

  $("dsBody").innerHTML = "";
  $("dsFeedback").innerHTML = "";
  draw();
}

/* Scored on whether you chunked, not on matching some "correct" grouping.
   There are many defensible ways to group a list, and marking one right would
   teach you to guess the app's answer instead of building your own. */
function gradeChunk() {
  const used = drill.buckets.filter((b) => b.items.length);
  const named = used.filter((b) => b.name.trim());
  const oversized = used.filter((b) => b.items.length > 3);

  drill.round = 1;
  drill.correct = (named.length === used.length && !oversized.length) ? 1 : 0;

  $("dsFeedback").innerHTML = `
    <div class="drillverdict ${drill.correct ? "right" : "neutral"}">
      ${drill.correct
        ? "Every group is named and none is bigger than three. That's a list you can hold."
        : "Grouped — but check the two things that make chunking work."}
    </div>
    <ul class="hint" style="margin-left:18px">
      <li>${named.length === used.length
        ? "✓ every group has a name"
        : `${used.length - named.length} group(s) still unnamed — an unnamed group is just a shorter list`}</li>
      <li>${oversized.length
        ? `${oversized.length} group(s) hold more than three — that's back over the limit`
        : "✓ no group holds more than three"}</li>
    </ul>
    <div class="md">${md("| Group | Items |\n|---|---|\n" + used.map((b) =>
      `| ${b.name || "(unnamed)"} | ${b.items.map((i) => i.name).join(", ")} |`
    ).join("\n"))}</div>
    <button class="btn primary" id="dsNext">Finish</button>`;
  $("dsNext").addEventListener("click", () => finishDrill(), { once: true });
}

/* --------------------------------- end -------------------------------- */

function finishDrill() {
  const total = drill.round || 1;
  $("dsBody").innerHTML = `
    <div class="drillverdict neutral">
      Done — ${drill.correct} of ${total}${
        drill.def.id === "sequence" ? `, finishing at span ${drill.span}` : ""}.
    </div>
    <p class="hint">${esc(drill.data.honesty || "")}</p>`;
  $("dsFeedback").innerHTML = `
    <div class="row">
      <button class="btn primary" id="dsAgain">Go again</button>
      <button class="btn ghost" id="dsBack">Back to drills</button>
    </div>`;
  $("dsAgain").addEventListener("click", () => startDrill(drill.def.id));
  $("dsBack").addEventListener("click", () => endDrill(true));
  endDrill.saved = false;
  // Save the run now; leaving the page shouldn't lose it.
  api("/api/drills/result", {
    method: "POST",
    body: JSON.stringify({
      drill: drill.def.id, score: drill.correct / total,
      rounds: total, correct: drill.correct,
      span: drill.def.id === "sequence" ? drill.span : null,
      ms: Math.round(performance.now() - drill.startedAt),
    }),
  }).catch(() => {});
}

onEnter("drills", () => loadDrills());
onEnter("quiz", () => refreshScopeCount());

/* ============ phase 5: timer, question tactics, note critique ==========
   The timer counts UP toward a limit and never cuts your off. Going over is
   information; it is not a failure, and it never touches mastery. */

const timerState = { seconds: null, label: "off", started: 0, tick: null, over: false };

async function loadTimerOptions() {
  try {
    const p = await api("/api/tactics/playbook");
    $("timerOptions").innerHTML = p.timers.map((t) => `
      <button class="timeropt ${t.seconds === timerState.seconds ? "on" : ""}"
              data-sec="${t.seconds === null ? "" : t.seconds}"
              data-label="${esc(t.label)}">
        <b>${esc(t.label)}</b><span>${esc(t.note)}</span>
      </button>`).join("");
    $("timerOptions").querySelectorAll(".timeropt").forEach((b) =>
      b.addEventListener("click", async () => {
        timerState.seconds = b.dataset.sec ? parseInt(b.dataset.sec, 10) : null;
        timerState.label = b.dataset.label;
        $("timerSummary").textContent = timerState.seconds
          ? `${timerState.seconds}s per question` : "off";
        $("timerOptions").querySelectorAll(".timeropt")
          .forEach((x) => x.classList.toggle("on", x === b));
        const g = await api("/api/tactics/timing", {
          method: "POST", body: JSON.stringify({ seconds: timerState.seconds }),
        });
        $("timerNote").textContent = g.body;
      }));

    renderPlaybook(p.playbook);
  } catch { /* offline is fine; the timer just stays off */ }
}

$("timerToggle").addEventListener("click", () => {
  const panel = $("timerPanel");
  panel.hidden = !panel.hidden;
  $("timerToggle").classList.toggle("open", !panel.hidden);
  if (!panel.hidden && !$("timerOptions").children.length) loadTimerOptions();
});

function startTimer() {
  stopTimer();
  if (!timerState.seconds) { $("timerBar").hidden = true; return; }
  timerState.started = Date.now();
  timerState.over = false;
  $("timerBar").hidden = false;
  $("timerBar").classList.remove("over");
  $("tLimit").textContent = `limit ${timerState.seconds}s`;
  paintTimer();
  timerState.tick = setInterval(paintTimer, 1000);
}

function paintTimer() {
  const elapsed = Math.floor((Date.now() - timerState.started) / 1000);
  const m = Math.floor(elapsed / 60), s = elapsed % 60;
  $("tClock").textContent = `${m}:${String(s).padStart(2, "0")}`;
  const pct = Math.min(100, (elapsed / timerState.seconds) * 100);
  $("tFill").style.width = `${pct}%`;
  if (elapsed >= timerState.seconds && !timerState.over) {
    // Deliberately does NOT submit or advance. Extended time is an
    // accommodation; a hard cut-off would defeat the point of practising.
    timerState.over = true;
    $("timerBar").classList.add("over");
    $("tLimit").textContent = "over the limit — keep going";
  }
}

function stopTimer() {
  if (timerState.tick) clearInterval(timerState.tick);
  timerState.tick = null;
}

function timerElapsedMs() {
  return timerState.started ? Date.now() - timerState.started : null;
}

/* ------------------------- question dissection ------------------------ */

$("dissectBtn").addEventListener("click", async () => {
  const q = state.questions[state.idx];
  if (!q) return;
  const box = $("qDissect");
  if (!box.hidden) { box.hidden = true; return; }

  const btn = $("dissectBtn");
  btn.disabled = true;
  try {
    let stem = q.stem;
    if (q.premise_table) stem += "\n\n" + q.premise_table;
    const d = await api("/api/tactics/dissect", {
      method: "POST", body: JSON.stringify({ stem }),
    });
    box.innerHTML = renderDissect(d);
    box.hidden = false;
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
});

function renderPlaybook(items) {
  const el = $("playbook");
  if (!el) return;
  el.innerHTML = items.map((p) => `
    <div class="play">
      <div class="ptitle">${esc(p.title)}</div>
      <div class="pbody">${esc(p.body)}</div>
      <div class="pwhy">${esc(p.why_you)}</div>
      <div class="pstatus">${esc(p.status)}</div>
    </div>`).join("");
}

/* ------------------------------ note check ---------------------------- */

$("noteGo").addEventListener("click", async () => {
  const body = $("noteBody").value.trim();
  if (!body) { toast("Paste some notes first."); return; }
  const btn = $("noteGo");
  btn.disabled = true; btn.textContent = "Reading…";
  try {
    const r = await api("/api/notes/review", {
      method: "POST",
      body: JSON.stringify({
        body, title: $("noteTitle").value,
        critique: $("noteWantCritique").checked,
      }),
    });
    renderNoteReview(r);
    loadNoteHistory();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Check these notes"; }
});

function renderNoteReview(r) {
  $("noteResult").hidden = false;
  const m = r.metrics;

  const metric = (v, label, bad) =>
    `<div class="metric ${bad === true ? "bad" : bad === false ? "good" : ""}">
       <div class="mv">${v}</div><div class="ml">${label}</div></div>`;

  $("noteMetrics").innerHTML = [
    metric(m.words, "words"),
    metric(m.words_per_line, "words per line", m.words_per_line > 20),
    metric(m.avg_sentence_words, "avg sentence", m.avg_sentence_words > 25),
    metric(m.longest_unbroken_list || "—", "longest list", m.longest_unbroken_list > 4),
    metric(m.table_rows, "table rows", m.has_table ? false : undefined),
    metric(m.headings, "headings", m.headings === 0 && m.lines > 8),
  ].join("");

  $("noteFlags").innerHTML = r.flags.length
    ? `<h4>What the shape says</h4>` + r.flags.map((f) => `
        <div class="noteflag ${f.severity}">
          <div class="nf">${esc(f.flag)}</div>
          <div class="ns">${esc(f.says)}</div>
          <div class="nw">${esc(f.why)}</div>
          <div class="ne">basis: ${esc(f.evidence)}</div>
        </div>`).join("")
    : `<p class="hint">No structural problems found in the shape of these notes.</p>`;

  const c = r.critique;
  if (!c) {
    $("noteCritique").innerHTML = r.critique_error
      ? `<h4>Written critique</h4><p class="hint">${esc(r.critique_error)}</p>
         <p class="hint">The measurements above ran offline and are unaffected.</p>`
      : "";
    return;
  }

  $("noteCritique").innerHTML = `
    <div class="verdictline">${esc(c.verdict)}</div>
    ${c.working.length ? `<h4>Already working</h4><ul class="dsteps">${
      c.working.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    <h4>What to change</h4>
    ${c.problems.map((p) => `
      <div class="problem">
        <b>${esc(p.problem)}</b>
        <div class="pq">${esc(p.quote)}</div>
        ${p.quote_verified === false
          ? `<div class="unverified">⚠ This quote doesn't appear verbatim in your
             notes — treat the point with caution.</div>` : ""}
        <p><b>Instead:</b> ${esc(p.instead)}</p>
        <div class="ne">basis: ${esc(p.evidence)}</div>
      </div>`).join("")}
    <h4>The same thing, better shaped</h4>
    <p class="hint">From: ${esc(c.rewrite_covers)}</p>
    <div class="md">${md(c.rewrite)}</div>
    <h4>Can these become questions?</h4>
    <p>${esc(c.retrieval_ready)}</p>
    <div class="verdictline" style="margin-top:16px">${esc(c.one_habit)}</div>`;
}

async function loadNoteHistory() {
  try {
    const h = await api("/api/notes");
    if (!h.reviews.length) { $("notePast").hidden = true; return; }
    $("notePast").hidden = false;
    $("noteTrend").innerHTML = h.trend
      ? `<p class="trendline">Your last three sets averaged
         <b>${h.trend.recent}</b> words per line, against <b>${h.trend.earlier}</b>
         earlier — ${esc(h.trend.direction)}. Compared with yourself only.</p>`
      : "";
    $("noteList").innerHTML = h.reviews.map((r) => `
      <div class="runrow">
        <span class="rdate">${new Date(r.ts * 1000).toLocaleDateString()}</span>
        <span>${esc(r.title || "untitled")}</span>
        <span class="rscore">${r.words} w</span>
        <span class="rscore">${r.words_per_line} w/line</span>
      </div>`).join("");
  } catch { /* history is a nicety */ }
}

// The playbook is rendered as a side effect of loading the timer options; it
// only needs fetching once.
onEnter("profile", () => {
  if (!$("playbook").children.length) loadTimerOptions();
});

/* ========== phase 6: per-question highlighting, notes in profile ======= */

/* Replaces the earlier line-role rendering. Every mark comes from the server's
   segments, so what's highlighted and what's classified can never disagree. */
function renderDissect(d) {
  const ADV_ICON = { warn: "⚠", act: "→", note: "·", skip: "~" };

  const line = (ln) => {
    const inner = (ln.segments || [{ text: ln.text, kind: null }]).map((seg) =>
      seg.kind
        ? `<span class="hl hl-${seg.kind}" data-label="${esc(seg.label || seg.kind)}">${
            esc(seg.text)}</span>`
        : esc(seg.text)).join("");
    return `<div class="sline ${ln.role}">${inner}</div>`;
  };

  const used = new Set();
  d.lines.forEach((ln) => (ln.segments || []).forEach((s) => s.kind && used.add(s.kind)));
  const legend = (d.legend || []).filter((l) => used.has(l.kind));

  return `
    ${d.negated ? `<div class="dnegated">⚠ Negated question — you're looking for
      the one that does NOT fit.</div>` : ""}

    <h5>This question</h5>
    <div class="advice">${(d.advice || []).map((a) => `
      <div class="adv ${a.kind}">
        <span class="aicon">${ADV_ICON[a.kind] || "·"}</span>
        <span>${esc(a.text)}</span>
      </div>`).join("")}</div>

    <h5>The stem, marked up</h5>
    ${legend.length ? `<div class="hllegend">${legend.map((l) =>
      `<span class="hl-${l.kind}">${esc(l.label)}</span>`).join("")}</div>` : ""}
    <div class="stemview">${d.lines.map(line).join("")}</div>

    <h5>Read it in this order</h5>
    <ol class="dsteps">${d.how_to_read.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>

    <p class="hint" style="margin-top:10px">Marked by pattern-matching, not by
      reading — it can mislabel a phrase. Treat it as a first pass.</p>`;
}

/* --------------------- note check, now in the profile ------------------ */

let noteSource = "paste";
let notePickedAsset = null;

if ($("noteSource")) {
  $("noteSource").addEventListener("click", (e) => {
    const b = e.target.closest(".stab");
    if (!b) return;
    noteSource = b.dataset.src;
    notePickedAsset = null;
    $("noteSource").querySelectorAll(".stab")
      .forEach((x) => x.classList.toggle("on", x === b));
    $("srcPaste").hidden = noteSource !== "paste";
    $("srcVault").hidden = noteSource !== "vault";
    $("srcUpload").hidden = noteSource !== "upload";
    if (noteSource === "vault") loadNoteSources();
  });
}

async function loadNoteSources() {
  try {
    const r = await api("/api/notes/sources");
    $("noteVaultList").innerHTML = r.assets.length
      ? r.assets.map((a) => `
        <button class="assetrow" data-asset="${esc(a.id)}"${
          a.readable ? "" : " disabled"}>
          <span class="aname">${esc(a.caption || a.filename)}
            <span class="areason">${esc(a.filename)}${
              a.reason ? " — " + esc(a.reason) : ""}</span></span>
          <span class="fmeta">${esc(a.kind)}</span>
          <span class="fmeta">${new Date(a.added_at * 1000).toLocaleDateString()}</span>
        </button>`).join("")
      : `<p class="hint">Nothing in the vault yet. Add documents on the Vault tab.</p>`;

    $("noteVaultList").querySelectorAll(".assetrow:not([disabled])").forEach((b) =>
      b.addEventListener("click", () => {
        notePickedAsset = b.dataset.asset;
        $("noteVaultList").querySelectorAll(".assetrow")
          .forEach((x) => x.classList.remove("sel"));
        b.classList.add("sel");
        b.style.borderColor = "var(--accent)";
        b.style.background = "var(--accent-soft)";
      }));
  } catch (e) { toast(e.message, true); }
}

if ($("noteDrop")) {
  const nd = $("noteDrop");
  nd.addEventListener("click", () => $("noteFile").click());
  ["dragenter", "dragover"].forEach((ev) =>
    nd.addEventListener(ev, (e) => { e.preventDefault(); nd.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    nd.addEventListener(ev, (e) => { e.preventDefault(); nd.classList.remove("over"); }));
  nd.addEventListener("drop", (e) => uploadNotes(e.dataTransfer.files[0]));
  $("noteFile").addEventListener("change", () => uploadNotes($("noteFile").files[0]));
}

async function uploadNotes(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("critique", $("noteWantCritique").checked ? "true" : "false");
  const btn = $("noteGo");
  btn.disabled = true; btn.textContent = "Reading…";
  try {
    const res = await fetch("/api/notes/upload", { method: "POST", body: fd });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    renderNoteReview(body);
    loadNoteHistory();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Check these notes"; $("noteFile").value = ""; }
}

/* Replaces the earlier paste-only handler: routes by whichever source is on. */
if ($("noteGo")) {
  $("noteGo").replaceWith($("noteGo").cloneNode(true));
  $("noteGo").addEventListener("click", async () => {
    const btn = $("noteGo");
    const wantCritique = $("noteWantCritique").checked;

    if (noteSource === "upload") {
      if (!$("noteFile").files[0]) { toast("Pick a file first."); return; }
      return uploadNotes($("noteFile").files[0]);
    }

    btn.disabled = true; btn.textContent = "Reading…";
    try {
      let r;
      if (noteSource === "vault") {
        if (!notePickedAsset) { toast("Pick a file from the vault first."); return; }
        r = await api("/api/notes/from-asset", {
          method: "POST",
          body: JSON.stringify({ asset_id: notePickedAsset, critique: wantCritique }),
        });
      } else {
        const body = $("noteBody").value.trim();
        if (!body) { toast("Paste some notes first."); return; }
        r = await api("/api/notes/review", {
          method: "POST",
          body: JSON.stringify({ body, title: $("noteTitle").value,
                                 critique: wantCritique }),
        });
      }
      renderNoteReview(r);
      loadNoteHistory();
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = "Check these notes"; }
  });
}

// The note check lives on Profile now, so load its history when that opens.
onEnter("profile", () => loadNoteHistory());

/* ============ phases 4-7: dashboard, progress, anki, analytics ========= */

/* --------------------------------- today ------------------------------ */

let dashRec = null;

async function loadDashboard() {
  try {
    // The recommendation comes from the same endpoint Practice uses. Two
    // copies of "what should I do next" would eventually disagree, and the
    // one on the home screen would be the one nobody re-checked.
    const [game, weak, modes, suggest] = await Promise.all([
      api("/api/game/state"),
      api("/api/mastery/weakest?limit=5"),
      api("/api/select/modes"),
      api("/api/select/recommend").catch(() => null),
    ]);
    dashRec = suggest;

    const lv = game.level;
    $("dashLevel").innerHTML =
      `<div class="lv">${lv.level}</div><div class="ll">level</div>`;

    const hour = new Date().getHours();
    $("dashGreeting").textContent =
      hour < 12 ? "This morning" : hour < 18 ? "This afternoon" : "Tonight";

    $("dashStats").innerHTML = [
      ["🔥 " + game.streak.streak, "in a row"],
      [game.answered, "answered"],
      [game.mastered, "mastered"],
      [`${game.achievements.unlocked}/${game.achievements.total}`, "achievements"],
    ].map(([v, l]) =>
      `<div class="statcell"><div class="sv">${esc(String(v))}</div>
       <div class="sl">${l}</div></div>`).join("");

    $("dashGoalFill").style.width = `${Math.round(lv.pct * 100)}%`;
    $("dashGoalText").textContent =
      `${lv.into_level} / ${lv.need} XP toward level ${lv.level + 1}`;

    $("dashDue").textContent = modes.due_now;
    $("dashDueNote").textContent = modes.due_now
      ? "Concepts whose review is scheduled for now."
      : "Nothing scheduled. Everything you've practised is still fresh.";
    $("dashReview").disabled = !modes.due_now;

    $("dashWeak").innerHTML = weak.weakest.length
      ? weak.weakest.map((w, i) => `
        <button class="weakrow" data-concept="${esc(w.concept_id)}">
          <span class="rank">${i + 1}</span>
          <span class="wname">${esc(w.name)}
            <span class="wtopic">${esc(w.topic)}</span></span>
          <span class="bandchip band-${w.band}">${
            (BANDS.find((b) => b[0] === w.band) || [, w.band])[1]}</span>
          <span class="wpct">${Math.round(w.effective * 100)}%</span>
        </button>`).join("")
      : `<p class="hint">Nothing measured yet — answer some questions and this fills in.</p>`;
    $("dashWeak").querySelectorAll(".weakrow").forEach((b) =>
      b.addEventListener("click", () => { showConcept(b.dataset.concept); }));

    // Headline: name the single most useful thing to do next.
    if (!modes.available_concepts) {
      $("dashHeadline").textContent = "Nothing in the bank yet";
      $("dashSub").textContent =
        "Add a lecture in the Library and build a question set from it.";
      $("dashStart").disabled = true;
    } else if (suggest) {
      $("dashHeadline").textContent = suggest.title;
      $("dashSub").textContent =
        suggest.why.charAt(0).toUpperCase() + suggest.why.slice(1) + ".";
      $("dashStart").disabled = false;
    } else {
      $("dashHeadline").textContent = "Ready when you are";
      $("dashSub").textContent = `${modes.available_concepts} concepts in your bank.`;
      $("dashStart").disabled = false;
    }

    loadDashExam();
  } catch (e) { toast(e.message, true); }
}

async function loadDashExam() {
  try {
    const r = await api("/api/exams?upcoming=true");
    const next = r.exams[0];
    if (!next) { $("dashExamCard").hidden = true; return; }
    $("dashExamCard").hidden = false;
    $("dashExam").innerHTML = `
      <div class="ptitle">${esc(next.name)}</div>
      <p class="hint">${esc(next.date)}</p>
      <div class="countdown ${countdownClass(next.days_left)}"
           style="margin-top:8px;display:inline-block">${countdownText(next.days_left)}</div>`;

    // Readiness is the number that decides what tonight is for, so it belongs
    // on the home screen rather than two clicks into Plan.
    const rd = await api(`/api/exams/${next.id}/readiness`).catch(() => null);
    if (rd && !rd.empty) {
      const top = (rd.high_risk || [])[0];
      $("dashExam").innerHTML += `
        <div class="dxready">
          <span class="rbar"><span class="rfill"
            style="width:${Math.round(rd.readiness * 100)}%"></span></span>
          <p class="hint"><b>${Math.round(rd.readiness * 100)}%</b> readiness ·
            ${rd.concepts_total} concepts mapped</p>
          ${top ? `<p class="hint">Top risk: <b>${esc(top.name)}</b></p>` : ""}
        </div>
        <button class="btn ghost small" data-view="plan">Open the plan</button>`;
    }
  } catch { $("dashExamCard").hidden = true; }
}

/* Continue starts the session it just described, rather than dropping you on
   a page of pickers to reconstruct it. */
$("dashStart").addEventListener("click", () => {
  navigate("quiz");
  refreshScopeCount();
  beginSession(rec.n, (dashRec && dashRec.mode) || sessionMode,
               $("dashStart"), "Continue studying");
});
$("dashReview").addEventListener("click", () => {
  navigate("quiz");
  refreshScopeCount();
  beginSession(rec.n, "spaced", $("dashReview"), "Review those");
});

/* -------------------------------- progress ---------------------------- */

async function loadProgress() {
  try {
    const [game, map, ach] = await Promise.all([
      api("/api/game/state"),
      api("/api/game/map"),
      api("/api/game/achievements"),
    ]);

    const lv = game.level;
    $("progLevel").innerHTML = `
      <div class="big">${lv.level}</div>
      <div>
        <div class="goalbar"><span class="goalfill"
          style="width:${Math.round(lv.pct * 100)}%"></span></div>
        <p class="meta">${lv.into_level} / ${lv.need} XP toward level ${lv.level + 1}
          · ${game.answered} answered · best run ${game.streak.best}</p>
      </div>`;

    $("territories").innerHTML = map.territories.map((t) => `
      <div class="terr b-${t.band}">
        <span class="tname">${esc(t.name)}</span>
        <span class="tbar"><span class="tfill fill-${t.band}"
          style="width:${Math.max(3, (t.mastery || 0) * 100)}%"></span></span>
        <span class="tmeta">${t.mastery === null ? "not started"
          : `${Math.round(t.mastery * 100)}% · ${t.mastered}/${t.concepts} mastered`}</span>
        ${t.boss_ready
          ? `<button class="btn small primary" data-boss="${esc(t.id)}">Boss challenge</button>`
          : `<span class="tmeta">${t.mastery === null ? "practise here first"
              : `${t.to_boss} weak concept${t.to_boss === 1 ? "" : "s"} before the boss`}</span>`}
      </div>`).join("");

    $("territories").querySelectorAll("[data-boss]").forEach((b) =>
      b.addEventListener("click", () => startBoss(b.dataset.boss)));

    $("achievements").innerHTML = ach.achievements.map((a) => `
      <div class="ach ${a.unlocked ? "on" : ""}">
        <div class="an">${a.unlocked ? "✓ " : ""}${esc(a.name)}</div>
        <div class="ah">${esc(a.how)}</div>
      </div>`).join("");
  } catch (e) { toast(e.message, true); }
}

async function startBoss(topicId) {
  try {
    const r = await api("/api/game/boss", {
      method: "POST", body: JSON.stringify({ topic_id: topicId, n: 8 }),
    });
    state.storedIds = Object.fromEntries(r.questions.map((q) => [q.id, q.id]));
    await startQuiz(r.questions, "boss");
    toast("Boss challenge — the hardest items in that system.");
  } catch (e) { toast(e.message, true); }
}

/* ---------------------------------- anki ------------------------------ */

let ankiSelection = "red_orange";
let ankiResult = null;

async function loadAnkiSelections() {
  try {
    const r = await api("/api/anki/selections");
    $("ankiSelections").innerHTML = r.selections
      .filter((s) => s.id !== "selected")
      .map((s) => {
        const n = r.counts[s.id] ?? 0;
        return `<button class="anksel ${s.id === ankiSelection ? "on" : ""}"
          data-sel="${esc(s.id)}"${n ? "" : " disabled"}>
          <span>${esc(s.label)}</span>
          <span class="ankn">${n} concept${n === 1 ? "" : "s"}</span>
        </button>`;
      }).join("");
    $("ankiSelections").querySelectorAll("[data-sel]").forEach((b) =>
      b.addEventListener("click", () => {
        ankiSelection = b.dataset.sel;
        $("ankiSelections").querySelectorAll(".anksel")
          .forEach((x) => x.classList.toggle("on", x === b));
      }));
  } catch (e) { toast(e.message, true); }
}

$("ankiBuild").addEventListener("click", async () => {
  const btn = $("ankiBuild");
  btn.disabled = true; btn.textContent = "Building…";
  try {
    ankiResult = await api("/api/anki/export", {
      method: "POST",
      body: JSON.stringify({
        selection: ankiSelection,
        limit: parseInt($("ankiLimit").value, 10) || 40,
        use_claude: $("ankiClaude").checked,
      }),
    });
    renderAnkiPreview(ankiResult);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Build the deck"; }
});

function renderAnkiPreview(r) {
  $("ankiNote").textContent = r.note
    ? r.note
    : `${r.cards.length} cards from ${r.concepts} concepts. Edit any of them below before exporting.`;
  $("ankiDownload").hidden = false;

  $("ankiPreview").innerHTML = r.cards.map((c, i) => `
    <div class="cardprev" data-i="${i}">
      <span class="ck">${esc(c.kind)}</span>
      <div class="cf">Front</div>
      <textarea data-field="front" data-i="${i}">${esc(c.front)}</textarea>
      <div class="cf">Back</div>
      <textarea data-field="back" data-i="${i}">${esc(c.back)}</textarea>
      <div class="ct">${(c.tags || []).map((t) =>
        `<span class="chipx">${esc(t)}</span>`).join("")}</div>
    </div>`).join("");

  $("ankiPreview").querySelectorAll("textarea").forEach((t) =>
    t.addEventListener("input", () => {
      ankiResult.cards[parseInt(t.dataset.i, 10)][t.dataset.field] = t.value;
    }));
}

$("ankiDownload").addEventListener("click", async () => {
  if (!ankiResult) return;
  try {
    // Re-render server-side so your edits land in the file, not just the preview.
    const fresh = await api("/api/anki/rebuild", {
      method: "POST",
      body: JSON.stringify({ cards: ankiResult.cards,
                             concept_list: ankiResult.concept_list }),
    });
    const blob = new Blob([fresh.tsv], { type: "text/tab-separated-values" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = ankiResult.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast(`${fresh.cards} cards exported. In Anki: File → Import, and set the field separator to Tab.`);
  } catch (e) { toast(e.message, true); }
});

/* ------------------------------- analytics ---------------------------- */

async function loadAnalytics() {
  try {
    const r = await api("/api/analytics");
    $("anMethod").textContent = r.method;

    $("anInsights").innerHTML = r.insights.length
      ? r.insights.map((c) => `
        <div class="insight">
          <div class="iclaim">${esc(c.claim)}</div>
          <div class="ibars">
            <span>${esc(c.a_name)}</span>
            <span class="ibar"><span class="ifill"
              style="width:${Math.round(c.a_acc * 100)}%"></span></span>
            <span class="cn">${Math.round(c.a_acc * 100)}%</span>
            <span>${esc(c.b_name)}</span>
            <span class="ibar"><span class="ifill"
              style="width:${Math.round(c.b_acc * 100)}%"></span></span>
            <span class="cn">${Math.round(c.b_acc * 100)}%</span>
          </div>
          <div class="iconf">${esc(c.confidence)}</div>
        </div>`).join("")
      : `<p class="hint">Nothing has cleared the evidence bar yet. That's the
         system working — with ${r.attempts} attempts logged, anything it claimed
         now would be noise.</p>`;

    const cal = r.calibration;
    $("anCalibration").innerHTML = `
      ${cal.buckets.map((b) => `
        <div class="calrow">
          <span>${b.confidence === "knew" ? "“I knew it”"
            : b.confidence === "unsure" ? "“Unsure”" : "“Guessed”"}</span>
          <span class="cbar"><span class="cfill fill-${
            b.accuracy >= 0.85 ? "dark_green" : b.accuracy >= 0.6 ? "yellow" : "red"}"
            style="width:${Math.round(b.accuracy * 100)}%"></span></span>
          <span class="cn">${Math.round(b.accuracy * 100)}%</span>
          <span class="cn">n=${b.n}</span>
        </div>`).join("")}
      <p class="${cal.verdict ? "why" : "hint"}" style="margin-top:12px">${
        esc(cal.verdict || cal.pending || "")}</p>`;

    const cues = r.cues;
    $("anCues").innerHTML = cues.note
      ? `<p>${esc(cues.note)}</p>`
      : `<p class="hint">${esc(cues.pending || "")}</p>`;

    $("anPending").innerHTML = r.pending.length
      ? r.pending.map((c) => `
        <div class="pendingrow">
          <span>${esc(c.a_name)} vs ${esc(c.b_name)}</span>
          <span class="pw">${esc(c.pending || "")}</span>
        </div>`).join("")
      : `<p class="hint">Everything the app tracks has enough evidence.</p>`;
  } catch (e) { toast(e.message, true); }
}

/* --------------------------------- book ------------------------------- */

let bookScan = null;

$("bookScan").addEventListener("click", async () => {
  const path = $("bookPath").value.trim();
  if (!path) { toast("Paste the full path to the PDF."); return; }
  const btn = $("bookScan");
  btn.disabled = true; btn.textContent = "Scanning…";
  $("bookHint").textContent = "Walking every page — this takes a minute or two.";
  try {
    bookScan = await api("/api/book/scan", {
      method: "POST", body: JSON.stringify({ path }),
    });
    renderBookScan(bookScan);
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = "Scan"; }
});

function renderBookScan(r) {
  $("bookResult").hidden = false;
  const done = new Set(r.already_ingested || []);
  $("bookStats").innerHTML = [
    [r.pages, "pages"],
    [r.sections.length, "sections"],
    [r.mapped, "mapped to topics"],
    [r.signals.rapid_review_ranges, "rapid-review ranges"],
  ].map(([v, l]) =>
    `<div class="planstat"><div class="pv">${v}</div><div class="pl">${l}</div></div>`
  ).join("");

  $("bookSections").innerHTML = r.sections.map((s, i) => `
    <div class="secrow ${s.topic_id === "unsorted" ? "unmapped" : ""}" data-i="${i}">
      <span>${esc(s.path)}</span>
      <span class="sp">p${s.page_start}-${s.page_end}</span>
      <span class="${done.has(s.path) ? "sdone" : "sp"}">${
        done.has(s.path) ? "✓ ingested"
        : s.topic_id === "unsorted" ? "unmapped" : `${s.pages}pp`}</span>
    </div>`).join("");

  const todo = r.sections.filter(
    (s) => s.topic_id !== "unsorted" && !done.has(s.path));
  $("bookIngestNote").textContent = todo.length
    ? `${todo.length} mapped sections not yet extracted. One API call each.`
    : "Every mapped section has been extracted.";
  $("bookIngest").disabled = !todo.length;
  $("bookHint").textContent =
    `Segmented locally — nothing was uploaded and no API call was made.`;
}

$("bookIngest").addEventListener("click", async () => {
  if (!bookScan) return;
  const done = new Set(bookScan.already_ingested || []);
  const todo = bookScan.sections
    .map((s, i) => ({ ...s, i }))
    .filter((s) => s.topic_id !== "unsorted" && !done.has(s.path));
  if (!todo.length) return;

  const btn = $("bookIngest");
  btn.disabled = true;
  $("bookProgress").hidden = false;
  let made = 0;

  for (let k = 0; k < todo.length; k++) {
    btn.textContent = `Extracting ${k + 1} of ${todo.length}…`;
    $("bookBar").style.width = `${(k / todo.length) * 100}%`;
    try {
      const r = await api("/api/book/ingest", {
        method: "POST",
        body: JSON.stringify({ path: bookScan.path, section_index: todo[k].i }),
      });
      made += r.concepts || 0;
      bookScan.already_ingested.push(todo[k].path);
      renderBookScan(bookScan);
    } catch (e) {
      toast(`Stopped at ${todo[k].path}: ${e.message}`, true);
      break;
    }
  }
  $("bookBar").style.width = "100%";
  btn.textContent = "Extract concepts from mapped sections";
  toast(`${made} concepts indexed from the book.`);
  setTimeout(() => { $("bookProgress").hidden = true; }, 800);
});

/* Per-view load work now lives in the ENTER table beside the nav. */

loadDashboard();


/* ============================ phase 8: polish ========================= */

/* --- keyboard shortcuts ----------------------------------------------- */

/* Answering with the keyboard removes a round trip to the mouse for every
   question. It matters more here than in most apps: extended time is an
   accommodation, and the fewer mechanical steps between reading and answering,
   the more of that time goes on the medicine. */
const LETTERS = "ABCDE";

document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const tag = (e.target.tagName || "").toLowerCase();
  const typing = tag === "input" || tag === "textarea" || e.target.isContentEditable;

  // Escape backs out of whatever is open, innermost first. `moreMenu` used to
  // be in this list and its declaration went with the drawer, so pressing
  // Escape anywhere threw a ReferenceError and closed nothing at all.
  if (e.key === "Escape") {
    if (!$("modal").hidden) { $("modal").hidden = true; return; }
    if (!$("addSheet").hidden) { closeAddSheet(); return; }
    if (!$("libDrawer").hidden) { closeDrawer(); return; }
    if (!$("libSearchDrop").hidden) { $("libSearchDrop").hidden = true; return; }
    if (!$("userMenu").hidden) { $("userMenu").hidden = true; return; }
    if (document.querySelector(".rowpop")) { closeRowMenu(); return; }
    if (!$("welcome").hidden) { dismissWelcome(); return; }
    if (!$("qDissect").hidden) { $("qDissect").hidden = true; return; }
  }

  const quizOpen = document.getElementById("view-quiz").classList.contains("active")
                   && !$("quizRunner").hidden;
  if (!quizOpen || typing) return;

  // Enter advances, whether that means grading or moving on.
  if (e.key === "Enter") {
    if (!$("qExplain").hidden) { e.preventDefault(); $("nextBtn").click(); }
    else if (!$("submitBtn").hidden) { e.preventDefault(); $("submitBtn").click(); }
    return;
  }

  if (state.answered) return;

  // 1-5 pick an option; A-E do the same for anyone who thinks in letters.
  const byNumber = "12345".indexOf(e.key);
  const byLetter = LETTERS.indexOf(e.key.toUpperCase());
  const idx = byNumber >= 0 ? byNumber : byLetter;
  if (idx >= 0) {
    const opts = $("qOptions").querySelectorAll(".opt");
    if (opts[idx]) { e.preventDefault(); opts[idx].click(); }
    return;
  }

  if (e.key === "?" || (e.key === "/" && e.shiftKey)) {
    e.preventDefault();
    $("dissectBtn").click();
  }
  if (e.key.toLowerCase() === "c" && $("cueBtn") && !$("cueBtn").disabled) {
    e.preventDefault();
    $("cueBtn").click();
  }
});

/* Show the keycaps only once you have used one, so they never add clutter for
   someone who only ever clicks. */
let keyboardUsed = false;
document.addEventListener("keydown", (e) => {
  if (!keyboardUsed && /^[1-5a-eA-E]$/.test(e.key)) {
    keyboardUsed = true;
    document.body.classList.add("kb");
    if ($("keyHint")) $("keyHint").textContent = "1-5 pick · enter check · c cue · ? break down";
  }
}, { once: false });


/* ----------------------------- backups -------------------------------- */

async function loadBackups() {
  try {
    const r = await api("/api/backups");
    $("bkList").innerHTML = r.backups.length
      ? r.backups.map((b) => `
        <div class="runrow">
          <span class="rdate">${esc(b.when)}</span>
          <span>${b.counts.attempt ?? "?"} answers · ${b.counts.concept ?? "?"} concepts</span>
          <span class="rscore">${b.mb} MB</span>
          <button class="btn small ghost" data-restore="${esc(b.name)}">Restore</button>
        </div>`).join("")
      : `<p class="hint">No backups yet — one is taken automatically once you've
         answered something.</p>`;

    $("bkList").querySelectorAll("[data-restore]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        // Destructive and hard to reason about, so it asks - and says what the
        // safety net is rather than just warning.
        if (!confirm(
          "Restore this backup?\n\nEverything currently in the app will be " +
          "replaced. A copy of the current data is saved first, so this can " +
          "be undone.")) return;
        btn.disabled = true; btn.textContent = "Restoring…";
        try {
          const res = await api("/api/backups/restore", {
            method: "POST", body: JSON.stringify({ name: btn.dataset.restore }),
          });
          toast(`Restored — ${res.now.attempts} answers. Your previous data is saved as ${res.safety_copy}.`);
          loadBackups();
          loadDashboard();
        } catch (e) { toast(e.message, true); btn.disabled = false; btn.textContent = "Restore"; }
      }));
  } catch { /* the panel is a convenience */ }
}

if ($("bkNow")) {
  $("bkNow").addEventListener("click", async () => {
    const b = $("bkNow");
    b.disabled = true; b.textContent = "Backing up…";
    try {
      const r = await api("/api/backups", { method: "POST" });
      toast(`Backed up — ${r.counts.attempt} answers, ${r.mb} MB.`);
      loadBackups();
    } catch (e) { toast(e.message, true); }
    finally { b.disabled = false; b.textContent = "Back up now"; }
  });
  $("bkDownloadDb").addEventListener("click", () => {
    window.location.href = "/api/backups/download";
  });
  $("bkExportJson").addEventListener("click", () => {
    window.location.href = "/api/backups/export.json";
  });
}

onEnter("profile", () => loadBackups());

/* ================= account, API keys, profile builder ================== */

const account = { user: null, users: [], profile: null, fields: null };

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2)
    .map((w) => w[0].toUpperCase()).join("");
}

function avatarHTML(user, cls) {
  if (!user) return `<span class="${cls}">?</span>`;
  return user.has_photo
    ? `<span class="${cls}"><img src="/api/users/${esc(user.id)}/photo?t=${Date.now()}" alt=""></span>`
    : `<span class="${cls}">${esc(initials(user.name))}</span>`;
}

async function loadAccount() {
  try {
    const [me, all] = await Promise.all([
      api("/api/users/me"), api("/api/users"),
    ]);
    account.user = me.user;
    account.profile = me.profile;
    account.fields = me.report_fields;
    account.users = all.users;
    renderWhoami();
    renderProfilePanel();
    // Scores and levers come from a second endpoint that is also per-user, so
    // switching people has to refresh both or the screen shows two people.
    loadProfile();
  } catch (e) { /* the app still works without an account */ }
}

function renderWhoami() {
  const u = account.user;
  $("userName").textContent = u ? u.name : "Set up";
  $("userAvatar").outerHTML = avatarHTML(u, "avatar").replace(
    'class="avatar"', 'class="avatar" id="userAvatar"');
}

$("userChip").addEventListener("click", (e) => {
  e.stopPropagation();
  const m = $("userMenu");
  if (!m.hidden) { m.hidden = true; return; }

  m.innerHTML = account.users.map((u) => `
      <button data-switch="${esc(u.id)}" class="${u.active ? "on" : ""}">
        ${avatarHTML(u, "avatar")}
        <span>${esc(u.name)}${u.active ? " ·" : ""}</span>
      </button>`).join("")
    + `<div class="sep"></div>
       <button data-add="1">+ Add someone</button>`
    + `<div class="sep"></div>`
    + MENU_VIEWS.map(([v, label]) =>
        `<button data-view="${v}">${label}</button>`).join("")
    + `<div class="sep"></div>
       <div class="menuline"><span>Appearance</span>
         <span class="themeswitch" id="themeSwitch" role="group"
               aria-label="Colour theme"></span></div>`;

  m.querySelectorAll("[data-switch]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/users/${b.dataset.switch}/active`, { method: "POST" });
      await loadAccount();
      toast(`Switched to ${account.user.name}.`);
      loadDashboard();
    }));
  m.querySelector("[data-add]").addEventListener("click", addUser);
  // The theme control is rebuilt with the menu, so it reads the cached state
  // rather than costing a request every time the menu opens.
  renderThemeSwitch(themeState.current, themeState.options);
  m.hidden = false;
});
document.addEventListener("click", (e) => {
  const m = $("userMenu");
  if (m.hidden) return;
  if (e.target.closest && e.target.closest("#themeSwitch")) return;
  if (e.target.closest && e.target.closest("#userChip")) return;
  m.hidden = true;
});

function addUser() {
  modal("Add someone", [
    { name: "name", label: "Name", placeholder: "Their name" },
  ], async (v) => {
    if (!v.name) throw new Error("Give them a name.");
    await api("/api/users", { method: "POST", body: JSON.stringify({ name: v.name }) });
    await loadAccount();
    show("screener");
    loadScreener();
    toast(`Welcome, ${v.name}. Set up a profile so the app knows how to teach you.`);
  });
}

/* ---------------------------- profile panel --------------------------- */

function renderProfilePanel() {
  const u = account.user, p = account.profile;
  if (!u || !p) return;

  $("profileWho").textContent = `${u.name}'s profile`;
  $("bigAvatar").outerHTML = avatarHTML(u, "bigavatar").replace(
    'class="bigavatar"', 'class="bigavatar" id="bigAvatar"');
  // The line above the summary table used to name one person's score. It has
  // to follow whoever is signed in, and say nothing specific when nothing is
  // known about them.
  if (p.why_table && $("whyTable")) $("whyTable").textContent = p.why_table;

  $("profileHeadline").textContent = p.headline;
  $("profileDetail").textContent = p.detail;
  $("profileCaveat").textContent = p.caveat || "";

  const levers = p.levers || [];
  $("profileLeverList").innerHTML = levers.length
    ? levers.map((l) => `
      <div class="lever">
        <div class="lf">${esc(l.finding)}</div>
        <div class="ls">${esc(l.score)}</div>
        <div class="lr">${esc(l.rule)}</div>
      </div>`).join("")
    : "";
}

$("editUserBtn").addEventListener("click", () => {
  const u = account.user;
  if (!u) return addUser();
  modal("Edit profile", [
    { name: "name", label: "Name", value: u.name },
  ], async (v) => {
    await api(`/api/users/${u.id}`, {
      method: "PATCH", body: JSON.stringify({ name: v.name }),
    });
    // A photo needs a file input, so it gets its own step rather than a
    // text field pretending to be one.
    const pick = document.createElement("input");
    pick.type = "file";
    pick.accept = "image/*";
    pick.addEventListener("change", async () => {
      if (!pick.files[0]) return;
      const fd = new FormData();
      fd.append("file", pick.files[0]);
      const res = await fetch(`/api/users/${u.id}/photo`, { method: "POST", body: fd });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        toast(b.detail || "Couldn't save that photo.", true);
      }
      await loadAccount();
    });
    await loadAccount();
    if (confirm("Name saved. Add or change a photo?")) pick.click();
  });
});

$("viewPromptBtn").addEventListener("click", async () => {
  const box = $("promptPreview");
  if (!box.hidden) { box.hidden = true; return; }
  try {
    const r = await api(`/api/users/${account.user.id}/profile/preview`);
    box.innerHTML = `<p class="hint">This is the exact instruction set the app
      sends with every request. Nothing about you is hidden from you.</p>
      <pre class="promptdump">${esc(r.prompt)}</pre>`;
    box.hidden = false;
  } catch (e) { toast(e.message, true); }
});

$("enterReportBtn").addEventListener("click", () => {
  const f = account.fields;
  const u = account.user;
  const cur = u.profile || {};

  const rows = (list, kind) => list.map((k) => `
    <label class="scoreline">
      <span>${esc(k)}</span>
      <input type="text" inputmode="numeric" data-${kind}="${esc(k)}"
             value="${esc(String((cur[kind + "es"] || cur[kind + "s"] || {})[k] ?? ""))}"
             placeholder="—">
    </label>`).join("");

  $("modalTitle").textContent = "Enter report scores";
  $("modalBody").innerHTML = `
    <p class="hint">${esc(f.note)}</p>
    <h4>Index scores <span class="hint">(mean 100)</span></h4>
    <div class="scoregrid">${rows(f.indexes, "index")}</div>
    <h4>Subtest scaled scores <span class="hint">(mean 10)</span></h4>
    <div class="scoregrid">${rows(f.subtests, "subtest")}</div>
    <label><span>Accommodations (comma separated)</span>
      <input type="text" id="mf_accom"
             value="${esc((cur.accommodations || []).join(", "))}"></label>
    <label><span>Anything else from the report</span>
      <textarea id="mf_notes">${esc(cur.notes || "")}</textarea></label>`;
  $("modal").hidden = false;

  $("modalCancel").onclick = () => { $("modal").hidden = true; };
  $("modalOk").onclick = async () => {
    const indexes = {}, subtests = {};
    document.querySelectorAll("[data-index]").forEach((i) => {
      if (i.value.trim()) indexes[i.dataset.index] = i.value.trim();
    });
    document.querySelectorAll("[data-subtest]").forEach((i) => {
      if (i.value.trim()) subtests[i.dataset.subtest] = i.value.trim();
    });
    try {
      await api(`/api/users/${u.id}/profile/report`, {
        method: "POST",
        body: JSON.stringify({
          indexes, subtests,
          accommodations: $("mf_accom").value.split(",")
            .map((x) => x.trim()).filter(Boolean),
          notes: $("mf_notes").value,
        }),
      });
      $("modal").hidden = true;
      await loadAccount();
      toast("Profile saved. Every prompt now carries it.");
    } catch (e) { toast(e.message, true); }
  };
});

$("runScreenerBtn").addEventListener("click", () => { show("screener"); loadScreener(); });

/* -------------------------------- keys -------------------------------- */

async function loadKeys() {
  try {
    const r = await api("/api/keys");
    // Three different situations read the same to the eye and need different
    // sentences: no keys at all, keys that are all unusable, and a working set.
    $("keyStatusLine").textContent = r.usable
      ? `${r.ready} of ${r.total} ready${r.env_fallback ? ", plus the .env key" : ""}. `
        + `A key that runs dry rests for ${r.cooldown_minutes} minutes, then rejoins.`
      : r.env_fallback ? "Using the key from your .env file."
      : r.total ? `${r.total === 1 ? "That key isn't" : `None of those ${r.total} keys are`}`
          + " usable right now — a rejected key is switched off until you replace"
          + " it, and one out of credit rests before it is tried again."
      : "No key yet — generation, the note critique and the exam chat need one."
        + " Everything else works without.";

    const nextUp = r.keys.findIndex((k) => k.status === "ready");
    $("keyList").innerHTML = r.keys.map((k, i) => `
      <div class="keyrow ${i === nextUp ? "first" : ""}">
        <span class="kord">${i + 1}</span>
        <span><b>${esc(k.label)}</b><span class="khint">${esc(k.hint)} · used ${k.uses}×</span></span>
        <span class="kstat ${k.status === "ready" ? "ready"
          : k.status === "disabled" ? "disabled" : "cooling"}">${esc(k.status)}${
            k.cooling_down ? ` ${Math.ceil(k.cooldown_remaining / 60)}m` : ""}</span>
        <button class="btn small ghost" data-ws="${esc(k.id)}"
                title="${k.workspace_id ? "Workspace: " + esc(k.workspace_id) : "No workspace set"}"
                >${k.workspace_id ? "Workspace ✓" : "Workspace…"}</button>
        <button class="btn small ghost" data-test="${esc(k.id)}">Test</button>
        <button class="btn small ghost" data-del="${esc(k.id)}">×</button>
      </div>`).join("");

    $("wakeKeysBtn").hidden = !r.keys.some((k) => k.cooling_down);

    $("keyList").querySelectorAll("[data-del]").forEach((b) =>
      b.addEventListener("click", async () => {
        await api(`/api/keys/${b.dataset.del}`, { method: "DELETE" });
        loadKeys();
      }));
    $("keyList").querySelectorAll("[data-ws]").forEach((b) =>
      b.addEventListener("click", async () => {
        const key = r.keys.find((k) => k.id === b.dataset.ws);
        const val = prompt(
          "Workspace ID for this key.\n\n" +
          "Only identity-linked keys need one. Find it in the Anthropic " +
          "Console under Settings → Workspaces, or in the URL while that " +
          "workspace is open. It looks like wrkspc_…\n\n" +
          "Leave blank to clear it.",
          (key && key.workspace_id) || "");
        if (val === null) return;
        try {
          await api(`/api/keys/${b.dataset.ws}`, {
            method: "PATCH",
            body: JSON.stringify({ workspace_id: val.trim() || null }),
          });
          toast(val.trim() ? "Workspace saved." : "Workspace cleared.");
          loadKeys();
        } catch (e) { toast(e.message, true); }
      }));
    $("keyList").querySelectorAll("[data-test]").forEach((b) =>
      b.addEventListener("click", async () => {
        b.disabled = true; b.textContent = "…";
        try {
          const res = await api(`/api/keys/${b.dataset.test}/test`, { method: "POST" });
          toast(res.message, !res.ok);
        } catch (e) { toast(e.message, true); }
        finally { b.textContent = "Test"; b.disabled = false; loadKeys(); checkHealth(); }
      }));
  } catch (e) { /* keys are optional */ }
}

$("addKeyBtn").addEventListener("click", async () => {
  const secret = $("keySecret").value.trim();
  if (!secret) { toast("Paste the key."); return; }
  try {
    await api("/api/keys", {
      method: "POST",
      body: JSON.stringify({
        label: $("keyLabel").value, secret,
        workspace_id: $("keyWorkspace").value.trim() || null,
      }),
    });
    $("keyLabel").value = ""; $("keySecret").value = "";
    $("keyWorkspace").value = "";
    loadKeys(); checkHealth();
    toast("Key added.");
  } catch (e) { toast(e.message, true); }
});

$("wakeKeysBtn").addEventListener("click", async () => {
  const r = await api("/api/keys/wake", { method: "POST" });
  toast(`${r.cleared} key(s) back in rotation.`);
  loadKeys();
});

loadAccount();

/* ============================== screener ==============================
   Four tasks, scored only against each other. The pair that matters is
   visual span vs SPOKEN span - presenting the same task in two modalities is
   what turns "I'm bad at remembering" into "the spoken channel is the narrow
   one", which is the whole basis of how this app teaches. */

const scr = { runId: null, task: null, data: null, round: 0,
              span: 3, results: [], t0: 0, catalogue: null };

const SHAPES = {
  circle: '<circle cx="50" cy="50" r="42"/>',
  square: '<rect x="10" y="10" width="80" height="80" rx="8"/>',
  triangle: '<polygon points="50,8 92,88 8,88"/>',
  diamond: '<polygon points="50,6 94,50 50,94 6,50"/>',
  hexagon: '<polygon points="50,6 92,28 92,72 50,94 8,72 8,28"/>',
  star: '<polygon points="50,5 61,38 96,38 68,59 79,93 50,72 21,93 32,59 4,38 39,38"/>',
  cross: '<polygon points="35,8 65,8 65,35 92,35 92,65 65,65 65,92 35,92 35,65 8,65 8,35 35,35"/>',
  heart: '<path d="M50 88C20 66 8 48 8 33a22 22 0 0142-10 22 22 0 0142 10c0 15-12 33-42 55z"/>',
  moon: '<path d="M62 8a44 44 0 100 84 36 36 0 010-84z"/>',
  arrow: '<polygon points="50,6 90,50 66,50 66,94 34,94 34,50 10,50"/>',
  cloud: '<path d="M26 76a20 20 0 010-40 26 26 0 0150-6 18 18 0 012 36z"/>',
  bolt: '<polygon points="58,4 20,56 44,56 38,96 80,42 54,42"/>',
};

const tileSVG = (t) =>
  `<svg viewBox="0 0 100 100" fill="${t.color}">${SHAPES[t.shape] || SHAPES.circle}</svg>`;

async function loadScreener() {
  try {
    const c = await api("/api/screener");
    scr.catalogue = c;
    $("scrDisclaimer").textContent = c.disclaimer;
    $("scrTasks").innerHTML = c.tasks.map((t) => `
      <div class="drillcard" style="cursor:default">
        <span class="dname">${esc(t.name)}</span>
        <span class="dtag">${esc(t.measures)}</span>
        <span class="dwhy">${esc(t.how)}</span>
        <span class="dbest">about ${t.minutes} minutes</span>
      </div>`).join("");
    $("scrIntro").hidden = false;
    $("scrStage").hidden = true;
    $("scrResult").hidden = true;
  } catch (e) { toast(e.message, true); }
}

$("scrSkip").addEventListener("click", () => show("today"));
$("scrQuit").addEventListener("click", () => { speechCancel(); loadScreener(); });

$("scrStart").addEventListener("click", async () => {
  const r = await api("/api/screener/start", {
    method: "POST",
    body: JSON.stringify({ user_id: account.user ? account.user.id : null }),
  });
  scr.runId = r.run_id;
  runTask(0);
});

async function runTask(index) {
  const tasks = scr.catalogue.tasks;
  if (index >= tasks.length) return finishScreener();

  scr.task = tasks[index];
  scr.taskIndex = index;
  scr.round = 0;
  scr.span = 3;
  scr.results = [];

  $("scrIntro").hidden = true;
  $("scrResult").hidden = true;
  $("scrStage").hidden = false;
  $("scrName").textContent = `${scr.task.name}  (${index + 1} of ${tasks.length})`;
  $("scrHow").textContent = scr.task.how;
  $("scrFeedback").innerHTML = "";

  scr.data = await api("/api/screener/build", {
    method: "POST",
    body: JSON.stringify({ task: scr.task.id, span: scr.span, rounds: 6 }),
  });
  nextRound();
}

function nextRound() {
  const id = scr.task.id;
  if (id === "visual_span") return roundVisualSpan();
  if (id === "spoken_span") return roundSpokenSpan();
  if (id === "naming") return roundNaming();
  if (id === "switching") return roundSwitching();
}

/* Spans run a fixed six rounds; the other tasks run whatever the server
   built, so the counter has to ask rather than assume. */
const scrTotal = () =>
  scr.task.id.endsWith("span") ? 6 : Math.min(8, scr.data.rounds.length);

const scrProgress = () =>
  `<div class="scrmeta"><span>round ${scr.round + 1} of ${scrTotal()}</span>` +
  (scr.task.id.endsWith("span") ? `<span>length ${scr.span}</span>` : "") + `</div>`;

/* --- visual span ------------------------------------------------------ */

async function roundVisualSpan() {
  const r = scr.data.rounds[0];
  const picks = [];

  $("scrBody").innerHTML = scrProgress() + `
    <div class="scrgrid" id="scrGrid">${r.grid.map((t, i) =>
      `<button class="scrtile" data-i="${i}" disabled>${tileSVG(t)}</button>`).join("")}</div>`;
  $("scrFeedback").innerHTML = "";

  const tiles = [...$("scrGrid").querySelectorAll(".scrtile")];
  await new Promise((res) => setTimeout(res, 600));
  for (const i of r.sequence) {
    tiles[i].classList.add("lit");
    await new Promise((res) => setTimeout(res, 700));
    tiles[i].classList.remove("lit");
    await new Promise((res) => setTimeout(res, 250));
  }

  tiles.forEach((t) => {
    t.disabled = false;
    t.addEventListener("click", () => {
      if (picks.includes(+t.dataset.i)) return;
      picks.push(+t.dataset.i);
      t.classList.add("picked");
      if (picks.length === r.sequence.length) {
        const ok = picks.every((v, k) => v === r.sequence[k]);
        tiles.forEach((x) => { x.disabled = true; });
        r.sequence.forEach((v) => tiles[v].classList.add(ok ? "right" : "wrong"));
        spanRoundDone(ok, r.sequence.length);
      }
    });
  });
}

/* --- spoken span ------------------------------------------------------ */

function speechCancel() {
  try { window.speechSynthesis.cancel(); } catch { /* not supported */ }
}

function speak(text) {
  return new Promise((resolve) => {
    if (!window.speechSynthesis) return resolve(false);
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.95;
    u.onend = () => resolve(true);
    u.onerror = () => resolve(false);
    window.speechSynthesis.speak(u);
  });
}

async function roundSpokenSpan() {
  const r = scr.data.rounds[0];
  const supported = !!window.speechSynthesis;

  $("scrBody").innerHTML = scrProgress() + `
    <div class="spokenbox">
      <div class="speaking" id="scrSpeak">${supported ? "Listen…" : ""}</div>
      ${supported ? "" : `<p class="hint">Your browser can't speak, so the words
        are shown instead. That makes this a second visual task rather than a
        spoken one — the comparison between the two will mean less.</p>`}
      <input type="text" id="scrWords" placeholder="Type the words in order, separated by spaces"
             autocomplete="off" disabled>
      <div class="row"><button class="btn primary" id="scrWordsGo" disabled>Check</button></div>
    </div>`;
  $("scrFeedback").innerHTML = "";

  for (const w of r.words) {
    if (supported) {
      $("scrSpeak").textContent = "🔊";
      await speak(w);
    } else {
      $("scrSpeak").textContent = w;
      await new Promise((res) => setTimeout(res, 900));
    }
    $("scrSpeak").textContent = "";
    await new Promise((res) => setTimeout(res, 250));
  }
  $("scrSpeak").textContent = "Now type them";

  const input = $("scrWords"), go = $("scrWordsGo");
  input.disabled = false; go.disabled = false;
  input.focus();

  const submit = () => {
    const said = input.value.toLowerCase().split(/[\s,]+/).filter(Boolean);
    const ok = said.length === r.words.length &&
               said.every((w, i) => w === r.words[i].toLowerCase());
    $("scrFeedback").innerHTML =
      `<div class="drillverdict ${ok ? "right" : "wrong"}">${
        ok ? "All in order." : `The words were: ${r.words.join(" · ")}`}</div>`;
    input.disabled = true; go.disabled = true;
    spanRoundDone(ok, r.words.length);
  };
  go.addEventListener("click", submit, { once: true });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go.click(); });
}

/* Shared span logic: lengthen on success, shorten on failure, and record the
   longest run reproduced correctly. */
async function spanRoundDone(ok, length) {
  scr.results.push({ span: length, correct: ok });
  scr.span = ok ? Math.min(9, scr.span + 1) : Math.max(2, scr.span - 1);
  scr.round++;

  $("scrFeedback").insertAdjacentHTML("beforeend",
    `<button class="btn primary" id="scrNext">${
      scr.round >= 6 ? "Done" : "Next"}</button>`);
  $("scrNext").addEventListener("click", async () => {
    if (scr.round >= 6) return finishTask();
    scr.data = await api("/api/screener/build", {
      method: "POST",
      body: JSON.stringify({ task: scr.task.id, span: scr.span, rounds: 1 }),
    });
    nextRound();
  }, { once: true });
}

/* --- naming ----------------------------------------------------------- */

function roundNaming() {
  const r = scr.data.rounds[scr.round];
  if (!r) return finishTask();
  scr.t0 = performance.now();

  $("scrBody").innerHTML = scrProgress() + `
    <div class="spokenbox">
      <div class="nameclue">${esc(r.prompt)}</div>
      <input type="text" id="scrName2" placeholder="Type the word" autocomplete="off">
      <div class="row"><button class="btn primary" id="scrNameGo">Next</button></div>
      <p class="hint">Not timed against anyone else — the app only compares your
        own answers with each other.</p>
    </div>`;
  $("scrFeedback").innerHTML = "";
  setTimeout(() => $("scrName2").focus(), 40);

  const submit = () => {
    const given = $("scrName2").value.trim().toLowerCase();
    const ok = given === r.answer || (r.accept || []).includes(given);
    scr.results.push({ ms: Math.round(performance.now() - scr.t0), correct: ok });
    scr.round++;
    if (scr.round >= scrTotal()) return finishTask();
    roundNaming();
  };
  $("scrNameGo").addEventListener("click", submit, { once: true });
  $("scrName2").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("scrNameGo").click();
  });
}

/* --- switching -------------------------------------------------------- */

function roundSwitching() {
  const r = scr.data.rounds[scr.round];
  if (!r) return finishTask();

  $("scrBody").innerHTML = `
    <div class="scrmeta"><span>round ${scr.round + 1} of ${scr.data.rounds.length}</span></div>
    <div class="rulebar ${r.switched ? "switched" : ""}">
      ${r.switched ? "⇄ The rule just changed — " : ""}Sort by
      <b>${esc(r.rule === "living" ? "living or not" : r.rule)}</b>
    </div>
    <div class="spokenbox"><div class="nameclue">${esc(r.word)}</div></div>
    <div class="oddgrid">${r.options.map((o) =>
      `<button class="oddopt" data-o="${esc(o)}"><span class="oname">${esc(o)}</span></button>`
    ).join("")}</div>`;
  $("scrFeedback").innerHTML = "";

  $("scrBody").querySelectorAll(".oddopt").forEach((b) =>
    b.addEventListener("click", () => {
      const ok = b.dataset.o === r.answer;
      scr.results.push({ correct: ok, switched: !!r.switched });
      scr.round++;
      if (scr.round >= scr.data.rounds.length) return finishTask();
      roundSwitching();
    }));
}

/* --- finishing -------------------------------------------------------- */

async function finishTask() {
  speechCancel();
  const id = scr.task.id;
  let result = {};

  if (id.endsWith("span")) {
    const correct = scr.results.filter((r) => r.correct);
    result = {
      best_span: correct.length ? Math.max(...correct.map((r) => r.span)) : 2,
      rounds: scr.results.length,
      accuracy: scr.results.length ? correct.length / scr.results.length : 0,
    };
  } else if (id === "naming") {
    const times = scr.results.map((r) => r.ms).sort((a, b) => a - b);
    result = {
      median_ms: times.length ? times[Math.floor(times.length / 2)] : null,
      accuracy: scr.results.length
        ? scr.results.filter((r) => r.correct).length / scr.results.length : 0,
      rounds: scr.results.length,
    };
  } else {
    const sw = scr.results.filter((r) => r.switched);
    const st = scr.results.filter((r) => !r.switched);
    const acc = (list) => list.length
      ? list.filter((r) => r.correct).length / list.length : null;
    result = {
      accuracy: acc(scr.results), switch_accuracy: acc(sw),
      stay_accuracy: acc(st), rounds: scr.results.length,
    };
  }

  try {
    await api("/api/screener/record", {
      method: "POST",
      body: JSON.stringify({ run_id: scr.runId, task: id, result }),
    });
  } catch (e) { toast(e.message, true); }
  runTask(scr.taskIndex + 1);
}

async function finishScreener() {
  const run = await api(`/api/screener/${scr.runId}`);
  const p = run.profile;

  $("scrStage").hidden = true;
  $("scrResult").hidden = false;
  $("scrProfile").innerHTML = `
    ${(p.contrasts || []).map((c) => `
      <div class="insight">
        <div class="iclaim">${esc(c.finding)}</div>
        <p style="margin-top:8px">${esc(c.means)}</p>
      </div>`).join("")}
    <h4>What the app will do</h4>
    <div class="md">${md(
      "| Setting | Value |\n|---|---|\n" +
      Object.entries(p.settings || {})
        .map(([k, v]) => `| ${k.replace(/_/g, " ")} | ${v} |`).join("\n"))}</div>
    ${(p.notes || []).map((n) => `<p class="honesty">${esc(n)}</p>`).join("")}`;
}

$("scrApply").addEventListener("click", async () => {
  try {
    await api(`/api/screener/${scr.runId}/apply`, {
      method: "POST",
      body: JSON.stringify({ user_id: account.user ? account.user.id : null }),
    });
    await loadAccount();
    toast("Profile saved. Every prompt now carries it.");
    show("today");
    loadDashboard();
  } catch (e) { toast(e.message, true); }
});
$("scrRedo").addEventListener("click", loadScreener);

/* ==================== file library and importing ======================
   Uploads used to live only in memory, so the Material tab emptied itself on
   every restart while the bytes stayed on disk. This reads the durable list. */

/* =============================== the Library ==========================
   Designed for the library this becomes, not the one it is: hundreds of
   lectures, slide decks, notes and textbooks across several terms.

   That rules out the card-per-file list this replaces. The unit is a row; the
   page is one server-side page of rows; the counts on it are cached rather
   than recomputed by scanning the question bank. Everything a row can do
   beyond opening lives in its overflow menu, so scanning a hundred names is
   not a walk past six hundred buttons. */

const lib = {
  q: "", term_id: "", exam_id: "", kind: "", status: "",
  sort: "added", offset: 0, limit: 50,
  total: 0, files: [], facets: null, opts: null,
  selected: new Set(),
  filtersReady: false,
};

const KIND_LABEL = {
  lecture: "Lecture", slides: "Slides", textbook: "Textbook",
  notes: "Notes", other: "Other",
};
const STATUS_LABEL = {
  ready: "Ready", concepts_only: "Concepts only",
  unprocessed: "Needs processing", missing: "File missing",
};

/* A status is only useful if it implies a next move. */
const STATUS_NEXT = {
  ready: "Questions from this are in rotation.",
  concepts_only: "Concepts are indexed, but no questions have been written yet.",
  unprocessed: "Nothing has been read out of this yet — copy its text and " +
               "write a question set, or let Claude read it.",
  missing: "The record is here but the file is not on disk. Re-add it to use it.",
};

function libQuery() {
  const p = new URLSearchParams();
  ["q", "term_id", "exam_id", "kind", "status", "sort"].forEach((k) => {
    if (lib[k]) p.set(k, lib[k]);
  });
  p.set("limit", lib.limit);
  p.set("offset", lib.offset);
  return p.toString();
}

async function libOptions() {
  if (lib.opts) return lib.opts;
  lib.opts = await api("/api/scope/options").catch(() => ({ terms: [], exams: [] }));
  scopeState.options = scopeState.options || lib.opts;
  return lib.opts;
}

function opt(value, label, current) {
  return `<option value="${esc(value)}"${
    String(value) === String(current) ? " selected" : ""}>${esc(label)}</option>`;
}

async function renderLibFilters() {
  if (lib.filtersReady) return;
  const o = await libOptions();

  $("libTerm").innerHTML = opt("", "All terms", lib.term_id) +
    (o.terms || []).map((t) => opt(t.id, t.name, lib.term_id)).join("");
  $("libExam").innerHTML = opt("", "All exams", lib.exam_id) +
    opt("none", "Not filed", lib.exam_id) +
    (o.exams || []).map((e) =>
      opt(e.id, e.name + (e.past ? " (sat)" : ""), lib.exam_id)).join("");
  $("libKind").innerHTML = opt("", "All types", lib.kind) +
    Object.entries(KIND_LABEL).map(([k, v]) => opt(k, v, lib.kind)).join("");
  $("libStatus").innerHTML = opt("", "Any status", lib.status) +
    Object.entries(STATUS_LABEL).map(([k, v]) => opt(k, v, lib.status)).join("");
  $("libSort").innerHTML = [
    ["added", "Newest first"], ["added_asc", "Oldest first"],
    ["name", "Name A-Z"], ["name_desc", "Name Z-A"],
    ["questions", "Most questions"], ["concepts", "Most concepts"],
    ["size", "Largest"],
  ].map(([k, v]) => opt(k, v, lib.sort)).join("");

  // The exam picker in the bulk bar offers the same choices.
  $("bulkExam").innerHTML = opt("", "Assign to exam\u2026", "") +
    (o.exams || []).map((e) => opt(e.id, e.name, "")).join("");
  $("bulkKind").innerHTML = opt("", "Set type\u2026", "") +
    Object.entries(KIND_LABEL).map(([k, v]) => opt(k, v, "")).join("");

  ["libTerm", "libExam", "libKind", "libStatus", "libSort"].forEach((id) => {
    $(id).addEventListener("change", () => {
      lib[{ libTerm: "term_id", libExam: "exam_id", libKind: "kind",
            libStatus: "status", libSort: "sort" }[id]] = $(id).value;
      lib.offset = 0;
      loadLibrary();
    });
  });
  $("libClear").addEventListener("click", () => {
    Object.assign(lib, { q: "", term_id: "", exam_id: "", kind: "",
                         status: "", sort: "added", offset: 0 });
    $("libSearch").value = "";
    ["libTerm", "libExam", "libKind", "libStatus"].forEach((i) => { $(i).value = ""; });
    $("libSort").value = "added";
    loadLibrary();
  });

  lib.filtersReady = true;
}

const fmtDate = (t) => new Date(t * 1000).toLocaleDateString(undefined,
  { month: "short", day: "numeric", year: "numeric" });

async function loadLibrary() {
  await renderLibFilters();
  let r;
  try {
    r = await api(`/api/library?${libQuery()}`);
  } catch (e) {
    $("libBody").innerHTML =
      `<tr><td colspan="8" class="tempty">${esc(e.message)}</td></tr>`;
    return;
  }

  lib.files = r.files || [];
  lib.total = r.total || 0;
  lib.facets = r.facets || null;

  const filtered = !!(lib.q || lib.term_id || lib.exam_id || lib.kind || lib.status);
  $("libClear").hidden = !filtered;

  const nothingAtAll = !filtered && lib.total === 0;
  $("libEmpty").hidden = !nothingAtAll;
  $("libTable").hidden = nothingAtAll;
  document.querySelector(".libfoot").hidden = nothingAtAll;

  renderLibRows();
  renderLibFoot();
  renderLibNag();
}

function statusChip(f) {
  return `<span class="stchip st-${f.status}">${
    esc(STATUS_LABEL[f.status] || f.status)}</span>`;
}

function renderLibRows() {
  const body = $("libBody");
  if (!lib.files.length) {
    body.innerHTML = `<tr><td colspan="8" class="tempty">
      Nothing matches these filters.</td></tr>`;
    $("libAll").checked = false;
    return;
  }

  body.innerHTML = lib.files.map((f) => `
    <tr class="librow${lib.selected.has(f.id) ? " on" : ""}${
        f.present ? "" : " gone"}" data-row="${esc(f.id)}">
      <td class="tcheck"><input type="checkbox" data-pick="${esc(f.id)}"
          ${lib.selected.has(f.id) ? "checked" : ""} aria-label="Select ${esc(f.name)}"></td>
      <td class="tname">
        <button class="linkname" data-open="${esc(f.id)}">${esc(f.name)}</button>
        <span class="rowsub">${esc(f.ext.toUpperCase())}${
          f.pages ? ` \u00b7 ${f.pages} pages` : ""} \u00b7 ${f.mb} MB${
          f.tags.length ? " \u00b7 " + f.tags.map(esc).join(", ") : ""}</span>
      </td>
      <td class="thide-s">${f.exam
        ? `<span class="examchip">${esc(f.exam.name)}</span>`
        : `<span class="muted">\u2014</span>`}</td>
      <td class="cnum thide-s">${f.concepts || `<span class="muted">\u2014</span>`}</td>
      <td class="cnum">${f.questions || `<span class="muted">\u2014</span>`}</td>
      <td class="tstatus">${statusChip(f)}</td>
      <td class="cnum thide-m mutedcell">${fmtDate(f.added_at)}</td>
      <td class="tmenu"><button class="rowmenu" data-menu="${esc(f.id)}"
          aria-label="More actions for ${esc(f.name)}">\u22ee</button></td>
    </tr>`).join("");

  body.querySelectorAll("[data-open]").forEach((b) =>
    b.addEventListener("click", () => openFile(b.dataset.open)));
  body.querySelectorAll("[data-pick]").forEach((b) =>
    b.addEventListener("change", () => {
      if (b.checked) lib.selected.add(b.dataset.pick);
      else lib.selected.delete(b.dataset.pick);
      b.closest("tr").classList.toggle("on", b.checked);
      renderBulk();
    }));
  body.querySelectorAll("[data-menu]").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); rowMenu(b); }));

  $("libAll").checked = lib.files.length > 0 &&
    lib.files.every((f) => lib.selected.has(f.id));
  renderBulk();
}

function renderLibFoot() {
  const from = lib.total ? lib.offset + 1 : 0;
  const to = Math.min(lib.offset + lib.limit, lib.total);
  $("libCount").textContent = lib.total
    ? `${from}\u2013${to} of ${lib.total} file${lib.total === 1 ? "" : "s"}`
    : "";

  const pages = Math.ceil(lib.total / lib.limit) || 1;
  const cur = Math.floor(lib.offset / lib.limit) + 1;
  $("libPager").innerHTML = pages < 2 ? "" : `
    <button class="btn ghost small" data-page="prev" ${cur === 1 ? "disabled" : ""}>Back</button>
    <span class="hint">Page ${cur} of ${pages}</span>
    <button class="btn ghost small" data-page="next" ${cur === pages ? "disabled" : ""}>Next</button>`;
  $("libPager").querySelectorAll("[data-page]").forEach((b) =>
    b.addEventListener("click", () => {
      lib.offset += (b.dataset.page === "next" ? 1 : -1) * lib.limit;
      lib.offset = Math.max(0, lib.offset);
      loadLibrary();
      document.querySelector(".tablewrap").scrollIntoView({ block: "start" });
    }));
}

function renderLibNag() {
  const box = $("libPresets");
  const un = lib.facets && lib.facets.exam ? (lib.facets.exam.none || 0) : 0;
  if (!un) { box.innerHTML = ""; box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = `<span>${un} file${un === 1 ? " is" : "s are"} not filed under
    an exam. Filing is what lets you practise "just Friday's paper".</span>
    <button class="btn ghost small" id="showUnfiled">Show them</button>`;
  $("showUnfiled").addEventListener("click", () => {
    lib.exam_id = "none"; lib.offset = 0;
    $("libExam").value = "none";
    loadLibrary();
  });
}

/* ------------------------------ selection ---------------------------- */

$("libAll").addEventListener("change", () => {
  const on = $("libAll").checked;
  lib.files.forEach((f) => on ? lib.selected.add(f.id) : lib.selected.delete(f.id));
  renderLibRows();
});

function renderBulk() {
  const n = lib.selected.size;
  $("libBulk").hidden = n === 0;
  $("libBulkCount").textContent = `${n} file${n === 1 ? "" : "s"} selected`;
}

async function runBulk(action, value) {
  const ids = [...lib.selected];
  if (!ids.length) return;
  try {
    const r = await api("/api/library/bulk", {
      method: "POST", body: JSON.stringify({ ids, action, value }),
    });
    const extra = r.concepts_attached
      ? ` \u00b7 ${r.concepts_attached} concepts added to the exam` : "";
    toast(`${r.done} file${r.done === 1 ? "" : "s"} updated${extra}.` +
          (r.failed.length ? ` ${r.failed.length} failed.` : ""));
    lib.selected.clear();
    loadLibrary();
  } catch (e) { toast(e.message, true); }
}

$("bulkExam").addEventListener("change", () => {
  if ($("bulkExam").value) { runBulk("exam", $("bulkExam").value); $("bulkExam").value = ""; }
});
$("bulkKind").addEventListener("change", () => {
  if ($("bulkKind").value) { runBulk("kind", $("bulkKind").value); $("bulkKind").value = ""; }
});
$("bulkTag").addEventListener("click", () => {
  modal("Tag these files", [{ name: "tag", label: "Tag",
    placeholder: "e.g. pharmacology" }], async (v) => {
    if (!v.tag) throw new Error("Give the tag a name.");
    await runBulk("tag", v.tag.trim());
  });
});
$("bulkDelete").addEventListener("click", () => {
  const n = lib.selected.size;
  if (!confirm(`Remove ${n} file${n === 1 ? "" : "s"}? ` +
               "The questions already made from them stay in your bank.")) return;
  runBulk("delete");
});
$("bulkClear").addEventListener("click", () => {
  lib.selected.clear();
  renderLibRows();
});

/* ------------------------------ row menu ----------------------------- */

function closeRowMenu() {
  document.querySelectorAll(".rowpop").forEach((x) => x.remove());
}
document.addEventListener("click", closeRowMenu);

function rowMenu(btn) {
  const id = btn.dataset.menu;
  const f = lib.files.find((x) => x.id === id);
  if (!f) return;
  const open = document.querySelector(`.rowpop[data-for="${id}"]`);
  closeRowMenu();
  if (open) return;

  const items = [
    ["open", "Open the detail view"],
    ["study", "Study just this"],
    ["text", "Copy its text"],
    ["preread", "Pre-read it"],
    ["download", "Open the document"],
    ["rename", "Rename\u2026"],
    ["kind", "Change type\u2026"],
    ["delete", "Remove"],
  ];
  const pop = document.createElement("div");
  pop.className = "rowpop";
  pop.dataset.for = id;
  pop.innerHTML = items.map(([k, label]) =>
    `<button data-act="${k}"${
      (!f.present && ["text", "preread", "download"].includes(k)) ? " disabled" : ""
    }${k === "delete" ? ' class="danger"' : ""}>${label}</button>`).join("");
  pop.addEventListener("click", (e) => e.stopPropagation());

  const r = btn.getBoundingClientRect();
  pop.style.top = `${r.bottom + window.scrollY + 4}px`;
  pop.style.left = `${r.right + window.scrollX - 196}px`;
  document.body.appendChild(pop);

  pop.querySelectorAll("[data-act]").forEach((b) =>
    b.addEventListener("click", () => { closeRowMenu(); rowAction(b.dataset.act, f, b); }));
}

async function rowAction(act, f, btn) {
  if (act === "open") return openFile(f.id);
  if (act === "text") return copyFileText(f.id, btn);
  if (act === "preread") { show("material"); return runPreread(f.id, btn); }
  if (act === "download") { window.location.href = `/api/library/${f.id}/download`; return; }
  if (act === "study") return studyFile(f);
  if (act === "rename") {
    return modal("Rename", [{ name: "name", label: "Name", value: f.name }],
      async (v) => {
        if (!v.name.trim()) throw new Error("Give it a name.");
        await api(`/api/library/${f.id}`, {
          method: "PATCH", body: JSON.stringify({ original_name: v.name.trim() }) });
        loadLibrary();
      });
  }
  if (act === "kind") {
    return modal("Change type", [{ name: "kind", label: "Type", type: "select",
      value: f.kind, options: Object.entries(KIND_LABEL)
        .map(([k, v]) => ({ value: k, label: v })) }],
      async (v) => {
        await api(`/api/library/${f.id}`, {
          method: "PATCH", body: JSON.stringify({ kind: v.kind }) });
        loadLibrary();
      });
  }
  if (act === "delete") {
    if (!confirm(`Remove "${f.name}"? The questions already made from it stay ` +
                 "in your bank.")) return;
    try {
      await api(`/api/library/${f.id}`, { method: "DELETE" });
      lib.selected.delete(f.id);
      toast("Removed.");
      loadLibrary();
    } catch (e) { toast(e.message, true); }
  }
}

/* Sends you into Practice with this one file as the whole pool. This is the
   connection that makes a Library worth having rather than a folder. */
function studyFile(f) {
  scopeState.upload_ids = [f.id];
  navigate("quiz");
  if (typeof renderScopeMaterial === "function") renderScopeMaterial();
  if (typeof refreshScopeCount === "function") refreshScopeCount();
  toast(`Practice is now drawing only from ${f.name}.`);
}

/* ----------------------------- detail panel -------------------------- */

async function openFile(uid) {
  const dw = $("libDrawer");
  $("dwBody").innerHTML = `<p class="hint">Loading\u2026</p>`;
  $("dwName").textContent = "";
  $("dwMeta").textContent = "";
  dw.hidden = false;
  $("libScrim").hidden = false;

  let d;
  try { d = await api(`/api/library/${uid}/detail`); }
  catch (e) { $("dwBody").innerHTML = `<p class="hint">${esc(e.message)}</p>`; return; }

  $("dwName").textContent = d.name;
  $("dwMeta").textContent = [
    KIND_LABEL[d.kind] || d.kind,
    d.exam ? d.exam.name : "not filed under an exam",
    d.pages ? `${d.pages} pages` : null,
    `${d.mb} MB`,
    `added ${fmtDate(d.added_at)}`,
  ].filter(Boolean).join(" \u00b7 ");

  const num = (v, label) =>
    `<div class="dwnum"><b>${v}</b><span>${label}</span></div>`;

  const weak = d.weak.length ? `
    <h4>Weakest from this file</h4>
    <div class="dwweaks">${d.weak.map((c) => `
      <button class="dwweak" data-concept="${esc(c.id)}">
        <span class="wname">${esc(c.name)}</span>
        <span class="wband band-${esc(c.band)}">${
          Math.round(c.effective * 100)}%</span>
      </button>`).join("")}</div>`
    : `<h4>Weakest from this file</h4>
       <p class="hint">Nothing from this file has been answered yet, so there is
         no weakness to report. That is different from knowing it.</p>`;

  $("dwBody").innerHTML = `
    <div class="dwacts">
      <button class="btn primary" data-dw="study">Study this</button>
      <button class="btn" data-dw="download" ${d.present ? "" : "disabled"}>Open document</button>
      <button class="btn ghost" data-dw="text" ${d.present ? "" : "disabled"}>Copy text</button>
      <button class="btn ghost" data-dw="preread" ${d.present ? "" : "disabled"}>Pre-read</button>
    </div>

    <div class="dwnums">
      ${num(d.concepts, "concepts")}
      ${num(d.questions, "questions")}
      ${num(d.assessed, "answered")}
      ${num(d.mastery === null ? "\u2014" : Math.round(d.mastery * 100) + "%",
            d.mastery === null ? "not assessed" : "mastery")}
    </div>
    <p class="dwstatus">${statusChip(d)}
      <span class="hint">${esc(STATUS_NEXT[d.status] || "")}</span></p>

    ${weak}

    <h4>Everything this file taught</h4>
    ${d.concept_list.length ? `<div class="dwconcepts">${d.concept_list.map((c) => `
      <button class="dwconcept" data-concept="${esc(c.id)}">
        <span>${esc(c.name)}</span>
        <span class="hy hy-${esc(c.hy_tier)}">${esc(c.hy_tier)}</span>
      </button>`).join("")}</div>`
      : `<p class="hint">No concepts are linked to this file yet. Add questions
           from it and they will appear here.</p>`}`;

  $("dwBody").querySelectorAll("[data-concept]").forEach((b) =>
    b.addEventListener("click", () => {
      closeDrawer(); showConcept(b.dataset.concept);
    }));
  $("dwBody").querySelectorAll("[data-dw]").forEach((b) =>
    b.addEventListener("click", () => {
      const act = b.dataset.dw;
      if (act === "study") { closeDrawer(); studyFile(d); return; }
      if (act === "preread") { closeDrawer(); runPreread(d.id, b); return; }
      rowAction(act, d, b);
    }));
}

function closeDrawer() {
  $("libDrawer").hidden = true;
  $("libScrim").hidden = true;
}
$("dwClose").addEventListener("click", closeDrawer);
$("libScrim").addEventListener("click", closeDrawer);

/* ------------------------------- search ------------------------------ */

let libSearchTimer = null;

$("libSearch").addEventListener("input", () => {
  clearTimeout(libSearchTimer);
  libSearchTimer = setTimeout(runLibSearch, 220);
});

$("libSearch").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { $("libSearchDrop").hidden = true; }
  if (e.key === "Enter") {
    lib.q = $("libSearch").value.trim();
    lib.offset = 0;
    $("libSearchDrop").hidden = true;
    loadLibrary();
  }
});

/* Three lists, not one ranked list. "Where is that lecture" and "what do I
   know about bethanechol" are different questions; merging them makes both
   answers harder to see. */
async function runLibSearch() {
  const text = $("libSearch").value.trim();
  const box = $("libSearchDrop");
  if (text.length < 2) {
    box.hidden = true;
    if (lib.q) { lib.q = ""; lib.offset = 0; loadLibrary(); }
    return;
  }
  let r;
  try { r = await api(`/api/library/search?q=${encodeURIComponent(text)}`); }
  catch { box.hidden = true; return; }

  const sec = (title, rows) => rows.length
    ? `<div class="sdsec"><h5>${title}</h5>${rows.join("")}</div>` : "";

  box.innerHTML =
    sec("Files", r.files.map((f) => `
      <button class="sdrow" data-sfile="${esc(f.id)}">
        <span>${esc(f.name)}</span>
        <span class="hint">${f.questions || 0} questions</span>
      </button>`)) +
    sec("Concepts", r.concepts.map((c) => `
      <button class="sdrow" data-sconcept="${esc(c.id)}">
        <span>${esc(c.name)}</span>
        <span class="hint">${esc(c.topic || "")}</span>
      </button>`)) +
    (r.questions
      ? `<div class="sdsec"><button class="sdrow" data-sq="1">
           <span>${r.questions} question${r.questions === 1 ? "" : "s"} mention
           "${esc(r.query)}"</span><span class="hint">filter the library</span>
         </button></div>`
      : "");

  if (!box.innerHTML) {
    box.innerHTML = `<div class="sdsec"><p class="hint">Nothing found.</p></div>`;
  }
  box.hidden = false;

  box.querySelectorAll("[data-sfile]").forEach((b) =>
    b.addEventListener("click", () => { box.hidden = true; openFile(b.dataset.sfile); }));
  box.querySelectorAll("[data-sconcept]").forEach((b) =>
    b.addEventListener("click", () => {
      box.hidden = true; showConcept(b.dataset.sconcept);
    }));
  box.querySelectorAll("[data-sq]").forEach((b) =>
    b.addEventListener("click", () => {
      box.hidden = true; lib.q = text; lib.offset = 0; loadLibrary();
    }));
}

document.addEventListener("click", (e) => {
  if (!e.target.closest || !e.target.closest(".searchwrap")) {
    $("libSearchDrop").hidden = true;
  }
});

/* --------------------------- adding material ------------------------- */

function openAddSheet() { $("addSheet").hidden = false; }
function closeAddSheet() { $("addSheet").hidden = true; }
$("addMaterialBtn").addEventListener("click", openAddSheet);
$("emptyAdd").addEventListener("click", openAddSheet);
$("addClose").addEventListener("click", closeAddSheet);
$("addSheet").addEventListener("click", (e) => {
  if (e.target === $("addSheet")) closeAddSheet();
});
$("uqClose").addEventListener("click", () => { $("upQueue").hidden = true; });

/* Dropping files anywhere on the Library works, rather than requiring you to
   find the dashed rectangle first. */
const matView = document.getElementById("view-material");
const carriesFiles = (e) =>
  e.dataTransfer && [...e.dataTransfer.types].includes("Files");

["dragenter", "dragover"].forEach((ev) =>
  matView.addEventListener(ev, (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault();
    matView.classList.add("dragging");
  }));
matView.addEventListener("dragleave", (e) => {
  if (e.relatedTarget && matView.contains(e.relatedTarget)) return;
  matView.classList.remove("dragging");
});
matView.addEventListener("drop", (e) => {
  if (!carriesFiles(e)) return;
  e.preventDefault();
  matView.classList.remove("dragging");
  // The sheet's own drop zone handles its own event; this is the page-wide
  // fallback, so it must not double-fire for the same drop.
  if (e.target.closest && e.target.closest("#drop")) return;
  upload(e.dataTransfer.files);
});

/* Extraction happens on this machine - reading a PDF you already have should
   not cost an API call. */
async function copyFileText(id, btn) {
  const was = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Reading\u2026"; }
  try {
    const r = await api(`/api/library/${id}/text`);
    if (!r.text || !r.text.trim()) {
      toast("No text could be extracted \u2014 this PDF is probably scanned images.", true);
      return;
    }
    await navigator.clipboard.writeText(r.text);
    toast(`Copied ${r.chars.toLocaleString()} characters. Paste it into your chat.`);
  } catch (e) {
    toast(e.message, true);
  } finally { if (btn) { btn.disabled = false; btn.textContent = was; } }
}

/* ---------------------------- importing ------------------------------ */

/* The spec is built on the server, not here. It is generated from the same
   constants the validator uses and carries your standing notes, so the chat
   that writes the questions already knows what the professor stressed and
   what you keep confusing - which is the entire reason notes exist. */

$("impCopySpec").addEventListener("click", async () => {
  const btn = $("impCopySpec");
  const was = btn.textContent;
  btn.disabled = true; btn.textContent = "Building…";
  try {
    const r = await api("/api/import/spec");
    await navigator.clipboard.writeText(r.spec);
    const notes = (r.spec.match(/STANDING NOTES/) || []).length;
    toast(`Format spec copied${notes ? ", including your standing notes" : ""}. `
          + "Paste it into the other chat first.");
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = was; }
});

function renderImportSummary(sum, errors) {
  const box = $("impResult");
  if (errors && errors.length) {
    box.innerHTML = `<div class="imperr"><b>${errors.length} problem(s).
      Nothing was saved.</b><ul>${
      errors.slice(0, 40).map((e) => `<li>${esc(e)}</li>`).join("")}</ul>${
      errors.length > 40 ? `<p>…and ${errors.length - 40} more.</p>` : ""}</div>`;
    $("impSave").disabled = true;
    return;
  }

  const total = sum.questions || 1;
  const segs = [1, 2, 3, 4].map((d) => {
    const n = sum.by_dok[String(d)] || 0;
    if (!n) return "";
    return `<span class="dokseg dok${d}" style="flex:${n}"
             title="DOK ${d} — ${esc(sum.dok_labels[String(d)])}: ${n}">${n}</span>`;
  }).join("");

  box.innerHTML = `
    <p class="hint" style="margin-top:12px">
      <b>${esc(sum.title)}</b> — ${sum.concepts} concepts, ${sum.questions} questions.</p>
    <div class="dokbar">${segs}</div>
    <div class="dokverdict ${sum.dok_on_target ? "ok" : "under"}">
      DOK 3-4: ${sum.dok_high} of ${sum.questions}
      (${Math.round(sum.dok_high_share * 100)}%) — target ${
        Math.round(sum.dok_target * 100)}%.
      ${sum.dok_on_target
        ? "On target for exam-level questions."
        : "Below target. Your exams are DOK 3-4, so a set that stops at DOK 2 tests recall you already has."}
    </div>
    ${(sum.flags || []).length
      ? `<p class="hint" style="margin-top:8px"><b>${sum.flags.length} flag(s)</b> noted in the material.</p>`
      : ""}`;
  $("impSave").disabled = false;
}

function parseImport() {
  const raw = $("impJson").value.trim();
  if (!raw) { toast("Paste the JSON first."); return null; }
  try {
    return JSON.parse(raw);
  } catch (e) {
    $("impResult").innerHTML =
      `<div class="imperr"><b>That is not valid JSON.</b><ul><li>${
        esc(e.message)}</li></ul><p>If the chat wrapped it in a code fence,
        paste only what is between the fences.</p></div>`;
    $("impSave").disabled = true;
    return null;
  }
}

$("impCheck").addEventListener("click", async () => {
  const payload = parseImport();
  if (!payload) return;
  try {
    const r = await api("/api/import/check", {
      method: "POST", body: JSON.stringify(payload),
    });
    renderImportSummary(r.summary, r.errors);
    if (r.ok) toast("Looks good. Save it when you're ready.");
  } catch (e) { toast(e.message, true); }
});

$("impSave").addEventListener("click", async () => {
  const payload = parseImport();
  if (!payload) return;
  const btn = $("impSave");
  btn.disabled = true; btn.textContent = "Saving…";
  try {
    const r = await api("/api/import/lecture", {
      method: "POST", body: JSON.stringify(payload),
    });
    toast(`Saved: ${r.imported_questions} questions across ${r.imported_concepts} concepts.`);
    $("impJson").value = "";
    $("impResult").innerHTML = "";
    loadLibrary();
    loadDashboard();
  } catch (e) {
    $("impResult").innerHTML =
      `<div class="imperr"><b>Not saved.</b><ul>${
        String(e.message).split("\\n").slice(0, 40)
          .map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div>`;
    toast("Not saved — see the problems listed.", true);
  } finally { btn.textContent = "Save to bank"; btn.disabled = false; }
});

/* Arrival is handled by the ENTER table beside the navigation. */

/* ============= filing files under exams, and scope presets ============ */

/* Named scopes. BCSC is the one that is genuinely hard to express by hand:
   a comprehensive paper covers the whole term INCLUDING blocks already sat,
   so "exclude past exams" has to stay off. */
async function renderScopePresets(container, onPick) {
  const o = scopeState.options || await api("/api/scope/options").catch(() => null);
  if (!o || !o.presets) return;
  scopeState.options = o;

  container.innerHTML = o.presets.map((p) => `
    <button class="preset" data-preset="${esc(p.id)}">
      ${esc(p.name)}<span class="pwhy">${esc(p.why)}</span>
    </button>`).join("");

  container.querySelectorAll("[data-preset]").forEach((b) =>
    b.addEventListener("click", () => {
      const preset = o.presets.find((x) => x.id === b.dataset.preset);
      if (!preset) return;
      container.querySelectorAll(".preset").forEach((x) =>
        x.classList.toggle("on", x === b));
      onPick(preset);
    }));
}

function applyScopePreset(preset) {
  const sc = preset.scope || {};
  scopeState.term_id = sc.term_id || "";
  scopeState.course_id = sc.course_id || "";
  scopeState.exam_ids = sc.exam_ids || [];
  scopeState.exclude_past = !!sc.exclude_past;
  scopeState.include_unmapped = sc.include_unmapped !== false;

  if ($("scopeTerm")) $("scopeTerm").value = scopeState.term_id;
  if ($("scopeCourse")) $("scopeCourse").value = scopeState.course_id;
  if (typeof renderScopeChildren === "function") renderScopeChildren();
  if ($("scopeExam")) $("scopeExam").value = (scopeState.exam_ids || [])[0] || "";
  if ($("scopeExcludePast")) $("scopeExcludePast").checked = scopeState.exclude_past;
  if ($("scopeIncludeUnmapped")) {
    $("scopeIncludeUnmapped").checked = scopeState.include_unmapped;
  }
  if (typeof refreshScopeCount === "function") refreshScopeCount();
  toast(`Scope: ${preset.name}`);
}

/* The unfiled nag is rendered from the facets that come back with the page,
   so it costs no extra request. */

/* ============ standing notes, and scoping to specific material ======== */

async function loadNotes() {
  if (!account.user) return;
  try {
    const r = await api(`/api/users/${account.user.id}/notes`);

    if (!$("noteKind").options.length) {
      $("noteKind").innerHTML = Object.entries(r.kinds)
        .map(([k, label]) => `<option value="${esc(k)}">${esc(label)}</option>`)
        .join("");
    }

    const notes = r.notes || [];
    $("noteList").innerHTML = notes.length
      ? notes.map((n) => `
        <div class="noterow ${n.active ? "" : "off"}">
          <span class="notekind k-${esc(n.kind)}">${esc(n.kind_label)}</span>
          <span class="notetext">${esc(n.text)}${
            n.active && !n.in_prompt
              ? ` <span class="noteoff">· kept for you, not sent to Claude</span>`
              : ""}</span>
          <button class="btn small ghost" data-toggle="${esc(n.id)}">${
            n.active ? "Mute" : "Unmute"}</button>
          <button class="btn small ghost" data-delnote="${esc(n.id)}">×</button>
        </div>`).join("")
      : `<p class="hint">No notes yet. Anything you'd otherwise repeat in every
         conversation belongs here.</p>`;

    $("noteList").querySelectorAll("[data-toggle]").forEach((b) =>
      b.addEventListener("click", async () => {
        const n = notes.find((x) => x.id === b.dataset.toggle);
        await api(`/api/standing-notes/${b.dataset.toggle}`, {
          method: "PATCH", body: JSON.stringify({ active: !n.active }),
        });
        loadNotes();
      }));
    $("noteList").querySelectorAll("[data-delnote]").forEach((b) =>
      b.addEventListener("click", async () => {
        const n = notes.find((x) => x.id === b.dataset.delnote);
        if (!confirm(`Delete this note?\n\n"${n.text}"\n\nMuting keeps it on file instead.`)) return;
        await api(`/api/standing-notes/${b.dataset.delnote}`, { method: "DELETE" });
        loadNotes();
      }));
  } catch (e) { /* notes are optional */ }
}

$("noteAdd").addEventListener("click", async () => {
  const text = $("noteText").value.trim();
  if (!text) { toast("Write the note first."); return; }
  if (!account.user) { toast("No active user.", true); return; }
  try {
    await api(`/api/users/${account.user.id}/notes`, {
      method: "POST",
      body: JSON.stringify({ text, kind: $("noteKind").value }),
    });
    $("noteText").value = "";
    loadNotes();
    toast("Saved. Every prompt carries it from now on.");
  } catch (e) { toast(e.message, true); }
});
$("noteText").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("noteAdd").click();
});

/* --------------------- scope: specific material ---------------------- */

async function renderScopeMaterial() {
  const box = $("scopeMaterial");
  if (!box) return;
  try {
    const r = await api("/api/library");
    const files = r.files || [];
    if (!files.length) {
      box.innerHTML = `<p class="hint">No files yet.</p>`;
      return;
    }
    const chosen = new Set(scopeState.upload_ids || []);
    box.innerHTML = files.map((f) => `
      <div class="matrow ${chosen.has(f.id) ? "on" : ""} ${
        f.questions ? "" : "empty"}" data-mat="${esc(f.id)}">
        <input type="checkbox" ${chosen.has(f.id) ? "checked" : ""}
               ${f.questions ? "" : "disabled"}>
        <span>${esc(f.name.replace(/\.pdf$/i, ""))}</span>
        <span class="mcount">${f.questions || 0} q</span>
      </div>`).join("");

    box.querySelectorAll("[data-mat]").forEach((row) => {
      const cb = row.querySelector("input");
      if (cb.disabled) return;
      row.addEventListener("click", (e) => {
        if (e.target !== cb) cb.checked = !cb.checked;
        row.classList.toggle("on", cb.checked);
        const picked = [...box.querySelectorAll("[data-mat] input:checked")]
          .map((c) => c.closest("[data-mat]").dataset.mat);
        scopeState.upload_ids = picked;
        refreshScopeCount();
      });
    });
  } catch { box.innerHTML = ""; }
}

/* currentScope() predates upload_ids, so extend rather than edit it. */
const _currentScopeBase = currentScope;
currentScope = function () {
  const sc = _currentScopeBase();
  if (scopeState.upload_ids && scopeState.upload_ids.length) {
    sc.upload_ids = scopeState.upload_ids;
  }
  return sc;
};

/* Picking a preset clears any file selection - otherwise the two intersect
   silently and the count drops for no visible reason. */
const _applyScopePresetBase = applyScopePreset;
applyScopePreset = function (preset) {
  scopeState.upload_ids = [];
  _applyScopePresetBase(preset);
  renderScopeMaterial();
};

onEnter("profile", () => loadNotes());

$("scopeToggle").addEventListener("click", () => {
  if (!$("scopePanel").hidden) renderScopeMaterial();
});

loadNotes();

/* ================ help, support and the first-run welcome ============= */

/* Written once and rendered in two places - the Help tab and the welcome
   overlay - so the instructions cannot drift apart. */
const SETUP_STEPS = [
  {
    title: "Add your Anthropic API key",
    body: `Go to <b>Profile &rsaquo; API keys</b> and paste a key from
      <code>console.anthropic.com/settings/keys</code>. You can add several:
      they are tried in order, so if one runs out of credit the next takes over
      mid-request instead of losing your work. Most of the app — practising,
      the mastery map, importing questions — works with no key at all.`,
  },
  {
    title: "If your key is identity-linked, add its Workspace ID",
    body: `Some Anthropic keys are tied to a workspace, and every request has to
      say which one — without it the API refuses the call with
      <code>anthropic-workspace-id is required</code>. You will know because the
      key tests as valid but nothing works. Click <b>Workspace…</b> next to the
      key and paste the ID from the Anthropic Console under
      <b>Settings &rsaquo; Workspaces</b> (it is also in the URL while that
      workspace is open). It looks like <code>wrkspc_…</code>. Organisation-level
      keys do not need this and can leave it blank.`,
  },
  {
    title: "Set up who is studying",
    body: `Under <b>Profile</b>, enter the scores from a neuropsychological
      report if you have one, or run the built-in screener. This is what shapes
      every question the app produces. Add <b>standing notes</b> for things no
      test measured — what a professor stressed, what you keep mixing up — and
      they travel with every request instead of being retyped.`,
  },
  {
    title: "Add your material",
    body: `Add lectures in the <b>Library</b>. Files stay on this machine
      and persist across restarts. Use <b>Copy text</b> to pull a PDF's text out
      locally — no API call — and file each lecture under the exam it belongs
      to so you can practise just that paper, or a whole term.`,
  },
  {
    title: "Make questions — two ways",
    body: `Either let the app generate them from a file, or write them
      elsewhere and paste them into <b>Paste questions from a chat</b>. Hit
      <b>Copy the format spec</b> first: it hands the other conversation the
      exact shape, the rules, your profile and your standing notes. Importing
      costs nothing at the API.`,
  },
  {
    title: "Configure it with Claude Code",
    body: `This app was built with <a href="https://claude.com/claude-code"
      target="_blank" rel="noopener">Claude Code</a>, and it is the fastest way
      to change it. Open a terminal in the project folder and run
      <code>claude</code>. There is a built-in <code>/lecture</code> skill that
      takes a slide deck all the way to banked questions — extraction,
      authoring, validation and filing — in one go.`,
  },
];

function renderSteps(el) {
  if (!el) return;
  el.innerHTML = SETUP_STEPS.map((s, i) => `
    <div class="step">
      <span class="stepnum">${i + 1}</span>
      <span>
        <div class="steptitle">${s.title}</div>
        <div class="stepbody">${s.body}</div>
      </span>
    </div>`).join("");
}

async function loadSupport() {
  renderSteps($("helpSteps"));
  try {
    const r = await api("/api/support");
    $("supportName").textContent = r.name ? `Built by ${r.name}` : "";

    $("supportLinks").innerHTML = (r.links || []).map((l) => `
      <a class="paylink" href="${esc(l.url)}" target="_blank" rel="noopener">
        ${esc(l.name)} &rsaquo;
      </a>`).join("");

    $("supportWallets").innerHTML = (r.wallets || []).map((w) => `
      <div class="wallet">
        <h4>${esc(w.chain)}</h4>
        <div class="qr">${w.qr}</div>
        <div class="waddr">${esc(w.address)}</div>
        ${w.tag ? `<div class="wtag">
            <span class="wtaglabel">Destination tag — required</span>
            <span class="wtagval">${esc(w.tag)}</span>
            <button class="btn small ghost" data-copyaddr="${esc(w.tag)}">Copy tag</button>
            <span class="wtagwarn">Without this tag the payment reaches the
              exchange but not this account.</span>
          </div>` : ""}
        <button class="btn small ghost" data-copyaddr="${esc(w.address)}">Copy address</button>
        <span class="wcheck ${w.checksummed ? "ok" : "weak"}">${
          w.checksummed ? "✓ " : "! "}${esc(w.check_note)}</span>
      </div>`).join("");

    // A fresh clone has no addresses configured. An unexplained empty box
    // reads as a bug; this says what the section is and how to fill it.
    const nothing = !(r.links || []).length && !(r.wallets || []).length;
    document.getElementById("supportCard").hidden = false;
    $("supportEmpty").hidden = !nothing;

    $("supportWallets").querySelectorAll("[data-copyaddr]").forEach((b) =>
      b.addEventListener("click", async () => {
        await navigator.clipboard.writeText(b.dataset.copyaddr);
        const was = b.textContent;
        b.textContent = "Copied";
        setTimeout(() => { b.textContent = was; }, 1400);
      }));

    // An address that failed its checksum is reported, never quietly dropped.
    $("supportWarn").innerHTML = (r.rejected || []).length
      ? `<p class="honesty">${r.rejected.length} address(es) failed validation
         and are not shown: ${r.rejected.map((x) =>
           `${esc(x.chain)} (${esc(x.reason)})`).join(", ")}.</p>`
      : "";
  } catch (e) { /* help still reads without the donate block */ }
}

/* ---------------------------- first run ------------------------------ */

async function maybeWelcome() {
  try {
    const r = await api("/api/support");
    if (!r.first_run) return;
    renderSteps($("welcomeSteps"));
    $("welcome").hidden = false;
  } catch { /* never block the app on this */ }
}

async function dismissWelcome() {
  $("welcome").hidden = true;
  // Recorded server-side, so it is once per install rather than once per
  // browser profile - the desktop window and a browser tab are the same app.
  try { await api("/api/support/seen", { method: "POST" }); } catch { /* ignore */ }
}

$("welcomeClose").addEventListener("click", dismissWelcome);
$("welcomeStart").addEventListener("click", dismissWelcome);
$("welcomeDonate").addEventListener("click", async () => {
  await dismissWelcome();
  show("help");
  loadSupport();
  const card = $("supportWallets").closest(".card");
  if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
});
$("welcome").addEventListener("click", (e) => {
  if (e.target.id === "welcome") dismissWelcome();
});

onEnter("help", () => loadSupport());

maybeWelcome();

/* ============================== themes ================================
   The attribute is already on <html> when the page arrives - the server puts
   it there. This only handles changing it. */

const THEME_LABELS = { auto: "Auto", light: "Light", dark: "Dark", mono: "B&W" };

const themeState = { current: "auto", options: ["auto", "light", "dark", "mono"] };

async function loadTheme() {
  try {
    const r = await api("/api/theme");
    themeState.current = r.theme;
    themeState.options = r.options;
    renderThemeSwitch(r.theme, r.options);
  } catch { /* the switch is optional; the theme still applies */ }
}

function renderThemeSwitch(current, options) {
  const box = $("themeSwitch");
  if (!box) return;
  box.innerHTML = options.map((t) => `
    <button data-theme-set="${esc(t)}" class="${t === current ? "on" : ""}"
            title="${t === "mono" ? "Black and white. Mastery bands switch to patterns so nothing depends on colour." : ""}">
      ${esc(THEME_LABELS[t] || t)}
    </button>`).join("");

  box.querySelectorAll("[data-theme-set]").forEach((b) =>
    b.addEventListener("click", async () => {
      const t = b.dataset.themeSet;
      themeState.current = t;
      applyTheme(t);
      box.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      try { await api("/api/theme", { method: "POST", body: JSON.stringify({ theme: t }) }); }
      catch (e) { toast(e.message, true); }
    }));
}

function applyTheme(t) {
  // "auto" means remove the attribute entirely, letting the
  // prefers-color-scheme media query decide again.
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
}

loadTheme();

/* Boot: honour a deep link, otherwise Home. Runs last so every screen's
   wiring is in place before one of them is opened. */
(function openInitialView() {
  const want = location.hash.slice(1);
  navigate(want && document.getElementById(`view-${want}`) ? want : "today");
})();

/* ======================= getting properly assessed ==================== */

async function loadEvaluations() {
  const box = $("evalBody");
  if (!box || box.dataset.ready) return;
  try {
    const r = await api("/api/evaluations");
    box.dataset.ready = "1";

    const link = (name, url) => url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(name)}</a>`
      : `<b>${esc(name)}</b>`;

    box.innerHTML = `
      <p class="honesty">${esc(r.disclaimer)}</p>

      <h4>${esc(r.formal.heading)}</h4>
      <p class="stepbody">${esc(r.formal.what)}</p>
      <div class="md">${md(
        "| Instrument | What it measures |\n|---|---|\n" +
        r.formal.instruments.map((i) => `| ${i.name} | ${i.measures} |`).join("\n"))}</div>
      <ul class="evallist">${r.formal.caveats.map((c) =>
        `<li>${esc(c)}</li>`).join("")}</ul>

      <h4>Where to find one</h4>
      <div class="evalrows">${r.where.map((w) => `
        <div class="evalrow">
          <span class="evalkind">${esc(w.kind)}</span>
          <span><span class="evalname">${link(w.name, w.url)}</span>
            <span class="stepbody">${esc(w.why)}</span></span>
        </div>`).join("")}</div>

      <h4>${esc(r.accommodations.heading)}</h4>
      <div class="evalrows">${r.accommodations.points.map((a) => `
        <div class="evalrow">
          <span class="evalkind">deadline</span>
          <span><span class="evalname">${link(a.name, a.url)}</span>
            <span class="stepbody">${esc(a.why)}</span></span>
        </div>`).join("")}</div>

      <h4>Free screeners — indicative, not diagnostic</h4>
      <div class="evalrows">${r.screeners.map((s) => `
        <div class="evalrow">
          <span class="evalkind screen">screening</span>
          <span><span class="evalname">${link(s.name, s.url)}</span>
            <span class="stepbody">${esc(s.what)}</span>
            <span class="stepbody warnnote">${esc(s.limit)}</span></span>
        </div>`).join("")}</div>

      <h4>${esc(r.avoid.heading)}</h4>
      <div class="evalrows">${r.avoid.items.map((a) => `
        <div class="evalrow">
          <span class="evalkind avoid">skip</span>
          <span><span class="evalname">${esc(a.name)}</span>
            <span class="stepbody">${esc(a.why)}</span></span>
        </div>`).join("")}</div>

      <h4>${esc(r.evidence.heading)}</h4>
      <div class="evalrows">${r.evidence.items.map((e) => `
        <div class="evalrow">
          <span class="evalkind good">use this</span>
          <span><span class="evalname">${link(e.name, e.url)}</span>
            <span class="stepbody">${esc(e.why)}</span></span>
        </div>`).join("")}</div>`;
  } catch (e) { /* the rest of Help still works */ }
}

if ($("evalPanel")) {
  $("evalPanel").addEventListener("toggle", () => {
    if ($("evalPanel").open) loadEvaluations();
  });
}

/* ==================== escaping the finished session ===================
   `finish()` hid the runner and showed the summary but never brought the
   launcher back, and the Practice tab only calls show("quiz") - which swaps
   views, not the panels inside one. So after "End & review" there was no route
   back to the length, mode, scope or timer pickers: not from the summary, and
   not by navigating away and returning. */

function backToLauncher() {
  $("quizDone").hidden = true;
  $("quizRunner").hidden = true;
  $("reviewCard").hidden = true;
  $("quizEmpty").hidden = false;
  if (typeof refreshScopeCount === "function") refreshScopeCount();
  window.scrollTo({ top: 0 });
}

if ($("newSessionBtn")) {
  $("newSessionBtn").addEventListener("click", backToLauncher);
}

/* Returning to Practice after a session has ended offers the pickers again;
   see ENTER.quiz beside the navigation table. */

/* ======================= pre-read (inspectional) ======================
   Adler's second level of reading: a systematic skim that establishes what a
   document IS and how it is built, before reading it properly. The point is
   that it makes the real read faster, so this stays short by design - it does
   not teach the content. */

async function runPreread(uid, btn) {
  const out = $("prereadOut");
  const was = btn.textContent;
  btn.disabled = true; btn.textContent = "Reading…";
  out.innerHTML = `<p class="hint">Skimming — this is one short request.</p>`;
  try {
    const r = await api("/api/preread", {
      method: "POST", body: JSON.stringify({ upload_id: uid }),
    });
    renderPreread(r);
  } catch (e) {
    out.innerHTML = `<div class="imperr"><b>Couldn't pre-read that.</b>
      <ul><li>${esc(e.message)}</li></ul></div>`;
  } finally { btn.disabled = false; btn.textContent = was; }
}

function renderPreread(r) {
  const list = (items, cls = "") => items && items.length
    ? `<ul class="preadlist ${cls}">${items.map((i) =>
        `<li>${esc(i)}</li>`).join("")}</ul>`
    : `<p class="hint">None noted.</p>`;

  $("prereadOut").innerHTML = `
    <div class="card preread">
      <div class="cardhead">
        <h3>Pre-read — ${esc(r.title || "material")}</h3>
        <span class="prhead">
          <span class="hint">${r.minutes.inspect} min skim ·
            ${r.minutes.close_read} min to read properly</span>
          <button class="btn small ghost" id="prDownload">Download</button>
          <button class="btn small ghost" id="prClose" aria-label="Close">×</button>
        </span>
      </div>
      <p class="why">An inspectional read, in Adler's sense: what this is and how
        it is put together, so the real read is aimed. It does not teach the
        content.</p>

      <div class="pclassify">
        <span class="ptag">${esc(r.classify.kind)}</span>
        <span class="ptag alt">${esc(r.classify.subject)}</span>
      </div>
      <p class="stepbody">${esc(r.classify.purpose)}</p>

      <h4>In one sentence</h4>
      <p class="punity">${esc(r.unity)}</p>

      <h4>The whole thing at a glance</h4>
      <div class="md">${md(r.orientation_table)}</div>

      <h4>How it is built</h4>
      <div class="partlist">${(r.parts || []).map((p, i) => `
        <div class="partrow">
          <span class="pnum">${i + 1}</span>
          <span><span class="pname">${esc(p.name)}</span>
            ${p.where ? `<span class="pwhere">${esc(p.where)}</span>` : ""}
            <span class="stepbody">${esc(p.covers)}</span>
            <span class="prel">${esc(p.relation)}</span></span>
        </div>`).join("")}</div>

      <h4>Come to terms first</h4>
      <p class="hint">Adler's rule: these words carry the argument, and an
        everyday reading of them will mislead you.</p>
      <div class="md">${md(
        "| Term | In plain words | Why it matters |\n|---|---|---|\n" +
        (r.terms || []).map((t) =>
          `| **${t.term}** | ${t.plain} | ${t.matters} |`).join("\n"))}</div>

      <h4>Questions this answers</h4>
      ${list(r.questions)}

      <div class="pcols">
        <div><h4>Read closely</h4>${list(r.read_closely, "close")}</div>
        <div><h4>Safe to skim</h4>${list(r.skim, "skim")}</div>
      </div>

      <h4>Assumes you already know</h4>
      ${list(r.assumed)}

      ${(r.flags || []).length
        ? `<h4>Flags</h4>${list(r.flags, "flags")}` : ""}
    </div>`;
  $("prereadOut").scrollIntoView({ behavior: "smooth", block: "start" });

  $("prClose").addEventListener("click", () => { $("prereadOut").innerHTML = ""; });

  // Downloads from the data already held - re-running the read to save it
  // would charge for the same work twice.
  $("prDownload").addEventListener("click", async () => {
    const btn = $("prDownload");
    btn.disabled = true; btn.textContent = "Saving\u2026";
    try {
      const res = await fetch("/api/preread/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(r),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `Pre-read - ${(r.title || "material").replace(/\.[^.]+$/, "")}.md`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      toast("Saved to your Downloads folder.");
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = "Download"; }
  });
}

/* ==================== where to re-read after a miss ===================
   "You got this wrong" is half an answer. The lecture is where the exam is
   written from; First Aid is where the same idea is compressed. Only shown on
   a miss - pointing someone at a page they just proved they know is noise. */

async function loadWhereTo(q, wasCorrect) {
  const box = $("eWhereTo");
  if (!box) return;
  box.innerHTML = "";
  if (wasCorrect) return;

  const qid = state.storedIds[q.id] || q.id;
  try {
    const w = await api(`/api/whereto/${encodeURIComponent(qid)}`);
    const lec = w.lecture || {};
    const rows = [];

    if ((lec.sources || []).length || lec.locator) {
      rows.push(`
        <div class="wtrow">
          <span class="wtkind lecture">lecture</span>
          <span><span class="wtname">${esc(
            (lec.sources[0] || {}).label || "Your material")}</span>
            ${lec.locator ? `<span class="wtwhere">${esc(lec.locator)}</span>` : ""}
          </span>
        </div>`);
    }
    for (const t of (w.textbook || [])) {
      rows.push(`
        <div class="wtrow">
          <span class="wtkind book">First Aid</span>
          <span><span class="wtname">${esc(t.section)}</span>
            <span class="wtwhere">p. ${esc(t.pages)}</span>
            <span class="wtnote">Open your own copy — the app stores page
              numbers, never the book's text.</span>
          </span>
        </div>`);
    }

    if (!rows.length) return;
    box.innerHTML = `
      <div class="whereto">
        <h4>Where to re-read this</h4>
        ${rows.join("")}
      </div>`;
  } catch { /* a pointer is a bonus; never let it break the explanation */ }
}
