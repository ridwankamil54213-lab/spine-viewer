import { Application, Container, Graphics, Assets, BaseTexture, Texture, RenderTexture, Rectangle, SCALE_MODES, MIPMAP_MODES, WRAP_MODES, ALPHA_MODES, BLEND_MODES } from "pixi.js";
import { Spine, SkeletonBounds, TextureAtlas } from "pixi-spine";
import { AtlasAttachmentLoader as AtlasAttachmentLoader41 } from "@pixi-spine/runtime-4.1";
import * as runtime38 from "@pixi-spine/runtime-3.8";
import * as runtime40 from "@pixi-spine/runtime-4.0";
import * as runtime41 from "@pixi-spine/runtime-4.1";
// Spine 4.2 needs a whole matching stack — pixi-spine's `Spine` hard-codes
// 3.7/3.8/4.0/4.1 and throws "Cant detect version of spine model 4.2.35"
// (then `null.Skeleton`) for anything newer. So 4.2 models are rendered by the
// official renderer pinned to the same 4.2.120 release as the parser.
//
// IMPORTANT: everything 4.2 must come from THIS ONE package.
// spine-pixi-v7-42 bundles its own nested spine-core, and its renderMeshes()
// dispatches with `attachment instanceof RegionAttachment`. Data parsed by a
// DIFFERENT copy of spine-core fails that check, so every slot is skipped and
// the model draws absolutely nothing — no error, zero draw calls.
// The package re-exports the whole core surface, so take all of it from here.
import {
	Spine as Spine42,
	SpineTexture as SpineTexture42,
	SkeletonBinary as SkeletonBinary42,
	SkeletonJson as SkeletonJson42,
	TextureAtlas as TextureAtlas42,
	AtlasAttachmentLoader as AtlasAttachmentLoader42,
} from "spine-pixi-v7-42";
import * as runtime42 from "spine-pixi-v7-42";
import { loadTextures } from "@pixi/assets";
import {
	detectSpineVersion,
	pickRuntime,
} from "./spine-version.js";
import { isLive2D, loadLive2D, live2DAnimations, playLive2DMotion } from "./live2d.js";
import { normalizeSpine2Json } from "./spine2-normalize.js";
import {
	loadSpine21Model,
	drawSpine21,
	advanceSpine21,
	spine21TrackTime,
	setSpine21Animation,
} from "./spine21-stage.js";

/* Pixi v7's loadTextures decodes via createImageBitmap(blob) with no options, so
 * the browser premultiplies alpha at decode time; alphaMode=UNPACK would then
 * premultiply AGAIN on upload. Disabling that path keeps alphaMode authoritative. */
loadTextures.config.preferCreateImageBitmap = false;
loadTextures.config.preferWorkers = false;

/**
 * PMA (premultiplied alpha) control
 *
 * Spine atlases come in two flavours: `pma: true` (colour channels already
 * multiplied by alpha) and plain (straight/unassociated alpha). Rendering a PMA
 * atlas as straight alpha — or vice versa — produces dark halos at the edges and
 * seams where attachments overlap, because the blend equation and the texture
 * data disagree about whether alpha has already been applied.
 *
 * Auto   → follow the atlas's own `pma:` flag (correct in almost every case)
 * On     → force PMA upload + PMA blend
 * Off    → force straight alpha upload + NPM blend
 * Upload → premultiply ON UPLOAD (UNPACK) + NPM blend. This is the fix for
 *          atlases whose transparent texels carry stale colour (white) while
 *          the visible pixels are straight alpha: "On" blends them as if the
 *          colours were already premultiplied, so hidden texels leak as white
 *          patches; "Off" leaves them straight so the transparent texels are
 *          sampled as-white AND drawn additively. UNPACK premultiplies each
 *          texel against its own alpha as it is uploaded, so an alpha-0 texel
 *          becomes black and contributes nothing. That matches what a GPU is
 *          supposed to do with an RGBA format that has no premultiply built in.
 *
 * alphaMode and blendMode are two halves of the same switch: both must flip
 * together or the seams stay.
 *
 * Some atlases ship without a `pma:` flag even though their pixels behave one
 * way or the other, so "auto" can only follow what the file declares. When the
 * user overrides a model, remember it (localStorage) so the choice sticks
 * across reloads and applies to whichever model it was made on.
 */
const PMA_MODES = { auto: "auto", on: "on", off: "off", upload: "upload" };
let pmaMode = PMA_MODES.auto;
let atlasSaysPMA = false;
/**
 * Game-level PMA assumption, used only when the atlas carries no `pma:` line.
 * Some games (Alliance Sages) ship premultiplied textures without declaring
 * it, so trusting the absent flag alone would leave dark fringes everywhere.
 */
let gamePmaDefault = false;

const PMA_STORE_KEY = "spine-stage:pma-overrides";

function loadOverrides() {
	try {
		return JSON.parse(localStorage.getItem(PMA_STORE_KEY)) || {};
	} catch {
		return {};
	}
}

function saveOverride(id, mode) {
	try {
		const all = loadOverrides();
		if (mode === PMA_MODES.auto) delete all[id];
		else all[id] = mode;
		localStorage.setItem(PMA_STORE_KEY, JSON.stringify(all));
	} catch {
		/* storage unavailable (private mode) — preference just won't persist */
	}
}

/** Reset the selector to "auto", or to this model's saved override. */
function syncPmaToModel(id) {
	const saved = id ? loadOverrides()[id] : null;
	pmaMode = saved || PMA_MODES.auto;
}

/** Is PMA in effect right now, given the atlas flag and the user's override? */
function declaredPMA() {
	// A page's `pma` is null when the atlas has no `pma:` line, false when it
	// explicitly says "pma: false". Only an explicit declaration is trusted;
	// otherwise fall back to the game's default.
	const flags = ([]).concat(
		...(current?.atlasPagesFlags || []).length
			? [current.atlasPagesFlags]
			: []
	);
	const explicit = flags.filter((f) => f === true || f === false);
	if (explicit.length) return explicit.some((f) => f === true);
	return gamePmaDefault;
}

/** Where the Auto decision came from: the atlas flag, or the game default. */
function pmaSource() {
	if (pmaMode === PMA_MODES.on) return "forced-on";
	if (pmaMode === PMA_MODES.off) return "forced-off";
	if (pmaMode === PMA_MODES.upload) return "forced-upload";
	const flags = current?.atlasPagesFlags || [];
	if (flags.some((f) => f === true || f === false)) return "atlas";
	return gamePmaDefault ? "game-default" : "default";
}

function pmaActive() {
	if (pmaMode === PMA_MODES.on) return true;
	if (pmaMode === PMA_MODES.off) return false;
	return declaredPMA(); // auto: atlas flag, else the game's default
}

/** The Pixi ALPHA_MODES value matching the current PMA setting. */
function currentAlphaMode() {
	// "upload" is its own thing — neither PMA nor straight. Hand Pixi a
	// straight-alpha bitmap (UNPACK means "the stored bytes are NOT
	// premultiplied") and let it premultiply during upload, with the NPM
	// blend. See the PMA_MODES comment for why this fixes white patches.
	if (pmaMode === PMA_MODES.upload) return ALPHA_MODES.UNPACK;
	return pmaActive() ? ALPHA_MODES.PMA : ALPHA_MODES.NPM;
}

/** Collect the atlas page baseTextures currently in use. */
function atlasBaseTextures() {
	const out = [];
	if (!spine) return out;
	const seen = new Set();
	const add = (bt) => {
		if (bt && !seen.has(bt.uid)) {
			seen.add(bt.uid);
			out.push(bt);
		}
	};
	for (const slot of spine.skeleton.slots) {
		const page = slot.getAttachment()?.region?.page;
		if (!page) continue;
		// pixi-spine pages expose `baseTexture` directly. The 4.2 runtime wraps
		// each page in SpineTexture, where the Pixi texture — and its
		// baseTexture — live one level deeper. Reading only `.baseTexture`
		// returned NOTHING for every 4.2 model, so applyPMA() silently iterated
		// zero textures: a `pma: true` atlas (e.g. all of CrossCore) stayed
		// uploaded as straight alpha and every sprite got a dark fringe that
		// the PMA toggle could not remove.
		add(page.baseTexture || page.texture?.texture?.baseTexture);
	}
	return out;
}

/**
 * Apply the PMA setting to the live textures AND their blend mode.
 * update() bumps dirtyStyleId, which is what makes Pixi re-upload/re-style
 * the texture — setting alphaMode alone is silently ignored.
 */
function applyPMA() {
	const alphaMode = currentAlphaMode();
	for (const bt of atlasBaseTextures()) {
		if (bt.alphaMode !== alphaMode) {
			bt.alphaMode = alphaMode;
			bt.update();
		}
	}
	if (spine) applyBlendMode();
	renderHud();
}

/** Route every slot's rendered sprite/mesh through the matching blend mode. */
function applyBlendMode() {
	if (!spine) return;
	// "upload" premultiplies the texture but still wants the straight-alpha
	// (NPM) blend, and it is not a real PMA state — keep it out of pmaActive()
	// so the HUD keeps reading it as straight.
	const pma = pmaActive() && pmaMode !== PMA_MODES.upload;

	// SlotData.blendMode holds a PIXI BLEND_MODES value (0=NORMAL, 1=ADD,
	// 2=MULTIPLY, 3=SCREEN), not a Spine index. PMA uses the standard set;
	// straight alpha uses the *_NPM set. MULTIPLY has no NPM variant.
	const NPM_FOR = new Map([
		[BLEND_MODES.NORMAL, BLEND_MODES.NORMAL_NPM],
		[BLEND_MODES.ADD, BLEND_MODES.ADD_NPM],
		[BLEND_MODES.SCREEN, BLEND_MODES.SCREEN_NPM],
	]);

	for (const slot of spine.skeleton.slots) {
		const base = slot.data.blendMode ?? BLEND_MODES.NORMAL;
		const mapped = pma ? base : NPM_FOR.get(base) ?? base;
		// SpineBase copies slot.blendMode onto the sprite/mesh every update(),
		// so assigning here persists across frames and attachment swaps.
		slot.blendMode = mapped;
		if (slot.currentSprite) slot.currentSprite.blendMode = mapped;
		if (slot.currentMesh) slot.currentMesh.blendMode = mapped;
	}
}

const $ = (sel) => document.querySelector(sel);

const el = {
	canvasWrap: $("#canvas-wrap"),
	hud: $("#hud"),
	empty: $("#empty"),
	list: $("#model-list"),
	search: $("#search"),
	count: $("#model-count"),
	gameList: $("#game-list"),
	modelView: $("#model-view"),
	backBtn: $("#back-btn"),
	libHeading: $("#lib-heading"),
	libSub: $("#lib-sub"),
	pager: $("#pager"),
	sidebar: $("#sidebar"),
	sidebarToggle: $("#sidebar-toggle"),

	// favorites
	favFilter: $("#fav-filter"),
	favCount: $("#fav-count"),

	animSelect: $("#anim-select"),
	skinSelect: $("#skin-select"),
	variantSelect: $("#variant-select"),
	variantWrap: $("#variant-wrap"),

	// timeline
	timeline: $("#timeline"),
	timelineBtn: $("#timeline-btn"),
	tlName: $("#tl-name"),
	tlMeta: $("#tl-meta"),
	tlTrack: $("#tl-track"),
	tlRuler: $("#tl-ruler"),
	tlKeys: $("#tl-keys"),
	tlPlayhead: $("#tl-playhead"),
	tlBone: $("#tl-bone"),
	tlProp: $("#tl-prop"),
	tlPrev: $("#tl-prev"),
	tlNext: $("#tl-next"),
	tlPos: $("#tl-pos"),
	tlEventsOnly: $("#tl-events-only"),

	// inspector
	inspector: $("#inspector"),
	inspectorBtn: $("#inspector-btn"),
	inspectorClose: $("#inspector-close"),
	slotList: $("#slot-list"),
	slotSearch: $("#slot-search"),
	slotSkin: $("#slot-skin"),
	slotCount: $("#slot-count"),
	cmpA: $("#cmp-a"),
	cmpB: $("#cmp-b"),
	cmpRun: $("#cmp-run"),
	cmpResult: $("#cmp-result"),
	playBtn: $("#play-btn"),
	prevBtn: $("#prev-btn"),
	nextBtn: $("#next-btn"),
	flipBtn: $("#flip-btn"),
	loopBtn: $("#loop-btn"),
	audioBtn: $("#audio-btn"),
	audioAutoBtn: $("#audio-auto-btn"),

	scrub: $("#scrub"),
	timeCur: $("#time-cur"),
	timeDur: $("#time-dur"),
	rateSelect: $("#rate-select"),

	zoomIn: $("#zoom-in"),
	zoomOut: $("#zoom-out"),
	zoomReset: $("#zoom-reset"),
	zoomLabel: $("#zoom-label"),
	fullscreenBtn: $("#fullscreen-btn"),
	exportBtn: $("#export-btn"),
	exportPng: $("#export-png"),
	exportPngNote: $("#export-png-note"),
	exportModal: $("#export-modal"),
	exportClose: $("#export-close"),
	exportCancel: $("#export-cancel"),
	exportRun: $("#export-run"),
	exportFormat: $("#export-format"),
	exportBg: $("#export-bg"),
	exportSize: $("#export-size"),
	exportFps: $("#export-fps"),
	exportNote: $("#export-note"),
	exportProgress: $("#export-progress"),
	exportBarFill: $("#export-bar-fill"),
	exportProgressText: $("#export-progress-text"),
	exportResult: $("#export-result"),
	exportDownload: $("#export-download"),
	exportMeta: $("#export-meta"),
	gridBtn: $("#grid-btn"),
	bonesBtn: $("#bones-btn"),
	partsBtn: $("#parts-btn"),
	pmaSelect: $("#pma-select"),

	// FPS meter
	fpsBtn: $("#fps-btn"),
	fpsMeter: $("#fps-meter"),
	fpsValue: $("#fps-value"),
	fpsMin: $("#fps-min"),
	fpsAvg: $("#fps-avg"),
	fpsGraph: $("#fps-graph"),
	fpsReset: $("#fps-reset"),

	error: $("#error"),
	loading: $("#loading"),
	grid: $("#grid"),
	stageBg: $("#stage-bg"),
	bgBtn: $("#bg-btn"),
	bgSelect: $("#bg-select"),
	toast: $("#toast"),
	drop: $("#drop"),
	file: $("#file"),
	folder: $("#folder"),
	uploadBtn: $("#upload-btn"),
	delBtn: $("#del-btn"),
};

/* ------------------------------------------------------------------ *
 * Pixi bootstrap
 * ------------------------------------------------------------------ */
const app = new Application({
	backgroundAlpha: 0,
	antialias: true,
	resolution: Math.min(window.devicePixelRatio || 1, 2),
	autoDensity: true,
	powerPreference: "high-performance",
});
el.canvasWrap.appendChild(app.view);

const world = new Container();
const stageRoot = new Container();
world.addChild(stageRoot);
app.stage.addChild(world);

let spine = null;
let current = null;
let animName = null;
let duration = 0;
/** Tears down the previous Cubism model (Live2DModel needs its own cleanup). */
let live2dDispose = null;
/** Cached centring offset for the current Cubism model (see fitModel). */
let live2dCentre = null;

const state = {
	playing: true,
	loop: true,
	rate: 1,
	flip: false,
	zoom: 1,
	panX: 0,
	panY: 0,
	showBones: false,
	showGrid: true,
	bg: "dark",
	scrubbing: false,
	trackTime: 0,
};

/**
 * Negara renderer Spine 2.1.
 *
 * Terpisah dari `spine` (model pixi-spine) karena kedua jalur tidak bisa
 * hidup di scene graph yang sama: spine.js 2.1 tidak mengerti Pixi, jadi ia
 * digambar ke kanvas 2D sendiri — bukan ke app.stage.
 */
const spine21 = {
	state: null,      // hasil loadSpine21Model
	active: false,
	canvas: null,
	ctx: null,
	rafId: 0,
	lastTime: 0,
	time: 0,
};

/* ------------------------------------------------------------------ *
 * Bones overlay
 * ------------------------------------------------------------------ */
const bonesGfx = new Graphics();
bonesGfx.visible = false;
stageRoot.addChild(bonesGfx);

function drawBones() {
	bonesGfx.clear();
	if (!spine || !state.showBones) return;
	const s = 1 / state.zoom;
	bonesGfx.lineStyle(2 * s, 0xff8a5c, 0.95);
	for (const b of spine.skeleton.bones) {
		const len = b.data.length || 12;
		const ex = b.worldX + b.a * len;
		const ey = b.worldY + b.b * len;
		bonesGfx.moveTo(b.worldX, b.worldY);
		bonesGfx.lineTo(ex, ey);
		bonesGfx.drawCircle(b.worldX, b.worldY, 3 * s);
	}
}

/* ------------------------------------------------------------------ *
 * Render loop
 *
 * pixi-spine's SpineBase only advances the animation inside update(),
 * which runs from autoUpdateTransform(). With autoUpdate = false that
 * hook is swapped out, so we must advance the track AND call update()
 * ourselves — that keeps pause / scrub / speed fully deterministic.
 * ------------------------------------------------------------------ */
app.ticker.add(() => {
	if (!spine) return;
	// Cubism models have no AnimationState; the plugin updates them itself.
	if (!spine.state) return;
	const track = spine.state.tracks[0];
	if (!track) return;

	// One clock drives everything: advance authored seconds by the ticker
	// delta scaled by the speed control, then move the track by exactly that.
	// Reading wall-clock time here instead would keep running while paused and
	// ignore the rate, so pause/scrub/speed could each disagree about where
	// the playhead is.
	const dt = clock.tick(app.ticker.deltaMS);

	if (state.scrubbing) {
		// The user is dragging: the track follows state.trackTime, and the
		// clock follows the track so nothing else drifts away from it.
		track.trackTime = state.trackTime;
		clock.syncTo(state.trackTime);
	} else if (state.playing) {
		track.trackTime += dt;
		if (track.trackTime >= duration) {
			if (state.loop) {
				track.trackTime = track.trackTime % duration;
			} else {
				track.trackTime = duration;
				setPlaying(false);
			}
		}
		clock.syncTo(track.trackTime);
	}

	// dt = 0: we already positioned the track, this only applies + renders it.
	spine.update(0);

	updateScrubUI();
	// Keep the timeline playhead in sync, but only when it's actually on
	// screen — building ticks for a hidden panel would be wasted work.
	if (!el.timeline.hidden) updateTimelinePlayhead();
	drawBones();
	// The part overlay is posed geometry, so it has to be redrawn as the
	// skeleton moves — a static snapshot would stop matching the model.
	if (parts.on) drawParts();
});

function updateScrubUI() {
	const track = spine?.state?.tracks?.[0];
	if (!track) return;
	const t = Math.min(track.trackTime, duration);
	if (!state.scrubbing) state.trackTime = t;
	el.scrub.value = String(duration ? (t / duration) * 1000 : 0);
	el.timeCur.textContent = t.toFixed(2) + "s";
}

/* ------------------------------------------------------------------ *
 * Viewport
 * ------------------------------------------------------------------ */
function fitModel() {
	if (!spine) return;
	const w = el.canvasWrap.clientWidth;
	const h = el.canvasWrap.clientHeight;
	// Cubism models expose width/height directly and have no SkeletonData.
	// Their declared size is the canvas the artist worked on, which can be far
	// larger than the artwork itself, and their anchor is (0,0) rather than
	// Spine's (0.5,0.5). Fitting on the declared box therefore zooms out too
	// far and pushes the character off-centre, so measure what is actually
	// drawn and centre that instead.
	if (spine.skeleton && spine.skeleton.data) {
		const data = spine.skeleton.data;
		const bw = data.width || data.height || 512;
		const bh = data.height || data.width || 512;
		state.zoom = Math.min((w * 0.82) / bw, (h * 0.82) / bh);
		state.panX = 0;
		state.panY = 0;
		applyTransform();
		return;
	}

	// getBounds() is in world space, so it already includes this model's
	// position — feeding its centre back through position.set() would double
	// the offset. Reset to the origin first and read the bounds from there.
	//
	// The measured centre is also cached per model: bounds change as the pose
	// and driven parameters change, so recomputing them on every "Pas" click
	// walks the model away from where it was centred on load.
	let b = null;
	if (live2dCentre) {
		spine.position.set(live2dCentre.x, live2dCentre.y);
	} else {
		try {
			spine.position.set(0, 0);
			b = typeof spine.getLocalBounds === "function" ? spine.getLocalBounds() : spine.getBounds?.();
		} catch {
			b = null;
		}
		if (b) {
			live2dCentre = { x: -(b.x + b.width / 2), y: -(b.y + b.height / 2) };
			spine.position.set(live2dCentre.x, live2dCentre.y);
		}
	}
	// Fall back to the declared size when the artwork bounds are unavailable.
	const bw = b?.width || spine.width || 512;
	const bh = b?.height || spine.height || 512;
	state.zoom = Math.min((w * 0.82) / bw, (h * 0.82) / bh);
	state.panX = 0;
	state.panY = 0;
	applyTransform();
}

function applyTransform() {
	const w = el.canvasWrap.clientWidth;
	const h = el.canvasWrap.clientHeight;
	world.position.set(w / 2 + state.panX, h / 2 + state.panY);
	world.scale.set(state.zoom * (state.flip ? -1 : 1), state.zoom);
	// The trailing "%" is drawn by CSS (.zoom-label::after) so the number here
	// stays tabular and the box doesn't resize between "9%" and "100%".
	el.zoomLabel.textContent = String(Math.round(state.zoom * 100));
	drawBones();
}

function zoomBy(factor, cx, cy) {
	const w = el.canvasWrap.clientWidth;
	const h = el.canvasWrap.clientHeight;
	cx = cx ?? w / 2;
	cy = cy ?? h / 2;
	const bx = (cx - w / 2 - state.panX) / state.zoom;
	const by = (cy - h / 2 - state.panY) / state.zoom;
	state.zoom = Math.min(12, Math.max(0.05, state.zoom * factor));
	state.panX = cx - w / 2 - bx * state.zoom;
	state.panY = cy - h / 2 - by * state.zoom;
	applyTransform();
}

/**
 * Return a BaseTexture `factor` times larger, for atlas pages stored at a
 * lower resolution than their atlas declares. Draws the loaded texture onto a
 * canvas at the declared size and uploads that, so Spine's region coordinates
 * (which are absolute, in declared-page pixels) resolve correctly.
 */
function upscaleBaseTexture(bt, factorX, factorY = factorX) {
	try {
		const w = Math.round(bt.width * factorX);
		const h = Math.round(bt.height * factorY);
		const cv = document.createElement("canvas");
		cv.width = w;
		cv.height = h;
		const ctx = cv.getContext("2d");
		ctx.imageSmoothingEnabled = true;
		ctx.imageSmoothingQuality = "high";
		// The source is a Pixi texture; grab its underlying image if possible.
		const src = bt.resource?.source || bt.resource?.bitmap || null;
		if (src) ctx.drawImage(src, 0, 0, w, h);
		else return bt; // no drawable source — keep original
		const up = new BaseTexture(cv, {
			scaleMode: SCALE_MODES.LINEAR,
			mipmap: MIPMAP_MODES.POW2,
			wrapMode: WRAP_MODES.CLAMP,
			alphaMode: ALPHA_MODES.NPM,
		});
		return up;
	} catch {
		return bt;
	}
}

/* ------------------------------------------------------------------ *
 * Spine runtime dispatch
 * ------------------------------------------------------------------ *
 * A skeleton can only be read by a runtime that supports its Spine version,
 * and each runtime REFUSES data newer than itself. Everything used to be
 * hard-wired to 4.1, so older models (Azur Lane ships 3.8.99) failed with
 * "Spine 4.1 loader cant load version ...".
 *
 * All matching runtimes are imported eagerly. Dynamic import() looks tidier
 * but esbuild is configured with format=iife, which does not support code
 * splitting — the "chunks" never get emitted, so the dynamic paths silently
 * fell back to 4.1 at runtime (every Azur Lane model logged a 4.1 and a 4.0
 * loader error before 3.8 finally parsed it).
 */
