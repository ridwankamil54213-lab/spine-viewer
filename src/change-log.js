"use strict";

/**
 * Change log per game: tanggal + model yang baru masuk/berubah.
 *
 * Dua sumber:
 *  1. SEED (satu kali, saat file belum ada): data/new-models.json `flagged`
 *     mencatat kapan tiap model pertama kali terdeteksi. Itu memberi riwayat
 *     awal pemulihan pustaka dari GDrive tanpa perlu menunggu apply baru.
 *  2. APPLY: setiap /api/update/:game?mode=apply yang sukses mencatat diff
 *     himpunan id model sebelum dan sesudah apply, plus versi pembaru dan
 *     status upload GDrive. Ini yang benar-benar menjawab "model baru apa
 *     yang masuk hari ini".
 *
 * File data/change-logs.json sengaja di luar git (runtime state). Daftar id
 * per entri dibatasi MAX_IDS supaya entri restore berisi 44 ribu model tidak
 * membengkak; jumlah penuh tetap disimpan di addedCount.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const FILE = process.env.CHANGE_LOG_FILE || path.join(ROOT, "data", "change-logs.json");
const NEW_FILE = process.env.NEW_MODELS_FILE || path.join(ROOT, "data", "new-models.json");
const MAX_ENTRIES = 60;
const MAX_IDS = 40;

let db = null;

function save() {
	const tmp = FILE + ".tmp";
	fs.mkdirSync(path.dirname(FILE), { recursive: true });
	fs.writeFileSync(tmp, JSON.stringify(db, null, 1), "utf8");
	fs.renameSync(tmp, FILE);
}

function seedFromFlagged() {
	let flagged = {};
	try {
		flagged = JSON.parse(fs.readFileSync(NEW_FILE, "utf8")).flagged || {};
	} catch {
		return;
	}
	// game|YYYY-MM-DD -> { game, at, ids (sampel), count }
	const groups = new Map();
	for (const [id, ts] of Object.entries(flagged)) {
		if (typeof ts !== "number" || !Number.isFinite(ts)) continue;
		const game = String(id).split("/")[0];
		if (!game) continue;
		const day = new Date(ts).toISOString().slice(0, 10);
		const key = `${game}|${day}`;
		let g = groups.get(key);
		if (!g) {
			g = { game, at: ts, ids: [], count: 0 };
			groups.set(key, g);
		}
		g.count += 1;
		if (g.ids.length < MAX_IDS) g.ids.push(id);
		if (ts > g.at) g.at = ts;
	}
	for (const g of groups.values()) {
		const list = db.games[g.game] || (db.games[g.game] = []);
		list.push({
			at: new Date(g.at).toISOString(),
			kind: "restore",
			version: null,
			added: g.ids,
			addedCount: g.count,
			removed: [],
			removedCount: 0,
			reportedNew: null,
			gdrive: null,
			diffAvailable: true,
		});
	}
	db.seededFrom = "new-models.json/flagged";
}

function ensure() {
	if (db) return db;
	try {
		const raw = JSON.parse(fs.readFileSync(FILE, "utf8"));
		if (raw && raw.games && typeof raw.games === "object") {
			db = { version: 1, games: raw.games, seededFrom: raw.seededFrom || null };
			return db;
		}
	} catch {
		/* file belum ada / rusak -> seed ulang */
	}
	db = { version: 1, games: {}, seededFrom: null };
	seedFromFlagged();
	save();
	return db;
}

/** Catat satu apply yang sukses. Tidak pernah melempar ke caller. */
function recordApply({ game, beforeIds, afterIds, result = {}, gdrive = null }) {
	const d = ensure();
	let added = [];
	let removed = [];
	const diffAvailable = beforeIds instanceof Set && afterIds instanceof Set;
	if (diffAvailable) {
		added = [...afterIds].filter((id) => !beforeIds.has(id));
		removed = [...beforeIds].filter((id) => !afterIds.has(id));
	}
	const entry = {
		at: new Date().toISOString(),
		kind: "apply",
		version: result?.version ?? null,
		added: added.slice(0, MAX_IDS),
		addedCount: added.length,
		removed: removed.slice(0, MAX_IDS),
		removedCount: removed.length,
		reportedNew: Number.isFinite(result?.new) ? result.new : null,
		gdrive: gdrive && typeof gdrive.ok === "boolean" ? gdrive.ok : null,
		diffAvailable,
	};
	const list = d.games[game] || (d.games[game] = []);
	list.unshift(entry);
	if (list.length > MAX_ENTRIES) list.length = MAX_ENTRIES;
	save();
	return entry;
}

function summary() {
	const d = ensure();
	return Object.entries(d.games)
		.map(([game, entries]) => ({
			game,
			count: entries.length,
			lastAt: entries[0]?.at || null,
			lastKind: entries[0]?.kind || null,
			newModels: entries.reduce((n, e) => n + (e.addedCount || 0), 0),
		}))
		.sort((a, b) => String(b.lastAt || "").localeCompare(String(a.lastAt || "")));
}

function forGame(game) {
	const d = ensure();
	return [...(d.games[game] || [])]
		.sort((a, b) => String(b.at).localeCompare(String(a.at)));
}

module.exports = { recordApply, summary, forGame, FILE, MAX_IDS };
