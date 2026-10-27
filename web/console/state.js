// Employer console state, constants and section list shared by every module.
export const DEMO_DAY = "2026-10-27";
export const PERIOD = "2026-10";
export const $ = (s) => document.querySelector(s);

/** The single mutable state object for the console. */
export const S = { sec: "overview", workers: [], names: {}, verify: null, wasBad: false, cap: [], lastResults: null, payRun: null,
  lastPoll: 0, lastOkAt: null, flip: null, detected: {}, tamper: {} };

export const SECTIONS = [
  ["overview", "⚑", "Overview"], ["hours", "⏱", "Hours & overtime"], ["pay", "₹", "Pay fairness"],
  ["skills", "🎓", "Skills coverage"], ["safety", "📷", "Safety & cameras"], ["voice", "📣", "Voice"], ["sdg8", "◎", "SDG 8"],
];
