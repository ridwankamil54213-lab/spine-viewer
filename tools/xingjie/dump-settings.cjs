// Ubah settings.js 性界大战 menjadi map.json ringkas:
//   skeletons[] = {path, uuid36}
//   textures[]  = {path, uuid36}
//   md5{}       = {import:{uuid36:hash}, "raw-assets":{uuid36:hash}}
//
// Pakai: node dump-settings.cjs settings.js map.json
const fs = require('fs');
const [src, dst] = process.argv.slice(2);
if (!src || !dst) { console.error('usage: dump-settings.cjs <settings.js> <map.json>'); process.exit(2); }

global.window = {};
require(require('path').resolve(src));
const s = window._CCSettings;

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function decodeUuid(u){
  if (!u || u.length !== 22) return u;
  let o = u[0] + u[1];
  for (let i = 2; i < 22; i += 2){
    const l = B64.indexOf(u[i]), r = B64.indexOf(u[i+1]);
    o += (((l >> 2)).toString(16)) + ((((l & 3) << 2) | (r >> 4)).toString(16)) + ((r & 0xF).toString(16));
  }
  return o.slice(0,8)+'-'+o.slice(8,12)+'-'+o.slice(12,16)+'-'+o.slice(16,20)+'-'+o.slice(20);
}

const types = s.assetTypes;
const si = types.indexOf('sp.SkeletonData');
const ti = types.indexOf('cc.Texture2D');
const A = s.rawAssets.assets;
const skeletons = [], textures = [];
for (const id in A){
  const e = A[id];
  const u36 = decodeUuid(s.uuids[id] || id);
  if (e[1] === si) skeletons.push({ path: e[0], uuid: u36 });
  else if (e[1] === ti) textures.push({ path: e[0], uuid: u36 });
}
const md5 = {};
for (const mount in s.md5AssetsMap){
  const arr = s.md5AssetsMap[mount]; md5[mount] = {};
  for (let i = 0; i < arr.length; i += 2){
    md5[mount][arr[i]] = arr[i+1];
    if (arr[i].length === 22) md5[mount][decodeUuid(arr[i])] = arr[i+1];
  }
}
fs.writeFileSync(dst, JSON.stringify({ skeletons, textures, md5 }, null, 1));
console.log('skeletons', skeletons.length, 'textures', textures.length,
            'md5.import', Object.keys(md5.import||{}).length, 'md5.raw-assets', Object.keys(md5['raw-assets']||{}).length);
