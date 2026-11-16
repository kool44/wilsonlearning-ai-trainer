/* Counselor Trainer front end. Vanilla JS, no build step. */
const $ = (s) => document.querySelector(s);
const state = { sessionId: null, moduleId: null, progress: null, busy: false };
const chat = $("#chat"), input = $("#input"), avatar = $("#avatar");

// ---------- status line
const AV_STATE = { speaking: "speaking", listening: "listening", thinking: "thinking", yourturn: "idle", idle: "idle" };
const STAGE_LINE = { speaking: "", listening: "I'm listening…", thinking: "Let me think about that…", yourturn: "Your turn.", idle: "Ready when you are." };
function setStatus(kind, text) {
  const el = $("#status"); el.className = "status " + kind; $("#status-text").textContent = text;
  $("#btn-stop").hidden = kind !== "speaking";
  if (window.Avatar?.el) Avatar.set(AV_STATE[kind] || "idle");
  if (kind !== "speaking") { $("#stage-line").textContent = STAGE_LINE[kind] ?? text; $("#stage-sub").textContent = kind === "yourturn" ? text.replace(/^Your turn\.?\s*/, "") : ""; }
}

// ---------- voice out: browser text-to-speech
const synth = window.speechSynthesis;
let voices = [], speakToken = 0;
function loadVoices() {
  voices = synth ? synth.getVoices().filter(v => v.lang.startsWith("en")) : [];
  const sel = $("#voice"); sel.innerHTML = "";
  voices.forEach((v, i) => { const o = document.createElement("option"); o.value = i; o.textContent = v.name; sel.appendChild(o); });
  const pref = voices.findIndex(v => /Samantha|Google US English|Microsoft Aria|Daniel/.test(v.name));
  if (pref >= 0) sel.value = pref;
}
if (synth) { loadVoices(); synth.onvoiceschanged = loadVoices; }
function stopSpeaking() {
  speakToken++;                       // invalidates any queued speak() promises
  if (synth) synth.cancel();
  avatar.classList.remove("speaking");
  if (state.progress) setStatus("yourturn", state.progress.phase === "roleplay" ? "Your turn. Speak to the customer." : "Your turn");
}
function speak(text, onWord) {
  if (!synth || !$("#tts").checked) { onWord && onWord(text.length); return Promise.resolve(); }
  synth.cancel();
  const myToken = ++speakToken;
  return new Promise(res => {
    const u = new SpeechSynthesisUtterance(text);
    const v = voices[$("#voice").value]; if (v) u.voice = v;
    u.rate = 1.06;
    u.onstart = () => { if (myToken === speakToken) { avatar.classList.add("speaking"); setStatus("speaking", "Speaking… (tap Stop or the mic to interrupt)"); } };
    // Captions: reveal by boundary events when the engine gives them, else by a time estimate (~16 chars/s).
    let revealed = 0, started = 0, sawBoundary = false;
    const reveal = (n) => { if (!onWord || myToken !== speakToken) return; if (n > revealed) { revealed = n; onWord(Math.min(n, text.length)); } };
    u.onboundary = (e) => { sawBoundary = true; reveal(e.charIndex + (e.charLength || 0)); };
    const ticker = setInterval(() => {
      if (myToken !== speakToken) { clearInterval(ticker); return; }
      if (!started && synth.speaking) started = Date.now();
      if (started && !sawBoundary) reveal(Math.floor((Date.now() - started) / 1000 * 16 * (u.rate || 1)));
    }, 120);
    u.onend = u.onerror = () => { clearInterval(ticker); avatar.classList.remove("speaking"); onWord && onWord(text.length); res(); };
    synth.speak(u);
    // Safari/Chrome sometimes never fire onend after cancel(); poll as a safety net.
    const iv = setInterval(() => { if (myToken !== speakToken || !synth.speaking) { clearInterval(iv); res(); } }, 250);
  });
}

