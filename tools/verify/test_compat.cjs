// Does the official 4.3 spine-pixi-v7 renderer accept SkeletonData produced by
// the 4.2 spine-core? The data model is near-identical; verify by walking the
// structures the renderer actually touches (bones, slots, skins, attachments).
const path = require("path");
const fs = require("fs");
const ROOT = "/srv/spine-viewer";
const ASSETS = path.join(ROOT, "assets/stellaraffinity");

const core42 = require(path.join(ROOT, "node_modules/spine-core42"));
const core43 = require(path.join(ROOT, "node_modules/@esotericsoftware/spine-core"));

console.log("core42:", require(path.join(ROOT, "node_modules/spine-core42/package.json")).version);
console.log("core43:", require(path.join(ROOT, "node_modules/@esotericsoftware/spine-core/package.json")).version);

class Fake {
  constructor() { this.width = 2048; this.height = 2048; }
  setFilters() {}
  setWraps() {}
  dispose() {}
}

const model = process.argv[2] || "c00001_01";
const dir = path.join(ASSETS, model);
const atlasText = fs.readFileSync(path.join(dir, model + ".atlas"), "utf8");
const atlas = new core42.TextureAtlas(atlasText, (p, cb) => cb(new Fake()));
const bin = new core42.SkeletonBinary(new core42.AtlasAttachmentLoader(atlas));
bin.scale = 1;
const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(dir, model + ".skel"))));

console.log("");
console.log("parsed 4.2 skeleton:", model);
console.log("  bones:", data.bones.length, "slots:", data.slots.length, "skins:", data.skins.length, "anims:", data.animations.length);

// Now try to drive it with the 4.3 runtime's Skeleton + AnimationState
try {
  const skel = new core43.Skeleton(data);
  skel.updateWorldTransform();
  const stateData = new core43.AnimationStateData(data);
  const state = new core43.AnimationState(stateData);
  if (data.animations.length) state.setAnimation(0, data.animations[0].name, true);
  state.update(0.016);
  state.apply(skel);
  skel.updateWorldTransform();
  console.log("  4.3 Skeleton accepts 4.2 data: YES");
  console.log("  first bone:", skel.bones[0]?.data?.name, "worldX:", skel.bones[0]?.worldX?.toFixed(2));
  // Check the renderer's hot path: iterate slots & attachments
  let withAttachment = 0;
  for (const slot of skel.slots) {
    const a = slot.getAttachment();
    if (a) withAttachment++;
  }
  console.log("  slots with attachment:", withAttachment, "/", skel.slots.length);
} catch (e) {
  console.log("  4.3 Skeleton accepts 4.2 data: NO ->", e.message);
}
