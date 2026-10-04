#!/usr/bin/env bash
# Bangun scsp2json (SCSP Yuna -> Spine JSON). Hanya butuh g++ + nlohmann json.
set -euo pipefail
cd "$(dirname "$0")"
OUT=${OUT:-/opt/czn-work}
mkdir -p "$OUT"
g++ -O2 -std=c++17 -Iparser parser/scsp_main.cpp parser/SCSPParser.cpp -o "$OUT/scsp2json"
echo "ok -> $OUT/scsp2json"