const RUNTIME_LOADERS = {
	// 3.7 has no SkeletonBinary of its own; the 3.8 package reads it.
	"3.7": () => markRuntime(runtime38, "3.8"),
	"3.8": () => markRuntime(runtime38, "3.8"),
	"4.0": () => markRuntime(runtime40, "4.0"),
	"4.1": () => markRuntime(runtime41, "4.1"),
	// Genuine Spine 4.2. Stellar Affinity ships 4.2.35; neither 4.1 nor 4.3
	// can read that layout (see the import note above).
	"4.2": () => markRuntime(runtime42, "4.2"),
};

// `runtime42` is the namespace we fall back to for version tagging, but the
// PARSERS must be the exact classes the renderer compares against with
// `instanceof` — see the import note. Override them per-key here.
const PARSER_OVERRIDES = {
	"4.2": { SkeletonBinary: SkeletonBinary42, SkeletonJson: SkeletonJson42 },
};

/**
 * Attachment loader matching a given runtime.
 *
 * The loader and the parser MUST come from the same Spine version: a 4.1
 * AtlasAttachmentLoader handed to a 4.2 SkeletonBinary produces attachments
 * the 4.2 data model doesn't recognise. The 3.8 path already proves the
 * pattern works — its data classes feed pixi-spine's renderer fine.
 */
const ATTACHMENT_LOADERS = {
	"3.7": (atlas) => new runtime38.AtlasAttachmentLoader(atlas),
	"3.8": (atlas) => new runtime38.AtlasAttachmentLoader(atlas),
	"4.0": (atlas) => new runtime40.AtlasAttachmentLoader(atlas),
	"4.1": (atlas) => new AtlasAttachmentLoader41(atlas),
	"4.2": (atlas) => new AtlasAttachmentLoader42(atlas),
};

/** Build the attachment loader for a runtime key, defaulting to 4.1. */
function makeAttachmentLoader(key, atlas) {
	const make = ATTACHMENT_LOADERS[key] || ATTACHMENT_LOADERS["4.1"];
	return make(atlas);
}

/**
 * Instantiate the renderer for a runtime key.
 *
 * Everything except 4.2 uses pixi-spine's Spine, whose createSkeleton()
 * only knows 3.7/3.8/4.0/4.1. A 4.2 model handed to it logs "Cant detect
 * version of spine model 4.2.35" and then dies on `null.Skeleton`, so 4.2
 * gets the official renderer instead.
 *
 * Both expose { skeleton, state, autoUpdate, update(dt), destroy() }, which
 * is all the stage drives.
 */
function makeSpine(key, skeletonData) {
	if (key === "4.2") return new Spine42({ skeletonData });
	return new Spine(skeletonData);
}

/** Tag a runtime module with the version it really is, so the HUD can't lie. */
function markRuntime(mod, version) {
	if (mod && !mod.__spineRuntimeVersion) {
		try {
			Object.defineProperty(mod, "__spineRuntimeVersion", { value: version });
		} catch {
			/* frozen module — the key is a good enough fallback */
		}
	}
	return mod;
}

const runtimeCache = new Map();

/** Which runtime is driving the model currently on stage (for the HUD). */
let spineRuntime = "4.1";
let spineVersion = null;
/** The atlas the on-stage model was parsed with (runtime-specific pages). */
let atlas = null;

async function getRuntime(key) {
	const k = RUNTIME_LOADERS[key] ? key : "4.1";
	if (!runtimeCache.has(k)) runtimeCache.set(k, Promise.resolve(RUNTIME_LOADERS[k]()));
	return runtimeCache.get(k);
}

/**
 * Parse skeleton data with the runtime matching its Spine version.
 * Falls back through the remaining runtimes if the chosen one fails: a version
 * string can't always be trusted (some games prefix their own header), and a
 * successful parse is the only proof that actually matters.
 */
/**
 * Build a TextureAtlas for a given runtime.
 *
 * Runtime 4.2 (official renderer) needs each page wrapped in SpineTexture:
 * SlotMesh does `this.texture = slotTexture.texture`, i.e. it reaches into
 * the wrapper for the Pixi texture. Hand it a bare BaseTexture and every
 * mesh ends up with `texture === undefined`, which renders absolutely
 * nothing and throws no error — the model just silently vanishes.
 */
function makeAtlas(key, atlasText, pageCache) {
	// spine-core 4.2's TextureAtlas takes ONLY the atlas text — no page
	// callback, no completion callback (unlike pixi-spine's, which resolves
	// through its third argument). Passing the pixi-spine signature here made
	// the atlas build fine but never settle: the load hung forever with zero
	// errors. So 4.2 gets its pages assigned afterwards, per page.
	if (key === "4.2") {
		const ta = new TextureAtlas42(atlasText);
		for (const page of ta.pages) {
			const bt = pageCache.get(page.name);
			if (!bt) throw new Error(`Halaman atlas “${page.name}” tidak tersedia.`);
			// The official renderer reads `region.texture.texture` — i.e. the
			// Pixi texture inside the SpineTexture wrapper. A bare BaseTexture
			// leaves every mesh with `texture === undefined`, which draws
			// absolutely nothing and throws no error.
			page.setTexture(SpineTexture42.from(bt));
		}
		return Promise.resolve(ta);
	}

	return new Promise((resolve, reject) => {
		const ta = new TextureAtlas(atlasText, (line, callback) => {
			const pageName = String(line).trim();
			const bt = pageCache.get(pageName);
			if (!bt) {
				reject(new Error(`Halaman atlas “${pageName}” tidak tersedia.`));
				return;
			}
			callback(bt);
		}, resolve);
		if (!ta) reject(new Error("Atlas tidak bisa diurai."));
	});
}

async function parseSkeletonData({ isBinary, rawSkeleton, atlasText, pageCache, atlas: presetAtlas, scale }) {
	// Compare-panel callers pass a ready-made atlas with stubbed pages; the
	// stage passes raw atlasText + a cache of real page textures and lets us
	// build the atlas per runtime attempt.
	if (presetAtlas) {
		return parseWithAtlases({ isBinary, rawSkeleton, scale, makeFor: () => presetAtlas });
	}
	return parseWithAtlases({ isBinary, rawSkeleton, scale, makeFor: (key) => makeAtlas(key, atlasText, pageCache) });
}

async function parseWithAtlases({ isBinary, rawSkeleton, scale, makeFor }) {
	// Detection needs byte indexing. For binaries the caller may hand us an
	// ArrayBuffer (fetch default) rather than a Uint8Array view, and indexing
	// an ArrayBuffer yields undefined — detection then silently returns null
	// and we'd try every runtime from 4.1 down, logging a loader error each
	// time before the right one finally succeeded.
	const bytes = isBinary
		? (rawSkeleton instanceof Uint8Array ? rawSkeleton : new Uint8Array(rawSkeleton))
		: rawSkeleton;

	const detected = detectSpineVersion({ isBinary, raw: bytes });
	const wanted = pickRuntime(detected);
	// Try the detected runtime first, then progressively OLDER ones.
	// A runtime refuses data newer than itself, so offering 4.0/4.1 to a 3.8
	// file can only fail (and each failure logs a console error before 3.8
	// succeeds). Newer-than-detected runtimes are therefore never tried.
	const all = Object.keys(RUNTIME_LOADERS);
	const num = (k) => Number(k);
	const order = [wanted, ...all.filter((k) => num(k) < num(wanted)).sort((a, b) => num(b) - num(a))];

	let lastErr = null;
	for (const key of order) {
		try {
			const mod = await getRuntime(key);
			let { SkeletonBinary, SkeletonJson } = mod;
			// Use the renderer's OWN parser classes when it has them, so the
			// attachments they produce pass its `instanceof` checks.
			const override = PARSER_OVERRIDES[key];
			if (override) {
				SkeletonBinary = override.SkeletonBinary;
				SkeletonJson = override.SkeletonJson;
			}
			if (isBinary && !SkeletonBinary) continue;

			// The attachment loader must come from the SAME runtime as the
			// parser. A 4.1 loader + a 4.2 SkeletonBinary yields attachments
			// the 4.2 data model rejects, so rebuild both on every attempt.
			// The atlas is rebuilt too: 4.2 needs SpineTexture-wrapped pages.
			const atlas = await makeFor(key);
			const attachmentLoader = makeAttachmentLoader(key, atlas);

			const parser = isBinary
				? new SkeletonBinary(attachmentLoader)
				: new SkeletonJson(attachmentLoader);
			parser.scale = scale ?? 1;

			// Skeleton JSON 2.x (hasil tools/convert-spine2.py, atau model
			// Epic Seven yang memang diekspor sebagai JSON) perlu dibereskan
			// dulu, atau runtime 3.8+ menolaknya:
			//   - event tanpa "name"  -> "eventDataName cannot be null"
			//   - skins berbentuk objek, padahal runtime mengharapkan larik
			// Tanpa ini, model gagal total. Dengan ini, runtime 4.1 memuatnya
			// baik-baik saja (terverifikasi 250/250).
			if (!isBinary && typeof rawSkeleton === "object") {
				normalizeSpine2Json(rawSkeleton, {
					onWarn: (m) => console.warn("[spine2]", m),
				});
			}

			const data = isBinary
				? parser.readSkeletonData(new Uint8Array(rawSkeleton))
				: parser.readSkeletonData(rawSkeleton);

			if (!data?.bones?.length) throw new Error("Data skeleton tidak berisi tulang.");
			// Report the runtime that actually loaded. RUNTIME_LOADERS maps
			// "3.7" onto the 3.8 package, so echoing `key` would claim "3.7".
			const actual = mod.__spineRuntimeVersion || key;
			return { data, atlas, runtime: actual, version: detected?.raw || null };
		} catch (err) {
			lastErr = err;
		}
	}
	throw lastErr || new Error("Tidak ada runtime yang bisa membaca skeleton ini.");
}

/* ------------------------------------------------------------------ *
 * Loading
 * ------------------------------------------------------------------ */
function baseTextureFromPixiTexture(tex) {
	if (!tex) return null;
	if (tex instanceof BaseTexture) return tex;
	return tex.baseTexture || tex.source || null;
}

/**
 * Render model Spine 2.x dengan runtime 2.1 official di kanvas 2D sendiri.
 *
 * Ini MENGGANTIKAN iframe ke penampil GWT vendored. Penampil itu punya loop
 * dan kontrol sendiri, sehingga timeline, skin, export PNG, dan FPS meter
 * viewer mati untuk model 2.x — padahal modelnya sendiri tidak bermasalah.
 *
 * Kenapa kanvas tersendiri, bukan Pixi: spine.js 2.1 lahir sebelum Pixi dan
 * tidak tahu PIXI.Container/texture. Ia tidak bisa masuk ke scene graph yang
 * dipakai model 3.8/4.x. Kanvas 2D ini menempel di atas kanvas Pixi dan
 * berbagi viewport (pan/zoom), jadi pergerakannya tetap terasa sama.
 */
async function loadLegacyModel(model) {
	const dirPath = String(model.id || "").split("#")[0];
	const base = "/assets/" + dirPath.split("/").map(encodeURIComponent).join("/") + "/";

	// Tear down any pixi-spine model currently on the stage.
	if (spine) {
		try {
			app.stage.removeChild(spine);
			spine.destroy?.();
		} catch {
			/* already gone */
		}
		spine = null;
	}
	teardownSpine21();
	current = model;

	el.loading.hidden = true;

	// Cari skeleton JSON dan atlas di direktori model.
	let json = model.skeletonFile;
	if (!json || !json.toLowerCase().endsWith(".json")) {
		// Model 2.x murni .skel belum dikonversi: tidak bisa dirender di sini.
		showError(
			"Model ini masih berbentuk .skel biner. Jalankan dulu " +
			"tools/convert-spine2.py untuk mengubahnya menjadi JSON.");
		return;
	}
	// Pakai atlasFile dari server. JANGAN ditebak dari nama skeleton: satu
	// folder bisa berisi beberapa model, dan pasangannya tidak searah nama —
	// 2001_1.json berpasangan dengan DragonPose1.atlas, bukan 2001.atlas.
	// Menebak menghasilkan atlas 404 untuk model-model itu.
	const atlasFileRaw = model.atlasFile || json.replace(/\.json$/i, ".atlas");
	// Id bisa berbentuk "<dir>#<stem>": "#<stem>" hanya penanda varian di
	// perpustakaan, bukan bagian path di disk.
	const jsonFile = String(json).split("#")[0];
	const atlasFile = String(atlasFileRaw).split("#")[0];

	try {
		spine21.state = await loadSpine21Model({
			basePath: base,
			jsonFile: encodeURIComponent(jsonFile),
			atlasFile: encodeURIComponent(atlasFile),
		});
	} catch (err) {
		showError("Gagal memuat model 2.1: " + (err?.message || err));
		return;
	}
	showError(null);

	spine21.active = true;
	spine21.lastTime = performance.now() / 1000;
	ensureSpine21Canvas();
	startSpine21Loop();

	// HUD: penanda bahwa model dimuat, dan renderer yang dipakai.
	el.hud.hidden = false;
	$("#title-model").textContent = model.name;
	el.delBtn.hidden = false;
	const hudModel = $("#hud-model");
	if (hudModel) hudModel.textContent = model.name;
	const hudStats = $("#hud-stats");
	if (hudStats) {
		hudStats.innerHTML =
			`<span><b>Spine ${model.spine || "2.1.27"}</b></span>` +
			`<span><b>runtime 2.1</b></span>`;
	}
	$("#empty").hidden = true;

	// Isi daftar animasi — sekarang NYATA, karena kitalah yang memutarnya.
	populateSpine21UI();

	// FPS meter kembali berarti: ticker kita yang menggambar.
	fps.external = false;
	fpsWarmup();
}

/** Isi pilihan animasi/skin dari skeleton 2.1 yang sedang aktif. */
function populateSpine21UI() {
	const st = spine21.state;
	if (!st) return;
	const anims = st.animations || [];
	if (el.animSelect) {
		el.animSelect.innerHTML = "";
		for (const name of anims) {
			const o = document.createElement("option");
			o.value = name;
			o.textContent = name;
			el.animSelect.appendChild(o);
		}
		el.animSelect.disabled = anims.length === 0;
		if (anims.length) el.animSelect.value = anims[0];
	}
	// Kendali tidak lagi dimatikan — berbeda dari jalur iframe dulu,
	// karena sekarang viewer yang memegang putarannya.
	for (const id of ["anim-select", "play-btn", "loop-btn", "scrub", "rate-select"]) {
		const n = document.getElementById(id);
		if (n) {
			n.disabled = false;
			n.removeAttribute("title");
		}
	}
}

/** Buat (atau pakai ulang) kanvas 2D yang menampung model 2.1. */
function ensureSpine21Canvas() {
	const host = document.getElementById("canvas-wrap") || document.querySelector(".main") || document.body;
	if (spine21.canvas && spine21.canvas.parentElement === host) return spine21.canvas;

	// Hanya lepas KANVAS-nya, jangan panggil teardownSpine21(): itu juga
	// mengosongkan spine21.state, sehingga loop yang menyusul langsung
	// berhenti karena tidak ada skeleton untuk digambar.
	if (spine21.rafId) cancelAnimationFrame(spine21.rafId);
	spine21.rafId = 0;
	if (spine21.canvas) spine21.canvas.remove();

	const canvas = document.createElement("canvas");
	canvas.id = "spine21-canvas";
	canvas.style.cssText =
		"position:absolute;inset:0;width:100%;height:100%;z-index:6;pointer-events:none;";
	host.appendChild(canvas);
	spine21.canvas = canvas;
	spine21.ctx = canvas.getContext("2d");

	// Ukuran awal: pakai ukuran CSS host kalau sudah diketahui. Tanpa ini
	// kanvas tetap 300x150 (bawaan) sampai frame pertama, dan apa pun yang
	// membaca dimension sebelum frame itu akan melihat angka yang salah.
	const w = host.clientWidth || 1;
	const h = host.clientHeight || 1;
	canvas.width = w;
	canvas.height = h;
	return canvas;
}

/** Hentikan loop dan lepas kanvas 2.1. */
function teardownSpine21() {
	if (spine21.rafId) cancelAnimationFrame(spine21.rafId);
	spine21.rafId = 0;
	if (spine21.canvas) spine21.canvas.remove();
	spine21.canvas = null;
	spine21.ctx = null;
	spine21.state = null;
	spine21.active = false;
}

/** Loop gambar: satu rAF yang juga dipakai FPS meter. */
function startSpine21Loop() {
	const frame = () => {
		if (!spine21.active || !spine21.state) return;
		const now = performance.now() / 1000;
		// Batasi delta: tab yang kembali dari latar bisa lapor puluhan detik,
		// yang melompatkan animasi jauh melewati akhirnya.
		const delta = Math.min(now - spine21.lastTime, 0.1);
		spine21.lastTime = now;

		spine21.time += state.playing ? delta * state.rate : 0;
		advanceSpine21(spine21.state, state.playing ? delta * state.rate : 0);

		const host = document.getElementById("canvas-wrap");
		const w = host?.clientWidth || 1;
		const h = host?.clientHeight || 1;
		const canvas = spine21.canvas;
		if (canvas && (canvas.width !== w || canvas.height !== h)) {
			canvas.width = w;
			canvas.height = h;
		}
		if (canvas && spine21.ctx) {
			drawSpine21(spine21.state, {
				ctx: spine21.ctx,
				width: w,
				height: h,
				zoom: state.zoom * (state.flip ? -1 : 1),
				panX: state.panX,
				// Kanvas 2.1 pakai y-up, jadi pan dibalik supaya searah Pixi.
				panY: -state.panY,
				bgColor: state.bg === "light" ? "#f4f4f6" : "#101014",
			});
		}
		if (el.timeline && !el.timeline.hidden) updateTimelinePlayhead();
		spine21.rafId = requestAnimationFrame(frame);
	};
	spine21.rafId = requestAnimationFrame(frame);
}

/** Lepas kanvas 2.1 dan hidupkan kembali kendali pixi-spine. */
/** Drop the legacy iframe and re-enable the pixi-spine controls. */
function teardownLegacyViewer() {
	const frame = document.getElementById("legacy-frame");
	if (frame) frame.remove();
	// Our ticker draws the stage again from here, so the FPS meter is
	// meaningful once more.
	fps.external = false;
	fpsWarmup();
	const note = document.getElementById("legacy-note");
	if (note) note.hidden = true;
	for (const id of ["anim-select", "skin-select", "pma-select", "play-btn", "loop-btn", "scrub", "rate-select"]) {
		const n = document.getElementById(id);
		if (n) {
			n.disabled = false;
			n.removeAttribute("title");
		}
	}
}

/**
 * Renders a Live2D Cubism model in place of a Spine skeleton.
 *
 * Cubism models have no bones, slots, skins or Spine animations, so most of
 * the Spine UI is meaningless here: we show the model, expose a single "idle"
 * animation entry, and leave the rest of the inspector hidden.
 */
async function loadLive2DModel(model) {
	// The id may carry a "#<stem>" suffix (B/M/T variants sharing a folder).
	// That suffix is not part of the path on disk.
	const dirPath = String(model.id || "").split("#")[0];
	const base =
		"/assets/" + dirPath.split("/").map(encodeURIComponent).join("/") + "/";

	const mocFile = model.skeletonFile;
	const textureFiles = model.textureFiles || [];
	if (!textureFiles.length) {
		throw new Error("Model Live2D tidak punya berkas tekstur.");
	}

	const { model: live2d, dispose } = await loadLive2D({
		base,
		mocFile,
		textureFiles,
		motionFiles: model.motionFiles || [],
	});

	// Drop any previous model before putting this one on the stage.
	if (spine) {
		stageRoot.removeChild(spine);
		spine.destroy(true);
		spine = null;
	}
	live2dDispose?.();
	live2dDispose = dispose;
	// New model, so its centring offset must be measured afresh.
	live2dCentre = null;

	spine = live2d;
	stageRoot.addChildAt(live2d, 0);
	bonesGfx.visible = false;
	stageRoot.addChild(bonesGfx);

	current = model;
	atlas = null;
	atlasSaysPMA = false;
	current.atlasPagesFlags = [];

	// Cubism has no Spine tracks; each motion is an independent clip.
	const anims = model.animations && model.animations.length ? model.animations : ["(diam)"];
	fillSelect(el.animSelect, anims, anims[0]);
	animName = anims[0];
	duration = 0;
	el.timeDur.textContent = "0.00s";

	// No Spine skins or slots to inspect.
	fillSelect(el.skinSelect, [], null);
	if (insp.open) {
		renderSkinOptions();
		renderSlots();
	}

	renderVariants(model);
	renderAudio(model);

	tl.anim = null;
	if (!el.timeline.hidden) renderTimeline();

	fitModel();
	el.empty.hidden = true;
	setActive(model.id);
	renderHud();
	// Same as the Spine path: fresh stats for a freshly loaded model.
	if (fps.on) fpsResetStats();
}

