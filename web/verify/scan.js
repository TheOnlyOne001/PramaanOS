/* Saakshi QR reader for the verify page.
 *
 * Uses the browser's built-in BarcodeDetector (format "qr_code") on a live camera stream or on an
 * image file. Every frame is decoded on this device: nothing is drawn to a canvas, stored or uploaded.
 * Exposes window.SaakshiScan = { support, start, stop, fromFile, extract }.
 */
(function () {
  "use strict";

  const SCAN_EVERY_MS = 200;
  let detector = null;
  let stream = null;
  let timer = 0;

  /** Resolves to {camera, image}: which QR sources this browser can read. Never rejects. */
  async function support() {
    const none = { camera: false, image: false };
    if (typeof window.BarcodeDetector !== "function") return none;
    try {
      const formats = await window.BarcodeDetector.getSupportedFormats();
      if (!formats.includes("qr_code")) return none;
      detector = new window.BarcodeDetector({ formats: ["qr_code"] });
    } catch {
      return none;
    }
    const md = navigator.mediaDevices;
    return { camera: !!(md && md.getUserMedia && window.isSecureContext), image: typeof window.createImageBitmap === "function" };
  }

  /** The credential part of a scanned value: the text after "#" of a verify link, or the value itself. */
  function extract(raw) {
    const s = String(raw || "").trim();
    const i = s.indexOf("#");
    return i >= 0 ? s.slice(i + 1) : s;
  }

  function stop() {
    clearTimeout(timer);
    timer = 0;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  /** Opens the rear camera into `video` and calls onCode(text) once, on the first QR it sees. */
  async function start(video, onCode) {
    stop();
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
    video.srcObject = stream;
    video.setAttribute("playsinline", "");
    video.muted = true;
    await video.play();
    const tick = async () => {
      if (!stream) return;
      try {
        if (video.readyState >= 2) {
          const codes = await detector.detect(video);
          const hit = codes.find((c) => c.rawValue);
          if (hit) { stop(); onCode(hit.rawValue); return; }
        }
      } catch { /* a dropped frame: try the next one */ }
      if (stream) timer = setTimeout(tick, SCAN_EVERY_MS);
    };
    tick();
  }

  /** Reads the first QR code in an image file; resolves to its text or null. */
  async function fromFile(file) {
    const bitmap = await createImageBitmap(file);
    try {
      const codes = await detector.detect(bitmap);
      const hit = codes.find((c) => c.rawValue);
      return hit ? hit.rawValue : null;
    } finally {
      if (bitmap.close) bitmap.close();
    }
  }

  window.SaakshiScan = { support, start, stop, fromFile, extract };
})();
