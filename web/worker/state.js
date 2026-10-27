// Worker app state and small lookups shared by every screen.
import { fmtDay } from "/shared/api.js";
import { t, LOCALE } from "/shared/i18n.js";

export const DEMO_DAY = "2026-10-27";
export const PERIOD = "2026-10";
export const HOURS_FROM = "2026-10-19";
export const POLL_MS = 3000;

export const qs = new URLSearchParams(location.search);

/** The single mutable state object for the worker app. */
export const S = {
  wid: (qs.get("w") || "W001").toUpperCase(),
  worker: null, lang: "en", tab: "today", names: {},
  mismatches: [], receipts: [], seenSeqs: null, pending: [], consentResult: null, listening: false,
  mismatchChanged: false, consentDirty: false,
  voice: { topic: null, text: "", scrub: null, cases: [] },
  rules: null,
};

/** Translate key `k` into the current language. */
export const L = (k, v) => t(S.lang, k, v);
export const $ = (s, root = document) => root.querySelector(s);
export const locale = () => LOCALE[S.lang] || "en-IN";
export const day = (d) => fmtDay(d, locale());
export const nameOf = (id) => S.names[id] || id || "";
export const firstName = (id) => nameOf(id).split(" ")[0];
