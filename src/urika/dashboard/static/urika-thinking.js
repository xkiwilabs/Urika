// urika-thinking.js — animated "thinking…" placeholder for any element
// with [data-urika-thinking]. See start/stop API.
//
// Usage:
//   const handle = window.urikaThinking.start(el);
//   // ... later, when real content arrives:
//   handle.stop();
//
// The element is decorated with class="urika-thinking" while active and
// has its textContent driven by a braille spinner + a rotating verb.
// On stop() the class is removed and textContent cleared so the element
// can be replaced by real content cleanly.

(function () {
  const SPINNER_FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"];
  const ACTIVITY_VERBS = [
    "Thinking", "Reasoning", "Analyzing", "Processing",
    "Exploring", "Evaluating", "Considering", "Reviewing",
  ];

  // 5 frames/sec — visible activity but not frantic.
  const SPINNER_INTERVAL_MS = 200;
  // Verb cadence: pick a fresh integer in [VERB_MIN_FRAMES, VERB_MAX_FRAMES]
  // every cycle, multiply by SPINNER_INTERVAL_MS, then add ± VERB_JITTER_MS
  // of jitter. setTimeout (NOT setInterval) so each cycle is a fresh draw.
  // Tuned for natural reading — average ≈ 2.4s between verb changes,
  // jittered ±1s so it never feels metronomic.
  const VERB_MIN_FRAMES = 9;
  const VERB_MAX_FRAMES = 16;
  const VERB_JITTER_MS = 1000;

  function urikaThinkingStart(el) {
    if (!el || el.dataset.urikaThinkingActive === "1") return null;
    el.dataset.urikaThinkingActive = "1";
    el.classList.add("urika-thinking");

    let spinnerIdx = 0;
    // Randomize starting verb so two placeholders on one page don't sync.
    let verbIdx = Math.floor(Math.random() * ACTIVITY_VERBS.length);

    const render = () => {
      el.textContent =
        SPINNER_FRAMES[spinnerIdx] + " " + ACTIVITY_VERBS[verbIdx] + "…";
    };
    render();

    const spin = setInterval(() => {
      spinnerIdx = (spinnerIdx + 1) % SPINNER_FRAMES.length;
      render();
    }, SPINNER_INTERVAL_MS);

    let verbTimer = null;
    const scheduleNextVerb = () => {
      const frames = VERB_MIN_FRAMES + Math.floor(
        Math.random() * (VERB_MAX_FRAMES - VERB_MIN_FRAMES + 1)
      );
      const jitter = (Math.random() * 2 - 1) * VERB_JITTER_MS;
      const ms = Math.max(400, frames * SPINNER_INTERVAL_MS + jitter);
      verbTimer = setTimeout(() => {
        verbIdx = (verbIdx + 1) % ACTIVITY_VERBS.length;
        render();
        scheduleNextVerb();
      }, ms);
    };
    scheduleNextVerb();

    return {
      stop() {
        clearInterval(spin);
        if (verbTimer) clearTimeout(verbTimer);
        el.classList.remove("urika-thinking");
        el.textContent = "";
        delete el.dataset.urikaThinkingActive;
      },
    };
  }

  window.urikaThinking = { start: urikaThinkingStart };
})();
