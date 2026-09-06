#!/bin/bash
# Deteksi game mana yang BENAR-BENAR punya aset Spine.
#
# Jangan menebak dari nama/jenis game — buktikan dari isinya.
# Dua sinyal:
#   1. File .skel / .atlas di dalam APK
#   2. Data game di /sdcard/Android/data/<pkg> (tempat aset unduhan)
#
# Pemakaian: bash tools/scan-spine-candidates.sh
export ANDROID_SERIAL=localhost:5556

CANDS="com.BonsaiCraftworks.MegahaRe
com.HoYoverse.hkrpgoversea
com.alluringgirl.qooapp
com.erolabs.orisries
com.gametree.lhlr.gp
com.himefun.stellaraffinity.erolabs
com.mjwygirls.qooapp
com.moonton.mobilehero
com.riichicity.happywoods.qooapp
jp.co.dmm.dmmgames.mist.adult
jp.co.fanzagames.dotabyss_x_a
jp.co.fanzagames.kke_aos
net.gameduo.dfd"

echo "=== PEMINDAIAN KANDIDAT SPINE ==="
echo

for PKG in $CANDS; do
  echo "--- $PKG ---"

  # 1. path APK
  APK=$(adb shell pm path "$PKG" 2>&1 | tr -d '\r' | sed 's/package://' | head -1)
  if [ -z "$APK" ]; then echo "    APK tidak ditemukan"; continue; fi

  SIZE=$(adb shell ls -la "$APK" 2>&1 | tr -d '\r' | awk '{print $5}')
  echo "    APK: ${SIZE:-?} byte"

  # 2. cari .skel/.atlas DI DALAM APK (unzip tidak ada, pakai grep binary)
  #    grep langsung di file zip tidak akan cocok karena terkompresi,
  #    jadi pakai pola nama file di central directory.
  HIT=$(adb shell "grep -c 'skel' '$APK' 2>/dev/null" 2>&1 | tr -d '\r')
  echo "    kecocokan 'skel' di APK: ${HIT:-0}"

  # 3. data game di sdcard
  DDIR="/sdcard/Android/data/$PKG"
  DSIZE=$(adb shell du -sh "$DDIR" 2>&1 | tr -d '\r' | awk '{print $1}')
  echo "    data: ${DSIZE:-tidak ada}"

  # 4. cari file skeleton di data (batasi kedalaman)
  SKEL=$(adb shell "find $DDIR -name '*.skel' 2>/dev/null | head -3" 2>&1 | tr -d '\r' | head -3)
  if [ -n "$SKEL" ]; then
    echo "    SKELETON DITEMUKAN:"
    echo "$SKEL" | sed 's/^/      /'
  fi
  echo
done
