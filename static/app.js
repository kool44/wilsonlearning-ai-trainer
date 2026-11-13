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
  if (kind !== "speaking") { $("#stage-line").textContent = STAGE_LINE[kind] ?? text; $("#stage-sub").textContent = kind === "yourturn" ? text : ""; }
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
    u.rate = 1.02;
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
function addMsg(m) {
  const el = document.createElement("div");
  const cls = ["msg", m.role === "user" ? "user" : "bot"];
  if (m.kind) cls.push(m.kind); if (m.passed) cls.push("pass");
  el.className = cls.join(" ");
  let tag = "";
  if (m.kind === "customer") tag = m.speaker || "Customer";
  else if (m.kind === "feedback") tag = `Feedback · ${m.score}/${m.max_score}`;
  else if (m.kind === "teach") tag = "Facilitator";
  else if (m.kind === "hint") tag = "Coach (role-play paused)";
  else if (m.kind === "complete") tag = "Module complete";
  if (tag) { const t = document.createElement("span"); t.className = "tag"; t.textContent = tag; el.appendChild(t); }
  const body = document.createElement("span"); body.className = "body";
  const caption = m.role !== "user" && $("#tts").checked && synth;
  body.textContent = caption ? "" : m.text;
  el.appendChild(body);
  el.reveal = (n) => { body.textContent = m.text.slice(0, n); chat.scrollTop = chat.scrollHeight; };
  if (m.kind === "feedback" && (m.met?.length || m.missed?.length)) {
    const r = document.createElement("div"); r.className = "rubric";
    (m.met || []).forEach(x => { const d = document.createElement("div"); d.textContent = x; r.appendChild(d); });
    (m.missed || []).forEach(x => { const d = document.createElement("div"); d.className = "miss"; d.textContent = x; r.appendChild(d); });
    el.appendChild(r);
  }
  chat.appendChild(el); chat.scrollTop = chat.scrollHeight;
  return el;
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
    const sc = p.scores[s.id] || { score: 0, max_score: s.max_score }; tot += sc.score; mx += sc.max_score;
    const pct = sc.max_score ? Math.round(100 * sc.score / sc.max_score) : 0;
    rows += `<tr><td>${i + 1}. ${s.title}</td><td style="width:120px"><div class="bar"><i style="width:${pct}%"></i></div></td><td class="r">${sc.score} / ${sc.max_score}</td></tr>`;
  });
  el.innerHTML = `<h3>Scorecard · ${tot} / ${mx}</h3><table>${rows}</table>`;
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
    else if (sc) li.className = sc.score >= s.pass_score ? "done" : "partial";
    li.innerHTML = `<span class="n">${i + 1}</span><span>${s.title}</span>` + (sc ? `<span class="sc">${sc.score}/${sc.max_score}</span>` : "");
    ol.appendChild(li);
    if (sc) { tot += sc.score; mx += sc.max_score; }
  });
  $("#score-total").textContent = `${tot} / ${mx}`;
  $("#step-now").textContent = p.step_id ? `Step ${p.step_index + 1} of ${p.step_total}: ${p.step_title}` : "Module complete";
  const rp = p.phase === "roleplay";
  $("#persona").hidden = !rp;
  if (rp && p.persona) {
    $("#persona-initial").textContent = p.persona.name[0];
    $("#persona-name").textContent = p.persona.name; $("#persona-role").textContent = p.persona.role;
    $("#persona-sit").textContent = p.persona.situation.split(". ").slice(0, 2).join(". ") + ".";
    $("#turns").textContent = `Turn ${p.turns_used} / ${p.max_turns}`;
  }
  input.placeholder = rp ? "You are the salesperson. Speak to the customer…" : "Type your answer, or tap the mic and speak…";
  $("#btn-repeat").disabled = rp;
  const teaching = p.phase === "teaching";
  if (teaching) $("#step-now").textContent += `  ·  part ${p.beat} of ${p.beats}`;
}
async function playMessages(msgs) {
  showQuick([]);
  for (const m of msgs) {
    const customer = m.kind === "customer";
    Avatar.persona(customer ? "customer" : "coach", customer ? (m.speaker || "Customer") : "Facilitator");
    $("#stage-line").textContent = customer ? `${m.speaker || "Customer"} is speaking` : (m.kind === "feedback" ? "Here's my feedback" : m.kind === "hint" ? "Quick coaching tip" : m.kind === "answer" ? "Good question" : "Teaching");
    $("#stage-sub").textContent = m.kind === "teach" && m.beats ? `Part ${m.beat} of ${m.beats}` : "";
    if (m.kind === "feedback" && m.passed) Avatar.set("happy");
    const el = addMsg(m); await speak(m.text, el.reveal); el.reveal(m.text.length);
  }
  afterPlay();
}
function afterPlay() {
  const p = state.progress;
  if (p?.phase === "done") addScorecard(p);
  if (p?.phase === "teaching") {
    showQuick([["Go on \u25B6", () => cmd("continue")], ["Say that again", () => cmd("repeat")], ["I have a question", () => { input.placeholder = "Ask your question\u2026"; input.focus(); }]]);
    if ($("#handsfree").checked && !listening) toggleMic();
    if (!listening) setStatus("yourturn", `Say "go on", or ask a question (${p.beat} of ${p.beats})`);
  } else if (p?.phase === "asked") {
    showQuick([["Repeat the question", () => cmd("repeat")]]);
    if ($("#handsfree").checked && !listening) toggleMic();
    if (!listening) setStatus("yourturn", "Your turn to answer");
  } else if (!listening) setStatus("yourturn", p?.phase === "roleplay" ? "Your turn. Speak to the customer." : "Your turn");
}
function setBusy(b) {
  state.busy = b; $("#btn-send").disabled = b; $("#btn-mic").disabled = b; $("#btn-hint").disabled = b; $("#btn-endcall").disabled = b;
  if (b) { setStatus("thinking", "Thinking…"); const t = document.createElement("div"); t.className = "typing"; t.id = "typing"; t.textContent = "…"; chat.appendChild(t); chat.scrollTop = chat.scrollHeight; }
  else { $("#typing")?.remove(); }
}

