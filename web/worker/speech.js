// Worker app: read-aloud (speech synthesis) and dictation (speech recognition), in the chosen language.
import { toast } from "/shared/api.js";
import { SPEECH_LANG } from "/shared/i18n.js";
import { S, L, $ } from "./state.js";

/** Browser speech recognition constructor, or undefined where unsupported. */
export const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

/** Speak `text`; a second press stops speaking. */
export function speak(text) {
  if (!("speechSynthesis" in window)) { toast(L("not_available")); return; }
  const synth = window.speechSynthesis;
  const btn = $("#speak");
  if (synth.speaking) { synth.cancel(); btn.classList.remove("on"); return; }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = SPEECH_LANG[S.lang] || "en-IN";
  const v = synth.getVoices().find((x) => x.lang && x.lang.replace("_", "-").toLowerCase().startsWith(u.lang.slice(0, 2).toLowerCase()));
  if (v) u.voice = v;
  u.rate = 0.92;
  u.onend = u.onerror = () => btn.classList.remove("on");
  btn.classList.add("on");
  synth.speak(u);
}

/** Text for "read aloud": the integrity banner first, then every [data-say] on the screen. */
export function screenSpeech() {
  const parts = [];
  const b = $("#banner [data-say]");
  if (b) parts.push(b.innerText);
  document.querySelectorAll("#screen [data-say]").forEach((el) => parts.push(el.getAttribute("data-say") || el.innerText));
  return parts.join(". ").replace(/\s+/g, " ").trim();
}

/** Start one recognition session. Calls onResult(alternatives) and always onEnd(error?). */
export function listen(onResult, onEnd) {
  if (!SR) return null;
  try {
    const r = new SR();
    r.lang = SPEECH_LANG[S.lang] || "ta-IN";
    r.interimResults = false;
    r.maxAlternatives = 4;
    r.onresult = (e) => onResult([...e.results[0]].map((a) => a.transcript));
    r.onerror = (e) => onEnd(e.error || "error");
    r.onend = () => onEnd();
    r.start();
    return r;
  } catch (e) { onEnd(String(e)); return null; }
}
