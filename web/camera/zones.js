// Restricted-zone editor drawn on an SVG laid exactly over the image's content box (object-fit: contain).
// Points are stored normalized 0..1 of the image, so zones survive any resolution or screen size.
import { api, esc } from "/shared/api.js";

const SVGNS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const clamp = (v) => Math.min(1, Math.max(0, v));
const r4 = (v) => Math.round(v * 10000) / 10000;

export function createZoneEditor({ camera, stage, img, svg, onChange }) {
  const st = { zones: [], saved: "[]", sel: -1, drawing: false, labels: true, box: { x: 0, y: 0, w: 1, h: 1 },
    drag: null, focusPt: -1, loaded: false };
  const ui = {
    draw: $("drawBtn"), add: $("addPtBtn"), finish: $("finishBtn"), cancel: $("cancelBtn"), del: $("deleteBtn"),
    reset: $("resetBtn"), save: $("saveBtn"), name: $("zoneName"), list: $("zoneList"), status: $("edStatus"),
    labels: $("labelsToggle"),
  };

  const snapshot = () => JSON.stringify(st.zones.map((z) => ({ id: z.id, name: z.name, points: z.points })));
  const dirty = () => snapshot() !== st.saved;
  const cur = () => st.zones[st.sel] || null;

  function say(msg, cls = "") { ui.status.textContent = msg; ui.status.className = "ed-status " + cls; }

  // ---- geometry: where the picture actually is inside the 16:9 stage ----
  function layout() {
    const W = stage.clientWidth, H = stage.clientHeight;
    const nw = img.naturalWidth || 16, nh = img.naturalHeight || 9;
    const s = Math.min(W / nw, H / nh);
    const w = Math.max(1, nw * s), h = Math.max(1, nh * s);
    st.box = { x: (W - w) / 2, y: (H - h) / 2, w, h };
    Object.assign(svg.style, { left: st.box.x + "px", top: st.box.y + "px", width: w + "px", height: h + "px" });
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    render();
  }
  const px = (p) => [p[0] * st.box.w, p[1] * st.box.h];
  function norm(ev) {
    const r = svg.getBoundingClientRect();
    return [r4(clamp((ev.clientX - r.left) / r.width)), r4(clamp((ev.clientY - r.top) / r.height))];
  }

  // ---- drawing ----
  function el(tag, attrs, text) {
    const e = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  }

  function render() {
    const keepFocus = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.pt : null;
    svg.replaceChildren();
    svg.classList.toggle("drawing", st.drawing);
    st.zones.forEach((z, zi) => {
      const sel = zi === st.sel;
      const pts = z.points.map(px);
      const open = sel && st.drawing;
      if (pts.length >= 2) {
        const poly = el(open ? "polyline" : "polygon", {
          points: pts.map((p) => p.join(",")).join(" "),
          class: "z-poly" + (sel ? " sel" : "") + (open ? " open" : ""), "data-zone": zi,
        });
        svg.appendChild(poly);
      }
      if (st.labels && pts.length >= 1 && !(open && pts.length < 2)) {
        const top = pts.reduce((a, p) => (p[1] < a[1] || (p[1] === a[1] && p[0] < a[0]) ? p : a), pts[0]);
        const label = z.name || "Restricted zone";
        const w = Math.max(84, label.length * 7.6 + 20);
        const x = Math.min(Math.max(0, top[0] - 4), st.box.w - w), y = Math.max(0, top[1] - 40);
        const g = el("g", { class: "z-tag", "aria-hidden": "true" });
        g.appendChild(el("rect", { x, y, width: w, height: 34, rx: 6, class: "z-label-bg" + (sel ? " sel" : "") }));
        g.appendChild(el("text", { x: x + 10, y: y + 13, class: "z-kind" }, "RESTRICTED"));
        g.appendChild(el("text", { x: x + 10, y: y + 28, class: "z-label" }, label));
        svg.appendChild(g);
      }
      if (sel) {
        if (open && pts.length >= 1) {
          const last = pts[pts.length - 1], first = pts[0];
          if (pts.length >= 2) svg.appendChild(el("line", { x1: last[0], y1: last[1], x2: first[0], y2: first[1], class: "ghost-line" }));
        }
        pts.forEach((p, pi) => {
          const h = el("circle", {
            cx: p[0], cy: p[1], r: 8, class: "h" + (pi === 0 ? " first" : "") + (st.drag && st.drag.pi === pi ? " on" : ""),
            tabindex: "0", role: "button", "data-pt": pi,
            "aria-label": `Corner ${pi + 1} of ${z.points.length}, ${z.name || "zone"}: ${Math.round(z.points[pi][0] * 100)}% across, ` +
              `${Math.round(z.points[pi][1] * 100)}% down. Arrow keys move it, Delete removes it.`,
          });
          svg.appendChild(h);
        });
      }
    });
    const want = st.focusPt >= 0 ? String(st.focusPt) : keepFocus;
    if (want != null) {
      const h = svg.querySelector(`[data-pt="${want}"]`);
      if (h) h.focus({ preventScroll: true });
    }
    st.focusPt = -1;
    sync();
  }

  function sync() {
    const z = cur();
    ui.add.classList.toggle("hidden", !st.drawing);
    ui.finish.classList.toggle("hidden", !st.drawing);
    ui.cancel.classList.toggle("hidden", !st.drawing);
    ui.draw.classList.toggle("hidden", st.drawing);
    ui.finish.disabled = !(z && z.points.length >= 3);
    ui.del.disabled = !z || st.drawing;
    const d = dirty();
    ui.reset.disabled = !d || st.drawing;
    ui.save.disabled = !d || st.drawing;
    ui.name.disabled = !z;
    if (document.activeElement !== ui.name) ui.name.value = z ? z.name : "";
    ui.list.replaceChildren(...st.zones.map((zz, zi) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("aria-pressed", String(zi === st.sel));
      b.innerHTML = `<span class="sw-dot" aria-hidden="true"></span>${esc(zz.name || "Unnamed zone")}` +
        `<span class="sr">, ${zz.points.length} corners${zz.id ? "" : ", not saved"}</span>`;
      b.addEventListener("click", () => { if (!st.drawing) { st.sel = zi; render(); } });
      li.appendChild(b);
      return li;
    }));
    if (onChange) onChange({ dirty: d, zones: st.zones });
  }

  // ---- actions ----
  function startDraw() {
    st.zones.push({ name: `Restricted zone ${st.zones.length + 1}`, kind: "restricted", points: [] });
    st.sel = st.zones.length - 1;
    st.drawing = true;
    say("Drawing: click on the view to add corners, or use Add point. Double-click or Enter to close.", "warn");
    render();
    svg.focus?.({ preventScroll: true });
  }
  function addPoint(p) {
    const z = cur(); if (!z) return;
    z.points.push(p);
    render();
  }
  function addPointKeyboard() {
    const z = cur(); if (!z) return;
    const n = z.points.length;
    const preset = [[0.35, 0.35], [0.65, 0.35], [0.65, 0.7], [0.35, 0.7]];
    const p = n < 4 ? preset[n] : [clamp(z.points[n - 1][0] + 0.05), clamp(z.points[n - 1][1])];
    z.points.push(p);
    st.focusPt = z.points.length - 1;
    render();
    say(`Corner ${z.points.length} added. Move it with the arrow keys.`, "warn");
  }
  function finish() {
    const z = cur();
    if (!z || z.points.length < 3) { say("A zone needs at least 3 corners.", "warn"); return; }
    st.drawing = false;
    say(`“${z.name}” closed. Name it, then Save zones.`, "warn");
    render();
    ui.name.focus();
    ui.name.select();
  }
  function cancel() {
    if (!st.drawing) return;
    st.zones.splice(st.sel, 1);
    st.sel = -1; st.drawing = false;
    say("Drawing cancelled.");
    render();
    ui.draw.focus();
  }
  function del() {
    const z = cur(); if (!z) return;
    st.zones.splice(st.sel, 1);
    st.sel = -1;
    say(`“${z.name}” removed. Save zones to apply.`, "warn");
    render();
  }
  function reset() {
    st.zones = JSON.parse(st.saved).map((z) => ({ ...z, kind: "restricted" }));
    st.sel = -1; st.drawing = false;
    say("Changes discarded.");
    render();
  }

  async function load() {
    const r = await api(`/edge/zones?camera=${encodeURIComponent(camera)}`);
    if (!r.ok) {
      say(r.status === 404 ? "Zone storage is not available on this server yet." : `Could not load zones (${r.error}).`, "crit");
      st.loaded = false;
      return false;
    }
    const zones = (r.data && r.data.zones) || [];
    st.zones = zones.filter((z) => Array.isArray(z.points)).map((z) => ({ id: z.id, name: z.name || "", kind: "restricted",
      points: z.points.map((p) => [Number(p[0]), Number(p[1])]) }));
    st.saved = snapshot();
    st.loaded = true;
    if (st.sel >= st.zones.length) st.sel = -1;
    render();
    return true;
  }

  async function save() {
    if (st.drawing) finish();
    const bad = st.zones.find((z) => z.points.length < 3);
    if (bad) { say(`“${bad.name}” needs at least 3 corners.`, "crit"); return; }
    ui.save.disabled = true;
    say("Saving…");
    const body = { camera, zones: st.zones.map((z) => {
      const o = { name: (z.name || "Restricted zone").trim().slice(0, 40), kind: "restricted", points: z.points.map((p) => [r4(p[0]), r4(p[1])]) };
      if (z.id) o.id = z.id;
      return o;
    }) };
    const r = await api("/edge/zones", { method: "PUT", body });
    if (!r.ok) { say(`Not saved: ${r.error}`, "crit"); sync(); return; }
    const selName = cur() && cur().name;
    await load();
    st.sel = st.zones.findIndex((z) => z.name === selName);
    render();
    const t = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
    say(`Saved ${st.zones.length} zone${st.zones.length === 1 ? "" : "s"} at ${t}. The edge box picks them up on its next heartbeat.`, "ok");
  }

  // ---- input ----
  let lastClick = 0;
  svg.addEventListener("pointerdown", (ev) => {
    const t = ev.target;
    if (t.dataset && t.dataset.pt != null) {
      st.drag = { pi: Number(t.dataset.pt), id: ev.pointerId, moved: false };
      svg.setPointerCapture(ev.pointerId);
      t.focus({ preventScroll: true });
      ev.preventDefault();
      return;
    }
    if (st.drawing) {
      ev.preventDefault();
      const now = Date.now();
      const p = norm(ev);
      const z = cur();
      const last = z && z.points[z.points.length - 1];
      // second press of a double-click lands on the same spot: it closes the shape instead of adding a corner
      if (last && now - lastClick < 350 && Math.hypot(p[0] - last[0], p[1] - last[1]) < 0.015) { lastClick = 0; finish(); return; }
      lastClick = now;
      addPoint(p);
      return;
    }
    if (t.dataset && t.dataset.zone != null) { st.sel = Number(t.dataset.zone); render(); return; }
    if (st.sel !== -1) { st.sel = -1; render(); }
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!st.drag || ev.pointerId !== st.drag.id) return;
    const z = cur(); if (!z) return;
    z.points[st.drag.pi] = norm(ev);
    st.drag.moved = true;
    render();
  });
  const endDrag = (ev) => {
    if (!st.drag || ev.pointerId !== st.drag.id) return;
    const moved = st.drag.moved, pi = st.drag.pi;
    st.drag = null;
    try { svg.releasePointerCapture(ev.pointerId); } catch { /* already released */ }
    if (moved) { st.focusPt = pi; render(); }
  };
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);
  svg.addEventListener("dblclick", (ev) => { if (st.drawing) { ev.preventDefault(); finish(); } });

  svg.addEventListener("keydown", (ev) => {
    const t = ev.target;
    if (st.drawing && ev.key === "Enter") { ev.preventDefault(); finish(); return; }
    if (st.drawing && ev.key === "Escape") { ev.preventDefault(); cancel(); return; }
    if (!(t.dataset && t.dataset.pt != null)) return;
    const z = cur(); if (!z) return;
    const pi = Number(t.dataset.pt);
    const step = ev.shiftKey ? 0.02 : 0.004;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
    if (d) {
      ev.preventDefault();
      z.points[pi] = [r4(clamp(z.points[pi][0] + d[0])), r4(clamp(z.points[pi][1] + d[1]))];
      st.focusPt = pi;
      render();
    } else if ((ev.key === "Delete" || ev.key === "Backspace") && (st.drawing || z.points.length > 3)) {
      ev.preventDefault();
      z.points.splice(pi, 1);
      st.focusPt = Math.min(pi, z.points.length - 1);
      render();
    } else if (ev.key === " " || (ev.key === "Enter" && !st.drawing)) {
      ev.preventDefault();
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (!st.drawing || ev.defaultPrevented || ev.target === ui.name) return;
    if (ev.key === "Enter" && !(ev.target instanceof HTMLButtonElement)) { ev.preventDefault(); finish(); }
    if (ev.key === "Escape") { ev.preventDefault(); cancel(); }
  });

  ui.draw.addEventListener("click", startDraw);
  ui.add.addEventListener("click", addPointKeyboard);
  ui.finish.addEventListener("click", finish);
  ui.cancel.addEventListener("click", cancel);
  ui.del.addEventListener("click", del);
  ui.reset.addEventListener("click", reset);
  ui.save.addEventListener("click", save);
  ui.name.addEventListener("input", () => { const z = cur(); if (z) { z.name = ui.name.value; render(); } });
  ui.name.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); if (!ui.save.disabled) save(); } });
  ui.labels.addEventListener("change", () => { st.labels = ui.labels.checked; render(); });

  new ResizeObserver(layout).observe(stage);
  img.addEventListener("load", layout);
  layout();

  return { load, layout, isDirty: dirty, isDrawing: () => st.drawing, zones: () => st.zones };
}
