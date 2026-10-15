// Live2D Cubism support for the viewer.
//
// DotAbyss ships Cubism 4 models (.moc3 + textures) with no .model3.json, so
// the viewer receives a folder of loose files and has to work out the texture
// order itself — see orderTextures() below.
import { Live2DModel } from "pixi-live2d-display/cubism4";
import { Ticker } from "pixi.js";

// The plugin drives model updates from a ticker it looks up globally.
if (typeof window !== "undefined") {
	window.PIXI = window.PIXI || {};
	window.PIXI.Ticker = Ticker;
}

/** True when a model folder looks like a Cubism model. */
export function isLive2D(model) {
	if (model?.format === "live2d") return true;
	const f = String(model?.skeletonFile || "").toLowerCase();
	return f.endsWith(".moc3") || f.endsWith(".model3.json");
}

/**
 * Ask the moc3 which texture indices it actually uses, then order the supplied
 * textures to match.
 *
 * The prefab bundle also contains a mask texture (GrabMask) that is NOT an
 * atlas. Including it — or getting the order wrong — loads without error but
 * renders the character as a pile of scattered polygons, so this is not
 * cosmetic: it is the difference between a model and garbage.
 */
function orderTextures(coreModel, textureUrls) {
	const usage = new Map();
	let count = 0;
	try {
		count = coreModel.getDrawableCount();
	} catch {
		return textureUrls;
	}
	for (let i = 0; i < count; i++) {
		let idx;
		try {
			idx = coreModel.getDrawableTextureIndex(i);
		} catch {
			continue;
		}
		usage.set(idx, (usage.get(idx) || 0) + 1);
	}
	// Texture index 0 is the first atlas, 1 the second, and so on. Sort
	// numerically — NOT by how many drawables reference each, which would
	// silently swap two atlases whenever the second happened to be denser.
	const indices = [...usage.keys()].sort((a, b) => a - b);
	if (!indices.length) return textureUrls;

	// Prefer files whose names contain the index ("texture_01.png" -> 1).
	// Require the strict texture_<n> form: prefabs also carry effect sprites
	// like "TX_E_Circle005.png", whose trailing digits would otherwise be
	// mistaken for a texture index and collide with a real atlas.
	const byIndex = new Map();
	for (const url of textureUrls) {
		const m = String(url).match(/texture_0*(\d+)(?=\.\w+$)/);
		if (m) byIndex.set(Number(m[1]), url);
	}
	const ordered = [];
	const used = new Set();
	for (const i of indices) {
		const hit = byIndex.get(i);
		if (hit) {
			ordered.push(hit);
			used.add(hit);
		}
	}
	// Anything we could not match by index keeps its original relative order.
	for (const url of textureUrls) if (!used.has(url)) ordered.push(url);
	return ordered;
}

/**
 * Load a Cubism model from a folder.
 * Resolves to { model, dispose }.
 */
export async function loadLive2D({ base, mocFile, textureFiles, motionFiles, expressionFiles, physicsFile, onProgress }) {
	const mocUrl = base + encodeURIComponent(mocFile);

	// The game never ships a .model3.json, so build the settings ourselves.
	// `url` is required by the plugin for resolving relative texture paths.
	const settings = {
		url: base + "model3.json",
		Version: 3,
		FileReferences: {
			Moc: mocUrl,
			Textures: textureFiles.map((t) => base + encodeURIComponent(t)),
		},
		// Declaring the EyeBlink group is what makes the plugin create its
		// auto-blink manager (idle blinking + occasional double-blink). The ids
		// are the Cubism standard; a model without them simply ignores the setter.
		Groups: [{ Name: "EyeBlink", Ids: ["ParamEyeLOpen", "ParamEyeROpen"] }],
		HitAreas: [],
	};

	// Physics (hair/clothes sway) is only loaded when the settings point at a
	// file; the plugin then evaluates it every frame. Without this the model
	// looks like a stiff poster even though a physics3.json ships next to it.
	if (physicsFile) {
		settings.FileReferences.Physics = base + encodeURIComponent(physicsFile);
	}

	// Register the expression set. Cubism only creates its ExpressionManager
	// when Expressions are declared up front, so without this the Skin dropdown
	// can never drive anything. Files sit in expressions/<name>.exp3.json.
	if (expressionFiles && expressionFiles.length) {
		settings.FileReferences.Expressions = expressionFiles.map((n) => ({
			Name: n,
			File: base + "expressions/" + encodeURIComponent(n) + ".exp3.json",
		}));
	}

	// The shipped build has no .motion3.json either; we synthesise them from
	// the Unity fade-assets. Registering them under Motions makes them
	// playable through the standard Cubism motion manager.
	if (motionFiles && motionFiles.length) {
		settings.FileReferences.Motions = {
			idle: motionFiles.map((f, i) => ({
				File: base + "motions/" + encodeURIComponent(f),
				// Motion3 has no "Weight"; Fade times keep blends smooth.
				FadeInTime: 0.5,
				FadeOutTime: 0.5,
			})),
		};
	}

	let model;
	try {
		model = await Live2DModel.from(settings, {
			autoInteract: false,
			autoHitTest: false,
			autoFocus: false,
		});
	} catch (err) {
		throw new Error(`Gagal memuat model Live2D: ${err?.message || err}`);
	}

	// Re-order textures to match what the moc3 indexes, then reload if it
	// differs from our first guess.
	const core = model.internalModel?.coreModel;
	if (core && textureFiles.length > 1) {
		const urls = textureFiles.map((t) => base + encodeURIComponent(t));
		const ordered = orderTextures(core, urls);
		const same = ordered.length === urls.length && ordered.every((u, i) => u === urls[i]);
		if (!same) {
			try {
				await model.internalModel?.textureManager?.release?.();
			} catch {
				/* best effort */
			}
			model.destroy?.();
			settings.FileReferences.Textures = ordered;
			model = await Live2DModel.from(settings, {
				autoInteract: false,
				autoHitTest: false,
				autoFocus: false,
			});
		}
	}

	// Parts default to opacity 0 because the game drives visibility through
	// AnimationClips we do not reconstruct. Force them visible for a static view.
	forcePartsVisible(model);

	// InternalModel.destroy() (pixi-live2d-display) is NOT idempotent — it calls
	// this.motionManager.destroy() and only THEN nulls motionManager, so a
	// SECOND destroy of the same model throws "Cannot read properties of
	// undefined (reading 'destroy')". Make disposal single-shot here, and skip a
	// model that never finished loading (internalModel is undefined until the
	// "modelLoaded" event and the plugin's destroy() dereferences it blindly).
	let disposed = false;
	return {
		model,
		dispose() {
			if (disposed) return;
			disposed = true;
			try {
				if (model?.internalModel) model.destroy?.();
			} catch {
				/* already gone / half-built */
			}
		},
	};
}