async function loadModel(model) {
	showError(null);
	el.loading.hidden = false;
	el.loading.textContent = "Memuat " + model.name + "…";

	try {
		// Any previous Spine 2.x model left an iframe over the stage; clear it
		// before deciding how to render this one.
		teardownLegacyViewer();

		// Live2D Cubism models (.moc3) take a completely different path —
		// they have no .skel/.atlas, and are rendered by the Cubism runtime.
		if (isLive2D(model)) {
			return await loadLive2DModel(model);
		}

		// Spine 2.x skeletons (Project QT) can't be read by any pixi-spine
		// runtime — the 3.8 weighted-mesh path desynchronises on their
		// 5-11 bones-per-vertex and scatters the vertices. They render
		// correctly in the vendored 2.1.27 viewer, so hand those off.
		if (model.needsLegacyViewer || model.spineRuntime === "2.1.27") {
			return await loadLegacyModel(model);
		}
		// The id may carry a "#<stem>" suffix when one folder holds several
		// models (B/M/T variants share a folder). That suffix distinguishes
		// them in the library but is NOT part of the path on disk, and a
		// literal '#' would be parsed as a URL fragment — the server would
		// only ever see the part before it (hence a 404).
		const dirPath = String(model.id || "").split("#")[0];
		// Encode each path segment, not the whole id: encoding the slashes too
		// turns "game/model" into one opaque segment.
		const base = "/assets/" + dirPath.split("/").map(encodeURIComponent).join("/");
		const skelUrl = `${base}/${encodeURIComponent(model.skeletonFile)}`;
		const atlasUrl = `${base}/${encodeURIComponent(model.atlasFile)}`;
		const isBinary = model.skeletonFile.toLowerCase().endsWith(".skel");

		// Atlas text and skeleton JSON are fetched directly: the pixi-spine loader
		// plugin would otherwise auto-infer a sibling "<name>.atlas" (wrong for
		// files like "spineboy-pro.json") and double-parse the skeleton.
		const [atlasText, rawSkeleton] = await Promise.all([
			fetch(atlasUrl).then((r) => {
				if (!r.ok) throw new Error(`HTTP ${r.status} untuk ${model.atlasFile}`);
				return r.text();
			}),
			isBinary
				? fetch(skelUrl).then((r) => {
						if (!r.ok) throw new Error(`HTTP ${r.status} untuk ${model.skeletonFile}`);
						return r.arrayBuffer();
					})
				: fetch(skelUrl).then((r) => {
						if (!r.ok) throw new Error(`HTTP ${r.status} untuk ${model.skeletonFile}`);
						return r.json();
					}),
		]);

		if (typeof atlasText !== "string" || !atlasText.trim()) {
			throw new Error(`Berkas atlas “${model.atlasFile}” kosong atau tidak bisa dibaca.`);
		}

		// Resolve texture pages relative to the atlas URL.
		const atlasBase = atlasUrl.slice(0, atlasUrl.lastIndexOf("/") + 1);

		// Load every atlas page UP FRONT and fail fast with a readable message.
		// Letting the TextureAtlas loader discover pages lazily meant a missing
		// page surfaced much later as "Cannot read properties of null (reading
		// 'findRegion')" — a null region inside the runtime, with no hint that
		// the real cause was one absent .png (multi-page atlases were the
		// usual culprit).
		// Parse each page's declared "size: W,H" so a page stored at a lower
		// resolution can be detected (and scaled) before regions are resolved.
		const declaredSizes = new Map();
		let pendingPage = null;
		for (const line of atlasText.split(/\r?\n/)) {
			const s = line.trim();
			if (/\.(png|jpe?g|webp)$/i.test(s) && !s.includes(" ")) {
				pendingPage = s;
			} else if (pendingPage && !declaredSizes.has(pendingPage)) {
				const m = s.match(/^size:\s*(\d+)\s*,\s*(\d+)/i);
				if (m) {
					declaredSizes.set(pendingPage, [Number(m[1]), Number(m[2])]);
					pendingPage = null;
				}
			}
		}

		const pageNames = [];
		for (const line of atlasText.split(/\r?\n/)) {
			const s = line.trim();
			if (/\.(png|jpe?g|webp)$/i.test(s) && !s.includes(" ")) pageNames.push(s);
		}

		// Per page: does any region actually fall outside the file?
		//
		// Needed because "declared size differs from the file" is too weak a
		// signal on its own — hundreds of pages differ by a percent or two
		// from rounding and render perfectly. Only a region that escapes the
		// loaded texture makes PIXI throw, so that is the real condition.
		//
		// Two parser traps:
		//  - `rotate:` comes AFTER `bounds:` in a region block (name / bounds /
		//    offsets / rotate). Reading rotation at the bounds line always
		//    yields false, so each block has to be buffered and evaluated when
		//    the NEXT region starts.
		//  - a rotated region stores its ORIGINAL w,h in `bounds:`; the packed
		//    rectangle in the page is the transpose. Without the swap every
		//    rotate:90 region looks like it overflows.
		const overflowsPage = (pageName, bt) => {
			if (!bt) return false;
			let current = null;
			let pending = null;   // {x, y, w, h}
			let rotated = false;
			let seenRotate = false;   // format lama: `rotate:` muncul sebelum xy/size
			const flush = () => {
				if (current !== pageName || !pending) return false;
				const { x, y, w, h } = pending;
				const pw = rotated ? h : w;
				const ph = rotated ? w : h;
				return x + pw > bt.width || y + ph > bt.height;
			};
			for (const line of atlasText.split(/\r?\n/)) {
				const s = line.trim();
				if (/\.(png|jpe?g|webp)$/i.test(s) && !s.includes(" ")) {
					if (flush()) return true;
					current = s;
					pending = null;
					rotated = false;
					seenRotate = false;
					continue;
				}
				const b = s.match(/^bounds:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
				if (b) {
					// Flush the PREVIOUS region before buffering this one. Skipping
					// this meant only the last region of a page was ever tested: a
					// page whose final region happens to fit reported no overflow
					// even when 16 of its 24 regions sat outside the file, so the
					// rescue path below never ran (DotAbyss AIBoss2018101_1).
					if (flush()) return true;
					// `rotate:` belongs to ONE region, so clear it on every new
					// `bounds:`. Leaving it set leaked the first region's rotation
					// onto every later one — an unrotated region then measured
					// transposed and looked like it overflowed a healthy page,
					// which blurred those pages by rescaling them for nothing.
					rotated = false;
					seenRotate = false;
					const [, x, y, w, h] = b.map(Number);
					pending = { x, y, w, h };
					continue;
				}
				// Legacy atlas format: `xy:` + `size:` instead of `bounds:`, and
				// `rotate:` comes BEFORE them. Roughly 74% of this collection
				// (10.9k of 14.7k atlases) uses it, so without this branch the
				// overflow test silently saw zero regions on most games.
				const xy = s.match(/^xy:\s*(\d+)\s*,\s*(\d+)\s*$/i);
				if (xy) {
					if (flush()) return true;
					rotated = seenRotate;
					seenRotate = false;
					pending = { x: Number(xy[1]), y: Number(xy[2]), w: 0, h: 0 };
					continue;
				}
				// Only the region's `size:` completes a legacy block; the page's
				// own `size:` sits directly under the page name, before any `xy:`.
				const sz = s.match(/^size:\s*(\d+)\s*,\s*(\d+)\s*$/i);
				if (sz && pending && pending.w === 0 && pending.h === 0) {
					pending.w = Number(sz[1]);
					pending.h = Number(sz[2]);
					continue;
				}
				if (/^rotate:\s*(90|270|true)/i.test(s)) {
					rotated = true;
					seenRotate = true;
				}
			}
			return flush();
		};
		const pageCache = new Map();
		await Promise.all(
			pageNames.map(async (pageName) => {
				const tex = await Assets.load({
					src: atlasBase + encodeURIComponent(pageName),
					data: { alphaMode: ALPHA_MODES.NPM },
				}).catch(() => null);
				let bt = baseTextureFromPixiTexture(tex);
				if (!bt) throw new Error(`Halaman atlas “${pageName}” tidak ditemukan.`);

				// Some publishers ship half-resolution atlas pages while the atlas
				// still declares full-res coordinates (this mirror has six such
				// models). Pixi sizes the base texture from the file, so every
				// region then lands outside it: "Texture Error: frame does not fit
				// inside the base Texture dimensions". Scale the page up by the
				// exact ratio so the declared coordinates are valid again — image
				// is softer, but it renders instead of failing.
				const declared = declaredSizes.get(pageName);
				if (declared && bt.width > 0 && bt.height > 0) {
					const rx = declared[0] / bt.width;
					const ry = declared[1] / bt.height;
					// Scale up whenever the file is smaller than what the atlas
					// Take the LARGER axis ratio so every declared
					// region fits: some pages ship at a different aspect (a
					// 1920x1080 file for a 4096x4096 atlas), and scaling by
					// one axis alone leaves regions outside the texture.
					// Aspect is preserved — the extra area stays transparent.
					// Only upscale when the page is a proportional downscale of
					// what the atlas declares (rx ~= ry). A mismatched aspect
					// means the wrong file was extracted, not a half-res page —
					// scaling that just scatters every region and renders the
					// model as scrambled shards, which is worse than failing.
					//
					// Not every downscale is proportional, though. DotAbyss
					// ships pages squashed by Unity's per-axis texture
					// downscaling (a 732x532 atlas whose page is 512x512), so
					// rx and ry differ on purpose. Stretching such a page to
					// the declared size is the correct inverse — verified
					// against the raw bundle: the crops come back as clean
					// body parts, where a uniform 1.43x scale leaves them
					// visibly off.
					//
					// Gated on overflow because the gap alone is far too loose:
					// hundreds of pages across every game differ by a few
					// percent from rounding and still render fine, and
					// rescaling those only softens them for nothing. Only
					// pages whose regions genuinely fall outside the file need
					// rescuing. gap < 0.45 then separates a squashed page from
					// an outright wrong texture (DotAbyss's broken SpineSD
					// pages sit at 0.83-2.95 and stay skipped).
					const ratio = Math.max(rx, ry);
					const aspectGap = Math.abs(Math.log(rx / ry));
					const over = overflowsPage(pageName, bt);
					if (ratio > 1.01 && ratio <= 8) {
						if (aspectGap < 0.02) {
							bt = upscaleBaseTexture(bt, ratio);
						} else if (aspectGap < 0.45 && over) {
							bt = upscaleBaseTexture(bt, rx, ry);
						}
					}
				}

				bt.scaleMode = SCALE_MODES.LINEAR;
				bt.mipmap = MIPMAP_MODES.POW2;
				bt.wrapMode = WRAP_MODES.CLAMP;
				bt.alphaMode = ALPHA_MODES.NPM;
				pageCache.set(pageName, bt);
			})
		);

		// The loader and ATLAS are built inside parseSkeletonData, per runtime
		// attempt. Runtime 4.2 needs its own TextureAtlas whose pages are
		// wrapped in SpineTexture — the official renderer reads
		// `region.texture.texture` (the Pixi texture inside the wrapper) and
		// silently draws nothing when handed a bare BaseTexture.
		const parsed = await parseSkeletonData({
			isBinary,
			rawSkeleton,
			atlasText,
			pageCache,
			scale: model.scale ?? 1,
		});
		const skeletonData = parsed.data;
		spineRuntime = parsed.runtime;
		spineVersion = parsed.version;
		// Keep the atlas the model actually rendered with — applyPMA() reads
		// its page flags, and the HUD reports them.
		atlas = parsed.atlas;

		if (!skeletonData?.bones?.length) throw new Error("Data skeleton tidak berisi tulang.");

		// 4.2 renders through the official runtime; everything else through
		// pixi-spine. Both are driven identically from here on.
		const next = makeSpine(spineRuntime, skeletonData);
		next.autoUpdate = false;

		if (spine) {
			stageRoot.removeChild(spine);
			spine.destroy(true);
		}
		spine = next;
		stageRoot.addChildAt(spine, 0);
		bonesGfx.visible = state.showBones;
		stageRoot.addChild(bonesGfx); // keep overlay on top

		// A Spine model must not inherit a Cubism centring offset.
		live2dCentre = null;
		live2dDispose?.();
		live2dDispose = null;

		current = model;

		// Apply any saved PMA override for THIS model before reading the atlas flag.
		syncPmaToModel(model.id);

		// Remember the game's own default, then read the atlas's `pma:` flags.
		// Both feed "Auto": an explicit atlas flag wins, otherwise we fall back
		// to what this game's assets are known to ship with.
		gamePmaDefault = !!model.pmaDefault;
		atlasSaysPMA = (atlas.pages || []).some((p) => p.pma);
		current.atlasPagesFlags = (atlas.pages || []).map((p) => p.pma ?? null);
		applyPMA();
		updatePmaUI();

		const anims = skeletonData.animations.map((a) => a.name);
		if (!anims.length) throw new Error("Model ini tidak punya animasi.");
		fillSelect(el.animSelect, anims, anims.includes("idle") ? "idle" : anims[0]);

		const skins = (skeletonData.skins || []).map((s) => s.name);
		fillSelect(el.skinSelect, ["default", ...skins.filter((s) => s !== "default")], "default");

		renderVariants(model);
		renderAudio(model);

		// Rebuild the timeline for the new skeleton. It may already be visible
		// from a previous model (or opened before anything was loaded), in
		// which case it would still be holding the old — or empty — data.
		tl.anim = null;
		if (!el.timeline.hidden) renderTimeline();

		// refresh the slot inspector for the new skeleton
		insp.skin = "default";
		if (insp.open) {
			renderSkinOptions();
			renderSlots();
		}

		setAnimation(el.animSelect.value, true);
		fitModel();
		el.empty.hidden = true;
		setActive(model.id);
		renderHud();
		// min/avg belong to the model on screen, so drop the old ones — the
		// first frames after a load also include parsing and texture upload.
		if (fps.on) fpsResetStats();
		// A different skeleton has different named regions; the old bounds
		// would answer hit tests with names this model doesn't have.
		parts.bounds = null;
		parts.hover = null;
	} catch (err) {
		console.error(err);
		showError(`Gagal memuat “${model.name}”: ${err.message}`);
	} finally {
		el.loading.hidden = true;
	}
}

function fillSelect(sel, values, preferred) {
	sel.innerHTML = "";
	if (!values.length) {
		sel.innerHTML = '<option value="">—</option>';
		sel.disabled = true;
		return;
	}
	sel.disabled = false;
	for (const v of values) {
		const o = document.createElement("option");
		o.value = v;
		o.textContent = v;
		sel.appendChild(o);
	}
	sel.value = values.includes(preferred) ? preferred : values[0];
}

function setAnimation(name, restart = false) {
	if (!spine || !name) return;
	animName = name;
	spine.state.setAnimation(0, name, state.loop);
	const track = spine.state.tracks[0];
	duration = track?.animation?.duration || 0;
	state.trackTime = restart ? 0 : Math.min(state.trackTime, duration);
	if (track) track.trackTime = state.trackTime;
	// A new clip re-anchors the clock: "0.5s into this animation" is a
	// different moment than "0.5s into the last one".
	clock.syncTo(state.trackTime);
	el.timeDur.textContent = duration.toFixed(2) + "s";
	spine.update(0);
	renderHud();
}

/* ------------------------------------------------------------------ *
 * Variants (Nikke ships c010 + c010/aim + c010/cover)
 * ------------------------------------------------------------------ */

/**
 * Fills the "Varian" dropdown next to Skin. Hidden entirely for models with no
 * siblings — 843 of the 2007 models have nothing to switch to, and an empty
 * dropdown there is just noise.
 */
function renderVariants(model) {
	const fam = model?.family;
	if (!fam || !fam.members?.length) {
		el.variantWrap.hidden = true;
		el.variantSelect.innerHTML = "";
		return;
	}
	el.variantWrap.hidden = false;
	fillSelect(
		el.variantSelect,
		fam.members.map((m) => m.label),
		fam.label
	);
	// remember the id behind each label so switching needs no lookup
	for (const opt of el.variantSelect.options) {
		const match = fam.members.find((m) => m.label === opt.value);
		if (match) opt.dataset.id = match.id;
	}
	el.variantSelect.title = `${fam.members.length} varian untuk model ini`;
}

/**
 * Brown Dust 2 voice lines (JP only).
 *
 * The server attaches `model.audio = { costumeId, lang, tracks }` when a model
 * has voices. There are 3 BattleReady variants per costume, so the button
 * cycles through them instead of replaying the same clip every time.
 *
 * Autoplay would be blocked by the browser until the user interacts, and a
 * voice that fires on every model load would be obnoxious — so this is
 * click-to-play only.
 */
let voiceEl = null;
let voiceQueue = [];
let voiceIndex = 0;

/**
 * Autoplay preference. Stored under "spine-stage:voice-autoplay" ("1"/"0").
 * Browsers block audio until the user has interacted with the page, so the
 * first load usually cannot play — we remember that the user wants autoplay
 * and start obeying it from their first click onwards.
 */
const VOICE_AUTOPLAY_KEY = "spine-stage:voice-autoplay";
let voiceAutoplay = (() => {
	try {
		return localStorage.getItem(VOICE_AUTOPLAY_KEY) !== "0";
	} catch {
		return true;
	}
})();

function setVoiceAutoplay(on) {
	voiceAutoplay = !!on;
	try {
		localStorage.setItem(VOICE_AUTOPLAY_KEY, voiceAutoplay ? "1" : "0");
	} catch {
		/* private mode — preference just won't stick */
	}
	// Only sync the switch's appearance — calling renderAudio() here would
	// re-trigger autoplay, making "off" immediately start a new clip.
	el.audioAutoBtn.dataset.on = String(voiceAutoplay);
	if (!voiceAutoplay) stopVoice();
}

let voiceUnlocked = false;

function renderAudio(model) {
	const tracks = model?.audio?.tracks || [];
	stopVoice();
	voiceQueue = tracks;
	voiceIndex = 0;
	el.audioBtn.hidden = !tracks.length;
	el.audioBtn.title = tracks.length
		? `Putar suara karakter (${tracks.length} varian, ${model.audio.lang})`
		: "Tidak ada suara untuk model ini";

	// The autoplay switch is meaningless for a model with no voices, so it
	// follows the play button's visibility.
	el.audioAutoBtn.hidden = !tracks.length;
	el.audioAutoBtn.dataset.on = String(voiceAutoplay);

	// Autoplay on load — if the browser lets us. The very first page load is
	// almost always blocked until the user interacts; see voiceUnlock().
	if (tracks.length && voiceAutoplay) playVoice({ auto: true });
}

function stopVoice() {
	if (voiceEl) {
		voiceEl.pause();
		voiceEl.currentTime = 0;
	}
	el.audioBtn.dataset.playing = "false";
}

/**
 * Play the next voice clip, or stop if one is already playing.
 *
 * `auto: true` means this came from a model load, not a click: if the browser
 * blocks it (autoplay policy) we fail SILENTLY and wait for the user's first
 * interaction instead of nagging with an error toast on every model.
 */
function playVoice({ auto = false } = {}) {
	if (!voiceQueue.length || (auto && !voiceAutoplay)) return;
	if (!voiceEl) {
		voiceEl = new Audio();
		voiceEl.addEventListener("ended", () => {
			el.audioBtn.dataset.playing = "false";
		});
		voiceEl.addEventListener("error", () => {
			el.audioBtn.dataset.playing = "false";
			if (!auto) toast("Suara gagal diputar.");
		});
	}
	// Already playing? stop — the button doubles as a stop control.
	if (!auto && !voiceEl.paused) {
		stopVoice();
		return;
	}
	voiceEl.src = voiceQueue[voiceIndex % voiceQueue.length];
	voiceIndex = (voiceIndex + 1) % voiceQueue.length;
	el.audioBtn.dataset.playing = "true";
	voiceEl.play().catch(() => {
		// Almost always the autoplay policy rather than a broken file.
		el.audioBtn.dataset.playing = "false";
		if (!auto) toast("Browser memblokir audio — klik lagi untuk memutar.");
	});
}

/**
 * Browsers only allow audio after a real user gesture. Retry the pending
 * autoplay once the user interacts, so a model loaded before that first
 * interaction starts talking as soon as the gesture happens.
 *
 * NOT registered with `{ once: true }`: picking a model already requires
 * clicking the game tile and the card, so a once-only listener burns itself on
 * those clicks — long before any model is loaded — and the retry never fires.
 * Stay attached until an unlock actually succeeds.
 */
function voiceUnlock() {
	if (voiceUnlocked) return;
	if (!voiceAutoplay || !voiceQueue.length) return;
	if (voiceEl && !voiceEl.paused) {
		voiceUnlocked = true;
		return;
	}
	playVoice({ auto: true });
	// playVoice() sets src and calls play(); if the browser refused it the
	// element stays paused, so only mark unlocked once it is really running.
	if (voiceEl && !voiceEl.paused) voiceUnlocked = true;
}
["pointerdown", "keydown"].forEach((ev) =>
	window.addEventListener(ev, voiceUnlock, { capture: true })
);

/**
 * Switch to a sibling variant without going back to the library.
 *
 * Loads fresh because variants are genuinely different skeletons: sampled
 * families share ZERO animation names, so carrying the current animation over
 * would leave us pointing at a clip that doesn't exist in the new skeleton.
 */
async function switchVariant(id) {
	if (!id || !current || id === current.id) return;
	const model = models.find((m) => m.id === id);
	if (!model) {
		showError(`Varian “${id}” tidak ditemukan di pustaka.`);
		return;
	}
	await loadModel(model);
	// The grid only lists family roots, so highlighting the variant's own id
	// would match nothing. Highlight its root instead — that's the entry the
	// user actually clicked to get here.
	const rootId = model.family?.root || id;
	const inScope = modelsInScope();
	if (inScope.some((m) => m.id === rootId)) setActive(rootId);
}

/* ------------------------------------------------------------------ *
 * Animation timeline
 *
 * Reads the keyframe data straight off the Spine Animation object. Timeline
 * frame layouts differ by type:
 *   - paired  (rotate/translate/scale/shear/IK/deform): [t0,v0, t1,v1, ...]
 *   - single  (attachment, draw order):                 [t0, t1, ...]
 *   - event:                                            [t0, t1, ...] with
 *                                                       names in .events
 * All of them carry a plain `frames` Float32Array, so one reader covers it.
 * ------------------------------------------------------------------ */

const tl = {
	anim: null,      // the Animation object currently shown
	keys: [],        // {time, kind, label} sorted by time
	duration: 0,
	bone: "",        // selected bone name, "" = all
	prop: "",        // selected property, "" = all
	eventsOnly: false,
	dragging: false,
};

/**
 * Maps a timeline to a label + how it stores frames.
 *
 * The class names carry a Spine version suffix ("RotateTimeline3" for the
 * physics-free variant, plain "RotateTimeline" elsewhere), so match on the
 * PREFIX — comparing the full name silently mis-classified every timeline as
 * "other", which then read value floats as if they were times.
 *
 * Frame layouts:
 *   paired (rotate/translate/scale/shear/IK/deform): [t0,v0, t1,v1, ...]
 *   single (attachment, draw order, event):          [t0, t1, ...]
 */
function timelineInfo(t) {
	const n = t.constructor.name;
	switch (true) {
		case n.startsWith("RotateTimeline"):
			return { kind: "rotate", prop: "Rotasi", paired: true };
		case n.startsWith("TranslateTimeline"):
			return { kind: "translate", prop: "Posisi", paired: true };
		case n.startsWith("ScaleTimeline"):
			return { kind: "scale", prop: "Skala", paired: true };
		case n.startsWith("ShearTimeline"):
			return { kind: "shear", prop: "Shear", paired: true };
		case n.startsWith("IkConstraintTimeline"):
			return { kind: "ik", prop: "IK", paired: true };
		case n.startsWith("DeformTimeline"):
			return { kind: "deform", prop: "Deform", paired: true };
		case n.startsWith("AttachmentTimeline"):
			return { kind: "attachment", prop: "Lampiran", paired: false };
		case n.startsWith("DrawOrderTimeline") || n.startsWith("_DrawOrderTimeline"):
			return { kind: "draworder", prop: "Urutan", paired: false };
		case n.startsWith("EventTimeline"):
			return { kind: "event", prop: "Event", paired: false };
		case n.startsWith("ColorTimeline") || n.startsWith("RGBATimeline"):
			return { kind: "color", prop: "Warna", paired: true };
		case n.startsWith("AlphaTimeline"):
			return { kind: "alpha", prop: "Alpha", paired: true };
		default:
			return { kind: "other", prop: n.replace(/\d+$/, "").replace("Timeline", ""), paired: false };
	}
}

/** Name of the bone/slot/constraint a timeline drives, or "" if not applicable. */
function timelineTarget(t, data) {
	try {
		if (t.boneIndex != null && data.bones[t.boneIndex]) return data.bones[t.boneIndex].name;
		if (t.slotIndex != null && data.slots[t.slotIndex]) return data.slots[t.slotIndex].name;
		if (t.ikConstraintIndex != null && data.ikConstraints?.[t.ikConstraintIndex])
			return data.ikConstraints[t.ikConstraintIndex].name;
	} catch {
		/* fall through */
	}
	return "";
}

/** Collect every keyframe of the given animation as {time, kind, prop, bone, label}. */
function collectKeys(anim, data) {
	const out = [];
	if (!anim?.timelines) return out;
	for (const t of anim.timelines) {
		const info = timelineInfo(t);
		const bone = timelineTarget(t, data);
		const frames = t.frames;
		if (!frames) continue;
		const step = info.paired ? 2 : 1;
		for (let i = 0; i < frames.length; i += step) {
			let label = info.prop;
			if (info.kind === "event") {
				const ev = t.events?.[i];
				label = ev?.data?.name || ev?.name || "event";
			} else if (info.kind === "attachment") {
				label = t.attachmentNames?.[i] || "lampiran";
			}
			out.push({
				time: frames[i],
				kind: info.kind,
				prop: info.prop,
				bone,
				label,
			});
		}
	}
	out.sort((a, b) => a.time - b.time);
	// Drop anything outside the clip. A mis-detected frame layout shows up here
	// as absurd times (we saw -202s and 60s on a 0.83s clip); clamping keeps the
	// lane honest instead of silently drawing ticks off-screen.
	const dur = anim.duration || 0;
	return out.filter((k) => Number.isFinite(k.time) && k.time >= 0 && k.time <= dur + 1e-3);
}

function tlVisibleKeys() {
	return tl.keys.filter((k) => {
		if (tl.eventsOnly && k.kind !== "event") return false;
		if (tl.bone && k.bone !== tl.bone) return false;
		if (tl.prop && k.prop !== tl.prop) return false;
		return true;
	});
}

/** Rebuild the timeline for whatever animation is playing. */
function renderTimeline() {
	if (!el.timeline) return;
	const anim = spine?.state?.tracks?.[0]?.animation;
	if (!anim || !spine) {
		tl.anim = null;
		tl.keys = [];
		return;
	}
	// rebuilding the DOM every frame would be wasteful — only redo it when the
	// animation itself changes (or the filters do)
	const changed = tl.anim !== anim;
	tl.anim = anim;
	tl.duration = anim.duration || 0;
	if (changed) {
		tl.keys = collectKeys(anim, spine.skeleton.data);
		tl.bone = "";
		tl.prop = "";
		renderTimelineOptions(anim);
	}
	drawTimelineKeys();
	updateTimelinePlayhead();
}

function renderTimelineOptions(anim) {
	const data = spine.skeleton.data;
	// bones that actually have keyframes in this animation
	const bones = [...new Set(tl.keys.map((k) => k.bone).filter(Boolean))].sort();
	const props = [...new Set(tl.keys.map((k) => k.prop).filter(Boolean))].sort();

	const prevBone = tl.bone;
	fillSelect(el.tlBone, ["Semua tulang", ...bones], "Semua tulang");
	tl.bone = bones.includes(prevBone) ? prevBone : "";
	el.tlBone.value = tl.bone || "Semua tulang";

	const prevProp = tl.prop;
	fillSelect(el.tlProp, ["Semua properti", ...props], "Semua properti");
	tl.prop = props.includes(prevProp) ? prevProp : "";
	el.tlProp.value = tl.prop || "Semua properti";

	// count events so the "hanya event" toggle can say whether there are any
	const evCount = tl.keys.filter((k) => k.kind === "event").length;
	el.tlEventsOnly.disabled = evCount === 0;
	el.tlEventsOnly.parentNode.title = evCount
		? `${evCount} event di animasi ini`
		: "Animasi ini tidak punya event";

	el.tlName.textContent = anim.name || "—";
	el.tlMeta.textContent = `${tl.keys.length} keyframe · ${tl.duration.toFixed(2)}s${
		evCount ? ` · ${evCount} event` : ""
	}`;
}

function drawTimelineKeys() {
	if (!el.tlKeys) return;
	const keys = tlVisibleKeys();
	const dur = tl.duration || 1;
	el.tlKeys.innerHTML = "";
	// An animation can hold 700+ keyframes but the lane is only ~300px wide, so
	// most ticks would land on the same pixel. Collapse anything that falls
	// within one tick-width (3px) of the previous one — dedupe in PIXEL space,
	// not a fixed percentage, so it stays correct at any panel width.
	const width = el.tlKeys.clientWidth || el.tlTrack.clientWidth || 300;
	const minPct = 3 / Math.max(1, width);
	let lastPct = -Infinity;
	for (const k of keys) {
		const pct = Math.max(0, Math.min(1, k.time / dur));
		if (pct - lastPct < minPct) continue;
		lastPct = pct;
		const d = document.createElement("span");
		d.className = "tl-key";
		d.dataset.kind = k.kind;
		d.dataset.time = k.time.toFixed(4);
		d.style.left = (pct * 100).toFixed(3) + "%";
		d.title = `${k.label} — ${k.time.toFixed(3)}s${k.bone ? ` (${k.bone})` : ""}`;
		el.tlKeys.appendChild(d);
	}
	drawTimelineRuler();
}

function drawTimelineRuler() {
	if (!el.tlRuler) return;
	el.tlRuler.innerHTML = "";
	const dur = tl.duration || 1;
	// Aim for a tick roughly every 80px. Ticks are positioned in PERCENT, so
	// the count depends on pixel width — hence the ResizeObserver in
	// initTimeline() that rebuilds this when the panel resizes.
	const width = el.tlRuler.clientWidth || 300;
	const wanted = Math.max(2, Math.floor(width / 80)); // how many ticks fit
	const step = niceStep(dur / wanted);
	// guard against a pathological step producing thousands of ticks
	if (!Number.isFinite(step) || step <= 0) return;
	for (let t = 0; t <= dur + 1e-6; t += step) {
		const d = document.createElement("span");
		d.className = "tl-tick";
		d.style.left = ((t / dur) * 100).toFixed(3) + "%";
		d.textContent = (step < 1 ? t.toFixed(1) : t.toFixed(0)) + "s";
		el.tlRuler.appendChild(d);
	}
}

/** Round a raw step up to a friendly 0.05 / 0.1 / 0.25 / 0.5 / 1 / 2 / 5 s. */
function niceStep(raw) {
	if (!Number.isFinite(raw) || raw <= 0) return 1;
	const candidates = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120];
	for (const c of candidates) if (raw <= c) return c;
	return Math.ceil(raw / 60) * 60;
}

