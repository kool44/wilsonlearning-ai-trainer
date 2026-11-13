/* Animated facilitator avatar. Pure SVG + CSS, no assets.
   States: idle | speaking | listening | thinking. Persona: "coach" (facilitator) | "customer" (role-play). */
(function () {
  const svg = `
<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" class="av">
  <defs>
    <radialGradient id="av-bg" cx="50%" cy="40%"><stop offset="0%" stop-color="var(--av-bg1)"/><stop offset="100%" stop-color="var(--av-bg2)"/></radialGradient>
  </defs>
  <circle cx="100" cy="100" r="96" fill="url(#av-bg)"/>
  <g class="av-ring"><circle cx="100" cy="100" r="96" fill="none" stroke="var(--av-ring)" stroke-width="3" opacity="0"/></g>
  <g class="av-body">
    <!-- shoulders -->
    <path d="M38 200 Q40 150 100 148 Q160 150 162 200 Z" fill="var(--av-shirt)"/>
    <!-- left arm (gestures while teaching) -->
    <g class="av-arm-l"><path d="M58 160 q-26 10 -30 36" stroke="var(--av-shirt)" stroke-width="18" stroke-linecap="round" fill="none"/><circle cx="28" cy="196" r="10" fill="var(--av-skin)"/></g>
    <!-- right arm -->
    <g class="av-arm-r"><path d="M142 160 q26 10 30 36" stroke="var(--av-shirt)" stroke-width="18" stroke-linecap="round" fill="none"/><circle cx="172" cy="196" r="10" fill="var(--av-skin)"/></g>
    <!-- neck -->
    <rect x="88" y="124" width="24" height="26" rx="8" fill="var(--av-skin)"/>
    <!-- head group: nods / tilts -->
    <g class="av-head">
      <ellipse cx="100" cy="92" rx="44" ry="48" fill="var(--av-skin)"/>
      <!-- hair -->
      <path class="av-hair" d="M56 86 Q58 40 100 40 Q142 40 144 86 Q130 70 100 66 Q70 70 56 86 Z" fill="var(--av-hair)"/>
      <!-- ears -->
      <ellipse cx="56" cy="96" rx="7" ry="10" fill="var(--av-skin)"/><ellipse cx="144" cy="96" rx="7" ry="10" fill="var(--av-skin)"/>
      <!-- brows -->
      <path class="av-brow-l" d="M76 76 q10 -6 20 -1" stroke="var(--av-hair)" stroke-width="3.5" stroke-linecap="round" fill="none"/>
      <path class="av-brow-r" d="M104 75 q10 -5 20 1" stroke="var(--av-hair)" stroke-width="3.5" stroke-linecap="round" fill="none"/>
      <!-- eyes -->
      <g class="av-eyes">
        <g class="av-eye"><ellipse cx="84" cy="92" rx="6" ry="7" fill="#fff"/><circle class="av-pupil" cx="85" cy="93" r="3.4" fill="#1b2130"/></g>
        <g class="av-eye"><ellipse cx="116" cy="92" rx="6" ry="7" fill="#fff"/><circle class="av-pupil" cx="117" cy="93" r="3.4" fill="#1b2130"/></g>
      </g>
      <!-- nose -->
      <path d="M100 96 q-4 10 2 12" stroke="var(--av-line)" stroke-width="2" stroke-linecap="round" fill="none"/>
      <!-- mouth: morphs when speaking -->
      <path class="av-mouth" d="M86 118 Q100 126 114 118" stroke="var(--av-line)" stroke-width="3" stroke-linecap="round" fill="var(--av-mouth)"/>
    </g>
  </g>
  <!-- thinking bubbles -->
  <g class="av-think"><circle cx="150" cy="44" r="4" fill="#fff"/><circle cx="160" cy="32" r="6" fill="#fff"/><circle cx="174" cy="18" r="8" fill="#fff"/></g>
  <!-- listening sound waves -->
  <g class="av-waves" stroke="var(--av-ring)" stroke-width="3" fill="none" stroke-linecap="round">
    <path d="M160 86 q6 14 0 28"/><path d="M170 78 q10 22 0 44"/><path d="M180 70 q14 30 0 60"/>
  </g>
</svg>`;

  const css = `
.avatar-stage{--av-bg1:#3b5bdb;--av-bg2:#1e2a5a;--av-ring:#7fb0ff;--av-skin:#f1c9a5;--av-hair:#3a2a1e;--av-shirt:#2f6fed;--av-line:#7a4a2a;--av-mouth:#8a3a3a;
  width:140px;height:140px;flex:none;position:relative;transition:transform .3s}
.avatar-stage.customer{--av-bg1:#7c5cd6;--av-bg2:#2a1f4d;--av-ring:#c4b5fd;--av-hair:#1d1a2a;--av-shirt:#5b45b8}
.avatar-stage .av{width:100%;height:100%;overflow:visible}
.av-head{transform-origin:100px 130px;transition:transform .4s}
.av-mouth{transition:d .08s}
.av-think,.av-waves{opacity:0;transition:opacity .3s}
.av-arm-l,.av-arm-r{transform-origin:60px 160px;transition:transform .3s}
.av-arm-r{transform-origin:140px 160px}
/* blink */
.av-eyes{animation:av-blink 4.2s infinite}
@keyframes av-blink{0%,92%,100%{transform:scaleY(1)}95%{transform:scaleY(.08)}}
.av-eye{transform-origin:100px 92px}
.av-eyes{transform-origin:100px 92px}
/* idle: gentle breathing */
.avatar-stage.idle .av-body{animation:av-breathe 3.6s ease-in-out infinite}
@keyframes av-breathe{50%{transform:translateY(1.5px)}}
/* speaking: mouth flaps, head nods, hand gestures, ring pulses */
.avatar-stage.speaking .av-mouth{animation:av-talk .28s infinite alternate}
@keyframes av-talk{0%{d:path("M86 118 Q100 124 114 118")}50%{d:path("M88 116 Q100 134 112 116")}100%{d:path("M90 118 Q100 128 110 118")}}
.avatar-stage.speaking .av-head{animation:av-nod 2.4s ease-in-out infinite}
@keyframes av-nod{0%,100%{transform:rotate(0)}30%{transform:rotate(-2.5deg) translateY(1px)}65%{transform:rotate(2deg)}}
.avatar-stage.speaking .av-arm-l{animation:av-gesture 1.9s ease-in-out infinite}
@keyframes av-gesture{0%,100%{transform:rotate(0)}40%{transform:rotate(-28deg) translate(4px,-6px)}}
.avatar-stage.speaking .av-ring circle{opacity:1;animation:av-ring 1.4s ease-out infinite}
@keyframes av-ring{0%{r:96;opacity:.8}100%{r:112;opacity:0}}
.avatar-stage.speaking .av-brow-l,.avatar-stage.speaking .av-brow-r{transform:translateY(-1.5px)}
/* listening: head tilts toward you, waves, pupils to the side */
.avatar-stage.listening .av-head{transform:rotate(7deg) translateX(3px)}
.avatar-stage.listening .av-waves{opacity:1;animation:av-wave .9s ease-in-out infinite alternate}
@keyframes av-wave{from{opacity:.4}to{opacity:1}}
.avatar-stage.listening .av-pupil{transform:translate(2px,0)}
.avatar-stage.listening .av-mouth{d:path("M90 118 Q100 122 110 118")}
/* thinking: look up, bubbles, hand to chin */
.avatar-stage.thinking .av-head{transform:rotate(-5deg)}
.avatar-stage.thinking .av-pupil{transform:translate(2px,-3px)}
.avatar-stage.thinking .av-think{opacity:1;animation:av-bob 1.2s ease-in-out infinite alternate}
@keyframes av-bob{to{transform:translateY(-3px)}}
.avatar-stage.thinking .av-arm-r{transform:rotate(-55deg) translate(-6px,-8px)}
.avatar-stage.thinking .av-brow-r{transform:translateY(-3px)}
/* celebrate (pass) */
.avatar-stage.happy .av-mouth{d:path("M84 116 Q100 132 116 116")}
.avatar-stage.happy .av-arm-l{transform:rotate(-70deg) translate(8px,-12px)}
.avatar-stage.happy .av-arm-r{transform:rotate(70deg) translate(-8px,-12px)}
.avatar-stage.happy{animation:av-hop .5s ease-out 2}
@keyframes av-hop{40%{transform:translateY(-6px)}}
.avatar-name{position:absolute;left:50%;bottom:-6px;transform:translateX(-50%);font-size:11px;color:var(--muted);white-space:nowrap;background:var(--panel);padding:1px 8px;border-radius:999px;border:1px solid #2b3449}
`;

  window.Avatar = {
    mount(el, name) {
      const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
      el.classList.add("avatar-stage", "idle"); el.innerHTML = svg + `<div class="avatar-name"></div>`;
      this.el = el; this.setName(name || "Facilitator");
    },
    set(state) {            // idle | speaking | listening | thinking | happy
      const el = this.el; if (!el) return;
      ["idle", "speaking", "listening", "thinking", "happy"].forEach(c => el.classList.remove(c));
      el.classList.add(state);
      if (state === "happy") setTimeout(() => { if (el.classList.contains("happy")) this.set("idle"); }, 1400);
    },
    persona(kind, name) {   // "coach" | "customer"
      this.el.classList.toggle("customer", kind === "customer"); this.setName(name);
    },
    setName(n) { const t = this.el.querySelector(".avatar-name"); if (t) t.textContent = n; },
  };
})();
