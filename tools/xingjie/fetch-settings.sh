#!/usr/bin/env bash
# 性界大战 (h5.spj2web.com) -> /opt/xingjie/{settings.js,map.json}
#
# Membaca hash build dari index.html (berubah tiap rilis), mengunduh settings.js,
# lalu mengekstrak map aset (rawAssets/uuids/md5AssetsMap) via node.
set -euo pipefail
OUT=${OUT:-/opt/xingjie}
BASE=${BASE:-https://h5.spj2web.com}
NODE=${NODE:-$(command -v node || echo /opt/node20/bin/node)}
mkdir -p "$OUT"

echo "== index.html =="
curl -fsSk --max-time 30 -A "Mozilla/5.0" "$BASE/" -o "$OUT/index.html" \
  || { echo "gagal ambil index.html"; exit 1; }

SET=$(grep -oE 'src/settings\.[0-9a-f]+\.js' "$OUT/index.html" -m1 || true)
PROJ=$(grep -oE 'src/project\.[0-9a-f]+\.js' "$OUT/index.html" -m1 || true)
[ -n "$SET" ] || { echo "settings.js tidak ditemukan di index.html"; exit 1; }
echo "  settings = $SET"
echo "  project  = $PROJ"

echo "== settings.js =="
curl -fsSk --max-time 60 -A "Mozilla/5.0" "$BASE/$SET" -o "$OUT/settings.js"
echo "  $(stat -c%s "$OUT/settings.js") byte"

echo "== plugin_conf.js (encriptKey/Sign) =="
curl -fsSk --max-time 30 -A "Mozilla/5.0" "$BASE/src/assets/plugin_conf.js" \
  -o "$OUT/plugin_conf.js" || true

echo "== map aset (node) =="
"$NODE" "$(dirname "$0")/dump-settings.cjs" "$OUT/settings.js" "$OUT/map.json"
echo "  -> $OUT/map.json"
