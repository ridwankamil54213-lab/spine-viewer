// Which module actually provides `physicsConstraints` on SkeletonData in 4.2?
const path = require("path");
const ROOT = "/srv/spine-viewer";

const c42 = require(path.join(ROOT, "node_modules/spine-core42"));
console.log("spine-core42 SkeletonData has physicsConstraints?");
const sd = new c42.SkeletonData();
console.log("  physicsConstraints:", Array.isArray(sd.physicsConstraints) ? "array len " + sd.physicsConstraints.length : typeof sd.physicsConstraints);
console.log("  ikConstraints     :", Array.isArray(sd.ikConstraints) ? "array" : typeof sd.ikConstraints);

// The renderer imports its own nested copy — check that one too.
const nested = path.join(ROOT, "node_modules/spine-pixi-v7-42/node_modules/@esotericsoftware/spine-core");
const c42n = require(nested);
const sd2 = new c42n.SkeletonData();
console.log("");
console.log("nested (renderer's) spine-core:");
console.log("  version:", require(path.join(nested, "package.json")).version);
console.log("  physicsConstraints:", Array.isArray(sd2.physicsConstraints) ? "array" : typeof sd2.physicsConstraints);

// Also: does the renderer's Spine accept a skeletonData directly?
const pixi42 = require(path.join(ROOT, "node_modules/spine-pixi-v7-42"));
console.log("");
console.log("renderer Spine exports:", typeof pixi42.Spine);
console.log("Spine.prototype keys:", Object.getOwnPropertyNames(pixi42.Spine.prototype).slice(0, 30).join(", "));
