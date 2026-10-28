#!/usr/bin/env python3
"""Ambil kunci AES Mobile Legends: Adventure dari proses game yang berjalan.

Kuncinya tidak ada di APK: Lua memanggil CCCrypto::setKey(<hex>) saat runtime.
Cara paling andal adalah spawn game dengan hook frida yang menangkap argumen
`aesDecrypt_zlibInflate` — argumen ke-3 adalah <key hex 32> + <iv hex 16>.

Hasil disimpan ke data/mlbb-crypto.json (dipakai tools/extract-mlbb.py).

Prasyarat:
  - game terpasang & bisa dijalankan di device redroid
  - frida-server jalan di device (lihat --push-frida)
  - adb forward tcp:27042 tcp:27042

Pakai:
  python tools/mlbb/capture_key.py --push-frida     # sekali saja
  python tools/mlbb/capture_key.py
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "mlbb-crypto.json")
PKG = "com.moonton.mobilehero"
ADB_DEV = os.environ.get("MLBB_ADB", "127.0.0.1:5556")
FRIDA_PORT = 27042
FRIDA_VER = "17.24.3"

HOOK = r"""
let mod = null;
function waitMod(cb) {
	const t = setInterval(() => {
		mod = Process.findModuleByName("libagame.so");
		if (mod) { clearInterval(t); cb(); }
	}, 300);
}
function start() {
	const sym = mod.findExportByName(
		"_Z45tolua_cocos2d_CCCrypto_aesDecrypt_zlibInflateP9lua_State");
	if (!sym) return;
	const tolstring = new NativeFunction(mod.findExportByName("lua_tolstring"),
		"pointer", ["pointer", "int", "pointer"]);
	const gettop = new NativeFunction(mod.findExportByName("lua_gettop"),
		"int", ["pointer"]);
	Interceptor.attach(sym, {
		onEnter(args) {
			const L = args[0];
			const top = gettop(L);
			if (top < 3) return;
			const lenp = Memory.alloc(8);
			const p = tolstring(L, 3, lenp);
			if (!p || p.isNull()) return;
			const len = lenp.readU64().toNumber();
			if (len !== 48) return;
			let s = "";
			for (let k = 0; k < len; k++) {
				const c = p.add(k).readU8();
				if (c < 0x20 || c > 0x7e) return;
				s += String.fromCharCode(c);
			}
			send({ key: s });
		},
	});
}
waitMod(start);
"""


def adb(*args, **kw):
    return subprocess.run(["adb", "-s", ADB_DEV] + list(args), **kw)


def push_frida():
    """Download + push frida-server matching the installed frida python."""
    import frida

    ver = frida.__version__
    name = "frida-server-%s-android-arm64" % ver
    here = os.path.dirname(os.path.abspath(__file__))
    xz = os.path.join(here, name + ".xz")
    if not os.path.exists(xz):
        url = ("https://github.com/frida/frida/releases/download/%s/%s.xz"
               % (ver, name))
        print("unduh", url)
        subprocess.run(["curl", "-sL", "--max-time", "180", "-o", xz, url], check=True)
    if not os.path.exists(os.path.join(here, "frida-server")):
        subprocess.run(["xz", "-dc", xz], stdout=open(os.path.join(here, "frida-server"), "wb"), check=True)
    adb("push", os.path.join(here, "frida-server"), "/data/local/tmp/frida-server")
    adb("shell", "chmod 755 /data/local/tmp/frida-server")
    adb("shell", "pkill -f frida-server || true")
    adb("shell", "setsid /data/local/tmp/frida-server -l 0.0.0.0:%d "
        ">/data/local/tmp/frida.log 2>&1 < /dev/null &" % FRIDA_PORT)
    time.sleep(3)
    adb("forward", "tcp:%d" % FRIDA_PORT, "tcp:%d" % FRIDA_PORT)
    print("frida-server siap di port", FRIDA_PORT)


def capture(timeout=60):
    import frida

    adb("forward", "tcp:%d" % FRIDA_PORT, "tcp:%d" % FRIDA_PORT)
    dev = frida.get_device_manager().add_remote_device("127.0.0.1:%d" % FRIDA_PORT)
    pid = dev.spawn([PKG])
    print("spawn pid", pid)
    session = dev.attach(pid)
    script = session.create_script(HOOK)
    got = {}

    def on_message(msg, data):
        if msg.get("type") == "send" and "key" in msg["payload"]:
            got["key"] = msg["payload"]["key"]
            print("kunci ditemukan")

    script.on("message", on_message)
    script.load()
    dev.resume(pid)
    deadline = time.time() + timeout
    while time.time() < deadline and "key" not in got:
        time.sleep(0.5)
    return got.get("key")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--push-frida", action="store_true",
                    help="unduh & jalankan frida-server di device")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    if args.push_frida:
        push_frida()

    key = capture(args.timeout)
    if not key:
        print("gagal menangkap kunci (game tidak sempat memuat aset?)", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"key": key, "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "package": PKG, "version": "1.1.704"},
              open(OUT, "w", encoding="utf-8"), indent=1)
    print("disimpan ke", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
