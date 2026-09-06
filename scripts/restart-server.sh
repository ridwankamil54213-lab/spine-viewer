#!/usr/bin/env bash
# Restart server spine-viewer secara idempoten.
#
# Kenapa perlu: menjalankan `node src/server.js` di background berkali-kali
# bikin proses kedua gagal dengan EADDRINUSE (port 3000 sudah dipakai yang
# pertama). Yang bikin bingung, proses yang GAGAL itu kadang start duluan
# dan memuat kode lama, jadi patch terbaru tidak aktif walau terlihat sudah
# di-restart.
#
# Skrip ini: matikan semua yang menguasai port 3000, tunggu port benar-benar
# lepas, lalu start tepat satu instance dan verifikasi dengan HTTP.
#
# Catatan: JANGAN pakai `pkill -f "src/server.js"` — pola itu cocok dengan
# perintah shell sendiri dan membunuh shell-nya (exit -15).

set -uo pipefail

PORT="${PORT:-3000}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${LOG:-/tmp/spine-viewer-server.log}"

port_pids() {
	ss -lptn "sport = :${PORT}" 2>/dev/null \
		| grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u
}

echo "== port ${PORT} =="
pids="$(port_pids)"
if [ -n "${pids}" ]; then
	echo "proses aktif: $(echo "${pids}" | tr '\n' ' ')"
	for pid in ${pids}; do
		kill "${pid}" 2>/dev/null && echo "  kill ${pid}"
	done
else
	echo "tidak ada proses"
fi

# Tunggu sampai port benar-benar lepas (maks 15 detik).
for _ in $(seq 1 30); do
	[ -z "$(port_pids)" ] && break
	sleep 0.5
done

if [ -n "$(port_pids)" ]; then
	echo "GAGAL: port ${PORT} masih dipakai: $(port_pids | tr '\n' ' ')" >&2
	exit 1
fi
echo "port bersih"

cd "${DIR}"
: >"${LOG}"
node src/server.js >>"${LOG}" 2>&1 &
newpid=$!
echo "start pid ${newpid}, log: ${LOG}"

# Tunggu siap (maks 40 detik). Jangan curl duluan — server butuh beberapa
# detik sebelum binding selesai, dan curl prematur cuma balas 000.
ok=0
for _ in $(seq 1 80); do
	code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
		"http://127.0.0.1:${PORT}/" 2>/dev/null)"
	if [ "${code}" = "200" ]; then
		ok=1
		break
	fi
	sleep 0.5
done

if [ "${ok}" != "1" ]; then
	echo "GAGAL: server tidak merespon 200. Log:" >&2
	tail -20 "${LOG}" >&2
	exit 1
fi

echo "OK — HTTP 200 (pid ${newpid})"
echo "jumlah instance: $(ps -eo args | grep -c '[s]rc/server.js')"
