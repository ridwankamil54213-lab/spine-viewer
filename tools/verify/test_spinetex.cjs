// Does SpineTexture.from() work on a plain Pixi BaseTexture outside a browser?
const path = require("path");
const ROOT = "/srv/spine-viewer";
const fs = require("fs");

const pixi42 = require(path.join(ROOT, "node_modules/spine-pixi-v7-42"));
const core42 = require(path.join(ROOT, "node_modules/spine-core42"));
console.log("SpineTexture:", typeof pixi42.SpineTexture);
console.log("SpineTexture.from:", typeof pixi42.SpineTexture?.from);

// SpineTexture.from expects a Pixi *BaseTexture* and does
//   (image.source as BaseImageResource).source
const { BaseTexture, Texture } = require(path.join(ROOT, "node_modules/pixi.js"));
console.log("");
console.log("pixi BaseTexture:", typeof BaseTexture);

// Build a minimal BaseTexture from a real PNG so `source` exists.
const png = path.join(ROOT, "assets/stellaraffinity/c00001_01/c00001_01.png");
console.log("png exists:", fs.existsSync(png), fs.statSync(png).size, "bytes");

const bt = BaseTexture.fromBuffer
  ? null
  : null;

// Simplest faithful test: use a canvas-free image resource is not available in
// node, so just inspect what SpineTexture's ctor touches.
const src = fs.readFileSync(path.join(ROOT, "node_modules/spine-pixi-v7-42/dist/SpineTexture.js"), "utf8");
const m = src.match(/constructor\s*\(image\)\s*\{[\s\S]{0,400}/);
console.log("");
console.log("--- SpineTexture constructor source ---");
console.log(m ? m[0] : "(not matched)");