function updateTimelinePlayhead() {
	if (!el.tlPlayhead || !tl.duration) return;
	const t = Math.min(state.trackTime, tl.duration);
	const pct = Math.max(0, Math.min(1, t / tl.duration));
	el.tlPlayhead.style.left = (pct * 100).toFixed(3) + "%";
	el.tlTrack.setAttribute("aria-valuenow", String(Math.round(pct * 100)));
	el.tlTrack.setAttribute("aria-valuetext", `${t.toFixed(2)}s dari ${tl.duration.toFixed(2)}s`);

	// highlight the tick nearest the playhead
	const near = tlVisibleKeys().reduce(
		(best, k) => (Math.abs(k.time - t) < Math.abs(best.time - t) ? k : best),
		{ time: Infinity }
	);
	if (el.tlPos) {
		el.tlPos.textContent = Number.isFinite(near.time)
			? `${near.time.toFixed(2)}s · ${tlVisibleKeys().length} kf`
			: "—";
	}
	// match on data-time rather than string-scanning the title
	for (const d of el.tlKeys.children) {
		const dt = parseFloat(d.dataset.time || "");
		d.classList.toggle(
			"is-near",
			Number.isFinite(dt) && Number.isFinite(near.time) && Math.abs(dt - near.time) < 1e-3
		);
	}
}

/** Jump the playhead to a time, pausing first so it stays where you put it. */
function tlSeek(time) {
	if (!spine || !tl.duration) return;
	const t = Math.max(0, Math.min(tl.duration, time));
	state.trackTime = t;
	const track = spine.state?.tracks?.[0];
	if (track) track.trackTime = t;
	clock.syncTo(t);
	spine.update(0);
	updateScrubUI();
	updateTimelinePlayhead();
}

/** Step to the previous / next visible keyframe. */
function tlStepKey(dir) {
	const keys = tlVisibleKeys();
	if (!keys.length) return;
	const t = state.trackTime;
	if (dir > 0) {
		const next = keys.find((k) => k.time > t + 1e-4);
		tlSeek(next ? next.time : keys[0].time);
	} else {
		const prev = [...keys].reverse().find((k) => k.time < t - 1e-4);
		tlSeek(prev ? prev.time : keys[keys.length - 1].time);
	}
}

function tlTimeFromEvent(e) {
	const r = el.tlTrack.getBoundingClientRect();
	if (!r.width) return 0;
	const pct = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
	return pct * tl.duration;
}

function setTimelineVisible(on) {
	el.timeline.hidden = !on;
	el.timelineBtn.dataset.on = String(on);
	el.timelineBtn.setAttribute("aria-pressed", String(on));
	// Only persist when the user actually toggles it — see initTimeline().
	try {
		localStorage.setItem("spine-stage:timeline", on ? "1" : "0");
	} catch {
		/* private mode — still works for this session */
	}
	// Force a rebuild: the panel may have been opened before any model was
	// loaded (empty data), or after switching to one with different timings.
	tl.anim = null;
	renderTimeline();
}

/** Restore the timeline's visibility from the last session. */
function initTimeline() {
	let stored = null;
	try {
		stored = localStorage.getItem("spine-stage:timeline");
	} catch {
		/* private mode — default to hidden */
	}
	const on = stored === "1";
	// Apply the saved state WITHOUT re-persisting it: writing on every boot
	// would clobber the user's choice with the default before they act.
	el.timeline.hidden = !on;
	el.timelineBtn.dataset.on = String(on);
	el.timelineBtn.setAttribute("aria-pressed", String(on));
	// The ruler is sized in percentages, but the tick COUNT depends on the
	// pixel width, so it has to be rebuilt when the panel resizes.
	const ro = new ResizeObserver(() => {
		if (tl.duration) drawTimelineRuler();
	});
	ro.observe(el.tlTrack);
}

/* --- events --- */
el.timelineBtn?.addEventListener("click", () =>
	setTimelineVisible(el.timeline.hidden)
);
el.tlPrev?.addEventListener("click", () => tlStepKey(-1));
el.tlNext?.addEventListener("click", () => tlStepKey(1));
el.tlBone?.addEventListener("change", () => {
	tl.bone = el.tlBone.value === "Semua tulang" ? "" : el.tlBone.value;
	el.tlProp.value = "Semua properti";
	tl.prop = "";
	drawTimelineKeys();
	updateTimelinePlayhead();
});
el.tlProp?.addEventListener("change", () => {
	tl.prop = el.tlProp.value === "Semua properti" ? "" : el.tlProp.value;
	drawTimelineKeys();
	updateTimelinePlayhead();
});
el.tlEventsOnly?.addEventListener("change", () => {
	tl.eventsOnly = el.tlEventsOnly.checked;
	drawTimelineKeys();
	updateTimelinePlayhead();
});

el.tlTrack?.addEventListener("pointerdown", (e) => {
	tl.dragging = true;
	el.tlTrack.setPointerCapture?.(e.pointerId);
	setPlaying(false); // scrubbing implies pause, like the main scrub bar
	tlSeek(tlTimeFromEvent(e));
});
el.tlTrack?.addEventListener("pointermove", (e) => {
	if (tl.dragging) tlSeek(tlTimeFromEvent(e));
});
const tlEndDrag = (e) => {
	if (!tl.dragging) return;
	tl.dragging = false;
	try {
		el.tlTrack.releasePointerCapture?.(e.pointerId);
	} catch {
		/* pointer already gone */
	}
};
el.tlTrack?.addEventListener("pointerup", tlEndDrag);
el.tlTrack?.addEventListener("pointercancel", tlEndDrag);
el.tlTrack?.addEventListener("keydown", (e) => {
	const step = tl.duration / 100 || 0.01;
	if (e.key === "ArrowRight") {
		e.preventDefault();
		tlSeek(state.trackTime + (e.shiftKey ? step * 10 : step));
	} else if (e.key === "ArrowLeft") {
		e.preventDefault();
		tlSeek(state.trackTime - (e.shiftKey ? step * 10 : step));
	}
});

/* ------------------------------------------------------------------ *
 * Inspector — slot/attachment debug + model comparison
 * ------------------------------------------------------------------ */

const insp = {
	open: false,
	tab: "slots",
	skin: "default",
	query: "",
};

/** Every attachment name a slot can show, across all skins + the setup pose. */
function attachmentsForSlot(data, slotIndex, skinName) {
	const names = new Set();
	// the setup pose attachment is valid even when no skin is applied
	const setup = data.slots?.[slotIndex]?.attachmentName;
	if (setup) names.add(setup);
	// collect from every skin, not just the active one
	for (const s of data.skins || []) {
		const entry = s.attachments?.[slotIndex];
		if (entry) for (const n of Object.keys(entry)) names.add(n);
	}
	return [...names].sort();
}

/**
 * Current attachment shown in a slot.
 * `slot.attachment` is null until a skin is applied; the setup pose lives on
 * slot.data.attachmentName, so fall back to that — otherwise every slot reads
 * as empty on models whose skins aren't named "default".
 */
function slotAttachmentName(slot) {
	return slot?.getAttachment?.()?.name || slot?.data?.attachmentName || "";
}

function renderSlots() {
	if (!el.slotList || !spine) return;
	const data = spine.skeleton.data;
	const q = insp.query.trim().toLowerCase();
	const slots = spine.skeleton.slots;

	el.slotList.innerHTML = "";
	let shown = 0;
	let filled = 0;

	slots.forEach((slot, i) => {
		const name = slot.data.name || `#${i}`;
		if (q && !name.toLowerCase().includes(q)) return;
		shown++;
		const current = slotAttachmentName(slot);
		if (current) filled++;

		const li = document.createElement("li");
		li.className = "slot" + (current ? "" : " is-empty");

		const nm = document.createElement("span");
		nm.className = "slot-name";
		nm.textContent = name;
		nm.title = `slot ${i} · ${name}`;

		const att = document.createElement("span");
		att.className = "slot-att" + (current ? "" : " is-none");
		att.textContent = current || "(kosong)";
		att.title = current || "tidak ada attachment aktif";

		li.append(nm, att);

		// per-slot picker — lets you try an attachment without touching skin
		const opts = attachmentsForSlot(data, i, insp.skin);
		if (opts.length) {
			const sel = document.createElement("select");
			sel.className = "slot-pick";
			sel.title = `${opts.length} attachment tersedia untuk slot ini`;
			const blank = document.createElement("option");
			blank.value = "";
			blank.textContent = current ? "— aktif —" : "—";
			sel.append(blank);
			for (const o of opts) {
				const op = document.createElement("option");
				op.value = o;
				op.textContent = o;
				sel.append(op);
			}
			sel.value = current && opts.includes(current) ? current : "";
			sel.addEventListener("change", () => {
				try {
					spine.skeleton.setAttachment(name, sel.value || null);
				} catch {
					/* attachment not valid for this slot — ignore */
				}
				spine.update(0);
				renderSlots();
			});
			li.append(sel);
		}

		el.slotList.append(li);
	});

	el.slotCount.textContent = `${filled}/${shown} slot terisi · ${slots.length} total`;
}

function renderSkinOptions() {
	if (!el.slotSkin || !spine) return;
	const names = (spine.skeleton.data.skins || []).map((s) => s.name);
	// Not every game ships a skin called "default" (Lost Sword uses "Daily" /
	// "None"), so offer whatever exists plus a no-skin entry.
	fillSelect(el.slotSkin, ["(tanpa skin)", ...names], "(tanpa skin)");
	el.slotSkin.value = names.includes(insp.skin) ? insp.skin : "(tanpa skin)";
	insp.skin = el.slotSkin.value;
}

/** Fill the compare tab's model pickers with the current library listing. */
function renderCompareOptions() {
	if (!el.cmpA || !el.cmpB) return;
	const list = modelsInScope().map((m) => ({ value: m.id, text: modelLabel(m) + " · " + m.id }));
	const opts = list.map((x) => x.value);
	const texts = Object.fromEntries(list.map((x) => [x.value, x.text]));

	const prevA = el.cmpA.value;
	const prevB = el.cmpB.value;
	for (const sel of [el.cmpA, el.cmpB]) {
		sel.innerHTML = "";
		for (const v of opts) {
			const o = document.createElement("option");
			o.value = v;
			o.textContent = texts[v];
			sel.append(o);
		}
	}
	el.cmpA.value = opts.includes(prevA) ? prevA : opts[0];
	el.cmpB.value = opts.includes(prevB) ? prevB : opts[Math.min(1, opts.length - 1)];
}

/** Load a model's skeleton data on demand, for comparison only. */
async function skeletonDataOf(model) {
	if (current && model.id === current.id && spine) return spine.skeleton.data;
	// Same URL rules as loadModel: drop any "#<stem>" suffix and encode per
	// path segment (see the comment there for why).
	const dirPath = String(model.id || "").split("#")[0];
	const base = "/assets/" + dirPath.split("/").map(encodeURIComponent).join("/");
	const atlasUrl = `${base}/${encodeURIComponent(model.atlasFile)}`;
	const skelUrl = `${base}/${encodeURIComponent(model.skeletonFile)}`;
	const isBinary = model.skeletonFile.toLowerCase().endsWith(".skel");

	const atlasText = await fetch(atlasUrl).then((r) => {
		if (!r.ok) throw new Error(`HTTP ${r.status} untuk ${model.atlasFile}`);
		return r.text();
	});
	// Pages are stubbed — we only need structure, never pixels.
	const atlas = new TextureAtlas(atlasText, (line, cb) => {
		cb({ width: 2048, height: 2048, valid: true, scaleMode: 1, setSize() {}, dispose() {} });
	});
	const raw = isBinary
		? await fetch(skelUrl).then((r) => r.arrayBuffer())
		: await fetch(skelUrl).then((r) => r.json());

	// Route through the same version-aware dispatcher the stage uses. This
	// path feeds the "compare" panel, and hard-coding the 4.1 runtime made
	// every 3.8 model log a loader error before the fallback succeeded.
	const { data } = await parseSkeletonData({
		isBinary,
		rawSkeleton: raw,
		atlas,
		scale: model.scale ?? 1,
	});
	return data;
}

function diffSets(a, b) {
	const A = new Set(a);
	const B = new Set(b);
	return {
		same: a.filter((x) => B.has(x)),
		onlyA: a.filter((x) => !B.has(x)),
		onlyB: b.filter((x) => !A.has(x)),
	};
}

function cmpBlock(title, a, b, unit = "") {
	const d = diffSets(a, b);
	const fmt = (n) => `${n}${unit}`;
	const el = document.createElement("div");
	el.className = "cmp-group";
	const h = document.createElement("h4");
	h.textContent = `${title} — ${fmt(d.same.length)} sama · hanya A ${fmt(d.onlyA.length)} · hanya B ${fmt(d.onlyB.length)}`;
	el.append(h);

	const items = document.createElement("div");
	items.className = "cmp-items";
	if (!d.onlyA.length && !d.onlyB.length) {
		const p = document.createElement("span");
		p.className = "cmp-empty";
		p.textContent = "identik";
		items.append(p);
	}
	for (const x of d.onlyA.slice(0, 40)) {
		const s = document.createElement("span");
		s.className = "cmp-item";
		s.dataset.tone = "only-a";
		s.textContent = "+ " + x;
		items.append(s);
	}
	for (const x of d.onlyB.slice(0, 40)) {
		const s = document.createElement("span");
		s.className = "cmp-item";
		s.dataset.tone = "only-b";
		s.textContent = "− " + x;
		items.append(s);
	}
	el.append(items);
	return el;
}

async function runCompare() {
	if (!el.cmpResult) return;
	const idA = el.cmpA.value;
	const idB = el.cmpB.value;
	if (!idA || !idB) return;
	el.cmpResult.innerHTML = '<div class="cmp-empty">Memuat…</div>';

	try {
		const mA = models.find((m) => m.id === idA);
		const mB = models.find((m) => m.id === idB);
		if (!mA || !mB) throw new Error("Model tidak ditemukan di pustaka");
		const [dA, dB] = await Promise.all([skeletonDataOf(mA), skeletonDataOf(mB)]);

		const names = (d) => (d.bones || []).map((b) => b.name);
		const slots = (d) => (d.slots || []).map((s) => s.name);
		const anims = (d) => (d.animations || []).map((a) => a.name);
		const skins = (d) => (d.skins || []).map((s) => s.name);
		const atts = (d) => {
			const out = new Set();
			for (const s of d.skins || [])
				for (const idx of Object.keys(s.attachments || {}))
					for (const n of Object.keys(s.attachments[idx] || {})) out.add(n);
			return [...out];
		};

		el.cmpResult.innerHTML = "";

		const sum = document.createElement("div");
		sum.className = "cmp-sum";
		const chip = (label, tone) => {
			const c = document.createElement("span");
			c.className = "cmp-chip";
			c.dataset.tone = tone;
			c.textContent = label;
			return c;
		};
		sum.append(
			chip(`A: ${modelLabel(mA)}`, "only-a"),
			chip(`B: ${modelLabel(mB)}`, "only-b"),
			chip(`tulang ${(dA.bones || []).length} vs ${(dB.bones || []).length}`, "same"),
			chip(`slot ${(dA.slots || []).length} vs ${(dB.slots || []).length}`, "same"),
			chip(`animasi ${(dA.animations || []).length} vs ${(dB.animations || []).length}`, "same")
		);
		el.cmpResult.append(sum);

		el.cmpResult.append(cmpBlock("Tulang", names(dA), names(dB)));
		el.cmpResult.append(cmpBlock("Slot", slots(dA), slots(dB)));
		el.cmpResult.append(cmpBlock("Animasi", anims(dA), anims(dB)));
		el.cmpResult.append(cmpBlock("Skin", skins(dA), skins(dB)));
		el.cmpResult.append(cmpBlock("Attachment", atts(dA), atts(dB)));
	} catch (e) {
		el.cmpResult.innerHTML = `<div class="cmp-empty">Gagal membandingkan: ${escapeHtml(
			String(e.message || e)
		)}</div>`;
	}
}

function setInspectorTab(tab) {
	insp.tab = tab;
	for (const b of document.querySelectorAll(".insp-tab")) {
		b.classList.toggle("is-on", b.dataset.tab === tab);
	}
	el.slotList.closest(".insp-body").hidden = tab !== "slots";
	el.cmpResult.closest(".insp-body").hidden = tab !== "compare";
	if (tab === "compare") renderCompareOptions();
	if (tab === "slots") renderSlots();
}

function setInspectorVisible(on) {
	insp.open = on;
	el.inspector.hidden = !on;
	el.inspectorBtn.dataset.on = String(on);
	el.inspectorBtn.setAttribute("aria-pressed", String(on));
	try {
		localStorage.setItem("spine-stage:inspector", on ? "1" : "0");
	} catch {
		/* private mode */
	}
	if (on) {
		renderSkinOptions();
		setInspectorTab(insp.tab);
	} else if (spine) {
		// leaving the panel: drop any per-slot overrides so the model snaps back
		spine.skeleton.setSlotsToSetupPose();
		spine.update(0);
		renderHud();
	}
}

function initInspector() {
	let stored = null;
	try {
		stored = localStorage.getItem("spine-stage:inspector");
	} catch {
		/* private mode */
	}
	const on = stored === "1";
	el.inspector.hidden = !on;
	el.inspectorBtn.dataset.on = String(on);
	insp.open = on;

	el.inspectorBtn?.addEventListener("click", () => setInspectorVisible(el.inspector.hidden));
	el.inspectorClose?.addEventListener("click", () => setInspectorVisible(false));
	for (const b of document.querySelectorAll(".insp-tab")) {
		b.addEventListener("click", () => setInspectorTab(b.dataset.tab));
	}
	el.slotSearch?.addEventListener("input", () => {
		insp.query = el.slotSearch.value;
		renderSlots();
	});
	el.slotSkin?.addEventListener("change", () => {
		insp.skin = el.slotSkin.value;
		// "(tanpa skin)" resets to the setup pose
		setSkin(insp.skin === "(tanpa skin)" ? null : insp.skin);
		renderSlots();
	});
	el.cmpRun?.addEventListener("click", runCompare);
}

function setSkin(name) {
	if (!spine) return;
	try {
		if (name) spine.skeleton.setSkinByName(name);
		else spine.skeleton.setSkin(null); // back to the setup pose
		spine.skeleton.setSlotsToSetupPose();
	} catch (err) {
		console.warn("skin", err);
	}
	spine.update(0);
}

function setPlaying(v) {
	state.playing = v;
	el.playBtn.dataset.playing = String(v);
	el.playBtn.setAttribute("aria-label", v ? "Jeda" : "Mainkan");
	el.playBtn.querySelector(".icon").innerHTML = v ? ICON.pause : ICON.play;
}

/* ------------------------------------------------------------------ *
 * HUD
 * ------------------------------------------------------------------ */