// ---------- voice in: browser speech recognition
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, listening = false, baseText = "", silenceTimer = null;
if (SR) {
  rec = new SR(); rec.continuous = true; rec.interimResults = true; rec.lang = "en-US";
  rec.onresult = (e) => {
    let finalT = "", interim = "";
    for (let i = 0; i < e.results.length; i++) (e.results[i].isFinal ? finalT += e.results[i][0].transcript : interim += e.results[i][0].transcript);
    input.value = (baseText + " " + finalT + " " + interim).trim(); autosize();
    if ($("#handsfree").checked) { clearTimeout(silenceTimer); silenceTimer = setTimeout(() => { if (listening && input.value.trim()) { rec.stop(); send(); } }, 1800); }
  };
  rec.onend = () => { listening = false; $("#btn-mic").classList.remove("listening"); if (!state.busy && !synth?.speaking) setStatus("yourturn", "Your turn"); };
  rec.onerror = (e) => { if (e.error === "not-allowed") addMsg({ role: "bot", kind: "info", text: "Microphone blocked. Allow mic access in the browser, or type instead." }); };
} else { $("#btn-mic").title = "Speech recognition not supported here. Use Chrome or Edge."; }
function toggleMic() {
  if (!rec) { addMsg({ role: "bot", kind: "info", text: "Speech input needs Chrome or Edge. You can type instead." }); return; }
  if (listening) { rec.stop(); return; }
  stopSpeaking();                      // barge-in: tapping the mic interrupts the bot
  baseText = input.value; listening = true; $("#btn-mic").classList.add("listening");
  setStatus("listening", "Listening… tap mic again when done"); rec.start();
}