/** Set every part to full opacity so the whole character is visible. */
export function forcePartsVisible(model) {
	const core = model?.internalModel?.coreModel;
	if (!core || typeof core.getPartCount !== "function") return 0;
	let n = 0;
	for (let i = 0; i < core.getPartCount(); i++) {
		try {
			core.setPartOpacityByIndex(i, 1);
			n++;
		} catch {
			/* ignore parts we cannot set */
		}
	}
	try {
		model.update(16.67);
	} catch {
		/* ignore */
	}
	return n;
}

/**
 * Play one of the synthesised motions by name.
 * Returns false when this model has no motions, so callers can fall back.
 */
export function playLive2DMotion(model, name) {
	const mm = model?.internalModel?.motionManager;
	if (!mm || typeof mm.startMotion !== "function" || !name) return false;
	// Motion definitions live under one group ("idle"); each def's file is a
	// full URL held in `File` (capital F — the Cubism MotionDef shape), with
	// `file`/`fileName` fallbacks for other builds. Match the basename's stem
	// so "idle" hits idle.motion3.json but NOT idle2.motion3.json.
	const stemOf = (d) => String(d?.File || d?.file || d?.fileName || d?.name || "")
		.split("/").pop().replace(/\.motion3\.json$/i, "");
	const groups = mm.definitions || {};
	for (const g of Object.keys(groups)) {
		const list = groups[g] || [];
		const idx = list.findIndex((d) => stemOf(d) === name);
		if (idx >= 0) {
			try {
				mm.startMotion(g, idx);
				return true;
			} catch {
				/* fall through to any other group */
			}
		}
	}
	return false;
}

/**
 * Apply a Cubism expression by name.
 *
 * Cubism models have no Spine "skins"; what users want from the Skin dropdown
 * on these models is the expression set (exp1/exp2/…). Returns false when the
 * model has no expressions so callers can fall back.
 */
export function setLive2DExpression(model, name) {
	const em = model?.internalModel?.motionManager?.expressionManager;
	if (!em || !name) return false;
	try {
		em.setExpression(name);
		return true;
	} catch {
		return false;
	}
}

/** Expression names from the loaded model's settings. */
export function live2DExpressions(model, fallback) {
	const em = model?.internalModel?.motionManager?.expressionManager;
	const defs = em?.definitions || em?._definitions;
	if (Array.isArray(defs) && defs.length) {
		return defs.map((d) => d?.Name || d?.name).filter(Boolean);
	}
	const list = model?.internalModel?.settings?.expressions;
	if (Array.isArray(list) && list.length) {
		return list.map((e) => e?.Name || e?.name).filter(Boolean);
	}
	// The settings are synthesised in this module, so the live lookup can miss;
	// fall back to what the server listed for this model's folder.
	if (Array.isArray(fallback) && fallback.length) {
		return fallback.filter((n) => n && n !== "(diam)");
	}
	return [];
}

/**
 * Turn the model's built-in "living" effects on or off.
 *
 *  - eyeBlink — auto blink (only exists when the EyeBlink group was declared).
 *  - physics  — hair/cloth sway (only exists when a physics3.json was loaded).
 *  - breath   — head/shoulder natural sway + chest breath.
 *
 * The plugin's per-frame `update()` calls these via optional chaining and does
 * NOT check any enable flag, so "off" means detaching the operator (null) while
 * keeping the original to restore. Returns which effects this model actually has.
 */