/** Part count for a Cubism coreModel, or null when unavailable. */
function modelPartCount(core) {
	if (core && typeof core.getPartCount === "function") {
		try {
			return core.getPartCount();
		} catch {
			return null;
		}
	}
	return null;
}

function renderHud() {
	if (!current || !spine) {
		el.hud.hidden = true;
		return;
	}
	el.hud.hidden = false;
	// Cubism models have no Spine skeleton; show what they do expose.
	if (isLive2D(current)) {
		const core = spine.internalModel?.coreModel;
		const d = core && typeof core.getDrawableCount === "function" ? core.getDrawableCount() : null;
		const p = modelPartCount(core);
		const tex = (current.textureFiles || []).length;
		$("#hud-model").textContent = current.name;
		$("#hud-stats").innerHTML =
			(d != null ? `<span><b>${d}</b> drawable</span>` : "") +
			(p != null ? `<span><b>${p}</b> part</span>` : "") +
			`<span><b>${tex}</b> tekstur</span>` +
			`<span><b>Live2D Cubism 4</b></span>` +
			(current.family ? `<span><b>${current.family.members.length}</b> varian</span>` : "");
		$("#title-model").textContent = current.name;
		return;
	}
	const slots = spine.skeleton.slots.length;
	const bones = spine.skeleton.bones.length;
	const anims = spine.skeleton.data.animations.length;
	$("#hud-model").textContent = current.name;
	$("#hud-stats").innerHTML =
		`<span><b>${slots}</b> slot</span>` +
		`<span><b>${bones}</b> tulang</span>` +
		`<span><b>${anims}</b> animasi</span>` +
		`<span data-pma="${pmaMode === PMA_MODES.upload ? "upload" : pmaActive() ? "on" : "off"}"><b>PMA ${pmaMode === PMA_MODES.upload ? "upload" : pmaActive() ? "aktif" : "nonaktif"}</b></span>` +
		// Show the variant count when there is a family, so it's obvious the
		// model has siblings even before the dropdown is noticed.
		(current.family
			? `<span><b>${current.family.members.length}</b> varian</span>`
			: "") +
		// Show the real Spine version + which runtime parsed it. When these
		// disagree with what the file claims (older models), it's the fastest
		// way to see why a model loaded — or didn't.
		(spineVersion
			? `<span><b>Spine ${spineVersion}</b></span>`
			: current.spine ? `<span><b>${current.spine}</b></span>` : "") +
		(spineRuntime && spineRuntime !== "4.1"
			? `<span><b>runtime ${spineRuntime}</b></span>`
			: "");
	$("#title-model").textContent = current.name;
	el.delBtn.hidden = false;
}

/* ------------------------------------------------------------------ *
 * Animation clock
 *
 * Wall-clock time (`performance.now`, `setTimeout`, ticker deltaMS) is the
 * wrong clock for anything tied to the skeleton: it keeps running while the
 * model is paused, ignores the speed control, and desynchronises the moment
 * a frame is slow. Everything that cares "how far into the animation are
 * we?" reads this instead.
 *
 * `now` is authored seconds: it advances by the ticker delta scaled by the
 * current rate, holds at its value while paused, and never jumps. Changing
 * the speed mid-flight simply changes how fast it advances from here —
 * nothing already scheduled needs rewriting.
 *
 * Deliberately NOT used for UI timers (toasts, resize debounce): those are
 * wall-clock concerns and should keep running while the model is paused.
 * ------------------------------------------------------------------ */

const clock = {
	now: 0,
	rate: () => state.rate,
	/** Advance the clock. Returns the delta actually applied, in seconds. */
	tick(deltaMS) {
		const d = (deltaMS / 1000) * (this.rate() || 0);
		this.now += d;
		return d;
	},
	/**
	 * Re-anchor the clock to an authored position.
	 *
	 * Used when something other than playback moves the playhead (a scrub, a
	 * seek, a new animation). Without this the clock would keep its own value
	 * and anything reading it would disagree with the skeleton about where we
	 * are — the exact desync this clock exists to prevent.
	 */
	syncTo(seconds) {
		if (Number.isFinite(seconds)) this.now = seconds;
	},
};

/* ------------------------------------------------------------------ *
 * Part picker — click a drawn part of the model to inspect it
 *
 * The overlay draws each attachment's posed bounding polygon, but the HIT
 * TEST runs against the same SkeletonBounds instance, never against the
 * drawn graphic. That matters: the graphic is a flattened approximation
 * redrawn every frame, while the bounds are the authoritative posed shape.
 * Testing against what we drew would let the two drift apart and report a
 * hit on a part that isn't under the cursor.
 *
 * Only bounding boxes (named regions) are pickable — that is the subset the
 * runtime gives us a name for, and the only subset worth naming in a viewer.
 * ------------------------------------------------------------------ */

const PARTS_KEY = "spine-stage:parts";

const parts = {
	on: false,
	bounds: null,
	gfx: null,
	hover: null,
};

function partGraphics() {
	if (parts.gfx) return parts.gfx;
	parts.gfx = new Graphics();
	parts.gfx.visible = false;
	parts.gfx.zIndex = 10;
	stageRoot.addChild(parts.gfx);
	return parts.gfx;
}

/** Draw the posed polygon for every named bounding-box attachment. */
function drawParts() {
	const gfx = partGraphics();
	gfx.clear();
	if (!parts.on || !spine) {
		gfx.visible = false;
		return;
	}
	if (!parts.bounds) {
		try {
			parts.bounds = new SkeletonBounds();
		} catch {
			return;
		}
	}
	parts.bounds.update(spine.skeleton, true);
	const polys = parts.bounds.polygons || [];
	const boxes = parts.bounds.boundingBoxes || [];
	if (!polys.length) {
		gfx.visible = false;
		return;
	}
	gfx.visible = true;

	// Stroke width in skeleton units so it stays thin at any zoom.
	const w = 1.5 / Math.max(state.zoom, 0.0001);
	gfx.lineStyle(w, 0x7fd1ff, 0.85);
	for (let i = 0; i < polys.length; i++) {
		const v = polys[i];
		if (!v || v.length < 6) continue;
		const name = boxes[i]?.name || boxes[i]?.data?.name || "";
		const hot = parts.hover && parts.hover === name;
		gfx.lineStyle(w, hot ? 0xffb02e : 0x7fd1ff, hot ? 1 : 0.65);
		gfx.beginFill(hot ? 0xffb02e : 0x7fd1ff, hot ? 0.16 : 0.05);
		gfx.moveTo(v[0], v[1]);
		for (let k = 2; k < v.length; k += 2) gfx.lineTo(v[k], v[k + 1]);
		gfx.closePath();
		gfx.endFill();
	}
}

/**
 * Which named bounding box is under this stage point, or null.
 * `x`/`y` are in stage-local (skeleton) coordinates.
 */
function partAt(x, y) {
	if (!spine || !parts.bounds) return null;
	try {
		const hit = parts.bounds.containsPoint(x, y);
		if (!hit) return null;
		return hit.name || hit.data?.name || null;
	} catch {
		return null;
	}
}

function setPartsVisible(on) {
	parts.on = on;
	parts.hover = null;
	el.partsBtn.dataset.on = String(on);
	el.partsBtn.setAttribute("aria-pressed", String(on));
	try {
		localStorage.setItem(PARTS_KEY, on ? "1" : "0");
	} catch {
		/* private mode */
	}
	// Rebuilding the bounds is cheap and avoids a stale pose from a model
	// that has since been swapped out.
	parts.bounds = null;
	drawParts();
}

function initParts() {
	let stored = null;
	try {
		stored = localStorage.getItem(PARTS_KEY);
	} catch {
		/* private mode */
	}
	const on = stored === "1";
	parts.on = on;
	el.partsBtn.dataset.on = String(on);
	el.partsBtn.setAttribute("aria-pressed", String(on));
}

/* ------------------------------------------------------------------ *
 * FPS meter
 *
 * Measures what the Pixi ticker actually delivers — the honest number for
 * "can this model hold 60?" — rather than anything the display claims.
 *
 * The big readout is averaged over a 250ms window so it is readable instead
 * of flickering every frame, but min/avg accumulate per FRAME. A single
 * hitch therefore stays visible in "min" even though the headline number
 * smoothed over it, which is exactly what you want when checking whether a
 * heavy skeleton stutters.
 * ------------------------------------------------------------------ */

const FPS_KEY = "spine-stage:fps";
const FPS_WINDOW_MS = 250; // how often the readout is republished
const FPS_GRAPH_POINTS = 80; // rolling samples drawn in the sparkline
const FPS_WARMUP = 20; // frames discarded after enabling / loading

const fps = {
	on: false,
	external: false, // true while the legacy 2.1.27 iframe owns the pixels
	frames: 0, // frames counted in the current window
	elapsed: 0, // ms accumulated in the current window
	shown: 0, // last published rolling average
	min: Infinity,
	sum: 0,
	count: 0,
	warmup: 0,
	peak: 0, // best sustained window seen -> proxy for refresh rate
	history: [],
	ctx: null,
	dpr: 0,
};

/** Estimated refresh rate of the panel, so tiers scale on 120Hz displays. */
function fpsRefreshRate() {
	const raw = fps.peak || 60;
	// Snap up to whatever common rate the observed peak fits: a 59.94Hz panel
	// should read as "60", not as permanently dropping frames.
	for (const c of [60, 75, 90, 100, 120, 144, 165, 240]) {
		if (raw <= c * 1.08) return c;
	}
	return Math.round(raw);
}

/** Discard the next few frames — asset uploads and are not render cost. */
function fpsWarmup() {
	fps.warmup = FPS_WARMUP;
	fps.frames = 0;
	fps.elapsed = 0;
}

function fpsResetStats() {
	fps.min = Infinity;
	fps.sum = 0;
	fps.count = 0;
	fps.peak = 0;
	fps.shown = 0;
	fps.history = [];
	// Warm up AND suppress publishing for the first window: without this the
	// readout refills within ~250ms and the reset looks like it did nothing.
	fps.warmup = FPS_WARMUP + Math.ceil(FPS_WINDOW_MS / 16);
	fps.frames = 0;
	fps.elapsed = 0;
	fpsPaint();
	fpsDrawGraph();
}

function fpsPaint() {
	if (!el.fpsMeter) return;
	// While the legacy viewer drives its own iframe, our ticker is not what
	// draws the model, so any number here would be meaningless.
	if (fps.external) {
		el.fpsValue.textContent = "—";
		el.fpsMin.textContent = "min —";
		el.fpsAvg.textContent = "avg —";
		el.fpsMeter.dataset.tier = "good";
		el.fpsMeter.title = "Penampil legacy (Spine 2.1.27) berjalan di iframe sendiri — FPS tidak terukur.";
		return;
	}
	el.fpsMeter.removeAttribute("title");
	const have = Number.isFinite(fps.min) && fps.count > 0;
	el.fpsValue.textContent = fps.shown ? String(Math.round(fps.shown)) : "—";
	el.fpsMin.textContent = `min ${have ? Math.round(fps.min) : "—"}`;
	el.fpsAvg.textContent = `avg ${have ? Math.round(fps.sum / fps.count) : "—"}`;

	const rate = fpsRefreshRate();
	// Colour carries the verdict: green at full rate, amber once frames are
	// actually being missed, red under half.
	const tier = !fps.shown ? "good" : fps.shown >= rate * 0.9 ? "good" : fps.shown >= rate * 0.5 ? "ok" : "bad";
	el.fpsMeter.dataset.tier = tier;
}

