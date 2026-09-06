#!/bin/bash
# Uji CAKUPAN: dari 4.004 bundle, grep hanya menandai 300.
# Apakah 3.704 sisanya benar-benar tidak berisi Spine, atau grep
# melewatkan mereka karena isinya terkompresi?
#
# Ambil sampel acak bundle yang TIDAK lolos grep, tarik ke host,
# lalu buka dengan UnityPy (sumber kebenaran).
export ANDROID_SERIAL=localhost:5556
PKG=com.tingzhou.cwcxtw.qooapp
SRC=/sdcard/Android/data/$PKG/files/yoo/ResPackage/CacheFiles
DST=/srv/spine-assets/hazereverb-negcheck
N=${N:-120}

mkdir -p "$DST"
cd "$DST" || exit 1

echo "=== ambil daftar SEMUA bundle ==="
adb shell "cd $SRC && find . -name __data 2>/dev/null" 2>&1 | tr -d '\r' \
  | sed 's|^\./||' | sort > all.txt
wc -l < all.txt | xargs echo "  total bundle:"

echo "=== buang yang sudah lolos grep ==="
sed 's|/__data||' /srv/spine-assets/hazereverb-bundles.txt | sort -u > pos.txt
comm -23 all.txt pos.txt > neg.txt
wc -l < neg.txt | xargs echo "  bukan-hasil-grep:"

echo "=== ambil $N sampel acak ==="
shuf -n "$N" neg.txt --random-source=<(yes) > sample.txt
wc -l < sample.txt | xargs echo "  sampel:"

echo "=== tarik ke host ==="
while read -r rel; do
  [ -z "$rel" ] && continue
  d=$(dirname "$(dirname "$rel")")
  h=$(basename "$(dirname "$rel")")
  mkdir -p "$d/$h"
  adb pull "$SRC/$rel" "$d/$h/__data" >/dev/null 2>&1
done < sample.txt
echo "  selesai, ukuran: $(du -sh . | cut -f1)"
