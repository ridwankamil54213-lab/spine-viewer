// Narrow down "physics is undefined": it's thrown inside Skeleton's
// constructor / updateWorldTransform. Print the real stack.
const path = require("path");
const fs = require("fs");
const ROOT = "/srv/spine-viewer";
const ASSETS = path.join(ROOT, "assets/stellaraffinity");
const core42 = require(path.join(ROOT, "node_modules/spine-core42"));

class Fake {
  constructor() { this.width = 2048; this.height = 2048; }
  setFilters() {}
  setWraps() {}
  dispose() {}
}

const model = process.argv[2] || "a01001";
const dir = path.join(ASSETS, model);
const atlasText = fs.readFileSync(path.join(dir, model + ".atlas"), "utf8");
const atlas = new core42.TextureAtlas(atlasText, (p, cb) => cb(new Fake()));
const bin = new core42.SkeletonBinary(new core42.AtlasAttachmentLoader(atlas));
bin.scale = 1;
const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(dir, model + ".skel"))));

console.log("model:", model);
console.log("SkeletonData fields:");
for (const k of ["bones", "slots", "skins", "animations", "ikConstraints", "transformConstraints", "pathConstraints", "physicsConstraints"]) {
  const v = data[k];
  console.log(`  ${k.padEnd(22)} ${Array.isArray(v) ? "array[" + v.length + "]" : typeof v}`);
}

console.log("");
console.log("--- new Skeleton(data) ---");
let skel;
try {
  skel = new core42.Skeleton(data);
  console.log("  OK bones:", skel.bones.length);
} catch (e) {
  console.log("  FAIL:", e.message);
  console.log(e.stack.split("\n").slice(0, 8).join("\n"));
  process.exit(0);
}

console.log("--- updateWorldTransform ---");
try {
  skel.updateWorldTransform();
  console.log("  OK");
} catch (e) {
  console.log("  FAIL:", e.message);
  console.log(e.stack.split("\n").slice(0, 8).join("\n"));
}