/** Size the sparkline's backing store for the device pixel ratio, once. */
function fpsSizeCanvas() {
	if (!el.fpsGraph) return;
	const dpr = Math.min(window.devicePixelRatio || 1, 2);
	const cssW = el.fpsGraph.clientWidth || 160;
	const cssH = el.fpsGraph.clientHeight || 34;
	if (fps.dpr === dpr && el.fpsGraph.width === Math.round(cssW * dpr)) return;
	fps.dpr = dpr;
	el.fpsGraph.width = Math.round(cssW * dpr);
	el.fpsGraph.height = Math.round(cssH * dpr);
	if (fps.ctx) fps.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function fpsDrawGraph() {
	if (!el.fpsGraph) return;
	// Hidden on phones and under prefers-reduced-motion — nothing to draw.
	if (!el.fpsGraph.offsetParent) return;
	if (!fps.ctx) {
		fps.ctx = el.fpsGraph.getContext("2d");
		fpsSizeCanvas();
		if (fps.ctx) fps.ctx.setTransform(fps.dpr, 0, 0, fps.dpr, 0, 0);
	}
	const ctx = fps.ctx;
	if (!ctx) return;
	const w = el.fpsGraph.width / (fps.dpr || 1);
	const h = el.fpsGraph.height / (fps.dpr || 1);
	ctx.clearRect(0, 0, w, h);

	const rate = fpsRefreshRate();
	const scale = Math.max(rate, fps.shown || 0) * 1.1;

	// Reference line at the target rate: everything below it is a dropped frame.
	const y = (v) => h - Math.min(1, v / scale) * (h - 1) - 0.5;
	const lineY = y(rate);
	ctx.strokeStyle = "rgba(255,255,255,0.16)";
	ctx.lineWidth = 1;
	ctx.beginPath();
	ctx.moveTo(0, lineY);
	ctx.lineTo(w, lineY);
	ctx.stroke();

	if (!fps.history.length) return;

	// Bars, coloured by how far below target each sample sat.
	const slot = w / FPS_GRAPH_POINTS;
	const bw = Math.max(1, slot - 0.6);
	for (let i = 0; i < fps.history.length; i++) {
		const v = fps.history[i];
		const top = y(v);
		ctx.fillStyle = v >= rate * 0.9 ? "#7fd1ff" : v >= rate * 0.5 ? "#ffb02e" : "#ff6b5e";
		ctx.fillRect(i * slot, top, bw, h - top);
	}
}

/** Called every frame from the Pixi ticker. */
function fpsSample(deltaMS) {
	if (!fps.on || fps.external) return;
	// Returning from a backgrounded tab delivers one enormous frame; counting
	// it would pin "min" to something like 2fps for the rest of the session.
	if (!(deltaMS > 0) || deltaMS > 500) return;

	if (fps.warmup > 0) {
		fps.warmup--;
		fps.frames = 0;
		fps.elapsed = 0;
		return;
	}

	const instant = 1000 / deltaMS;
	fps.frames++;
	fps.elapsed += deltaMS;
	fps.sum += instant;
	fps.count++;
	if (instant < fps.min) fps.min = instant;

	if (fps.elapsed >= FPS_WINDOW_MS) {
		const windowed = (fps.frames * 1000) / fps.elapsed;
		fps.shown = windowed;
		if (windowed > fps.peak) fps.peak = windowed;
		fps.history.push(windowed);
		if (fps.history.length > FPS_GRAPH_POINTS) fps.history.shift();
		fps.frames = 0;
		fps.elapsed = 0;
		fpsPaint();
		fpsDrawGraph();
	}
}

function setFpsVisible(on) {
	fps.on = on;
	el.fpsMeter.hidden = !on;
	el.fpsBtn.dataset.on = String(on);
	el.fpsBtn.setAttribute("aria-pressed", String(on));
	try {
		localStorage.setItem(FPS_KEY, on ? "1" : "0");
	} catch {
		/* private mode — works for this session */
	}
	if (on) {
		fpsResetStats();
		fpsSizeCanvas();
	} else {
		fps.history = [];
		fps.shown = 0;
	}
}

/** Restore visibility from the last session, without re-persisting it. */
function initFps() {
	let stored = null;
	try {
		stored = localStorage.getItem(FPS_KEY);
	} catch {
		/* private mode */
	}
	const on = stored === "1";
	fps.on = on;
	el.fpsMeter.hidden = !on;
	el.fpsBtn.dataset.on = String(on);
	el.fpsBtn.setAttribute("aria-pressed", String(on));
	if (on) fpsWarmup();
}

/* The ticker is the real clock here: it fires once per rendered frame, which
 * is exactly the interval we are trying to measure. Registered separately
 * from the render loop above, which bails out early when no model is loaded
 * — the meter should still read even on an empty stage. */
app.ticker.add(() => fpsSample(app.ticker.deltaMS));

window.addEventListener("resize", () => {
	if (!fps.on) return;
	fps.ctx = null; // force a fresh backing store at the new size
	fpsSizeCanvas();
	fpsDrawGraph();
});

/* ------------------------------------------------------------------ *
 * Model list
 * ------------------------------------------------------------------ */
let models = [];
/** model id -> thumbnail path relative to /thumbs (e.g. "nikke/xxx.png") */
let thumbs = {};
/** game key -> icon URL under /thumbs/_game/ */
let gameIcons = {};

/* Two-step browse: the sidebar shows games first; picking one swaps in a
 * paginated grid of that game's models. With 2000+ models a single scrolling
 * list is unusable, and a <select> filter hides how big each library is. */
const PAGE_SIZE = 60;
const browse = { view: "games", game: null, page: 1, favOnly: false };

/**
 * Games, A→Z by display label.
 *
 * Was sorted biggest-library-first, which is nice for discovery but makes a
 * known title impossible to find by eye once there are 20+ games. Alphabetical
 * sort uses localeCompare with numeric: true so "Epic Seven 2" doesn't land
 * before "Epic Seven", and sensitivity: "base" so accents don't reorder.
 */
function gameBuckets() {
	const seen = new Map();
	for (const m of models) {
		const key = m.game || "lainnya";
		if (!seen.has(key)) seen.set(key, { key, label: m.gameLabel || "Lainnya", items: [] });
		seen.get(key).items.push(m);
	}
	return [...seen.values()].sort((a, b) =>
		(a.label || a.key).localeCompare(b.label || b.key, undefined, {
			numeric: true,
			sensitivity: "base",
		})
	);
}

/** One or two letters to stand in for a game with no logo. */
const badgeLetter = (label) => (label || "?").trim().charAt(0).toUpperCase();

/**
 * Label for one grid card. Prefers the real character name, and appends the
 * variant so c010 / c010+aim / c010+cover don't read as three identical "Rapi".
 */
function modelLabel(m) {
	if (m.character) {
		const v = m.family && m.family.root !== m.id ? " " + m.family.label : "";
		return `${m.character.name}${v}`;
	}
	return m.id.split("/").pop();
}

/** Extra line for the card: character details when we have them. */
function modelSubLabel(m) {
	if (!m.character) return null;
	// BD2 entries carry a costume name rather than Nikke's class/squad; show
	// it here or every card in the game looks identical ("Lathel" ×6).
	if (m.character.costume) return m.character.costume;
	// rarity + class only — the card is ~100px wide and adding the squad
	// pushed every name into an ellipsis. Squad stays in the tooltip.
	const bits = [m.character.rarity, m.character.class].filter(Boolean);
	return bits.join(" · ") || null;
}

/** Everything we know, for the hover tooltip. */
function modelTooltip(m) {
	if (!m.character) return m.id;
	// BD2: rarity + costume is the useful pair (no class/squad/element).
	if (m.character.costume) {
		const cbits = [m.character.rarity, m.character.costume].filter(Boolean).join(" · ");
		return cbits ? `${m.id}\n${m.character.name} — ${cbits}` : `${m.id}\n${m.character.name}`;
	}
	const bits = [m.character.rarity, m.character.class, m.character.squad, m.character.element]
		.filter(Boolean)
		.join(" · ");
	return bits ? `${m.id}\n${m.character.name} — ${bits}` : `${m.id}\n${m.character.name}`;
}

/**
 * "725 model · +776 varian" — the grid lists characters only, so the hidden
 * variant count is spelled out instead of silently vanishing from the total.
 */
function gameSummary(items) {
	const roots = items.filter((m) => !m.family || m.family.root === m.id);
	const variants = items.length - roots.length;
	return variants
		? `${roots.length} model · +${variants} varian`
		: `${roots.length} model`;
}

/**
 * Fallback shown when a model has no thumbnail art (~7% of Nikke, and every
 * BD2 model). Uses the TAIL of the id, not the head: BD2 ids like
 * avatarbodyaccessory_1006 / _1007 all share a long prefix, so leading chars
 * produced the same badge for every card in the grid.
 */
function initials(m) {
	// use the character name when we have one — "RA" beats "C01"
	if (m.character?.name) {
		const clean = m.character.name.split(":")[0].trim();
		const parts = clean.split(/\s+/);
		if (parts.length > 1) return (parts[0][0] + parts[1][0]).toUpperCase();
		return clean.slice(0, 2).toUpperCase();
	}
	const leaf = (m.id || "").split("/").pop() || "?";
	const alnum = leaf.replace(/[^a-z0-9]/gi, "");
	if (!alnum) return "?";
	// keep the last 2 digits-if-any plus a leading letter when it's short
	const digits = (alnum.match(/\d+$/) || [""])[0];
	const letters = alnum.slice(0, alnum.length - digits.length).replace(/[^a-z]/gi, "");
	if (digits) return (letters.slice(-1) + digits.slice(-2)).toUpperCase();
	return alnum.slice(0, 3).toUpperCase();
}

function renderGames(filter = "") {
	const q = filter.trim().toLowerCase();
	el.gameList.innerHTML = "";
	// Same "Favorit" filter applies here: only keep games that actually
	// contain a starred model, otherwise the grid looks unchanged.
	let buckets = gameBuckets().filter(
		(g) => !q || g.label.toLowerCase().includes(q) || g.key.includes(q)
	);
	if (browse.favOnly) {
		buckets = buckets
			.map((g) => ({ ...g, items: g.items.filter((m) => favorites.has(m.id)) }))
			.filter((g) => g.items.length);
	}

	if (!buckets.length) {
		el.gameList.innerHTML = `<li class="list-empty">Tidak ada game yang cocok.</li>`;
	}
	for (const g of buckets) {
		const li = document.createElement("li");
		const btn = document.createElement("button");
		btn.className = "game";
		btn.dataset.key = g.key;
		btn.innerHTML = `
			<span class="game-badge"></span>
			<span class="game-body">
				<span class="game-name">${escapeHtml(g.label)}</span>
				<span class="game-meta">${escapeHtml(gameSummary(g.items))}</span>
			</span>
			<svg viewBox="0 0 24 24" class="game-chevron" aria-hidden="true"><path d="M9 6l6 6-6 6z"/></svg>
		`;
		// Prefer the game's own icon; fall back to the letter badge when there
		// isn't one, so a missing image never leaves an empty box.
		const badge = btn.querySelector(".game-badge");
		const src = gameIcons[g.key];
		if (src) {
			const icon = document.createElement("img");
			icon.className = "game-icon";
			icon.src = src;
			icon.alt = "";
			icon.loading = "lazy";
			icon.decoding = "async";
			// Still guard on error: the file can vanish after the manifest
			// was read, and a broken image beats an empty badge.
			icon.addEventListener(
				"error",
				() => {
					icon.remove();
					badge.textContent = badgeLetter(g.label);
				},
				{ once: true }
			);
			badge.appendChild(icon);
		} else {
			badge.textContent = badgeLetter(g.label);
		}
		btn.addEventListener("click", () => openGame(g.key));
		li.appendChild(btn);
		el.gameList.appendChild(li);
	}
	el.count.textContent = String(buckets.length);
}

function openGame(key) {
	browse.view = "models";
	browse.game = key;
	browse.page = 1;
	el.search.value = "";
	// Must go through syncPanes: renderModels fills the grid, but the pane it
	// lives in starts `hidden`, so calling renderModels directly renders into
	// a container nobody can see.
	renderLibrary();
}

function backToGames() {
	browse.view = "games";
	browse.game = null;
	browse.page = 1;
	el.search.value = "";
	renderLibrary();
}

/** Models of the current game, filtered by the search box. */
function modelsInScope() {
	const q = el.search.value.trim().toLowerCase();
	const inGame = browse.game ? models.filter((m) => (m.game || "lainnya") === browse.game) : models;
	// "Favorit" filter: narrow to starred models before anything else, so it
	// works from either the game grid or a single game's list.
	const scoped = browse.favOnly ? inGame.filter((m) => favorites.has(m.id)) : inGame;
	// Variants (nikke/c010/aim, /cover) are reachable from the stage's "Varian"
	// dropdown, so listing them here too just tripled the grid — 776 of Nikke's
	// 1501 entries were duplicates of a character already in the list.
	const roots = scoped.filter((m) => !m.family || m.family.root === m.id);
	// Models added by the updater float to the top so a fresh download is
	// visible without hunting for it; newest first, then alphabetical.
	const order = (list) =>
		list.slice().sort((a, b) => {
			const na = isNewModel(a) ? loadNewSet()[a.id] || 0 : 0;
			const nb = isNewModel(b) ? loadNewSet()[b.id] || 0 : 0;
			if (na || nb) {
				if (na !== nb) return nb - na;      // baru lebih dulu
				return a.id.localeCompare(b.id);
			}
			return a.id.localeCompare(b.id);
		});
	const hit = (m) =>
		m.id.toLowerCase().includes(q) ||
		(m.name || "").toLowerCase().includes(q) ||
		// search must hit character names too — that's the whole point of
		// loading them ("rapi" should find c010, "matis" finds the squad)
		(m.character?.name || "").toLowerCase().includes(q) ||
		(m.character?.squad || "").toLowerCase().includes(q);
	return order(q ? roots.filter(hit) : roots);
}

/** How many variants are hidden from the grid for the current game. */
function hiddenVariantCount() {
	const inGame = browse.game ? models.filter((m) => (m.game || "lainnya") === browse.game) : models;
	return inGame.filter((m) => m.family && m.family.root !== m.id).length;
}

function renderModels() {
	const list = modelsInScope();
	const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
	// Clamp so deleting a model or narrowing a search can't strand us off-list.
	if (browse.page > pages) browse.page = pages;
	if (browse.page < 1) browse.page = 1;

	const start = (browse.page - 1) * PAGE_SIZE;
	const slice = list.slice(start, start + PAGE_SIZE);

	el.list.innerHTML = "";
	if (!slice.length) {
		el.list.innerHTML = `<li class="list-empty">Tidak ada model yang cocok.</li>`;
	}
	for (const m of slice) {
		const li = document.createElement("li");
		const btn = document.createElement("button");
		btn.className = "model";
		btn.dataset.id = m.id;
		// Show the real asset id — with 2000+ models an auto-titlecased name
		// ("Char000101") is far less useful than the id itself.
		const file = thumbs[m.id];
		// The manifest value is "<game>/<file>" (older Nikke entries ship a
		// bare filename), so encode per segment: encoding the slash turned
		// "azurlane/x.png" into one opaque segment and 404'd.
		const thumbPath = file
			? String(file).split("/").map(encodeURIComponent).join("/")
			: "";
		const art = file
			? `<img class="model-thumb" src="/thumbs/${thumbPath}" alt="" loading="lazy" decoding="async" width="128" height="128" />`
			: `<span class="model-thumb model-thumb-none" aria-hidden="true">${escapeHtml(
					initials(m)
			  )}</span>`;
		// Tooltip carries the full id + character details; the card itself
		// can only fit the short label.
		const details = modelSubLabel(m);
		btn.title = modelTooltip(m);
		const newTag = isNewModel(m)
			? `<span class="badge-new" title="Baru ditambahkan">NEW</span>`
			: "";
		btn.innerHTML = `
		${art}
		<span class="model-text">
			<span class="model-name">${escapeHtml(modelLabel(m))}${newTag}</span>
			<span class="model-meta">${details ? escapeHtml(details) + " · " : ""}${m.animations.length ? m.animations.length + " animasi" : "—"}</span>
		</span>
		`;
		btn.addEventListener("click", () => loadModel(m));

		// Star toggle. Nested inside the card, but a separate button so
		// clicking it doesn't also load the model.
		const star = document.createElement("button");
		star.className = "model-fav" + (isFavorite(m.id) ? " is-on" : "");
		star.type = "button";
		star.setAttribute("aria-pressed", String(isFavorite(m.id)));
		star.setAttribute("aria-label", isFavorite(m.id) ? "Hapus dari favorit" : "Tambah ke favorit");
		star.title = isFavorite(m.id) ? "Hapus dari favorit" : "Tambah ke favorit";
		// Build a real <svg> element — assigning the bare <path> markup from
		// ICON.star renders nothing, because innerHTML parses it as an unknown
		// top-level element instead of an SVG graphic.
		star.innerHTML = `<svg viewBox="0 0 24 24" class="icon" aria-hidden="true">${ICON.star}</svg>`;
		star.addEventListener("click", (ev) => {
			ev.stopPropagation();
			toggleFavorite(m.id);
		});
		li.appendChild(btn);
		li.appendChild(star);
		el.list.appendChild(li);
	}

	el.count.textContent = String(list.length);
	renderPager(pages, list.length, start, slice.length);
	if (current) setActive(current.id);
}

/** Page buttons with a sliding window so 26 pages don't render 26 buttons. */
function renderPager(pages, total, start, shown) {
	el.pager.innerHTML = "";
	if (pages <= 1) {
		el.pager.innerHTML = `<span class="pager-info">${total} model</span>`;
		return;
	}

	const add = (label, page, { disabled = false, current: isCur = false } = {}) => {
		const b = document.createElement("button");
		b.className = "pager-btn" + (isCur ? " is-current" : "");
		b.textContent = label;
		b.disabled = disabled;
		if (!disabled && !isCur) b.addEventListener("click", () => gotoPage(page));
		el.pager.appendChild(b);
	};

	const addGap = () => {
		const s = document.createElement("span");
		s.className = "pager-info";
		s.textContent = "…";
		el.pager.appendChild(s);
	};

	add("‹", browse.page - 1, { disabled: browse.page <= 1 });

	const window_ = 2; // pages shown on each side of the current one
	const nums = new Set([1, pages]);
	for (let p = browse.page - window_; p <= browse.page + window_; p++) {
		if (p >= 1 && p <= pages) nums.add(p);
	}
	const sorted = [...nums].sort((a, b) => a - b);
	let prev = 0;
	for (const p of sorted) {
		if (prev && p - prev > 1) addGap();
		add(String(p), p, { current: p === browse.page });
		prev = p;
	}

	add("›", browse.page + 1, { disabled: browse.page >= pages });

	const info = document.createElement("span");
	info.className = "pager-info";
	info.textContent = `${start + 1}–${start + shown} dari ${total}`;
	el.pager.appendChild(info);
}

function gotoPage(p) {
	browse.page = p;
	renderModels();
	// Keep the grid in view after paging — but only scroll the grid itself,
	// never the whole page (on mobile that would yank the stage away).
	el.list.scrollTop = 0;
}

/** Sync which of the two panes is visible and what the header says. */
function syncPanes() {
	const inGame = browse.view === "models" && browse.game;
	const bucket = inGame ? gameBuckets().find((g) => g.key === browse.game) : null;

	el.gameList.hidden = !!inGame;
	el.modelView.hidden = !inGame;
	el.backBtn.hidden = !inGame;
	el.search.hidden = !inGame;
	el.search.placeholder = inGame ? `Cari di ${bucket?.label || "game"}…` : "Cari game…";

	if (inGame) {
		el.libHeading.textContent = bucket?.label || "Model";
		el.libSub.textContent = gameSummary(bucket?.items || []);
	} else {
		el.libHeading.textContent = "Pustaka";
		el.libSub.textContent = `${models.length} model · ${gameBuckets().length} game`;
	}

	syncUpdater(inGame ? browse.game : null);
}

/* --- Asset updater ----------------------------------------------------
 * Only games with a fetch script on the server get the buttons.
 * Key di sini adalah nilai `game` dari /api/models (lihat GAME_ROOTS di
 * server.js), sehingga "mitao" → folder mitao-utopia juga cocok.
 */
const UPDATABLE = {
	arkrecode: "/api/update/arkrecode",
	shoujoukaisen: "/api/update/shoujoukaisen",
	"mitao-utopia": "/api/update/mitao-utopia",
};

/** Berapa berkas/model baru menurut laporan pemeriksa tiap game. */
function pendingCount(info) {
	// Ark Re:Code melapor "wanted" (berkas), Shoujou Kaisen "new" (model).
	return info?.new ?? info?.wanted ?? info?.added ?? 0;
}

let updaterBase = null;
let updaterGame = null;
// Has an update been found but not yet downloaded? Drives the red dot.
let updatePending = false;

function setUpdateDot(on) {
	const dot = document.getElementById("update-dot");
	if (dot) dot.hidden = !on;
	const btn = document.getElementById("update-check");
	if (btn) btn.title = on ? "Ada pembaruan — klik untuk mengunduh" : "Periksa pembaruan aset";
}

/* --- "NEW" badge -------------------------------------------------------
 * Models added by the updater during this browser session. Kept in
 * sessionStorage so the badge survives a reload but eventually fades on
 * its own rather than flagging models forever.
 */
const NEW_KEY = "spine-stage:new-models";
const NEW_TTL_MS = 7 * 24 * 60 * 60 * 1000; // seminggu

function loadNewSet() {
	try {
		const raw = JSON.parse(sessionStorage.getItem(NEW_KEY) || "{}");
		// { id: timestamp }
		const cutoff = Date.now() - NEW_TTL_MS;
		const out = {};
		for (const [id, ts] of Object.entries(raw)) {
			if (ts && ts > cutoff) out[id] = ts;
		}
		return out;
	} catch {
		return {};
	}
}

function markNew(ids) {
	if (!ids?.length) return;
	const cur = loadNewSet();
	const now = Date.now();
	for (const id of ids) cur[id] = now;
	try {
		sessionStorage.setItem(NEW_KEY, JSON.stringify(cur));
	} catch {
		/* penyimpanan penuh — badge hanya hilang setelah muat ulang */
	}
}

function isNewModel(m) {
	return !!loadNewSet()[m.id];
}

/** Show the button only for games that have an updater, then auto-check. */
function syncUpdater(game) {
	const btn = document.getElementById("update-check");
	if (!btn) return;
	const base = game && UPDATABLE[game];
	btn.hidden = !base;
	updaterBase = base || null;
	updaterGame = base ? game : null;
	if (!base) {
		updatePending = false;
		setUpdateDot(false);
		return;
	}
	// Auto-check on entering the game; the red dot appears if there is
	// something new. Silent on failure — the button stays usable.
	autoCheckUpdate();
}

let autoChecked = {};

async function autoCheckUpdate() {
	if (!updaterBase || !updaterGame) return;
	// Only auto-check once per game per page load.
	if (autoChecked[updaterGame]) {
		setUpdateDot(updatePending);
		return;
	}
	autoChecked[updaterGame] = true;
	try {
		const info = await fetch(`${updaterBase}?mode=check`).then((r) => r.json());
		if (info.error) return;
		// Ada yang belum diunduh kalau versinya berubah ATAU masih tersisa
		// model/berkas baru. Shoujou Kaisen pernah melapor versi sama
		// (0.820.48) tetapi masih punya 14 model yang belum diambil, jadi
		// jangan hanya mengandalkan `changed`.
		const hasNew = !!info.changed || !info.previous || pendingCount(info) > 0;
		updatePending = hasNew;
		setUpdateDot(updatePending);
	} catch {
		/* biarkan tombol tetap bisa dipakai manual */
	}
}

/** Manual check / start download from the header button. */
async function checkUpdate() {
	if (!updaterBase) return;
	const btn = document.getElementById("update-check");
	const dot = document.getElementById("update-dot");
	btn.classList.add("is-checking");

	let info;
	try {
		info = await fetch(`${updaterBase}?mode=check`).then((r) => r.json());
	} catch (err) {
		btn.classList.remove("is-checking");
		toast?.(`Gagal memeriksa pembaruan: ${err.message}`);
		return;
	}
	btn.classList.remove("is-checking");
	if (info.error) {
		toast?.(`Gagal memeriksa: ${info.error}`);
		return;
	}

	const hasNew = !!info.changed || !info.previous || pendingCount(info) > 0;
	updatePending = hasNew;
	setUpdateDot(updatePending);

	if (!hasNew) {
		toast?.(`Sudah versi terbaru (${info.version ?? info.catalog}).`);
		return;
	}
	// Ada yang baru: tanya dulu sebelum mengunduh (bisa ratusan MB).
	const n = pendingCount(info);
	const what = updaterGame === "shoujoukaisen" || updaterGame === "mitao-utopia" ? "model" : "berkas";
	const detail = n > 0 ? `${n} ${what} baru` : "versi baru";
	if (!confirm(`Versi ${info.version ?? info.catalog}: ${detail}. Unduh sekarang?`)) return;
	applyUpdate();
}

async function applyUpdate() {
	if (!updaterBase) return;
	const btn = document.getElementById("update-check");
	btn.classList.add("is-checking");
	btn.disabled = true;
	toast?.("Mengunduh pembaruan… ini bisa beberapa menit.");
	try {
		const started = await fetch(`${updaterBase}?mode=apply`).then((r) => r.json());
		if (!started.started) {
			toast?.(started.reason || "Tidak bisa memulai unduhan.");
			btn.disabled = false;
			btn.classList.remove("is-checking");
			return;
		}
		for (let i = 0; i < 600; i++) {
			await new Promise((r) => setTimeout(r, 3000));
			const st = await fetch(`${updaterBase}/status`).then((r) => r.json());
			if (st.running) continue;
			const res = st.result || {};
			updatePending = false;
			setUpdateDot(false);
			// Tandai model hasil unduhan supaya diberi badge NEW.
			const added = res.new_models || [];
			if (added.length) {
				// Prefix harus sama dengan id model di library (“<game>/<folder>”).
				const NEW_PREFIX = { shoujoukaisen: "shoujoukaisen", "mitao-utopia": "mitao-utopia" };
				const prefix = NEW_PREFIX[updaterGame] || "arkrecode";
				markNew(added.map((n) => `${prefix}/${n}`));
			}
			toast?.(
				res.error
					? `Gagal: ${res.error}`
					: `Selesai: ${res.downloaded ?? 0} berkas diunduh` +
						(res.failed ? `, ${res.failed} gagal` : "") +
						(res.extracted ? ` · ${res.extracted} model baru` : "") +
						(res.already_had ? ` · ${res.already_had} sudah ada` : "") +
						". Muat ulang untuk melihatnya."
			);
			btn.disabled = false;
			btn.classList.remove("is-checking");
			return;
		}
		toast?.("Masih berjalan — cek lagi nanti.");
	} catch (err) {
		toast?.(`Gagal mengunduh: ${err.message}`);
	}
	btn.disabled = false;
	btn.classList.remove("is-checking");
}

function renderLibrary() {
	syncPanes();
	if (browse.view === "models" && browse.game) renderModels();
	else renderGames(el.search.value);
}

function setActive(id) {
	for (const b of el.list.querySelectorAll(".model")) b.classList.toggle("is-active", b.dataset.id === id);
}

async function refresh() {
	try {
		const res = await fetch("/api/models");
		const data = await res.json();
		models = data.models || [];
		// Thumbnails are a nice-to-have: if this fails the grid still renders,
		// just with the initial-letter fallback instead of art.
		try {
			const t = await fetch("/api/thumbnails").then((r) => r.json());
			thumbs = t.thumbs || {};
		} catch {
			thumbs = {};
		}
		// Game icons are cosmetic too — a failure just means letter badges.
		try {
			const g = await fetch("/api/game-icons").then((r) => r.json());
			gameIcons = g.icons || {};
		} catch {
			gameIcons = {};
		}
		renderLibrary();
	} catch (err) {
		showError("Tidak bisa mengambil daftar model dari server.");
	}
}

/* ------------------------------------------------------------------ *
 * Helpers
 * ------------------------------------------------------------------ */
const ICON = {
	play: '<path d="M8 5v14l11-7z"/>',
	pause: '<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>',
	star: '<path d="M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/>',
};

function fmtBytes(n) {
	if (!n) return "0 B";
	const u = ["B", "KB", "MB", "GB"];
	const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
	return (n / 1024 ** i).toFixed(i ? 1 : 0) + " " + u[i];
}

function escapeHtml(s) {
	return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ------------------------------------------------------------------ *
 * Favorites
 * ------------------------------------------------------------------ *
 * Starred models. localStorage is the source of truth so the star
 * survives reloads with zero backend dependency; the server copy is a
 * best-effort mirror so the same list follows the user to another
 * browser. If the server is unreachable the local list still works. */
const FAV_KEY = "spine-stage:favorites";
let favorites = new Set();

function loadFavorites() {
	try {
		const raw = JSON.parse(localStorage.getItem(FAV_KEY) || "[]");
		favorites = new Set(Array.isArray(raw) ? raw : []);
	} catch {
		favorites = new Set();
	}
	// Pull the server copy in the background; newer wins on merge (union is
	// safer than replace — it can't lose stars the user just added offline).
	fetch("/api/favorites")
		.then((r) => (r.ok ? r.json() : null))
		.then((d) => {
			if (!d || !Array.isArray(d.favorites)) return;
			let changed = false;
			for (const id of d.favorites) {
				if (!favorites.has(id)) {
					favorites.add(id);
					changed = true;
				}
			}
			// Re-persist + refresh the badge: when this fetch resolves the
			// initial syncFavCount() has already run against an empty set,
			// so without this the counter stays stale at 0.
			saveFavorites(false);
			syncFavCount();
			if (changed && typeof renderLibrary === "function") renderLibrary();
		})
		.catch(() => {
			/* offline — local list stands */
		});
}

function saveFavorites(pushToServer = true) {
	try {
		localStorage.setItem(FAV_KEY, JSON.stringify([...favorites]));
	} catch {
		/* quota / private mode — ignore */
	}
	if (!pushToServer) return;
	fetch("/api/favorites", {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ favorites: [...favorites] }),
	}).catch(() => {
		/* server mirror is optional */
	});
}

function isFavorite(id) {
	return favorites.has(id);
}

/** Wire the favorites UI: load stored stars, then refresh the badge count. */
function initFavorites() {
	loadFavorites();
	syncFavCount();
	el.favFilter?.classList.toggle("is-on", browse.favOnly);
	el.favFilter?.setAttribute("aria-pressed", String(browse.favOnly));
}

/** Keep the "Favorit" button's counter in sync with the current set. */
function syncFavCount() {
	if (el.favCount) el.favCount.textContent = String(favorites.size);
}

function toggleFavorite(id) {
	if (favorites.has(id)) favorites.delete(id);
	else favorites.add(id);
	saveFavorites();
	syncFavCount();
	// Keep the grid in sync without a full refetch.
	if (browse.favOnly) renderLibrary();
	else {
		const btn = el.list.querySelector(`.model[data-id="${CSS.escape(id)}"]`);
		if (btn) {
			const star = btn.parentElement.querySelector(".model-fav");
			if (star) {
				star.classList.toggle("is-on", favorites.has(id));
				star.setAttribute("aria-pressed", String(favorites.has(id)));
				star.title = favorites.has(id) ? "Hapus dari favorit" : "Tambah ke favorit";
			}
		}
	}
	toast?.(favorites.has(id) ? "Ditambahkan ke favorit" : "Dihapus dari favorit");
}

let toastTimer;
function toast(msg) {
	el.toast.textContent = msg;
	el.toast.classList.add("is-on");
	clearTimeout(toastTimer);
	toastTimer = setTimeout(() => el.toast.classList.remove("is-on"), 2600);
}

function showError(msg) {
	if (!msg) {
		el.error.hidden = true;
		return;
	}
	el.error.hidden = false;
	el.error.querySelector("p").textContent = msg;
}

/* ------------------------------------------------------------------ *
 * Events
 * ------------------------------------------------------------------ */
el.playBtn.addEventListener("click", () => setPlaying(!state.playing));
el.loopBtn.addEventListener("click", () => {
	state.loop = !state.loop;
	el.loopBtn.dataset.on = String(state.loop);
	const track = spine?.state.tracks[0];
	if (track) track.loop = state.loop;
});
el.audioBtn.addEventListener("click", () => playVoice());
el.audioAutoBtn.addEventListener("click", () => setVoiceAutoplay(!voiceAutoplay));
el.flipBtn.addEventListener("click", () => {
	state.flip = !state.flip;
	el.flipBtn.dataset.on = String(state.flip);
	applyTransform();
});

el.prevBtn.addEventListener("click", () => stepAnimation(-1));
el.nextBtn.addEventListener("click", () => stepAnimation(1));

function stepAnimation(dir) {
	if (!spine) return;
	const anims = spine.skeleton.data.animations.map((a) => a.name);
	if (!anims.length) return;
	const i = anims.indexOf(animName);
	const next = anims[(i + dir + anims.length) % anims.length];
	el.animSelect.value = next;
	setAnimation(next, true);
	if (!state.playing) setPlaying(true);
}

el.animSelect.addEventListener("change", () => {
	// Cubism motions are played by the Cubism motion manager, not by a Spine
	// AnimationState. Cubism models must never reach setAnimation() — they
	// have no spine.state, so it would throw.
	if (isLive2D(current)) {
		playLive2DMotion(spine, el.animSelect.value);
		return;
	}
	setAnimation(el.animSelect.value, true);
	renderTimeline();
});
el.skinSelect.addEventListener("change", () => setSkin(el.skinSelect.value));
el.variantSelect.addEventListener("change", () => {
	const opt = el.variantSelect.selectedOptions[0];
	switchVariant(opt?.dataset?.id);
});
el.rateSelect.addEventListener("change", () => (state.rate = parseFloat(el.rateSelect.value)));

el.scrub.addEventListener("pointerdown", () => (state.scrubbing = true));
window.addEventListener("pointerup", () => (state.scrubbing = false));
el.scrub.addEventListener("input", () => {
	if (!duration || !spine) return;
	state.trackTime = (parseFloat(el.scrub.value) / 1000) * duration;
	const track = spine.state?.tracks?.[0];
	if (track) track.trackTime = state.trackTime;
	el.timeCur.textContent = state.trackTime.toFixed(2) + "s";
	spine.update(0);
	drawBones();
});

/**
 * Convert a viewport point to stage-local (skeleton) coordinates.
 *
 * `world` carries the user's zoom/pan/flip, so the inverse has to undo all
 * three — a flip mirrors X, which is easy to forget and produces hits that
 * are correct on one side of the model and mirrored on the other.
 */
function toStagePoint(clientX, clientY) {
	const r = el.canvasWrap.getBoundingClientRect();
	const sx = clientX - r.left;
	const sy = clientY - r.top;
	const wx = (sx - world.position.x) / (world.scale.x || 1);
	const wy = (sy - world.position.y) / (world.scale.y || 1);
	// spine sits inside stageRoot inside world; both are untransformed
	// relative to world except for world's own transform, so this is enough
	// for hit testing against the skeleton's own bounds.
	const p = { x: wx, y: wy };
	if (spine) {
		p.x -= spine.x;
		p.y -= spine.y;
	}
	return p;
}

// Part picker: hover highlights, click reports. Only bound while the overlay
// is on — otherwise this would add a hit test to every mouse move for nothing.
el.canvasWrap.addEventListener("pointermove", (e) => {
	if (!parts.on || !spine || dragging) return;
	const p = toStagePoint(e.clientX, e.clientY);
	const name = partAt(p.x, p.y);
	if (name !== parts.hover) {
		parts.hover = name;
		el.canvasWrap.style.cursor = name ? "pointer" : "";
		drawParts();
	}
});

el.canvasWrap.addEventListener("pointerdown", (e) => {
	if (!parts.on || !spine) return;
	if (e.button !== 0) return;
	const p = toStagePoint(e.clientX, e.clientY);
	const name = partAt(p.x, p.y);
	if (name) toast(`Bagian: ${name}`);
});

el.zoomIn.addEventListener("click", () => zoomBy(1.15));
el.zoomOut.addEventListener("click", () => zoomBy(1 / 1.15));
el.zoomReset.addEventListener("click", () => fitModel());