// ---------- rendering
let lastStepId = null, activeCard = null;
function stepTitle(id) { const p = state.progress; const i = p ? p.steps.findIndex(s => s.id === id) : -1; return i >= 0 ? `Step ${i + 1} · ${p.steps[i].title}` : ""; }
function divider(stepId) {
  if (!stepId || stepId === lastStepId) return; lastStepId = stepId;
  const d = document.createElement("div"); d.className = "divider"; d.textContent = stepTitle(stepId); chat.appendChild(d);
}
function addMsg(m, { instant = false } = {}) {
  if (m.role !== "user") divider(m.step_id);
  const el = document.createElement("div");
  const cls = ["msg", m.role === "user" ? "user" : "bot"];
  if (m.kind) cls.push(m.kind); if (m.passed) cls.push("pass"); if (m.quick) cls.push("quick-fb");
  el.className = cls.join(" ");
  let tag = "";
  if (m.kind === "customer") tag = m.speaker || "Customer";
  else if (m.kind === "feedback") tag = m.quick ? (m.passed ? "Correct" : "Not quite") : `Feedback · ${m.score}/${m.max_score}`;
  else if (m.kind === "activity") tag = m.label || "Your turn";
  else if (m.kind === "hint") tag = "Coach (role-play paused)";
  else if (m.kind === "complete") tag = "Module complete";
  else if (m.kind === "answer") tag = "Good question";
  if (tag) { const t = document.createElement("span"); t.className = "tag"; t.textContent = tag; el.appendChild(t); }
  const body = document.createElement("span"); body.className = "body";
  const caption = !instant && m.role !== "user" && $("#tts").checked && synth && m.kind !== "activity";
  body.textContent = caption ? "" : m.text;
  el.appendChild(body);
  el.reveal = (n) => { body.textContent = m.text.slice(0, n); chat.scrollTop = chat.scrollHeight; };
  if (m.kind === "activity" && m.activity) renderActivity(el, m.activity, instant);
  if (m.kind === "feedback" && !m.quick && (m.met?.length || m.missed?.length)) {
    const r = document.createElement("div"); r.className = "rubric";
    (m.met || []).forEach(x => { const d = document.createElement("div"); d.textContent = x; r.appendChild(d); });
    (m.missed || []).forEach(x => { const d = document.createElement("div"); d.className = "miss"; d.textContent = x; r.appendChild(d); });
    el.appendChild(r);
  }
  if (m.kind === "feedback" && m.quick && activeCard) markCard(activeCard, m);
  chat.appendChild(el); chat.scrollTop = chat.scrollHeight;
  return el;
}
function renderActivity(el, a, disabled) {
  if (a.type === "open") { activeCard = null; return; }
  const box = document.createElement("div"); box.className = "options " + a.type;
  const picked = [];
  const status = document.createElement("div"); status.className = "order-status";
  const statusText = document.createElement("span"); status.appendChild(statusText);
  (a.options || []).forEach(o => {
    const b = document.createElement("button"); b.className = "opt"; b.dataset.key = o.key;
    b.innerHTML = `<span class="k">${o.key}</span><span class="t"></span>`; b.querySelector(".t").textContent = o.text;
    b.disabled = disabled;
    b.onclick = () => {
      if (state.busy) return;
      if (a.type === "choice") { box.querySelectorAll(".opt").forEach(x => x.disabled = true); b.classList.add("picked"); sendText(o.key, `${o.key}. ${o.text}`); return; }
      if (b.classList.contains("picked")) return;
      picked.push(o.key); b.classList.add("picked"); b.querySelector(".k").textContent = picked.length;
      statusText.textContent = picked.length < a.options.length ? `Tap the next one (${picked.length} of ${a.options.length})` : "";
      if (picked.length === a.options.length) {
        box.querySelectorAll(".opt").forEach(x => x.disabled = true); status.hidden = true;
        sendText("order: " + picked.join(", "), picked.map((k, i) => `${i + 1}. ${a.options.find(x => x.key === k).text}`).join("\n"));
      }
    };
    box.appendChild(b);
  });
  if (a.type === "order" && !disabled) {
    statusText.textContent = `Tap the ${a.options.length} items in the right order`;
    const reset = document.createElement("button"); reset.className = "link"; reset.textContent = "Reset";
    reset.onclick = () => { picked.length = 0; box.querySelectorAll(".opt").forEach(x => { x.classList.remove("picked"); x.querySelector(".k").textContent = x.dataset.key; }); statusText.textContent = `Tap the ${a.options.length} items in the right order`; };
    status.appendChild(reset);
  }
  el.appendChild(box); if (a.type === "order") el.appendChild(status);
  activeCard = disabled ? null : box;
}
function markCard(box, m) {
  box.querySelectorAll(".opt").forEach(b => {
    b.disabled = true;
    if (m.correct) { if (b.dataset.key === m.correct) b.classList.add("right"); else if (b.dataset.key === m.chosen) b.classList.add("wrong"); }
    if (m.correct_order) { const pos = m.chosen_order.indexOf(b.dataset.key); const ok = m.correct_order[pos] === b.dataset.key; b.classList.add(ok ? "right" : "wrong"); }
  });
  activeCard = null;
}
function showQuick(items) {
  $("#quick")?.remove();
  if (!items.length) return;
  const q = document.createElement("div"); q.id = "quick"; q.className = "quick";
  items.forEach(([label, fn]) => { const b = document.createElement("button"); b.textContent = label; b.onclick = fn; q.appendChild(b); });
  $("#composer").insertAdjacentElement("beforebegin", q);
}
function addScorecard(p) {
  const el = document.createElement("div"); el.className = "scorecard";
  let tot = 0, mx = 0, rows = "";
  p.steps.forEach((s, i) => {
    const sc = p.scores[s.id]; if (!sc) return; tot += sc.score; mx += sc.max_score;
    const pct = sc.max_score ? Math.round(100 * sc.score / sc.max_score) : 0;
    rows += `<tr><td>${i + 1}. ${s.title}</td><td style="width:120px"><div class="bar"><i style="width:${pct}%"></i></div></td><td class="r">${sc.score} / ${sc.max_score}</td></tr>`;
  });
  el.innerHTML = `<h3>Scorecard · ${tot} / ${mx}</h3><table>${rows}</table>`;
  const again = document.createElement("button"); again.className = "primary"; again.textContent = "Run it again with new questions";
  again.onclick = () => cmd("restart"); el.appendChild(again);
  chat.appendChild(el); chat.scrollTop = chat.scrollHeight;
}
function renderProgress(p) {
  state.progress = p;
  const ol = $("#steps"); ol.innerHTML = "";
  let tot = 0, mx = 0;
  p.steps.forEach((s, i) => {
    const li = document.createElement("li");
    const sc = p.scores[s.id];
    if (i === p.step_index) li.className = "current";
    else if (sc) li.className = sc.passed ? "done" : "partial";
    li.innerHTML = `<span class="n">${i + 1}</span><span>${s.title}</span>` + (sc ? `<span class="sc">${sc.score}/${sc.max_score}</span>` : "");
    ol.appendChild(li);
    if (sc) { tot += sc.score; mx += sc.max_score; }
  });
  $("#score-total").textContent = `${tot} / ${mx}`;
  $("#step-now").textContent = p.step_id ? `Step ${p.step_index + 1} of ${p.step_total}: ${p.step_title}` : "Module complete";
  $("#bar-fill").style.width = `${Math.round(100 * p.step_index / p.step_total)}%`;
  const st = $("#streak"); st.hidden = (p.streak || 0) < 2; st.textContent = `🔥 ${p.streak} in a row`;
  const rp = p.phase === "roleplay";
  $("#persona").hidden = !rp;
  if (rp && p.persona) {
    $("#persona-initial").textContent = p.persona.name[0];
    $("#persona-name").textContent = p.persona.name; $("#persona-role").textContent = p.persona.role;
    $("#persona-sit").textContent = p.persona.situation.split(". ").slice(0, 2).join(". ").replace(/\.?$/, ".");
    $("#turns").textContent = `Turn ${p.turns_used} / ${p.max_turns}`;
  }
  const tapOnly = p.phase === "asked" && (p.activity_type === "choice" || p.activity_type === "order");
  input.placeholder = rp ? "You are the salesperson. Speak to the customer…" : tapOnly ? "Tap an option above, say the letter, or ask a question…" : "Type your answer, or tap the mic and speak…";
}
const pause = (ms) => new Promise(r => setTimeout(r, ms));
async function playMessages(msgs) {
  showQuick([]);
  for (const m of msgs) {
    const customer = m.kind === "customer";
    Avatar.persona(customer ? "customer" : "coach", customer ? (m.speaker || "Customer") : "Facilitator");
    $("#stage-line").textContent = customer ? `${m.speaker || "Customer"} is speaking` :
      m.kind === "feedback" ? (m.passed ? "Nice one!" : "Here's my feedback") : m.kind === "hint" ? "Quick coaching tip" :
      m.kind === "activity" ? (m.label || "Your turn") : m.kind === "answer" ? "Good question" : stepTitle(m.step_id) || "Teaching";
    $("#stage-sub").textContent = m.kind === "teach" && m.beats > 1 ? `${m.beat} of ${m.beats}` : "";
    if (m.kind === "feedback") Avatar.set(m.passed ? "happy" : "idle");
    const el = addMsg(m);
    if (m.kind === "activity" && m.activity.type !== "open") { await speak(m.text); }
    else { await speak(m.text, el.reveal); el.reveal(m.text.length); }
    if (!$("#tts").checked || !synth) await pause(m.kind === "teach" ? 500 : 250);
    else await pause(150);
  }
  afterPlay();
}
function afterPlay() {
  const p = state.progress;
  if (p?.phase === "done") { addScorecard(p); setStatus("idle", "Module complete"); return; }
  if (p?.phase === "asked") {
    const tap = p.activity_type === "choice" || p.activity_type === "order";
    showQuick([["Say that again", () => cmd("repeat")]]);
    if ($("#handsfree").checked && !listening) toggleMic();
    if (!listening) setStatus("yourturn", tap ? "Tap your answer, or say the letter" : "Your turn to answer");
  } else if (!listening) setStatus("yourturn", p?.phase === "roleplay" ? "Your turn. Speak to the customer." : "Your turn");
}
function setBusy(b, label) {
  state.busy = b; $("#btn-send").disabled = b; $("#btn-mic").disabled = b; $("#btn-hint").disabled = b; $("#btn-endcall").disabled = b;
  if (b) { setStatus("thinking", label || "Thinking…"); $("#stage-line").textContent = label || "Let me think about that…"; const t = document.createElement("div"); t.className = "typing"; t.id = "typing"; t.innerHTML = "<i></i><i></i><i></i>"; chat.appendChild(t); chat.scrollTop = chat.scrollHeight; }
  else { $("#typing")?.remove(); }
}

