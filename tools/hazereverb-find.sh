#!/bin/bash
# DAFTAR bundle Haze Reverb yang akan diekstrak.
#
# == JANGAN PAKAI GREP UNTUK MENYARING BUNDLE ==
#
# Versi pertama script ini menyaring dengan:
#     adb shell "cd $SRC && grep -rl '\.skel' ."
# dan itu GAGAL TOTAL.
#
# Bukti: dari 120 bundle yang TIDAK lolos grep, 82 (68%) ternyata berisi
# skeleton. Contoh yang terlewat: dongzuo_juese_xinzhi_pf,
# dongzuo_juese_siposi, dongzuo_juese_hualian, boss_dongzuo_shuimu,
# panduola. Dari 829 bundle, grep hanya menandai 300 — sisanya 529,
# dan sekitar 360 di antaranya berisi model sungguhan.
#
# Penyebab: UnityFS mengompresi isinya, sehingga nama TextAsset seperti
# "dongzuo_juese_aertaiya.skel" tidak selalu muncul sebagai teks utuh
# di dalam berkas. Grep hanya menemukan yang kebetulan tidak
# terkompresi.
#
# Karena itu sekarang kita ambil SEMUA bundle dan biarkan
# tools/extract-hazereverb.py yang memutuskan (ia membuka tiap bundle
# dengan UnityPy — itu sumber kebenaran).
#
# Keluaran: /srv/spine-assets/hazereverb-all.txt (path per baris)
export ANDROID_SERIAL=localhost:5556
PKG=com.tingzhou.cwcxtw.qooapp
SRC=/sdcard/Android/data/$PKG/files/yoo/ResPackage/CacheFiles
OUT=/srv/spine-assets/hazereverb-all.txt

echo "=== mendaftar SEMUA bundle (tanpa penyaringan grep) ==="
adb shell "cd $SRC && find . -name __data 2>/dev/null" 2>&1 \
  | tr -d '\r' | sed 's|^\./||' | sort > "$OUT"

N=$(wc -l < "$OUT")
echo "ditemukan: $N bundle"
echo "tersimpan di: $OUT"

# Catatan: total 829 bundle. Angka 4.004 yang muncul sebelumnya itu salah —
# ia menghitung berkas, dan tiap bundle terdiri dari __data + __info.
echo
echo "CATATAN: MediaPackage (4.5 GB) memang tidak berisi Spine — sudah"
echo "diperiksa dan 0 bundle di sana mengandung aset skeleton."