el.gridBtn.addEventListener("click", () => {
	state.showGrid = !state.showGrid;
	el.grid.classList.toggle("is-on", state.showGrid);
	el.gridBtn.dataset.on = String(state.showGrid);
});
el.bonesBtn.addEventListener("click", () => {
	state.showBones = !state.showBones;
	bonesGfx.visible = state.showBones;
	el.bonesBtn.dataset.on = String(state.showBones);
	drawBones();
});

// FPS meter toggle.
el.fpsBtn?.addEventListener("click", () => setFpsVisible(!fps.on));
el.fpsReset?.addEventListener("click", fpsResetStats);

// Part picker toggle.
el.partsBtn?.addEventListener("click", () => setPartsVisible(!parts.on));

// --- stage backdrop -------------------------------------------------------
// Cycling the backdrop is how you actually see edge problems: a dark or light
// halo around the art (a PMA mistake) disappears against the default dark grid
// and is obvious against mid-grey or the checkerboard.
const BG_ORDER = ["dark", "grey", "light", "checker", "magenta", "green"];
const BG_LABEL = { dark: "Gelap", grey: "Abu-abu", light: "Terang", checker: "Papan catur", magenta: "Magenta", green: "Hijau" };

function setStageBg(name, { persist = true } = {}) {
	state.bg = name;
	el.stageBg.dataset.bg = name;
	el.bgSelect.value = name;
	// "Latar" reads as on whenever we're off the default, so the toggle still
	// means something even though there are six choices.
	el.bgBtn.dataset.on = String(name !== "dark");
	if (!persist) return;
	try {
		localStorage.setItem("stageBg", name);
	} catch {
		/* private mode — preference just won't stick */
	}
}

el.bgBtn.addEventListener("click", () => {
	// Cycle through the options; the select is there for direct jumps.
	const next = BG_ORDER[(BG_ORDER.indexOf(state.bg) + 1) % BG_ORDER.length];
	setStageBg(next);
	toast(`Latar: ${BG_LABEL[next]}`);
});
el.bgSelect.addEventListener("change", () => {
	setStageBg(el.bgSelect.value);
	toast(`Latar: ${BG_LABEL[el.bgSelect.value] || el.bgSelect.value}`);
});

el.pmaSelect.addEventListener("change", () => {
	pmaMode = el.pmaSelect.value;
	// Remember the choice per model; "auto" clears any saved override.
	if (current) saveOverride(current.id, pmaMode);
	applyPMA();
	updatePmaUI();
	toast(`PMA: ${pmaMode === "auto" ? "Otomatis" : pmaMode === "on" ? "Aktif" : pmaMode === "upload" ? "Upload PMA" : "Nonaktif"}`);
});

/** Reflect the effective PMA state (override + atlas flag) in the transport. */
function updatePmaUI() {
	if (!el.pmaSelect) return;
	el.pmaSelect.value = pmaMode;
	const effective = pmaActive();
	el.pmaSelect.dataset.effective = String(effective);
	// Say where Auto got its answer: an atlas `pma:` line, or the game's own
	// default for assets that ship premultiplied without declaring it.
	const origin =
		pmaMode !== PMA_MODES.auto
			? " (dipaksa)"
			: pmaSource() === "atlas"
				? " (dari atlas)"
				: pmaSource() === "game-default"
					? " (bawaan game)"
					: " (bawaan)";
	if (pmaMode === PMA_MODES.upload) {
		el.pmaSelect.title = "Alpha lurus, dipramultiply saat upload (perbaiki bercak putih)" + origin;
		return;
	}
	el.pmaSelect.title = effective
		? "Alpha pramultiplied aktif" + origin
		: "Alpha lurus (tanpa pramultiply)" + origin;
}

el.canvasWrap.addEventListener(
	"wheel",
	(e) => {
		// Let the FPS meter handle its own wheel; zooming the stage because the
		// cursor happened to be over the overlay is never what was meant.
		if (e.target instanceof Element && e.target.closest(".fps-meter")) return;
		e.preventDefault();
		const r = el.canvasWrap.getBoundingClientRect();
		zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
	},
	{ passive: false }
);

/* Pointer handling: one pointer pans, two pinch-zoom, double-tap resets the
 * fit. On touch we track pointers in a Map so a second finger upgrades the
 * gesture instead of fighting the pan. */
const pointers = new Map();
let dragging = null;
let pinch = null;
// Timestamp of the last pinch teardown. Read by the double-tap handler (below)
// to avoid re-fitting the camera when both fingers lift from a pinch.
let pinchEndedAt = 0;

const pinchDist = () => {
	const [a, b] = [...pointers.values()];
	return Math.hypot(a.x - b.x, a.y - b.y);
};
const pinchCenter = () => {
	const [a, b] = [...pointers.values()];
	return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
};

el.canvasWrap.addEventListener("pointerdown", (e) => {
	// Overlays inside the stage (the FPS meter, the HUD) own their own clicks.
	// Capturing the pointer here would swallow their mouseup, so a button
	// inside them would receive mousedown and never a click.
	if (e.target instanceof Element && e.target.closest(".fps-meter")) return;
	if (e.pointerType === "mouse" && e.button !== 0 && e.button !== 1) return;
	pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
	// Capture can throw for synthetic/expired pointers, and an escape here would
	// leave `pointers` out of sync with the real gesture. Never let it break us.
	try {
		el.canvasWrap.setPointerCapture(e.pointerId);
	} catch {
		/* pointer already gone — pinch/pan still track via the Map */
	}

	if (pointers.size === 1) {
		dragging = { x: e.clientX, y: e.clientY };
		el.canvasWrap.classList.add("is-dragging");
	} else if (pointers.size === 2) {
		// second finger down: stop panning, start pinching
		dragging = null;
		const r = el.canvasWrap.getBoundingClientRect();
		const c = pinchCenter();
		pinch = { dist: pinchDist(), cx: c.x - r.left, cy: c.y - r.top };
	}
});

el.canvasWrap.addEventListener("pointermove", (e) => {
	if (!pointers.has(e.pointerId)) return;
	pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

	if (pointers.size >= 2 && pinch) {
		const dist = pinchDist();
		if (pinch.dist > 0 && dist > 0) {
			zoomBy(dist / pinch.dist, pinch.cx, pinch.cy);
			pinch.dist = dist;
		}
		return;
	}

	if (!dragging) return;
	state.panX += e.clientX - dragging.x;
	state.panY += e.clientY - dragging.y;
	dragging = { x: e.clientX, y: e.clientY };
	applyTransform();
});

const endDrag = (e) => {
	if (e) pointers.delete(e.pointerId);
	if (pointers.size < 2) {
		if (pinch) pinchEndedAt = Date.now();
		pinch = null;
	}
	if (pointers.size === 0) {
		dragging = null;
		el.canvasWrap.classList.remove("is-dragging");
	} else if (pointers.size === 1) {
		// lifted one finger of a pinch: resume panning from the survivor
		const [p] = [...pointers.values()];
		dragging = { x: p.x, y: p.y };
	}
};
el.canvasWrap.addEventListener("pointerup", endDrag);
el.canvasWrap.addEventListener("pointercancel", endDrag);

// Double-tap (or double-click) resets the view to fit — but only when the
// pointer barely moved, no other fingers are down, and we didn't just finish a
// pinch. Without the pinch guard, lifting both fingers re-fits the camera and
// silently throws away the zoom the user just dialled in.
let lastTap = 0;
let downAt = null;
el.canvasWrap.addEventListener("pointerdown", (e) => {
	downAt = { x: e.clientX, y: e.clientY };
});
el.canvasWrap.addEventListener("pointerup", (e) => {
	if (!downAt) return;
	const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
	downAt = null;
	if (moved > 10) return;        // that was a drag, not a tap
	if (pointers.size > 0) return; // other fingers still down (pinch end)
	if (Date.now() - pinchEndedAt < 350) return; // just finished pinching
	const now = Date.now();
	if (now - lastTap < 300) {
		lastTap = 0;
		fitModel();
	} else {
		lastTap = now;
	}
});

/* --- sidebar collapse ------------------------------------------------- */
/* Persisted so a refresh doesn't undo the choice. On mobile the sidebar starts
 * collapsed — the stage is the point, and it would otherwise eat the screen. */
const SIDEBAR_KEY = "spine-stage:sidebar-hidden";

function setSidebarHidden(hidden, { persist = true } = {}) {
	document.querySelector(".layout")?.classList.toggle("sidebar-hidden", hidden);
	el.sidebar?.setAttribute("aria-hidden", String(hidden));
	if (el.sidebarToggle) {
		el.sidebarToggle.setAttribute("aria-expanded", String(!hidden));
		const label = hidden ? "Tampilkan pustaka" : "Sembunyikan pustaka";
		el.sidebarToggle.setAttribute("aria-label", label);
		el.sidebarToggle.setAttribute("title", `${label} (\\)`);
	}
	if (persist) {
		try {
			localStorage.setItem(SIDEBAR_KEY, hidden ? "1" : "0");
		} catch {
			/* private mode — the toggle still works for this session */
		}
	}
}

function initSidebar() {
	let stored = null;
	try {
		stored = localStorage.getItem(SIDEBAR_KEY);
	} catch {
		/* private mode — fall back to the viewport default below */
	}
	let hidden = stored === "1";
	// Default to collapsed on narrow screens when the user has never chosen.
	if (stored === null && window.matchMedia("(max-width: 720px)").matches) hidden = true;
	setSidebarHidden(hidden, { persist: false });
	el.sidebarToggle?.addEventListener("click", () =>
		setSidebarHidden(!document.querySelector(".layout")?.classList.contains("sidebar-hidden"))
	);
}

/* ------------------------------------------------------------------ *
 * Fullscreen
 * ------------------------------------------------------------------ *
 * Fullscreens the whole document rather than just the canvas, and hides
 * the sidebar while it's active so the stage gets the extra room. The
 * user's own sidebar preference is never overwritten — we borrow the
 * screen and hand it back exactly as we found it.
 */
const fsEl = () => document.fullscreenElement || document.webkitFullscreenElement || null;
let fsSidebarWasHidden = false;
let fsFitTimer = 0;

function requestFullscreen() {
	const node = document.documentElement;
	const req = node.requestFullscreen || node.webkitRequestFullscreen;
	if (!req) {
		toast("Layar penuh tidak didukung browser ini.");
		return;
	}
	const p = req.call(node, { navigationUI: "hide" });
	if (p?.catch) p.catch(() => toast("Gagal masuk layar penuh."));
}

function exitFullscreen() {
	const exit = document.exitFullscreen || document.webkitExitFullscreen;
	if (!exit) return;
	const p = exit.call(document);
	if (p?.catch) p.catch(() => {});
}

function toggleFullscreen() {
	if (fsEl()) exitFullscreen();
	else requestFullscreen();
}

function syncFullscreenUI() {
	const on = !!fsEl();
	if (el.fullscreenBtn) {
		el.fullscreenBtn.dataset.on = String(on);
		const label = on ? "Keluar layar penuh" : "Layar penuh";
		el.fullscreenBtn.setAttribute("aria-label", label);
		el.fullscreenBtn.setAttribute("title", `${label} (F)`);
	}
	// The stage just changed size; let the model settle into the new frame.
	clearTimeout(fsFitTimer);
	fsFitTimer = setTimeout(() => {
		fsFitTimer = 0;
		if (spine) fitModel();
	}, 120);
}

function onFullscreenChange() {
	const on = !!fsEl();
	if (on) {
		fsSidebarWasHidden = !!document
			.querySelector(".layout")
			?.classList.contains("sidebar-hidden");
		if (!fsSidebarWasHidden) setSidebarHidden(true, { persist: false });
	} else if (!fsSidebarWasHidden) {
		setSidebarHidden(false, { persist: false });
	}
	syncFullscreenUI();
}

function initFullscreen() {
	document.addEventListener("fullscreenchange", onFullscreenChange);
	document.addEventListener("webkitfullscreenchange", onFullscreenChange);
	el.fullscreenBtn?.addEventListener("click", toggleFullscreen);
	syncFullscreenUI();
}

/* ------------------------------------------------------------------ *
 * Live-wallpaper export
 * ------------------------------------------------------------------ *
 * Frames are rendered OFFLINE: for each frame we seek the animation track
 * to an exact time and render once at the export resolution. Recording the
 * live canvas instead would tie frame timing to how fast the encoder
 * happens to be, which makes loops visibly stutter at the seam.
 *
 * Capturing is done with app.renderer.extract.canvas() over a temporary
 * container: it renders the model into its own frame sized to the model's
 * bounds, so the export is independent of the user's current zoom, pan and
 * window size. Note the grid and HUD are DOM overlays, not canvas content,
 * so they never leak into the output.
 */
const EXPORT_STATE = { busy: false, cancel: false };

function exportJobId() {
	return Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
}

/* ------------------------------------------------------------------ *
 * Native-resolution measurement
 *
 * An atlas page is a real bitmap: a region drawn at 2x its own size is
 * blurry no matter how large the exported canvas is, and a region drawn at
 * 0.5x has detail that no export can recover. So "how big should this PNG
 * be?" is answered by the art itself — measure atlas pixels per skeleton
 * unit, and render at 1:1 with the source.
 *
 * Taken per attachment rather than from the whole model: a rig mixes sharply
 * drawn body parts with background/filler regions stretched far past their
 * own resolution. A MEAN would be dragged upward by that filler and export
 * larger than the art supports; a low PERCENTILE sits in the narrow band
 * where the real art lives and is immune to those outliers.
 * ------------------------------------------------------------------ */

const EXPORT_SCALE_PERCENTILE = 0.35;
const MAX_EXPORT_DIM = 8192; // glMAX_TEXTURE_SIZE guard on modest GPUs
/* Some rigs declare canvases far larger than their art actually occupies
 * (one here reports 3839x6715 and exports a 2000x4500 PNG mostly full of
 * transparent padding). Cap the default at a size anyone can actually use —
 * 2K is what most art tools expect — while still scaling small models UP to
 * their native size rather than down. */
const MAX_EXPORT_HEIGHT = 2160;

/**
 * The region's own width/height in atlas pixels.
 *
 * Needed because runtimes disagree about where this lives: spine-core puts a
 * `rotate` flag and expects the caller to transpose, while some builds expose
 * already-oriented `width`/`height`. UV extent is unambiguous, so measure
 * that and use the region size only as a cross-check.
 */
function regionPixelSize(region, page) {
	const w = page?.width || page?.baseTexture?.width || 0;
	const h = page?.height || page?.baseTexture?.height || 0;
	if (!w || !h) return null;
	// u/v are normalised 0..1 in every Spine version.
	const uSpan = Math.abs((region.u2 ?? 0) - (region.u ?? 0));
	const vSpan = Math.abs((region.v2 ?? 0) - (region.v ?? 0));
	const rotated = region.rotate === true || region.degrees === 90 || region.degrees === 270;
	const uw = uSpan * w;
	const uh = vSpan * h;
	if (uw <= 0 || uh <= 0) return null;
	// A rotated region stores its ORIGINAL size, so the packed rectangle in
	// the page is the transpose.
	return { w: rotated ? uh : uw, h: rotated ? uw : uh, rotated };
}

/**
 * Source atlas pixels per skeleton unit for a drawn attachment.
 *
 * Compares a world-space edge against the atlas pixels that edge covers:
 * pixels per unit = atlasPixels / worldLength. Averaged over the edges of the
 * attachment's quad so one degenerate (zero-length) edge cannot dominate.
 *
 * Works across runtimes by preferring `regionUVs` (mesh) and falling back to
 * the region's own u/v rectangle — several builds leave `attachment.uvs`
 * empty, which silently made every measurement zero.
 */
function attachmentPixelScale(slot, attachment) {
	const region = attachment?.region;
	const page = region?.page || region?.texture;
	if (!region || !page) return 0;

	const px = regionPixelSize(region, page);
	if (!px) return 0;

	// The quad's atlas footprint: for a plain region that is just the region
	// rectangle; for a mesh it is the bounding box of its UVs.
	let uvW = px.w;
	let uvH = px.h;
	const ruv = attachment.regionUVs;
	if (ruv && ruv.length >= 4) {
		let minU = Infinity, minV = Infinity, maxU = -Infinity, maxV = -Infinity;
		for (let i = 0; i + 1 < ruv.length; i += 2) {
			if (ruv[i] < minU) minU = ruv[i];
			if (ruv[i] > maxU) maxU = ruv[i];
			if (ruv[i + 1] < minV) minV = ruv[i + 1];
			if (ruv[i + 1] > maxV) maxV = ruv[i + 1];
		}
		const uw = (maxU - minU) * (page.width || px.w);
		const vh = (maxV - minV) * (page.height || px.h);
		if (uw > 0 && vh > 0) {
			uvW = px.rotated ? vh : uw;
			uvH = px.rotated ? uw : vh;
		}
	}
	if (!(uvW > 0) || !(uvH > 0)) return 0;

	// World-space extent of this attachment, in skeleton units.
	let w = 0;
	let h = 0;
	try {
		if (attachment.worldVerticesLength) {
			const verts = new Float32Array(attachment.worldVerticesLength);
			attachment.computeWorldVertices(slot, 0, verts.length, verts, 0, 2);
			let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
			for (let i = 0; i + 1 < verts.length; i += 2) {
				if (verts[i] < minX) minX = verts[i];
				if (verts[i] > maxX) maxX = verts[i];
				if (verts[i + 1] < minY) minY = verts[i + 1];
				if (verts[i + 1] > maxY) maxY = verts[i + 1];
			}
			w = maxX - minX;
			h = maxY - minY;
		}
	} catch {
		/* fall through */
	}

	// Region attachments have no worldVerticesLength in some builds; their
	// local size is stored on the attachment itself.
	if (!(w > 0) && !(h > 0)) {
		w = attachment.width || 0;
		h = attachment.height || 0;
	}
	if (!(w > 0) && !(h > 0)) return 0;

	// Pixels per unit on each axis; the smaller is the binding constraint —
	// it is the axis where the art is stretched most relative to its source.
	const sx = uvW / w;
	const sy = uvH / h;
	const best = Math.min(sx, sy) || Math.max(sx, sy);
	return best > 0 && Number.isFinite(best) ? best : 0;
}

/**
 * Representative source pixels per skeleton unit for the current pose.
 * Returns 0 when nothing measurable was found (caller falls back).
 */
function sourcePixelScale(sp) {
	const scales = [];
	for (const slot of sp.skeleton.slots) {
		const att = slot.getAttachment?.();
		if (!att) continue;
		const s = attachmentPixelScale(slot, att);
		if (s > 0 && Number.isFinite(s)) scales.push(s);
	}
	if (!scales.length) return 0;
	const sorted = scales.sort((a, b) => a - b);
	return sorted[Math.floor((sorted.length - 1) * EXPORT_SCALE_PERCENTILE)];
}

/** Model bounds in skeleton units, from the setup pose + current animation. */
function modelBounds(sp) {
	sp.skeleton.setToSetupPose();
	sp.skeleton.updateWorldTransform?.();
	sp.update(0);
	const b = sp.getLocalBounds ? sp.getLocalBounds() : null;
	if (!b || !isFinite(b.width) || !isFinite(b.height) || b.width <= 0 || b.height <= 0) {
		const d = sp.skeleton.data;
		return { x: -(d.width || 512) / 2, y: 0, w: d.width || 512, h: d.height || 512 };
	}
	return { x: b.x, y: b.y, w: b.width, h: b.height };
}

function setExportProgress(done, total) {
	const pct = total ? Math.round((done / total) * 100) : 0;
	el.exportBarFill.style.width = pct + "%";
	el.exportProgressText.textContent = `${done} / ${total}`;
}