export function setLive2DLive(model, on) {
	const im = model?.internalModel;
	if (!im) return { eyeBlink: false, physics: false, breath: false };
	const have = {
		eyeBlink: !!(im.eyeBlink || im._savedEyeBlink),
		physics: !!(im.physics || im._savedPhysics),
		breath: !!(im.breath || im._savedBreath),
	};
	const detach = (key) => {
		if (im[key]) {
			im["_saved" + key[0].toUpperCase() + key.slice(1)] = im[key];
			im[key] = null;
		}
	};
	const restore = (key) => {
		const saved = "_saved" + key[0].toUpperCase() + key.slice(1);
		if (im[saved] !== undefined && im[saved] !== null) {
			im[key] = im[saved];
			im[saved] = undefined;
		}
	};
	for (const key of ["eyeBlink", "physics", "breath"]) {
		if (on) restore(key);
		else detach(key);
	}
	return have;
}

/**
 * Group the model's motion names into categories so a 30–140 entry dropdown
 * stays usable. Purely name-based and game-agnostic:
 *   touch_*  -> "Sentuhan"   idle* -> "Diam"     main_* -> "Utama"   drag -> ...
 *   home/login/mail/mission/wedding/effect/... -> its own category
 * Anything unrecognised falls into "Lain". Returns [{ label, names }], in a
 * sensible display order, and [] when there are no motions.
 */
export function live2DMotionGroups(model, names) {
	const list = Array.isArray(names) ? names.filter(Boolean) : [];
	if (!list.length) return [];

	const CATS = [
		["idle", "Diam", (n) => /^idle/i.test(n) || /^change_?idle/i.test(n)],
		["touch", "Sentuhan", (n) => /^(touch|tap)/i.test(n)],
		["drag", "Geser", (n) => /drag/i.test(n)],
		["main", "Utama", (n) => /^main/i.test(n)],
		["special", "Spesial", (n) => /^(wedding|special|login|home|complete|mission|mail|effect|win|lose)/i.test(n)],
	];
	const used = new Set();
	const out = [];
	for (const [key, label, test] of CATS) {
		const hit = list.filter((n) => !used.has(n) && test(n));
		hit.forEach((n) => used.add(n));
		if (hit.length) out.push({ key, label, names: hit });
	}
	const rest = list.filter((n) => !used.has(n));
	if (rest.length) out.push({ key: "other", label: "Lain", names: rest });
	return out;
}

/** True once the model's currently-playing motion has run to the end. */
export function live2DMotionFinished(model) {
	const mm = model?.internalModel?.motionManager;
	if (!mm || typeof mm.isFinished !== "function") return false;
	try {
		return mm.isFinished();
	} catch {
		return false;
	}
}

/** The motion queue entry currently playing (or null). */
function live2DEntry(model) {
	const mm = model?.internalModel?.motionManager;
	const q = mm?.queueManager?._motions;
	return Array.isArray(q) ? q.find(Boolean) : null;
}

/**
 * Playback position (seconds) of the Cubism motion on stage.
 *
 * The Cubism motion manager has no getter for this: an entry stores only its
 * start time (`_startTimeSeconds`, in the SAME second-scale as performance.now()
 * divided by 1000), so the elapsed position is the difference. That is also how
 * the plugin decides the current frame — which makes seeking trivial (below).
 * Returns null when nothing is playing.
 */
export function live2DMotionTime(model) {
	const e = live2DEntry(model);
	if (!e || typeof e._startTimeSeconds !== "number") return null;
	return performance.now() / 1000 - e._startTimeSeconds;
}

/** Length (seconds) of the motion on stage — its loop length, else 0. */
export function live2DMotionDuration(model) {
	const e = live2DEntry(model);
	const m = e?._motion;
	if (!m) return 0;
	let d = typeof m.getLoopDuration === "function" ? m.getLoopDuration() : m._loopDurationSeconds;
	if (!(typeof d === "number" && d > 0)) d = typeof m.getDuration === "function" ? m.getDuration() : 0;
	return typeof d === "number" && d > 0 ? d : 0;
}

/** Seek the playing motion to `t` seconds by shifting its start time. */
export function live2DSeekMotion(model, t) {
	const e = live2DEntry(model);
	if (!e || typeof e._startTimeSeconds !== "number") return false;
	e._startTimeSeconds = performance.now() / 1000 - Math.max(0, t);
	return true;
}

/** True while a motion is still playing (so auto-advance can wait its turn). */
export function live2DMotionBusy(model) {
	const mm = model?.internalModel?.motionManager;
	if (!mm || typeof mm.isFinishedByHandle !== "function") return false;
	try {
		return !mm.isFinished();
	} catch {
		return false;
	}
}

/** Cubism models have no Spine animations; expose a single idle entry. */
export function live2DAnimations() {
	return ["idle"];
}