// ---------- API
async function api(path, body) {
  const r = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(r.status === 404 ? "This session has expired. Tap Restart to begin again." : await r.text());
  return r.json();
}
function showApp() { $("#start-card").hidden = true; $("#stage").hidden = false; $("#chat").hidden = false; $("#composer").hidden = false; $("#progress-bar").hidden = false; }
async function start() {
  $("#btn-start").disabled = true;
  const name = $("#learner-name").value.trim();
  showApp();                                    // switch screens at once; don't wait on the network
  chat.innerHTML = ""; lastStepId = null;
  Avatar.set("happy"); $("#stage-line").textContent = name ? `Hi ${name}!` : "Hi there!"; $("#stage-sub").textContent = "Getting your first lesson ready…";
  setBusy(true, "Getting ready…");
  try {
    if (!state.moduleId) { const mods = await api("/api/modules"); state.moduleId = mods[0].id; }
    const res = await api("/api/session", { module_id: state.moduleId, learner_name: name || null });
    state.sessionId = res.session_id; try { localStorage.setItem("trainer.session", res.session_id); } catch (_) {}
    setBusy(false); renderProgress(res.progress); await playMessages(res.messages);
  } catch (e) { setBusy(false); addMsg({ role: "bot", kind: "info", text: "Couldn't start: " + e.message }); $("#btn-start").disabled = false; }
}
async function sendText(text, display) {
  if (!text || state.busy) return;
  if (listening) rec.stop();
  stopSpeaking(); showQuick([]);
  addMsg({ role: "user", text: display || text });
  const p = state.progress;
  const slow = p && (p.phase === "roleplay" || p.activity_type === "open");
  setBusy(true, p?.phase === "roleplay" ? `${p.persona?.name?.split(" ")[0] || "The customer"} is thinking…` : slow ? "Reading your answer…" : "Checking…");
  try { const res = await api(`/api/session/${state.sessionId}/message`, { text }); setBusy(false); renderProgress(res.progress); await playMessages(res.messages); }
  catch (e) { setBusy(false); addMsg({ role: "bot", kind: "info", text: "Something went wrong: " + e.message }); setStatus("idle", "Error"); }
}
async function send() {
  const text = input.value.trim(); if (!text || state.busy) return;
  input.value = ""; autosize();
  await sendText(text); input.focus();
}
async function cmd(c) {
  if (state.busy) return; stopSpeaking(); showQuick([]); setBusy(true, c === "end_call" ? "Scoring your call…" : c === "hint" ? "Pausing the role-play…" : "One moment…");
  try { const res = await api(`/api/session/${state.sessionId}/command`, { cmd: c }); setBusy(false); if (c === "restart") { chat.innerHTML = ""; lastStepId = null; } renderProgress(res.progress); await playMessages(res.messages); }
  catch (e) { setBusy(false); addMsg({ role: "bot", kind: "info", text: e.message }); }
}
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; }