async function runExport() {
	if (EXPORT_STATE.busy) return;
	if (!spine) {
		toast("Pilih model dulu sebelum mengekspor.");
		return;
	}

	const format = el.exportFormat.value === "gif" ? "gif" : "webm";
	const background = el.exportBg.value;
	const height = Number(el.exportSize.value) || 720;
	const fps = Number(el.exportFps.value) || 30;

	// Transparency only survives in GIF on this ffmpeg (verified: its VP9/VP8
	// silently drop alpha). Switch the format and say so rather than quietly
	// shipping an opaque file the user thinks is transparent.
	const transparent = background === "transparent";
	const outFmt = transparent ? "gif" : format;
		if (transparent && format !== "gif") {
			showExportNote(
				"ffmpeg di server ini tidak mendukung WebM transparan (alpha ikut hilang). " +
				"Hasilnya otomatis jadi GIF biar transparansinya terjaga. GIF dibatasi 360p " +
				"supaya ukurannya tidak membengkak."
			);
		} else if (!transparent && format === "gif") {
			showExportNote("GIF dibatasi 360p — format ini membengkak cepat di resolusi tinggi.");
		} else {
			showExportNote(null);
		}

	const frames = Math.min(600, Math.max(1, Math.round(duration * fps)));
	if (!duration || frames < 1) {
		toast("Animasi ini tidak punya durasi yang bisa diekspor.");
		return;
	}

	// GIF stores 256-colour frames, and cost grows with the square of the
	// pixel count — a 480p GIF of a detailed model hit 15 MB. Cap GIF
	// dimensions hard; WebM has no such problem.
	const effHeight = transparent || format === "gif" ? Math.min(height, 360) : height;

	EXPORT_STATE.busy = true;
	EXPORT_STATE.cancel = false;
	el.exportRun.disabled = true;
	el.exportRun.textContent = "Mengekspor…";
	el.exportProgress.hidden = false;
	el.exportResult.hidden = true;
	setExportProgress(0, frames);

	// Freeze the live view so the user's playback state can't interfere and
	// we can restore it exactly when we're done.
	const wasPlaying = state.playing;
	const wasTrackTime = spine.state?.tracks?.[0]?.trackTime ?? 0;
	setPlaying(false);

	// Stop the render ticker for the duration. Every await below yields to
	// the event loop, which otherwise lets the ticker redraw the whole live
	// stage between frames — pure waste, since we're rendering into our own
	// RenderTexture, and it competes for the same GPU/CPU.
	app.ticker.stop();

	const job = exportJobId();
	const bounds = modelBounds(spine);
	const outH = Math.max(2, Math.round(effHeight / 2) * 2);
	const outW = Math.max(2, Math.round((bounds.w / Math.max(bounds.h, 1)) * outH / 2) * 2);

	const holder = new Container();
	const snapshot = new Container();
	holder.addChild(snapshot);

	// Render into a RenderTexture sized to the OUTPUT, not to the model's
	// native bounds. Extracting a full-size frame and downscaling costs a
	// glReadPixels + CPU flip over the whole source (measured: ~2.7s/frame on
	// a 2242x2239 model); rendering at target size is ~58ms/frame.
	const rt = RenderTexture.create({ width: outW, height: outH });
	const fit = Math.min(outW / Math.max(bounds.w, 1), outH / Math.max(bounds.h, 1)) * 0.97;

	// Place the model with an explicit transform instead of composing two
	// nested containers: this is the one place where getting the Y axis wrong
	// silently produces an upside-down or cropped video.
	//
	// Verified empirically: app.renderer.extract() does NOT flip Y (a red
	// square drawn at GL top-left stays top-left), and Pixi's Spine container
	// already renders Y-up content the right way up. So the correct transform
	// is a POSITIVE y scale — negating it produces an upside-down export.
	//   screenX = (x - bounds.x) * fit + offX
	//   screenY = (y - bounds.y) * fit + offY
	const offX = (outW - bounds.w * fit) / 2;
	const offY = (outH - bounds.h * fit) / 2;
	const tx = offX - bounds.x * fit;
	const ty = offY - bounds.y * fit;

	const out = document.createElement("canvas");
	out.width = outW;
	out.height = outH;
	const ctx = out.getContext("2d");

	let ok = false;
	try {
		for (let i = 0; i < frames; i++) {
			if (EXPORT_STATE.cancel) break;

			// Seek deterministically, then apply the pose.
			const t = (i / frames) * duration;
			const track = spine.state?.tracks?.[0];
			if (track) track.trackTime = t;
			spine.update(0);

			// Re-parent into the snapshot so we render the pose without the
			// live stage's zoom/pan/flip baked in.
			const parent = spine.parent;
			const x = spine.x, y = spine.y;
			const sx = spine.scale.x, sy = spine.scale.y;
			if (parent) parent.removeChild(spine);
			snapshot.addChild(spine);
			spine.position.set(0, 0);
			spine.scale.set(1, 1);

			// Apply the Spine -> target transform derived above (positive Y).
			holder.position.set(tx, ty);
			holder.scale.set(fit, fit);

			let canvas;
			try {
				app.renderer.render(holder, { renderTexture: rt, clear: true });
				canvas = app.renderer.extract.canvas(rt);
			} catch {
				canvas = app.renderer.extract.canvas(holder);
			}

			// restore
			snapshot.removeChild(spine);
			if (parent) parent.addChild(spine);
			spine.position.set(x, y);
			spine.scale.set(sx, sy);

			// Paint the background if the user asked for a solid one.
			ctx.clearRect(0, 0, outW, outH);
			if (!transparent) {
				ctx.fillStyle = background === "white" ? "#ffffff" : background === "#1a1620" ? "#1a1620" : "#000000";
				ctx.fillRect(0, 0, outW, outH);
			}
			ctx.drawImage(canvas, 0, 0, outW, outH);

			// Opaque exports go over the wire as JPEG: a PNG of noise costs
			// ~400KB/frame while a high-quality JPEG is ~40KB, and VP9 re-
			// encodes anyway so the extra fidelity is thrown away. Transparent
			// exports must stay PNG — JPEG has no alpha channel.
			const mime = transparent ? "image/png" : "image/jpeg";
			const blob = await new Promise((res) => out.toBlob(res, mime, 0.92));
			if (!blob) throw new Error("Gagal membuat bingkai.");

			const r = await fetch(
				`/api/export/frame?job=${job}&i=${i}&n=${frames}`,
				{ method: "POST", headers: { "Content-Type": mime }, body: blob }
			);
			if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Gagal mengunggah bingkai.");

			setExportProgress(i + 1, frames);
			// Yield to the browser so the UI can actually paint progress.
			if (i % 4 === 3) await new Promise((r2) => setTimeout(r2, 0));
		}

		if (EXPORT_STATE.cancel) {
			await fetch("/api/export/cancel", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ job }),
			}).catch(() => {});
			toast("Ekspor dibatalkan.");
			return;
		}

		const res = await fetch("/api/export/finish", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				job,
				format: outFmt,
				background,
				fps,
				frames,
				width: outW,
				height: outH,
				name: (current?.name || animName || "wallpaper").replace(/\s+/g, "-"),
			}),
		});
		const data = await res.json().catch(() => ({}));
		if (!res.ok) throw new Error(data.error || "Gagal menggabungkan video.");

		el.exportDownload.href = data.url;
		el.exportDownload.setAttribute("download", data.url.split("/").pop());
		const kb = Math.round((data.size || 0) / 1024);
		el.exportMeta.textContent = `${data.format.toUpperCase()} · ${data.frames} bingkai · ${kb} KB${data.alpha ? " · transparan" : ""}`;
		el.exportResult.hidden = false;
		ok = true;
		toast("Live wallpaper siap diunduh.");
	} catch (err) {
		showExportNote("Ekspor gagal: " + err.message);
		toast("Ekspor gagal.");
	} finally {
		holder.destroy({ children: true });
		rt.destroy(true);
		app.ticker.start();
		EXPORT_STATE.busy = false;
		el.exportRun.disabled = false;
		el.exportRun.textContent = "Mulai ekspor";
		// Put the playhead back exactly where we found it.
		const track = spine?.state.tracks[0];
		if (track) track.trackTime = wasTrackTime;
		if (spine) spine.update(0);
		if (wasPlaying) setPlaying(true);
		if (!ok) el.exportProgress.hidden = true;
	}
}

/**
 * Tight-crop a canvas to its non-transparent pixels.
 *
 * Scans the alpha channel from each edge inward. Deliberately not
 * pixel-perfect on the interior — only the bounding box matters, so we stop
 * at the first opaque row/column from each side.
 */
function tightCrop(canvas) {
	const ctx = canvas.getContext("2d");
	const { width: w, height: h } = canvas;
	if (!w || !h) return { x: 0, y: 0, w, h };
	let data;
	try {
		data = ctx.getImageData(0, 0, w, h).data;
	} catch {
		return { x: 0, y: 0, w, h }; // tainted canvas — keep the whole thing
	}

	let top = 0, bottom = h - 1, left = 0, right = w - 1;
	const rowHas = (y) => {
		const row = y * w;
		for (let x = 0; x < w; x++) if (data[(row + x) * 4 + 3] > 0) return true;
		return false;
	};
	const colHas = (x) => {
		for (let y = 0; y < h; y++) if (data[(y * w + x) * 4 + 3] > 0) return true;
		return false;
	};

	while (top <= bottom && !rowHas(top)) top++;
	if (top > bottom) return { x: 0, y: 0, w, h }; // fully empty
	while (bottom > top && !rowHas(bottom)) bottom--;
	while (left <= right && !colHas(left)) left++;
	while (right > left && !colHas(right)) right--;

	return { x: left, y: top, w: right - left + 1, h: bottom - top + 1 };
}

/**
 * Render the current pose to a PNG at the art's native resolution.
 *
 * The size is derived from the atlas, not from a dropdown: a model whose art
 * is 900px tall exports ~900px tall whether or not that looks big on screen.
 * Asking for more would only upscale pixels that do not exist; asking for
 * less throws away detail that does.
 */
async function exportPng({ background = "transparent" } = {}) {
	if (!spine) {
		toast("Pilih model dulu sebelum mengekspor.");
		return;
	}
	// Freeze the pose BEFORE measuring: the dialog predicted a size from the
	// pose it was opened on, and a moving model changes its bounds between
	// that prediction and this render. Pausing makes the two agree, and is
	// what the user expects from "save this frame" anyway.
	const wasPlaying = state.playing;
	const wasTrackTime = spine.state?.tracks?.[0]?.trackTime ?? 0;
	setPlaying(false);
	app.ticker.stop();
	spine.update(0);

	const holder = new Container();
	const snapshot = new Container();
	holder.addChild(snapshot);

	let rt = null;
	try {
		const parent = spine.parent;
		const x = spine.x, y = spine.y;
		const sx = spine.scale.x, sy = spine.scale.y;
		if (parent) parent.removeChild(spine);
		snapshot.addChild(spine);
		spine.position.set(0, 0);
		spine.scale.set(1, 1);

		// Measure AFTER neutralising the transform: the scale we want is atlas
		// pixels per SKELETON unit, and the live stage's zoom would corrupt it.
		// Same helper the dialog's preview uses, so the number it promised is
		// exactly the number produced here.
		const target = pngOutputSize(spine);
		const bounds = spine.getLocalBounds ? spine.getLocalBounds() : null;
		// pngOutputSize measured the live pose; re-measure here so the render
		// uses the very same rectangle the size was predicted from. Reading
		// bounds twice can straddle a sub-pixel difference in the pose and
		// shift the output by a few pixels.
		const bw = target?.bw || bounds?.width || spine.skeleton.data.width || 512;
		const bh = target?.bh || bounds?.height || spine.skeleton.data.height || 512;
		const bx = bounds?.x ?? 0;
		const by = bounds?.y ?? 0;
		const outW = target?.w || Math.max(2, Math.round(bw));
		const outH = target?.h || Math.max(2, Math.round(bh));
		const scale = Math.min(outW / Math.max(bw, 1), outH / Math.max(bh, 1));

		rt = RenderTexture.create({ width: outW, height: outH });
		holder.position.set(-bx * scale, -by * scale);
		holder.scale.set(scale, scale);

		let shot;
		try {
			app.renderer.render(holder, { renderTexture: rt, clear: true });
			shot = app.renderer.extract.canvas(rt);
		} catch {
			shot = app.renderer.extract.canvas(holder);
		}

		// restore the stage
		snapshot.removeChild(spine);
		if (parent) parent.addChild(spine);
		spine.position.set(x, y);
		spine.scale.set(sx, sy);

		const opaque = background !== "transparent";
		const out = document.createElement("canvas");
		out.width = outW;
		out.height = outH;
		const ctx = out.getContext("2d");
		if (opaque) {
			ctx.fillStyle =
				background === "white" ? "#ffffff" : background === "#1a1620" ? "#1a1620" : "#000000";
			ctx.fillRect(0, 0, outW, outH);
		}
		ctx.drawImage(shot, 0, 0, outW, outH);

		// Crop only when transparent: an opaque export is defined by its
		// canvas edges, and trimming those would change the framing.
		let final = out;
		if (!opaque) {
			const c = tightCrop(out);
			if (c.w > 0 && c.h > 0 && (c.w !== outW || c.h !== outH)) {
				const trimmed = document.createElement("canvas");
				trimmed.width = c.w;
				trimmed.height = c.h;
				trimmed.getContext("2d").drawImage(out, c.x, c.y, c.w, c.h, 0, 0, c.w, c.h);
				final = trimmed;
			}
		}

		const blob = await new Promise((res) => final.toBlob(res, "image/png"));
		if (!blob) throw new Error("Gagal membuat PNG.");

		const name = (current?.name || animName || "model").replace(/[^\w.-]+/g, "-");
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `${name}-${final.width}x${final.height}.png`;
		a.click();
		setTimeout(() => URL.revokeObjectURL(url), 4000);

		const kb = Math.round(blob.size / 1024);
		toast(
			`PNG ${final.width}×${final.height} (${kb} KB)${target?.native ? " · resolusi asli" : " · perkiraan"}`
		);
	} catch (err) {
		toast("Ekspor PNG gagal: " + err.message);
	} finally {
		if (rt) rt.destroy(true);
		holder.destroy({ children: true });
		app.ticker.start();
		const track = spine?.state?.tracks?.[0];
		if (track) track.trackTime = wasTrackTime;
		spine?.update(0);
		if (wasPlaying) setPlaying(true);
	}
}

function showExportNote(msg) {
	if (!el.exportNote) return;
	if (!msg) {
		el.exportNote.hidden = true;
		el.exportNote.textContent = "";
		return;
	}
	el.exportNote.textContent = msg;
	el.exportNote.hidden = false;
}

/** Predicted PNG size for the model on stage, or null when unmeasurable. */
function pngTargetSize() {
	if (!spine) return null;
	return pngOutputSize(spine);
}

/**
 * The PNG's output dimensions, shared by the preview and the real export so
 * the number shown before clicking is exactly the number produced.
 */
function pngOutputSize(sp) {
	const pxPerUnit = sourcePixelScale(sp);
	const bounds = sp.getLocalBounds ? sp.getLocalBounds() : null;
	const bw = bounds?.width || sp.skeleton.data.width || 512;
	const bh = bounds?.height || sp.skeleton.data.height || 512;
	if (!bw || !bh) return null;
	// pxPerUnit is atlas pixels per skeleton unit: rendering at exactly that
	// makes one atlas pixel land on one output pixel — the sharpest the art
	// can be, with no upscaling.
	// When the atlas cannot be read, target a sane height so the export is
	// still useful rather than 1:1 with a bogus measurement.
	const fit = pxPerUnit > 0 ? pxPerUnit : MAX_EXPORT_HEIGHT / Math.max(bh, 1);
	let w = Math.max(2, Math.round(bw * fit));
	let h = Math.max(2, Math.round(bh * fit));

	// Shrink oversized rigs to a usable ceiling, but never magnify: a model
	// smaller than the ceiling exports at its own native size.
	const shrink = Math.max(h / MAX_EXPORT_HEIGHT, w / MAX_EXPORT_DIM, 1);
	if (shrink > 1) {
		w = Math.max(2, Math.round(w / shrink));
		h = Math.max(2, Math.round(h / shrink));
	}
	// bw/bh travel with the result so the renderer frames the exact rectangle
	// these dimensions were computed from — measuring again can land a few
	// pixels off and quietly change the crop.
	return { w, h, native: pxPerUnit > 0, bw, bh };
}

function openExport() {
	if (!spine) {
		toast("Pilih model dulu sebelum mengekspor.");
		return;
	}
	el.exportModal.hidden = false;
	showExportNote(null);
	el.exportProgress.hidden = true;
	el.exportResult.hidden = true;

	// Predicting a size from a moving model is a promise we can't keep: the
	// pose — and therefore the bounds — shifts before the user clicks. Pause
	// on open so the stated size is the size produced, and so "Simpan PNG"
	// captures the frame the user is actually looking at.
	if (state.playing) setPlaying(false);
	spine?.update(0);

	// Tell the user what "Simpan PNG" will produce before they click it: the
	// size comes from the art, so it is worth stating rather than surprising.
	if (el.exportPngNote) {
		const s = pngTargetSize();
		if (!s) {
			el.exportPngNote.textContent = "";
		} else {
			// A transparent export is tight-cropped to the drawn pixels, so
			// the canvas size is an upper bound and the file comes out at or
			// just under it — say so rather than promising an exact number.
			const transparent = (el.exportBg?.value || "transparent") === "transparent";
			el.exportPngNote.textContent =
				`${s.w}×${s.h}px${s.native ? " · resolusi asli" : " · perkiraan"}` +
				(transparent ? " · dipotong rapat" : "");
		}
	}
}

function closeExport() {
	if (EXPORT_STATE.busy) {
		EXPORT_STATE.cancel = true;
		return;
	}
	el.exportModal.hidden = true;
}

function initExport() {
	el.exportBtn?.addEventListener("click", () => {
		if (el.exportModal.hidden) openExport();
		else closeExport();
	});
	el.exportPng?.addEventListener("click", () => {
		// The "Latar" picker already means what it says for the video path, so
		// reuse it: an opaque PNG gets that colour, transparent stays cut out.
		exportPng({ background: el.exportBg?.value || "transparent" });
	});
	el.exportClose?.addEventListener("click", closeExport);
	el.exportCancel?.addEventListener("click", closeExport);
	el.exportRun?.addEventListener("click", runExport);
	el.exportModal?.addEventListener("click", (e) => {
		if (e.target?.dataset?.close) closeExport();
	});

	// Reflect the transparency/format rule as soon as the user picks a bg.
	el.exportBg?.addEventListener("change", () => {
		if (el.exportBg.value === "transparent" && el.exportFormat.value !== "gif") {
			el.exportFormat.value = "gif";
			showExportNote(
				"ffmpeg di server ini tidak mendukung WebM transparan. Format dialihkan ke GIF " +
				"supaya latar transparannya benar-benar terjaga."
			);
		} else if (el.exportBg.value !== "transparent") {
			showExportNote(null);
		}
		// The PNG line says whether the result gets tight-cropped, which
		// depends on this choice — keep it in sync.
		if (el.exportPngNote) {
			const s = pngTargetSize();
			if (s) {
				const transparent = el.exportBg.value === "transparent";
				el.exportPngNote.textContent =
					`${s.w}×${s.h}px${s.native ? " · resolusi asli" : " · perkiraan"}` +
					(transparent ? " · dipotong rapat" : "");
			}
		}
	});
}

el.search.addEventListener("input", () => {
	// Searching resets to page 1 — staying on page 7 of a 2-page result is a
	// dead end the user has to notice and recover from.
	browse.page = 1;
	if (browse.view === "models" && browse.game) renderModels();
	else renderGames(el.search.value);
});
el.backBtn?.addEventListener("click", backToGames);

// Favorit filter — toggles a "starred only" view of the current scope.
el.favFilter?.addEventListener("click", () => {
	browse.favOnly = !browse.favOnly;
	browse.page = 1;
	el.favFilter.classList.toggle("is-on", browse.favOnly);
	el.favFilter.setAttribute("aria-pressed", String(browse.favOnly));
	renderLibrary();
	if (browse.favOnly && !favorites.size) {
		toast?.("Belum ada favorit — klik bintang pada model.");
	}
});

window.addEventListener("keydown", (e) => {
	if (e.target instanceof HTMLElement && e.target.matches("input, select, textarea")) return;
	switch (e.key) {
		case " ":
			e.preventDefault();
			setPlaying(!state.playing);
			break;
		case "ArrowRight":
			stepAnimation(1);
			break;
		case "ArrowLeft":
			stepAnimation(-1);
			break;
		case "=":
		case "+":
			zoomBy(1.15);
			break;
		case "-":
			zoomBy(1 / 1.15);
			break;
		case "0":
			fitModel();
			break;
		case "b":
		case "B":
			el.bonesBtn.click();
			break;
		case "g":
		case "G":
			el.gridBtn.click();
			break;
		case "l":
		case "L":
			el.bgBtn.click();
			break;
		case "f":
		case "F":
			e.preventDefault();
			toggleFullscreen();
			break;
		case "e":
		case "E":
			e.preventDefault();
			el.exportBtn?.click();
			break;
		case "\\":
			e.preventDefault();
			el.sidebarToggle?.click();
			break;
		case "t":
		case "T":
			e.preventDefault();
			el.timelineBtn?.click();
			break;
		case "i":
		case "I":
			e.preventDefault();
			el.inspectorBtn?.click();
			break;
		case "p":
		case "P":
			e.preventDefault();
			el.fpsBtn?.click();
			break;
		case "r":
		case "R":
			e.preventDefault();
			el.partsBtn?.click();
			break;
		case ",":
			// step keyframes, but only when the timeline is open
			if (!el.timeline.hidden) {
				e.preventDefault();
				tlStepKey(-1);
			}
			break;
		case ".":
			if (!el.timeline.hidden) {
				e.preventDefault();
				tlStepKey(1);
			}
			break;
		case "Escape":
			// The export dialog is the topmost thing on screen, so it gets
			// first refusal on Escape.
			if (!el.exportModal?.hidden) {
				e.preventDefault();
				closeExport();
			} else if (browse.view === "models") {
				// back out of a game's model list to the game picker
				e.preventDefault();
				backToGames();
			}
			break;
	}
});

// upload
el.uploadBtn.addEventListener("click", () => el.file.click());
el.file.addEventListener("change", () => doUpload(el.file.files));

// asset updater
document.getElementById("update-check")?.addEventListener("click", checkUpdate);
document.getElementById("update-apply")?.addEventListener("click", applyUpdate);

["dragenter", "dragover"].forEach((ev) =>
	el.drop.addEventListener(ev, (e) => {
		e.preventDefault();
		el.drop.classList.add("is-over");
	})
);
["dragleave", "drop"].forEach((ev) =>
	el.drop.addEventListener(ev, (e) => {
		e.preventDefault();
		if (ev === "dragleave" && el.drop.contains(e.relatedTarget)) return;
		el.drop.classList.remove("is-over");
	})
);
el.drop.addEventListener("drop", (e) => {
	e.preventDefault();
	if (e.dataTransfer?.files?.length) doUpload(e.dataTransfer.files);
});

async function doUpload(fileList) {
	if (!fileList?.length) return;
	const fd = new FormData();
	for (const f of fileList) fd.append("files", f);
	if (el.folder.value.trim()) fd.append("folder", el.folder.value.trim());
	el.loading.hidden = false;
	el.loading.textContent = "Mengunggah…";
	try {
		const res = await fetch("/api/upload", { method: "POST", body: fd });
		const data = await res.json();
		if (!res.ok) throw new Error(data.error || "Unggahan gagal");
		toast(`Model “${data.folder}” ditambahkan.`);
		el.folder.value = "";
		el.file.value = "";
		await refresh();
	} catch (err) {
		showError(err.message);
	} finally {
		el.loading.hidden = true;
	}
}

el.delBtn.addEventListener("click", async () => {
	if (!current) return;
	if (!confirm(`Hapus model “${current.name}” beserta semua berkasnya?`)) return;
	try {
		const res = await fetch("/api/models/" + encodeURIComponent(current.id), { method: "DELETE" });
		const data = await res.json();
		if (!res.ok) throw new Error(data.error || "Gagal menghapus");
		if (spine) {
			stageRoot.removeChild(spine);
			spine.destroy(true);
			spine = null;
		}
		current = null;
		animName = null;
		duration = 0;
		el.empty.hidden = false;
		el.hud.hidden = true;
		el.delBtn.hidden = true;
		$("#title-model").textContent = "—";
		toast("Model dihapus.");
		await refresh();
	} catch (err) {
		showError(err.message);
	}
});

/* Debug handle: lets you inspect the live skeleton from devtools. */
window.spineStage = {
	get spine() {
		return spine;
	},
	get model() {
		return current;
	},
	get pma() {
		return {
			mode: pmaMode,
			atlasSaysPMA,
			gamePmaDefault,
			source: pmaSource(),
			active: pmaActive(),
			alphaMode: currentAlphaMode(),
		};
	},
	// Voice playback is driven by a detached Audio() object, which page JS
	// cannot find via document.querySelector — expose it so tests (and the
	// console) can assert on real playback instead of a button flag.
	get voice() {
		if (!voiceEl) return { hasElement: false, tracks: voiceQueue.length };
		return {
			hasElement: true,
			src: voiceEl.currentSrc || voiceEl.src,
			currentTime: voiceEl.currentTime,
			duration: voiceEl.duration,
			paused: voiceEl.paused,
			ended: voiceEl.ended,
			readyState: voiceEl.readyState,
			error: voiceEl.error ? voiceEl.error.code : null,
			tracks: voiceQueue.length,
		};
	},
	get voiceAutoplay() {
		return { on: voiceAutoplay, unlocked: voiceUnlocked, pending: voiceQueue.length };
	},
	setVoiceAutoplay,
	setPMA(mode) {
		pmaMode = mode;
		applyPMA();
		updatePmaUI();
	},
	state,
	browse,
	gameBuckets,
	switchVariant,
	timeline: tl,
	get runtime() {
		return spineRuntime;
	},
	get version() {
		return spineVersion;
	},
	// handles used by the export profiler / tests
	get app() {
		return app;
	},
	__pixi: { Container, Rectangle, RenderTexture, Graphics },
};

const ro = new ResizeObserver(() => {
	app.renderer.resize(el.canvasWrap.clientWidth, el.canvasWrap.clientHeight);
	applyTransform();
});
ro.observe(el.canvasWrap);

/* ------------------------------------------------------------------ *
 * Boot
 * ------------------------------------------------------------------ */
setPlaying(true);
el.loopBtn.dataset.on = "true";
el.gridBtn.dataset.on = "true";
el.grid.classList.add("is-on");
el.bonesBtn.dataset.on = "false";
el.flipBtn.dataset.on = "false";
el.delBtn.hidden = true;

/* Debug handle: lets the smoke tests (and the browser console) inspect the
 * live viewer state without re-deriving it — harmless in production. */
window.__spineStage = {
	get spine() { return spine; },
	get state() { return state; },
	get clock() { return clock; },
	get fps() { return fps; },
	get parts() { return parts; },
	sourcePixelScale: () => (spine ? sourcePixelScale(spine) : 0),
	pngOutputSize: () => (spine ? pngOutputSize(spine) : null),
};

initSidebar();
initTimeline();
initInspector();
initFullscreen();
initExport();
initFavorites();
initFps();
initParts();

// Restore the saved backdrop, if any. setStageBg() would also persist it, so
// only call it when we actually have a stored value.
try {
	const savedBg = localStorage.getItem("stageBg");
	if (savedBg && BG_ORDER.includes(savedBg)) setStageBg(savedBg, { persist: false });
} catch {
	/* private mode — keep the default */
}

app.renderer.resize(el.canvasWrap.clientWidth, el.canvasWrap.clientHeight);
refresh();
