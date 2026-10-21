// Reproduce the export pipeline over HTTP only, so the server's 500 body is
// visible (the browser just logs "Failed to load resource").
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const BASE = process.env.BASE || "http://127.0.0.1:3000";
const JOB = "testjob" + Date.now().toString(36); // /^[a-z0-9]{6,32}$/

// Build a tiny valid PNG (solid 8x8 red square) without dependencies.
function crc32(buf) {
  let c, crc = 0xFFFFFFFF;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    crc = c ^ (crc >>> 8);
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function makePng(w, h) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const raw = Buffer.alloc(h * (1 + w * 4));
  for (let y = 0; y < h; y++) {
    const off = y * (1 + w * 4);
    raw[off] = 0;
    for (let x = 0; x < w; x++) {
      const p = off + 1 + x * 4;
      raw[p] = 220; raw[p + 1] = 40; raw[p + 2] = 40; raw[p + 3] = 255;
    }
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

(async () => {
  console.log("capabilities:", await (await fetch(BASE + "/api/export/capabilities")).text());

  // NOTE: /api/export/frame takes a RAW body (express.raw) plus query params,
  // not multipart FormData — job/i/n travel in the query string.
  const N = 6;
  for (let i = 0; i < N; i++) {
    const png = makePng(64, 64);
    const url = `${BASE}/api/export/frame?job=${JOB}&i=${i}&n=${N}`;
    const r = await fetch(url, {
      method: "POST",
      headers: { "content-type": "image/png" },
      body: png,
    });
    const t = await r.text();
    if (!r.ok) { console.log(`frame ${i}: HTTP ${r.status} ${t.slice(0, 300)}`); process.exit(1); }
  }
  console.log(`posted ${N} frames OK`);

  const r = await fetch(BASE + "/api/export/finish", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ job: JOB, format: process.env.FMT || "gif", background: process.env.BG || "black", fps: 12, frames: N }),
  });
  const body = await r.text();
  console.log(`finish: HTTP ${r.status}`);
  try { console.log(JSON.stringify(JSON.parse(body), null, 1)); }
  catch { console.log(body.slice(0, 600)); }

  if (r.ok) {
    const j = JSON.parse(body);
    const url = j.url || (j.file && "/exports/" + j.file);
    if (url) {
      const g = await fetch(BASE + url);
      const b = Buffer.from(await g.arrayBuffer());
      console.log(`GET ${url} -> ${g.status}, ${b.length} bytes, magic ${b.subarray(0, 6).toString("ascii")}`);
      console.log(b.length > 500 ? "EXPORT HTTP TEST: PASS" : "EXPORT HTTP TEST: FAIL (too small)");
    }
  }
})();
