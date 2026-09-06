#!/bin/bash
# Tarik 300 bundle Spine Haze Reverb dari perangkat ke host.
#
# Struktur YooAsset: tiap bundle berupa folder <2hex>/<hash>/ berisi
# __data (UnityFS) dan __info. Yang dibutuhkan hanya __data.
# Nama folder asli dipertahankan agar tidak ada tabrakan nama.
export ANDROID_SERIAL=localhost:5556
PKG=com.tingzhou.cwcxtw.qooapp
SRC=/sdcard/Android/data/$PKG/files/yoo/ResPackage/CacheFiles
DST=/srv/spine-assets/hazereverb-raw
LIST=/srv/spine-assets/hazereverb-bundles.txt

mkdir -p "$DST"
N=0
TOTAL=$(wc -l < "$LIST")
echo "menarik $TOTAL bundle -> $DST"

while read -r rel; do
  [ -z "$rel" ] && continue
  # rel = "8e/8ed30.../__data"
  d=$(dirname "$(dirname "$rel")")   # 8e
  h=$(basename "$(dirname "$rel")")  # 8ed30...
  mkdir -p "$DST/$d/$h"
  if [ ! -s "$DST/$d/$h/__data" ]; then
    adb pull "$SRC/$rel" "$DST/$d/$h/__data" >/dev/null 2>&1 || echo "  GAGAL $rel"
  fi
  N=$((N+1))
  if [ $((N % 50)) = 0 ]; then echo "  $N/$TOTAL"; fi
done < "$LIST"

echo "selesai: $N bundle"
du -sh "$DST" | xargs echo "ukuran:"
