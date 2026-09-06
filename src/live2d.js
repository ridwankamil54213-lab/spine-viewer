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
export async function loadLive2D({ base, mocFile, textureFiles, motionFiles, onProgress }) {
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
		Groups: [],
		HitAreas: [],
	};

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

	return {
		model,
		dispose() {
			try {
				model.destroy?.();
			} catch {
				/* already gone */
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
	// Motion groups are keyed by the group name used when loading; "idle" is
	// what loadLive2D() registers everything under.
	const groups = mm.definitions || {};
	for (const g of Object.keys(groups)) {
		const list = groups[g] || [];
		const idx = list.findIndex((d) => (d?.name || d?.fileName || "").includes(name));
		if (idx >= 0) {
			mm.startMotion(g, idx);
			return true;
		}
	}
	return false;
}

/** Cubism models have no Spine animations; expose a single idle entry. */
export function live2DAnimations() {
	return ["idle"];
}
