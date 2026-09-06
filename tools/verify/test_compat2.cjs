// Full 4.2 stack: parse with spine-core42, drive with the 4.2 Skeleton, and
// confirm the renderer's hot path (slots -> attachments -> vertices) works.
const path = require("path");
const fs = require("fs");
const ROOT = "/srv/spine-viewer";
const ASSETS = path.join(ROOT, "assets/stellaraffinity");

const core42 = require(path.join(ROOT, "node_modules/spine-core42"));
const _unused = require(path.join(ROOT, "node_modules/spine-core42"));

console.log("core42      :", require(path.join(ROOT, "node_modules/spine-core42/package.json")).version);
const pixi42 = require(path.join(ROOT, "node_modules/spine-pixi-v7-42"));
console.log("pixi-v7-42  :", require(path.join(ROOT, "node_modules/spine-pixi-v7-42/package.json")).version);
console.log("  has Spine:", typeof pixi42.Spine, " SpineTexture:", typeof pixi42.SpineTexture);
// Does the renderer bundle its own core, or use spine-core42?
const nested = path.join(ROOT, "node_modules/spine-pixi-v7-42/node_modules/@esotericsoftware/spine-core");
console.log("  nested core:", fs.existsSync(nested) ? "YES (separate instance)" : "no (hoisted)");

class Fake {
  constructor() { this.width = 2048; this.height = 2048; }
  setFilters() {}
  setWraps() {}
  dispose() {}
}

const models = fs.readdirSync(ASSETS).filter((m) => fs.statSync(path.join(ASSETS, m)).isDirectory()).sort();
console.log("");
console.log("models:", models.length);

let ok = 0; const fails = [];
for (const model of models) {
  const dir = path.join(ASSETS, model);
  try {
    const atlasText = fs.readFileSync(path.join(dir, model + ".atlas"), "utf8");
    const atlas = new core42.TextureAtlas(atlasText, (p, cb) => cb(new Fake()));
    const bin = new core42.SkeletonBinary(new core42.AtlasAttachmentLoader(atlas));
    bin.scale = 1;
    const data = bin.readSkeletonData(new Uint8Array(fs.readFileSync(path.join(dir, model + ".skel"))));

    // Drive it the way Spine (the renderer) does.
    const skel = new core42.Skeleton(data);
    skel.updateWorldTransform(core42.Physics.none);
    const stateData = new core42.AnimationStateData(data);
    const state = new core42.AnimationState(stateData);
    if (data.animations.length) state.setAnimation(0, data.animations[0].name, true);
    state.update(0.016);
    state.apply(skel);
    skel.updateWorldTransform(core42.Physics.none);

    let withAtt = 0;
    for (const slot of skel.slots) if (slot.getAttachment()) withAtt++;
    if (!skel.bones.length) throw new Error("no bones");
    ok++;
    if (ok <= 3) {
      console.log(`  ${model}: bones=${data.bones.length} slots=${data.slots.length} skins=${data.skins.length} anims=${data.animations.length} attached=${withAtt}`);
    }
  } catch (e) {
    if (fails.length < 8) fails.push(model + ": " + e.message);
  }
}
console.log("");
console.log("=== RESULT ===");
console.log("driven OK:", ok, "/", models.length);
console.log("failed   :", models.length - ok);
fails.forEach((f) => console.log("  !", f));
