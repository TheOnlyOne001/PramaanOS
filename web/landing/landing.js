// Landing page: fills the live trust strip from the public GET /api/site (no auth needed).
// Falls back to a calm "offline" state so the page never looks broken.

const $ = (id) => document.getElementById(id);

function setStatus(cls, text) {
  const chip = document.createElement("span");
  chip.className = `chip ${cls}`;
  chip.textContent = text;
  $("trustStatus").replaceChildren(chip);
}

async function loadSite() {
  const strip = $("trust");
  try {
    const res = await fetch("/api/site", { headers: { accept: "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const site = await res.json();
    const key = (site.public_keys && site.public_keys.site) || "";
    $("trustSite").textContent = [site.name, site.state].filter(Boolean).join(" · ") || "Demo site";
    $("trustEvents").textContent = Number(site.n_events || 0).toLocaleString("en-IN");
    $("trustKey").textContent = key ? `${key.slice(0, 16)}…` : "—";
    if (key) $("trustKey").title = key;
    setStatus("ok", "✓ Live ledger");
  } catch {
    $("trustSite").textContent = "Tiruppur Knits, Export Unit 3 (demo)";
    $("trustEvents").textContent = "—";
    $("trustKey").textContent = "unavailable";
    setStatus("neutral", "Offline: open the apps to load data");
  } finally {
    strip.setAttribute("aria-busy", "false");
  }
}

loadSite();