// ---------- API
async function api(path, body) {
  const r = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function start() {
  const mods = await api("/api/modules");
  state.moduleId = mods[0].id; $("#module-title").textContent = mods[0].short_title;
  $("#btn-start").disabled = true;
  const res = await api("/api/session", { module_id: state.moduleId, learner_name: $("#learner-name").value || null });
  state.sessionId = res.session_id; localStorage.setItem("trainer.session", res.session_id);
  $("#start-card").hidden = true; $("#stage").hidden = false; $("#chat").hidden = false; $("#composer").hidden = false;
  renderProgress(res.progress); await playMessages(res.messages); input.focus();
}
async function send() {
  const text = input.value.trim(); if (!text || state.busy) return;
  if (listening) rec.stop();
  stopSpeaking();
  input.value = ""; autosize(); addMsg({ role: "user", text });
  setBusy(true);
  try { const res = await api(`/api/session/${state.sessionId}/message`, { text }); setBusy(false); renderProgress(res.progress); await playMessages(res.messages); }
  catch (e) { setBusy(false); addMsg({ role: "bot", kind: "info", text: "Something went wrong: " + e.message }); setStatus("idle", "Error"); }
  input.focus();
}
async function cmd(c) {
  if (state.busy) return; stopSpeaking(); showQuick([]); setBusy(true);
  try { const res = await api(`/api/session/${state.sessionId}/command`, { cmd: c }); setBusy(false); if (c === "restart") chat.innerHTML = ""; renderProgress(res.progress); await playMessages(res.messages); }
  catch (e) { setBusy(false); addMsg({ role: "bot", kind: "info", text: e.message }); }
}
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; }

// ---------- avatar
Avatar.mount($("#avatar-big"), "Facilitator");

// ---------- wiring
$("#btn-start").onclick = start;
$("#btn-send").onclick = send;
$("#btn-mic").onclick = toggleMic;
$("#btn-stop").onclick = stopSpeaking;
$("#btn-repeat").onclick = () => cmd("repeat");
$("#btn-skip").onclick = () => cmd("skip");
$("#btn-hint").onclick = () => cmd("hint");
$("#btn-endcall").onclick = () => { if (confirm("End the call and get your feedback?")) cmd("end_call"); };
$("#btn-restart").onclick = () => { if (confirm("Restart the module from the beginning?")) cmd("restart"); };
$("#tts").onchange = () => { if (!$("#tts").checked) stopSpeaking(); };
input.addEventListener("input", () => { autosize(); if (synth?.speaking) stopSpeaking(); });   // typing interrupts the bot
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } if (e.key === "Escape") stopSpeaking(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") stopSpeaking(); });
async function resume(sid) {
  const res = await api(`/api/session/${sid}`);
  state.sessionId = sid; state.moduleId = res.progress.module_id;
  $("#start-card").hidden = true; $("#stage").hidden = false; $("#chat").hidden = false; $("#composer").hidden = false;
  res.messages.forEach(m => { const el = addMsg(m); el.reveal(m.text.length); }); renderProgress(res.progress);
  afterPlay(); input.focus();
}
(async () => {
  const sid = localStorage.getItem("trainer.session"); if (!sid) return;
  try {
    const res = await api(`/api/session/${sid}`);
    if (res.progress.phase === "done") return;
    const b = document.createElement("button"); b.textContent = `Resume previous session (step ${res.progress.step_index + 1} of ${res.progress.step_total})`;
    b.onclick = () => resume(sid); $("#btn-start").insertAdjacentElement("afterend", b);
  } catch (_) { localStorage.removeItem("trainer.session"); }
})();
api("/api/modules").then(m => { $("#module-title").textContent = m[0].short_title; $("#start-module").textContent = m[0].title; }).catch(() => {});