// ---------- avatar
Avatar.mount($("#avatar-big"), "Facilitator");

// ---------- wiring
$("#btn-start").onclick = start;
$("#btn-send").onclick = send;
$("#btn-mic").onclick = toggleMic;
$("#learner-name").addEventListener("keydown", (e) => { if (e.key === "Enter") start(); });
$("#btn-stop").onclick = stopSpeaking;
$("#btn-repeat").onclick = () => { if (state.sessionId) cmd("repeat"); };
$("#btn-skip").onclick = () => { if (state.sessionId) cmd("skip"); };
$("#btn-hint").onclick = () => cmd("hint");
$("#btn-endcall").onclick = () => { if (confirm("End the call and get your feedback?")) cmd("end_call"); };
$("#btn-restart").onclick = () => { if (!state.sessionId) return; if (confirm("Restart the module with fresh questions?")) cmd("restart"); };
$("#tts").onchange = () => { if (!$("#tts").checked) stopSpeaking(); };
input.addEventListener("input", () => { autosize(); if (synth?.speaking) stopSpeaking(); });   // typing interrupts the bot
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } if (e.key === "Escape") stopSpeaking(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") stopSpeaking(); });
async function resume(sid) {
  const res = await api(`/api/session/${sid}`);
  state.sessionId = sid; state.moduleId = res.progress.module_id;
  showApp(); chat.innerHTML = ""; lastStepId = null; state.progress = res.progress;
  const lastAct = res.progress.phase === "asked" ? res.messages.map(m => m.kind).lastIndexOf("activity") : -1;
  res.messages.forEach((m, i) => { addMsg(m, { instant: i !== lastAct || m.kind !== "activity" }); });
  if (lastAct >= 0 && res.messages.slice(lastAct + 1).some(m => m.role === "user" || m.kind === "feedback")) activeCard = null;
  renderProgress(res.progress); afterPlay(); input.focus();
}
(async () => {
  let sid = null; try { sid = localStorage.getItem("trainer.session"); } catch (_) {} if (!sid) return;
  try {
    const res = await api(`/api/session/${sid}`);
    if (res.progress.phase === "done") return;
    const b = document.createElement("button"); b.textContent = `Resume previous session (step ${res.progress.step_index + 1} of ${res.progress.step_total})`;
    b.onclick = () => resume(sid); $("#btn-start").insertAdjacentElement("afterend", b);
  } catch (_) { try { localStorage.removeItem("trainer.session"); } catch (_) {} }
})();
api("/api/modules").then(m => { state.moduleId = m[0].id; $("#module-title").textContent = m[0].short_title; $("#start-module").textContent = m[0].title; }).catch(() => {});
