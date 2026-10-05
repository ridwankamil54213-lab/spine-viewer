const fs = require("fs");
const path = process.argv[2];
const raw = JSON.parse(fs.readFileSync(path, "utf8"));
console.log("file version:", raw.skeleton && raw.skeleton.spine);

for (const key of ["runtime-3.7", "runtime-3.8", "runtime-4.0", "runtime-4.1"]) {
  let mod;
  try {
    mod = require("@pixi-spine/" + key);
  } catch (e) {
    console.log(key, "-> import fail", e.message);
    continue;
  }
  // Dummy atlas: no pages needed for the parse test.
  const fakeAtlas = { pages: [], regions: [], findRegion: () => null };
  try {
    const loader = new mod.AtlasAttachmentLoader(fakeAtlas);
    const parser = new mod.SkeletonJson(loader);
    const data = parser.readSkeletonData(raw);
    console.log(key, "-> OK bones=", data.bones.length, "slots=", data.slots.length, "anim=", data.animations.length);
  } catch (e) {
    console.log(key, "-> FAIL", String(e.message).slice(0, 100));
  }
}

// Also try pixi-spine's own version-detecting Spine loader.
try {
  const ps = require("pixi-spine");
  console.log("pixi-spine exported:", Object.keys(ps).filter(k => /Skeleton|Atlas|Spine/i.test(k)).join(","));
} catch (e) {
  console.log("pixi-spine import fail", e.message);
}
