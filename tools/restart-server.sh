#!/usr/bin/env bash
# Restart the viewer server and wait until /api/models answers.
#
# A supervisor (PPID 1) respawns the server, so killing the old pid races
# with the new one binding port 3000 (EADDRINUSE). This kills by port,
# waits for the port to actually free up, then starts a fresh instance.
set -u
cd /srv/spine-viewer || exit 1

port_pids() { ss -tlnp 2>/dev/null | grep ':3000' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u; }

for pid in $(port_pids); do
	kill "$pid" 2>/dev/null
done

for _ in $(seq 1 30); do
	[ -z "$(port_pids)" ] && break
	sleep 1
done

if [ -n "$(port_pids)" ]; then
	echo "GAGAL: port 3000 masih dipakai: $(port_pids | tr '\n' ' ')"
	exit 1
fi

nohup node src/server.js > /tmp/spine-server.log 2>&1 &
child=$!

for _ in $(seq 1 120); do
	code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' http://127.0.0.1:3000/ 2>/dev/null)
	if [ "$code" = "200" ]; then
		echo "siap (pid $child, HTTP 200)"
		exit 0
	fi
	sleep 2
done

echo "GAGAL: server tidak siap. Log terakhir:"
tail -15 /tmp/spine-server.log
exit 1
