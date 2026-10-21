// Ask ws-scrcpy's own ADB stack (adbkit) what it sees.
// The web UI showed "State: offline" for 127.0.0.1:5555 while the host `adb`
// also reported offline — but adbd IS running inside the container and the port
// IS open. adbkit talks a different code path, so it can disambiguate
// "adbd refusing us" from "ws-scrcpy can't reach it".
const Adb = require("/srv/redroid/ws-scrcpy/node_modules/@dead50f7/adbkit/lib/adb");
const client = Adb.createClient({ host: "127.0.0.1", port: 5037 });

(async () => {
  // First make sure the ADB server has the device registered.
  const { spawn } = require("child_process");
  await new Promise((r) => {
    const p = spawn("/usr/bin/adb", ["connect", "127.0.0.1:5555"]);
    p.on("close", r);
    setTimeout(r, 15000);
  });

  try {
    const devices = await client.listDevices();
    console.log("adbkit devices:", JSON.stringify(devices));
  } catch (e) {
    console.log("listDevices error:", e.message.slice(0, 200));
  }

  for (const id of ["127.0.0.1:5555", "emulator-5554"]) {
    try {
      const t = await client.getDevice(id);
      const out = await t.shell("getprop ro.build.version.release").then(Adb.util.readAll);
      console.log(`${id}: getprop -> ${out.toString().trim()}`);
    } catch (e) {
      console.log(`${id}: ERR ${e.message.slice(0, 120)}`);
    }
  }
  process.exit(0);
})();
