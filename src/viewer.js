import { Application, Container, Graphics, Assets, BaseTexture, Texture, RenderTexture, Rectangle, SCALE_MODES, MIPMAP_MODES, WRAP_MODES, ALPHA_MODES, BLEND_MODES } from "pixi.js";
import { Spine, SkeletonBounds, TextureAtlas } from "pixi-spine";
import * as runtime37 from "@pixi-spine/runtime-3.7";
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
// Spine 4.3 — same story as 4.2: pixi-spine's `Spine` only knows 3.7/3.8/4.0/4.1,
// and 4.2's spine-core predates the 4.3 binary layout (it never gets past
// readString on the header). So 4.3 models are parsed AND drawn by the official
// renderer at the matching release, all taken from this one package (its nested
// spine-core must be the same copy the renderer's `instanceof` checks use).
import {
	Spine as Spine43,
	SpineTexture as SpineTexture43,
	SkeletonBinary as SkeletonBinary43,
	SkeletonJson as SkeletonJson43,
	TextureAtlas as TextureAtlas43,
	AtlasAttachmentLoader as AtlasAttachmentLoader43,
} from "@esotericsoftware/spine-pixi-v7";
import * as runtime43 from "@esotericsoftware/spine-pixi-v7";
import { InteractionController } from "./interaction-core.js";
import { libraryIndex } from "./library-index.js";
import { loadTextures } from "@pixi/assets";
import {
	detectSpineVersion,
	pickRuntime,
} from "./spine-version.cjs";
import {
	isLive2D,
	loadLive2D,
	live2DAnimations,
	playLive2DMotion,
	setLive2DExpression,
	live2DExpressions,
	setLive2DLive,
	live2DMotionGroups,
	live2DMotionFinished,
	live2DMotionTime,
	live2DMotionDuration,
	live2DSeekMotion,
} from "./live2d.js";
import { loadVideo, disposeVideo, videoElement, videoStageActive } from "./video-stage.js";
import { loadImage, disposeImage, imageStageActive, imageElement } from "./image-stage.js";
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
 * Game-level PMA default — a full MODE (auto / on / off / upload), not just a
 * boolean. Set per game from the model metadata (`pmaDefault` on /api/models),
 * so a whole game can default to e.g. "upload" without touching every model.
 * Used whenever the viewer's selector is on Auto:
 *   - "on"     → the game ships premultiplied textures without saying so
 *                (dark fringes if treated as straight) → force PMA
 *   - "off"    → straight alpha, atlas says nothing
 *   - "upload" → straight textures with stale colour in transparent texels
 *                (white patches) → premultiply on upload
 */
let gameDefaultMode = PMA_MODES.auto;

/** Accepts true/false (legacy booleans) or a mode string; returns a mode. */
function normalizePmaMode(v) {
	if (v === true) return PMA_MODES.on;
	if (v === false || v == null) return PMA_MODES.auto;
	const s = String(v);
	return PMA_MODES[s] ? s : PMA_MODES.auto;
}

/** The mode actually in effect: the user's pick, else what Auto resolves to. */
function resolvedMode() {
	// An explicit user pick always wins.
	if (pmaMode !== PMA_MODES.auto) return pmaMode;
	// Auto. This keeps the ORIGINAL decision untouched — an explicit atlas
	// `pma:` flag wins, otherwise the game default (false/on/off) applies —
	// and only refines the straight-alpha case with the game-level "upload"
	// mode. So games whose default is on/off/auto behave exactly as before.
	if (declaredPMA()) return PMA_MODES.on;
	if (gameDefaultMode === PMA_MODES.upload) return PMA_MODES.upload;
	return PMA_MODES.off;
}

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
	// otherwise fall back to the game's default mode.
	const flags = ([]).concat(
		...(current?.atlasPagesFlags || []).length
			? [current.atlasPagesFlags]
			: []
	);
	const explicit = flags.filter((f) => f === true || f === false);
	if (explicit.length) return explicit.some((f) => f === true);
	return gameDefaultMode === PMA_MODES.on;
}

/** Where the Auto decision came from: the atlas flag, or the game default. */
function pmaSource() {
	if (pmaMode === PMA_MODES.on) return "forced-on";
	if (pmaMode === PMA_MODES.off) return "forced-off";
	if (pmaMode === PMA_MODES.upload) return "forced-upload";
	const flags = current?.atlasPagesFlags || [];
	if (flags.some((f) => f === true || f === false)) return "atlas";
	return gameDefaultMode !== PMA_MODES.auto ? "game-default" : "default";
}

function pmaActive() {
	// An explicit user pick always wins over the atlas and the game default.
	if (pmaMode === PMA_MODES.on) return true;
	if (pmaMode === PMA_MODES.off || pmaMode === PMA_MODES.upload) return false;
	// Auto: an explicit atlas `pma:` line wins, else the game's default mode.
	return declaredPMA();
}

/** The Pixi ALPHA_MODES value matching the current PMA setting. */
function currentAlphaMode() {
	// "upload" is its own thing — neither PMA nor straight. Hand Pixi a
	// straight-alpha bitmap (UNPACK means "the stored bytes are NOT
	// premultiplied") and let it premultiply during upload, with the NPM
	// blend. See the PMA_MODES comment for why this fixes white patches.
	if (resolvedMode() === PMA_MODES.upload) return ALPHA_MODES.UNPACK;
	return pmaActive() ? ALPHA_MODES.PMA : ALPHA_MODES.NPM;
}

/** Collect the atlas page baseTextures currently in use. */
function atlasBaseTextures() {
	const out = [];
	// Live2D/Cubism models have no spine.skeleton — bail out, or a PMA toggle
	// (which calls applyPMA for every model type) dies on `undefined.slots`.
	if (!spine?.skeleton) return out;
	const seen = new Set();
	const add = (bt) => {
		if (bt && !seen.has(bt.uid)) {
			seen.add(bt.uid);
			out.push(bt);
		}
	};
	for (const slot of spine.skeleton.slots) {
		const page = slotAttachment(slot)?.region?.page;
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
	// Only Spine models have `skeleton.slots`. A Live2D model reaches here via a
	// PMA toggle (applyPMA runs for every model type), where `spine.skeleton` is
	// undefined → "Cannot read properties of undefined (reading 'slots')".
	if (!spine?.skeleton) return;
	// "upload" premultiplies the texture but still wants the straight-alpha
	// (NPM) blend, and it is not a real PMA state — keep it out of pmaActive()
	// so the HUD keeps reading it as straight. Same for a game default of
	// "upload" reached through Auto.
	const pma = pmaActive() && resolvedMode() !== PMA_MODES.upload;

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
	viewListBtn: $("#view-list-btn"),
	layoutEl: $(".layout"),
	viewGridBtn: $("#view-grid-btn"),

	// Filter CZN (tab Combatants/Partner + atribut wiki)
	cznFilters: $("#czn-filters"),
	cznReset: $("#czn-reset"),
	favCount: $("#fav-count"),

	animSelect: $("#anim-select"),
	skinSelect: $("#skin-select"),
	variantSelect: $("#variant-select"),
	variantWrap: $("#variant-wrap"),
	// BD2 variant popup (right stage edge) — replaces the inline dropdown there.
	variantBtn: $("#variant-btn"),
	variantCount: $("#variant-count"),
	variantPopup: $("#variant-popup"),
	variantList: $("#variant-list"),
	variantPopTitle: $("#variant-popup-title"),
	variantPopClose: $("#variant-popup-close"),
	// Tab varian cepat (<=3 varian) + preview hover di popup.
	variantTabs: $("#variant-tabs"),
	variantPreview: $("#variant-preview"),
	variantPreviewImg: $("#variant-preview-img"),
	variantPreviewLabel: $("#variant-preview-label"),

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
	slotToggleAll: $("#slot-toggle-all"),
	slotCount: $("#slot-count"),
	cmpA: $("#cmp-a"),
	cmpB: $("#cmp-b"),
	cmpRun: $("#cmp-run"),
	abToggle: $("#ab-toggle"),
	abLabel: $("#ab-label"),
	abBar: $("#ab-bar"),
	abLayout: $("#ab-layout"),
	abOnion: $("#ab-onion"),
	abReset: $("#ab-reset"),
	abLock: $("#ab-lock"),
	abOffset: $("#ab-offset"),
	abScale: $("#ab-scale"),
	cmpNote: $("#cmp-note"),
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
	fsExit: $("#fs-exit"),
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
	updateLogBtn: $("#update-log-btn"),
	updateLogModal: $("#update-log-modal"),
	updateLogView: $("#update-log-view"),
	updateLogStatus: $("#update-log-status"),
	updateLogClose: $("#update-log-close"),
	updateLogClose2: $("#update-log-close2"),
	updateLogClear: $("#update-log-clear"),
	healthBtn: $("#health-btn"),
	healthModal: $("#updater-health-modal"),
	healthRows: $("#health-rows"),
	healthSummary: $("#health-summary"),
	healthStatus: $("#health-status"),
	healthLog: $("#health-log"),
	healthRefresh: $("#health-refresh"),
	healthApply: $("#health-apply"),
	healthClose: $("#health-close"),
	healthClose2: $("#health-close2"),
	gridBtn: $("#grid-btn"),
	bonesBtn: $("#bones-btn"),
	boundsBtn: $("#bounds-btn"),
	boundsPanel: $("#bounds-panel"),
	vtxBtn: $("#vtx-btn"),
	vtxPanel: $("#vtx-panel"),
	partsBtn: $("#parts-btn"),
	boneEditBtn: $("#bone-edit-btn"),
	ikBtn: $("#ik-btn"),
	ikPanel: $("#ik-panel"),
	bonePanel: $("#bone-panel"),
	boneTree: $("#bone-tree"),
	boneSearch: $("#bone-search"),
	slotTipBtn: $("#slot-tip-btn"),
	cardsBtn: $("#cards-btn"),
	cardsModal: $("#cards-modal"),
	cardsGrid: $("#cards-grid"),
	cardsClose: $("#cards-close"),
	densitySelect: $("#density-select"),
	pmaSelect: $("#pma-select"),

	// Live2D extras (hidden for non-Cubism models)
	l2dExtra: $("#l2d-extra"),
	l2dLiveBtn: $("#l2d-live-btn"),
	l2dRandomBtn: $("#l2d-random-btn"),
	l2dAutoBtn: $("#l2d-auto-btn"),
	l2dTouchBtn: $("#l2d-touch-btn"),

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
	stageBackdrop: $("#stage-backdrop"),
	backdropBtn: $("#backdrop-btn"),
	backdropSelect: $("#backdrop-select"),
	toast: $("#toast"),
	drop: $("#drop"),
	file: $("#file"),
	folder: $("#folder"),
	uploadBtn: $("#upload-btn"),
	delBtn: $("#del-btn"),

	// permalink / "Tautan tampilan"
	gridLink: $("#link-btn"),
	linkModal: $("#link-modal"),
	linkUrl: $("#link-url"),
	linkCopy: $("#link-copy"),
	linkRefresh: $("#link-refresh"),
	linkClose: $("#link-close"),
	linkNote: $("#link-note"),
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

/* Renderer kedua untuk panel B.
 *
 * Kenapa renderer terpisah, bukan satu renderer yang dibagi dua: satu kanvas
 * berarti satu kamera, jadi zoom/pan langsung berlaku untuk A dan B sekaligus.
 * Canvas Spine beda-beda besar (3839x6715 vs 1136x2260 pada pengujian), dan
 * tanpa kamera sendiri per panel, salah satu model pasti tampil melenceng. */
let appB = null;
/** Kamera panel B — terpisah dari `state` milik A. */
const camB = { zoom: 1, panX: 0, panY: 0, flip: false };

let spine = null;
let current = null;
let animName = null;
let duration = 0;
/** Tears down the previous Cubism model (Live2DModel needs its own cleanup). */
let live2dDispose = null;
/**
 * Destroy the model currently on the stage exactly once and forget it.
 *
 * A Live2D model is reachable through BOTH `spine` and `live2dDispose`, and
 * pixi-live2d-display's InternalModel.destroy() is NOT idempotent (a second
 * call dereferences its already-nulled motionManager → "Cannot read properties
 * of undefined (reading 'destroy')"). Routing EVERY teardown through here — and
 * clearing both refs BEFORE destroying — makes disposal single-shot whichever
 * path gets there first (load, eject, game switch, delete). Never call
 * spine.destroy()/live2dDispose() directly.
 */
/* ------------------------------------------------------------------ *
 * Banding A/B: dua model, satu jam
 * ------------------------------------------------------------------ *
 * Pilihan desain yang sengaja dibuat:
 *
 * - Model B hidup sebagai instance `AB.second` TERPISAH dari `spine`. Semua
 *   jalur teardown, PMA, part picker, dan inspector sudah berputar di sekitar
 *   `spine`; menaruh model kedua di variabel yang sama akan membuat separuh
 *   kode mengira B itu model utama.
 * - Keduanya digerakkan oleh SATU clock (`clock.tick`), bukan dua ticker,
 *   sehingga A dan B tidak pernah melenceng satu sama lain.
 * - Onion skin memakai snapshot pose (bukan salinan render), supaya biayanya
 *   hanya update skeleton + sekali gambar per bayangan.
 */
const AB = {
	on: false,
	second: null,      // instance Spine model B
	runtime: null,
	model: { A: null, B: null },
	anim: { A: null, B: null },
	dur: { A: 0, B: 0 },
	layout: "split",   // "split" (berdampingan) | "overlay" (tumpang tindih)
	offset: { x: 0, y: 0 },   // geseran manual model B, dalam piksel layar
	// Kunci sinkron: kalau true, model A ikut bergerak saat B digeser, jadi
	// yang berubah hanya posisi relatifnya. Kalau false, geser B menjauh dari A.
	lock: false,
	// Cara menyamakan ukuran saat canvas kedua model berbeda.
	//   "fit"       -> tiap model diskalakan agar tingginya sama (default;
	//                  membuat karakter seukuran, bukan kanvasnya)
	//   "canvas"    -> tiap model diskalakan agar KANVAS deklaratifnya sama
	//                  besar, jadi perbandingan 1:1 seperti aslinya
	//   "native"    -> tanpa penyesuaian, zoom yang sama persis (yang lama)
	scaleMode: "fit",
	onion: 0,          // jumlah bayangan ke belakang (0 = mati)
	opacity: 0.3,
	seq: 0,
	busy: false,
	pending: null,
	ghostRoot: null,
	ghosts: [],
};

/** Seretan posisi model B. null = tidak sedang menyeret. */
let abDrag = null;
/** Panel yang kameranya sedang diseret: "A", "B", atau "BOTH" (overlay). */
let dragPane = null;
/** Panel yang sedang di-pinch, untuk zoom sentuh. */
let pinchPane = "A";

/** Panel mana yang berada di bawah titik layar ini. */
function paneUnder(clientX, clientY) {
	const paneB = document.getElementById("ab-pane-b");
	if (!AB.on || !AB.second || !paneB || paneB.hidden) return "A";
	// Mode tumpang tindih: panel B menutupi semuanya, jadi seretan
	// menggerakkan KEDUA kamera supaya posisi relatifnya tidak berubah.
	if (AB.layout === "overlay") return "BOTH";
	const r = paneB.getBoundingClientRect();
	const inB =
		clientX >= r.left && clientX <= r.right &&
		clientY >= r.top && clientY <= r.bottom;
	return inB ? "B" : "A";
}
/** Container model B — hidup di luar `world` supaya posisinya piksel layar. */
let abSecondRoot = null;

/**
 * Akhiri seretan A/B.
 *
 * Terpasang di `window`, bukan di #canvas-wrap: seretan tombol kanan tidak
 * mengisi map gesture `pointers`, dan tanpa setPointerCapture yang berhasil
 * pointerup-nya bisa mendarat di mana saja — jadi endDrag yang lama tidak
 * pernah membersihkan abDrag dan seretan "menempel" setelah mouse dilepas.
 */
function abEndDrag() {
	if (!abDrag) return;
	abDrag = null;
	el.canvasWrap.classList.remove("is-dragging");
	schedulePermalinkWrite?.();
}
window.addEventListener("pointerup", abEndDrag);
window.addEventListener("pointercancel", abEndDrag);

/**
 * Apakah titik layar ini jatuh di panel B (sisi kanan saat split)?
 * Dipakai supaya seretan kiri/kanan tidak perlu modifier terus-menerus.
 */
function abHitB(clientX) {
	if (!AB.on || !AB.second) return false;
	if (AB.layout === "overlay") return true;   // tumpang tindih: selalu B
	const r = el.canvasWrap.getBoundingClientRect();
	return clientX - r.left > r.width / 2;
}

/** Buat renderer panel B kalau belum ada; pasang kanvasnya di panel B. */
function ensureAppB() {
	const pane = document.getElementById("ab-pane-b");
	if (!pane) return null;
	if (appB) {
		try {
			const w = pane.clientWidth || 1;
			const h = pane.clientHeight || 1;
			appB.renderer.resize(w, h);
		} catch {
			/* renderer belum siap */
		}
		return appB;
	}
	try {
		appB = new Application({
			backgroundAlpha: 0,
			antialias: true,
			resolution: Math.min(window.devicePixelRatio || 1, 2),
			autoDensity: true,
			powerPreference: "high-performance",
			width: Math.max(1, pane.clientWidth || 1),
			height: Math.max(1, pane.clientHeight || 1),
		});
		pane.appendChild(appB.view);
		return appB;
	} catch (err) {
		// Dua konteks WebGL bisa gagal di GPU terbatas; A/B jatuh ke satu
		// panggung daripada tidak bisa dipakai sama sekali.
		console.error("[ab] renderer kedua gagal dibuat:", err);
		return null;
	}
}

/** Tutup renderer panel B dan lepas kanvasnya. */
function destroyAppB() {
	if (!appB) return;
	try {
		appB.destroy(true, { children: true, texture: false, baseTexture: false });
	} catch {
		/* sudah hilang */
	}
	appB = null;
}

/** Instance yang digerakkan ticker: `spine`, plus model B saat A/B aktif. */
function drivenSpines() {
	return AB.on && AB.second?.skeleton ? [spine, AB.second] : [spine];
}

/** Seek instance ke detik `t` pada animasinya, lalu terapkan posenya. */
function poseAt(inst, animName, t) {
	if (!inst?.state || !inst?.skeleton || !animName) return;
	let track = inst.state.tracks?.[0];
	// Instance baru belum punya track sama sekali, dan track lama bisa saja
	// memegang animasi lain — dua keadaan yang harus ditangani terpisah.
	// (Hanya mengandalkan `track.animation.name !== animName` membuat model B
	// diam di pose setup:-track-nya undefined, bukan beda nama.)
	if (!track || !track.animation || track.animation.name !== animName) {
		inst.state.setAnimation(0, animName, true);
		track = inst.state.tracks?.[0];
		if (!track) return;
	}
	track.trackTime = t;
	// dt = 0: kita yang menempatkan track, update() hanya menerapkan + gambar.
	inst.update?.(0);
}

function destroyCurrent({ removeFromStage = true } = {}) {
	const s = spine;
	const d = live2dDispose;
	// Clear both referents FIRST so a re-entrant teardown is a no-op.
	spine = null;
	live2dDispose = null;
	if (s && removeFromStage) {
		try {
			stageRoot.removeChild(s);
		} catch {
			/* not a child */
		}
	}
	if (s) {
		try {
			// Guard: a Cubism model that never finished loading has no
			// internalModel, and the plugin's destroy() dereferences it blindly.
			if (!s.internalModel || s.internalModel.destroyed !== true) {
				s.destroy?.(true);
			}
		} catch {
			/* already gone / half-built */
		}
	}
	// The wrapper's dispose() is idempotent, so even when the same model is both
	// `s` and `d` it can only be destroyed once.
	if (typeof d === "function") {
		try {
			d();
		} catch {
			/* already gone */
		}
	}
}
/** Cached centring offset for the current Cubism model (see fitModel). */
let live2dCentre = null;

/* --- Live2D "living" extras: blink/breath/physics, random, auto-advance ---- */
/** Master switch for auto-blink + breath + physics on Cubism models. */
let live2dLiveOn = true;
/** Random motion every few seconds while it sits on an idle clip. */
let live2dRandomOn = false;
/** Advance to the next motion once the current one finishes. */
let live2dAutoNext = false;
let live2dAutoNextAt = 0;
/** Extra touch motions layered ON TOP of the base animation (Cubism motions
 *  play additively via the motion queue), so a tap animates the tapped part
 *  without losing the idle movement. */
let live2dTouchOn = true;
const live2dTouchRecent = [];
/** Smallest interval between two touch reactions, so a spam of taps on a
 *  hundred-motion model does not queue up minutes of animation. */
const LIVE2D_TOUCH_COOLDOWN = 350;

/** Apply the current "living" switch to whichever Cubism model is on stage. */
function live2dLiveApply(m) {
	if (!m || !m.internalModel) return;
	setLive2DLive(m, live2dLiveOn);
}

/** Play a touch reaction: pick the best matching motion for a hit zone.
 *  Most models have touch_head/touch_body; a few (girlwars) use tapHead/tapXiong
 *  and tapPigu, so a tap in the lower third rotates through the "rods". */
function live2dTouchPlay(part, xFrac) {
	if (!isLive2D(current) || !spine) return false;
	const names = (current.animations || []).filter(Boolean);
	if (!names.length) return false;
	const has = (n) => names.find((v) => v.toLowerCase() === n.toLowerCase());
	const startWith = (pre) => names.filter((n) => n.toLowerCase().startsWith(pre));
	let pick = null;
	if (part === "head") {
		pick = has("touch_head") || has("taphead") || startWith("touch_head")[0] || startWith("taphead")[0];
	} else if (part === "body") {
		pick = has("touch_body") || has("tapxiong") || startWith("touch_body")[0];
	} else {
		// lower third: boy/girl models many, girlwars per-part taps
		const parts = ["tapxiong", "tappigu", "tapleg", "tapsiwa", "tapyifu", "tapmaojin", "tapkou"]
			.map((p) => startWith(p)[0])
			.filter(Boolean);
		pick = startWith("touch_drag")[0] || (parts.length ? parts[Math.floor((xFrac || 0.5) * parts.length)] : null);
	}
	if (!pick) pick = startWith("touch_")[0] || startWith("tap")[0];
	if (!pick) return false;
	return playLive2DMotion(spine, pick);
}

/** Touch handling on the model: translate the click into the model's own
 *  coordinate space, then pick a zone by the hit height (upper third = head,
 *  middle = body, lower = legs/rods). Physics shifts with a small kick. */
function live2dTouchAt(ev) {
	if (!live2dTouchOn || !isLive2D(current) || !spine) return;
	const now = performance.now();
	if (now - (live2dTouchRecent[live2dTouchRecent.length - 1] || 0) < LIVE2D_TOUCH_COOLDOWN) return;
	live2dTouchRecent.push(now);
	if (live2dTouchRecent.length > 10) live2dTouchRecent.shift();
	// Map the pointer into the model's vertical span (0 = feet, 1 = crown), so a
	// tap high on the body hits "head" and a low tap hits the legs.
	let frac = 0.5;
	try {
		const p = toStagePoint(ev.clientX, ev.clientY);
		const b = spine.getBounds(); // model AABB in stage pixels
		if (b && b.height > 0) {
			frac = Math.min(1, Math.max(0, 1 - (p.y - b.y) / b.height));
		}
	} catch {
		/* fall back to the middle zone */
	}
	const part = frac > 0.62 ? "head" : frac > 0.33 ? "body" : "lower";
	const played = live2dTouchPlay(part, frac);
	if (played) live2dUpdateDuration();
	// Reflect the reaction in the dropdown so it is clear what just played.
	if (played && el.animSelect && current && current.animations) {
		const names = current.animations;
		const hit = names.find((n) => /^(touch|tap)/i.test(n) && (part === "head" ? /head/i : part === "body" ? /(body|xiong)/i : /(drag|leg|pigu|siwa|yifu)/i).test(n));
		const pick = hit || names.find((n) => /^(touch|tap)/i.test(n));
		if (pick) {
			animName = pick;
			el.animSelect.value = pick;
		}
	}
	// A tap plays a real touch motion (real reaction); no synthetic kick — the
	// plugin overwrites these parameters every frame anyway.
}

/** Nudge the head/body angle parameters so a tap visibly registers even with
 *  no free touch motion available. */
function live2dHeadKick(part) {
	const core = spine?.internalModel?.coreModel;
	if (!core) return;
	try {
		const t = part === "head" ? 1 : 0.5;
		const dir = Math.random() < 0.5 ? -1 : 1;
		const set = (id, v) => {
			try {
				core.setParameterValueById(id, v);
			} catch {
				/* not every model has these */
			}
		};
		set("ParamAngleZ", 10 * t * dir);
		set("ParamBodyAngleZ", 4 * t * dir);
	} catch {
		/* ignore */
	}
}


/** True once the currently playing Cubism motion has ended (or nothing plays). */
function live2dMotionDone() {
	if (!isLive2D(current) || !spine) return true;
	return live2DMotionFinished(spine);
}

/** Read the on-stage motion's length (seconds) into the shared duration + label.
 *  Called after any motion starts, since the Cubism manager knows the length
 *  only once a motion is queued. */
function live2dUpdateDuration() {
	if (!isLive2D(current) || !spine) return;
	const d = live2DMotionDuration(spine);
	duration = d > 0 ? d : 0;
	if (el.timeDur) el.timeDur.textContent = d > 0 ? d.toFixed(2) + "s" : "—";
}

// Debug hook: the headless harness needs to read the live-effect state and to
// drive one update explicitly (the plugin's own update is internal).
window.__l2d = {
	touchAt: (x, y) => live2dTouchAt({ clientX: x, clientY: y, button: 0 }),
	state: () => ({
		live: live2dLiveOn,
		random: live2dRandomOn,
		autoNext: live2dAutoNext,
		touch: live2dTouchOn,
		anim: animName,
		isLive2D: isLive2D(current),
		time: isLive2D(current) ? live2DMotionTime(spine) : null,
		duration: isLive2D(current) ? live2DMotionDuration(spine) : null,
	}),
};



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
	// Gambar latar (backdrop) opsional: `backdropOn` = tombol on/off,
	// `backdrop` = scene terakhir yang dipilih (tetap diingat saat mati).
	backdropOn: false,
	backdrop: "aurora",
	// Render pixel density. "auto" = devicePixelRatio capped at 2 (previous
	// behaviour); a number overrides it, so the stage can be rendered at 3-4x
	// for extra sharpness on zoomed-in art or high-DPI screens.
	density: "auto",
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
 * Kartu skill Chaos Zero Nightmare
 *
 * Tombol "Kartu" hanya muncul untuk model CZN yang id-nya bisa dipetakan ke
 * id karakter numerik. Kartu milik karakter itu diambil dari
 * /api/czn-cards/<charid> lalu ditampilkan sebagai petak ilustrasi.
 *
 * Id rig CZN punya BANYAK bentuk, bukan hanya "1056_01":
 *   portrait_1003_front, model_1003, liveevent_1003, battle_1004, 1056_01
 * Karena itu angka karakter diambil dari MANA PUN di bagian akhir id, bukan
 * hanya dari awalan. Versi pertama hanya membaca awalan, akibatnya tombol
 * Kartu cuma muncul di 8 dari 1143 model — padahal kartu tersedia untuk 69
 * karakter dan 271 model bisa dipetakan.
 *
 * Kandidat angka disaring dengan daftar id karakter yang benar-benar punya
 * kartu (diambil sekali dari /api/czn-cards), supaya "01" pada "1056_01"
 * tidak salah dianggap id karakter.
 * ------------------------------------------------------------------ */
const CZN_CHAR_RE = /^(?:czn-(?:rigs|cutins-cg)|chaoszero)\//;

/** Set id karakter yang punya kartu, diisi sekali lewat ensureCznCharIds(). */
let cznCharIds = null;
let cznCharIdsPromise = null;

function ensureCznCharIds() {
	if (cznCharIds) return Promise.resolve(cznCharIds);
	if (!cznCharIdsPromise) {
		cznCharIdsPromise = fetch("/api/czn-cards")
			.then((r) => r.json())
			.then((d) => {
				cznCharIds = new Set(Object.keys(d.chars || {}));
				// Setelah daftar siap, tombol untuk model yang sedang tampil
				// perlu dihitung ulang: sebelum ini tebakannya mungkin salah.
				if (current) syncCardsButton(current);
				return cznCharIds;
			})
			.catch(() => {
				cznCharIds = new Set();
				return cznCharIds;
			});
	}
	return cznCharIdsPromise;
}

/** id karakter CZN dari sebuah model, atau null. */
function cznCharId(model) {
	const id = String(model?.id || "");
	if (!CZN_CHAR_RE.test(id)) return null;
	const leaf = id.split("/").pop() || "";
	const cands = leaf.match(/\d{3,6}/g) || [];
	if (!cands.length) return null;
	if (cznCharIds && cznCharIds.size) {
		// Cocokkan dengan daftar yang benar-benar punya kartu.
		return cands.find((c) => cznCharIds.has(c)) || null;
	}
	// Daftar belum siap: pakai angka terpanjang sebagai tebakan terbaik.
	return cands.slice().sort((a, b) => b.length - a.length)[0];
}

/** Tampilkan/sembunyikan tombol Kartu sesuai model yang sedang dibuka. */
function syncCardsButton(model) {
	const id = cznCharId(model);
	if (el.cardsBtn) el.cardsBtn.hidden = !id;
	// Panel ditutup saat model berganti: daftar kartu lama tidak berlaku lagi.
	if (el.cardsModal && !el.cardsModal.hidden && !id) closeCards();
}

function closeCards() {
	if (el.cardsModal) el.cardsModal.hidden = true;
}

async function openCards() {
	const id = cznCharId(current);
	if (!id || !el.cardsModal) return;
	el.cardsModal.hidden = false;
	if (el.cardsGrid) el.cardsGrid.innerHTML = "";
	// Tidak ada teks status: panel ini hanya menampilkan ilustrasi.
	try {
		const data = await fetch(`/api/czn-cards/${id}`).then((r) => r.json());
		const cards = data.cards || [];
		if (!el.cardsGrid) return;
		renderCards(cards);
	} catch {
		// Gagal memuat: biarkan panel kosong, tanpa pesan teks.
	}
}

/** Gambar petak kartu. Panel ini sengaja tanpa teks: tidak ada judul,
 *  caption, maupun tombol saringan — hanya ilustrasi dan bingkainya. */
function renderCards(cards) {
	if (!el.cardsGrid) return;
	el.cardsGrid.innerHTML = "";
	for (const c of cards) {
		{
			const fig = document.createElement("figure");
			fig.className = "card-tile";
			// Utamakan animasi .webm; ilustrasi .webp hanya cadangan. Sebagian
			// besar kartu "unique" punya animasi, kartu "start" tidak.
			let media;
			if (c.video && c.videoUrl) {
				const v = document.createElement("video");
				v.src = c.videoUrl;
				v.width = 210;
				v.height = 316;
				v.autoplay = true;
				v.loop = true;
				v.muted = true; // wajib: autoplay diblokir kalau bersuara
				v.playsInline = true;
				v.preload = "metadata";
				// Kalau .webm gagal, jatuh ke ilustrasi diam tanpa memaksa
				// pengguna memuat ulang panel.
				v.addEventListener(
					"error",
					() => {
						const img = document.createElement("img");
						img.src = c.url;
						img.alt = c.file.replace(/\.webp$/i, "");
						img.width = 210;
						img.height = 316;
						v.replaceWith(img);
					},
					{ once: true }
				);
				media = v;
			} else {
				const img = document.createElement("img");
				img.src = c.url;
				img.alt = c.file.replace(/\.webp$/i, "");
				img.loading = "lazy";
				img.decoding = "async";
				img.width = 210;
				img.height = 316;
				media = img;
			}
			const isUnique = /^unique/i.test(c.file);
			// Bingkai mengikuti data wiki, bukan hardcode: ego milik karakter dan
			// rarity kartu (common/rare/legend/unique). Fallback aman kalau
			// metadata lama belum punya field ini.
			const EGO_FRAMES = ["instinct", "norms", "love", "creed", "narcissism"];
			const RARITY_FRAMES = ["common", "rare", "legend", "unique"];
			const ego = EGO_FRAMES.includes(String(c.ego || "").toLowerCase())
				? String(c.ego).toLowerCase() : "creed";
			const rarity = RARITY_FRAMES.includes(String(c.rarity || "").toLowerCase())
				? String(c.rarity).toLowerCase() : (isUnique ? "unique" : "common");
			const name = c.name || c.file.replace(/\.webp$/i, "");
			const desc = c.desc || "";
			fig.title = desc ? `${name}\n${desc}` : name;
			fig.setAttribute("aria-label", desc ? `${name}. ${desc}` : name);

			// Semua lapisan visual (media + bingkai + rarity + kilau) dibungkus
			// supaya absolute positioning-nya berhenti di tepi ilustrasi dan
			// tidak menutupi caption deskripsi di bawahnya.
			const art = document.createElement("span");
			art.className = "ct-art";
			const frame = document.createElement("span");
			frame.className = "ct-frame";
			frame.style.backgroundImage = `url(/czn-frame/card_ego_${ego}.webp)`;
			const rar = document.createElement("img");
			rar.className = "ct-rarity";
			rar.src = `/czn-frame/card_rarity_${rarity}.webp`;
			rar.alt = "";
			const shine = document.createElement("span");
			shine.className = "ct-shine";
			art.append(media, frame, rar, shine);

			// Deskripsi dari desc_display wiki. HTML-nya sudah disanitasi di
			// tools/czn/refresh-cards.py: cuma <span style>, <u> dan <br>.
			const variants = Array.isArray(c.descs) ? c.descs : [];
			const cap = document.createElement("figcaption");
			cap.className = "ct-caption";
			const cost = typeof c.cost === "number"
				? `<span class="ct-cost" title="Cost">${c.cost}</span>` : "";
			const body = c.descHtml || escapeHtml(desc);
			cap.innerHTML = `<span class="ct-name">${escapeHtml(name)}${cost}</span>` +
				`<span class="ct-desc">${body}</span>`;
			if (variants.length > 1) {
				const more = document.createElement("button");
				more.type = "button";
				more.className = "ct-more";
				more.textContent = `+${variants.length - 1} varian`;
				more.addEventListener("click", (e) => {
					e.stopPropagation();
					const on = fig.classList.toggle("is-expanded");
					more.textContent = on ? "Tutup varian" : `+${variants.length - 1} varian`;
				});
				cap.append(more);
				const panel = document.createElement("div");
				panel.className = "ct-variants";
				panel.innerHTML = variants.map((v, i) =>
					`<p><b>${i + 1}.</b> ${v.html || escapeHtml(v.text || "")}</p>`).join("");
				art.append(panel);
			}
			fig.append(art, cap);
			wireCardTilt(fig);
			el.cardsGrid.append(fig);
		}
	}
}

/**
 * Efek kartu bergerak: tilt 3D + kilau mengikuti kursor.
 *
 * Meniru perilaku kartu di wiki: saat kursor bergerak di atas kartu, kartu
 * dimiringkan pada sumbu X/Y (perspective) dan lapisan kilau bergeser
 * mengikuti posisi kursor. Sudut dibatasi ±12° supaya tidak terlihat seperti
 * kartu yang terpelintir.
 *
 * Nilai ditulis sebagai CSS custom property, bukan style transform langsung,
 * supaya transisi halus saat kursor keluar (kartu kembali datar) tidak
 * bertabrakan dengan pembaruan tiap gerakan.
 */
function wireCardTilt(el) {
	const MAX = 12;
	const onMove = (ev) => {
		const r = el.getBoundingClientRect();
		if (!r.width || !r.height) return;
		// −1..1 dari tengah kartu
		const px = (ev.clientX - r.left) / r.width;
		const py = (ev.clientY - r.top) / r.height;
		const rotY = (px - 0.5) * 2 * MAX;
		const rotX = -(py - 0.5) * 2 * MAX;
		el.style.setProperty("--tilt-x", `${rotX.toFixed(2)}deg`);
		el.style.setProperty("--tilt-y", `${rotY.toFixed(2)}deg`);
		el.style.setProperty("--glow-x", `${(px * 100).toFixed(1)}%`);
		el.style.setProperty("--glow-y", `${(py * 100).toFixed(1)}%`);
		el.classList.add("is-tilting");
	};
	const onLeave = () => {
		el.classList.remove("is-tilting");
		el.style.setProperty("--tilt-x", "0deg");
		el.style.setProperty("--tilt-y", "0deg");
	};
	el.addEventListener("pointermove", onMove);
	el.addEventListener("pointerleave", onLeave);
	// Perangkat sentuh: kembalikan ke posisi datar setelah sentuhan berakhir.
	el.addEventListener("pointercancel", onLeave);
}

el.cardsBtn?.addEventListener("click", openCards);
el.cardsClose?.addEventListener("click", closeCards);
el.cardsModal?.querySelector('[data-close="1"]')?.addEventListener("click", closeCards);

/* ------------------------------------------------------------------ *
 * Bones overlay
 * ------------------------------------------------------------------ */
const bonesGfx = new Graphics();
// Overlay kotak bounds attachment (mode Bounds). Lapisan terpisah supaya
// drawBones() dan drawBoundsOverlay() tidak saling menghapus.
const boundsGfx = new Graphics();
// Overlay titik vertex mesh (mode Vertex).
const vtxGfx = new Graphics();
bonesGfx.visible = false;
stageRoot.addChild(bonesGfx);
stageRoot.addChild(boundsGfx);
boundsGfx.visible = false;
stageRoot.addChild(vtxGfx);
vtxGfx.visible = false;

/**
 * Bone editor — putar bone dengan mouse, simpan pose, ekspor ke JSON.
 *
 * Kenapa di world space dan bukan local: runtime Spine menyimpan rotasi bone
 * sebagai `rotation` (lokal, derajat) dan dunia diturunkan lewat
 * updateWorldTransform(). Mengubah rotasi lokal satu bone akan menggeser
 * SEMUA turunannya, yang justru yang diinginkan saat menggerakkan lengan.
 * Sudut disetel dari vektor world (bone -> kursor), lalu dikonversi balik ke
 * lokal dengan rotasi parent, supaya hasilnya tidak "melompat" saat bone
 * induknya sudah diputar lebih dulu.
 */
const BONES = {
	on: false,
	selected: null,
	dragging: false,
	hover: null,
	/**
	 * Rotasi hasil edit, disimpan per nama bone.
	 *
	 * Animasi menulis ulang `bone.rotation` setiap frame, jadi nilai hasil
	 * geser tidak bisa disimpan di bone itu sendiri — akan tertimpa. Map ini
	 * dipasang ulang setelah spine.update() di render loop.
	 */
	edits: new Map(),
	hitRadius: 18,
	/** Mode seret: "rotate" | "move" | "scale". */
	mode: "rotate",
	/** Titik awal seret, untuk menghitung selisih (mode move/scale). */
	dragStart: null,
	/** Nilai tulang saat seret dimulai. */
	dragBase: null,
};

/**
 * Pasang kembali semua hasil edit ke bone (dipanggil tiap frame).
 *
 * Nilai disimpan sebagai objek {rotation, x, y, scaleX, scaleY}; hanya field
 * yang benar-benar diubah yang ditulis, supaya tulang yang cuma diputar tidak
 * ikut "mengunci" posisinya dan tetap mengikuti animasi.
 */
function applyBoneEdits() {
	if (!spine?.skeleton) return;
	for (const b of spine.skeleton.bones) {
		const e = BONES.edits.get(b.data.name);
		if (!e) continue;
		if (typeof e === "number") {
			// Bentuk lama (pose tersimpan sebelum ada posisi/skala).
			b.rotation = e;
			continue;
		}
		if (e.rotation != null) b.rotation = e.rotation;
		if (e.x != null) b.x = e.x;
		if (e.y != null) b.y = e.y;
		if (e.scaleX != null) b.scaleX = e.scaleX;
		if (e.scaleY != null) b.scaleY = e.scaleY;
	}
}

/** Ambil record edit sebuah tulang sebagai objek (selalu objek baru). */
function boneEdit(name) {
	const e = BONES.edits.get(name);
	if (e == null) return {};
	return typeof e === "number" ? { rotation: e } : { ...e };
}

/** Simpan sebagian perubahan ke sebuah tulang. */
function writeBoneEdit(name, patch) {
	const next = { ...boneEdit(name), ...patch };
	BONES.edits.set(name, next);
	return next;
}

/** Semua bone yang bisa dipilih, urut dari yang paling dalam (anak dulu). */
function editableBones() {
	if (!spine?.skeleton) return [];
	return spine.skeleton.bones || [];
}

/**
 * Posisi & arah world sebuah bone.
 *
 * Runtime Spine 4.x TIDAK punya `worldX`/`worldY`/`a`/`b` (itu API 3.x).
 * Yang tersedia `bone.matrix` (affine 2D) berisi {a,b,c,d,tx,ty}:
 *   - (tx, ty)            = titik pangkal bone di world
 *   - atan2(c, a)         = rotasi world
 *   - normalize(a, b)     = sumbu X lokal (arah panjang bone)
 * Semua kode bone memakai helper ini supaya tidak menebak properti.
 */
function boneWorld(b) {
	const m = b.matrix;
	if (!m) return null;
	const x = m.tx;
	const y = m.ty;
	if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
	return {
		x,
		y,
		angle: Math.atan2(m.c, m.a),
		// sumbu X lokal yang sudah dinormalisasi (0..1)
		ux: m.a,
		uy: m.b,
		len: b.data.length || 0,
	};
}

/** Cari bone terdekat dari sebuah titik world. */
function boneAt(x, y) {
	const list = editableBones();
	if (!list.length) return null;
	const s = 1 / (state.zoom || 1);
	let best = null;
	let bestD = Infinity;
	for (const b of list) {
		const w = boneWorld(b);
		if (!w) continue;
		// Bone tanpa panjang tetap bisa dipilih lewat titik pangkalnya.
		let d;
		if (w.len > 0.01) {
			const ex = w.x + Math.cos(w.angle) * w.len;
			const ey = w.y + Math.sin(w.angle) * w.len;
			d = distToSegment(x, y, w.x, w.y, ex, ey);
		} else {
			d = Math.hypot(x - w.x, y - w.y);
		}
		if (d < bestD) {
			bestD = d;
			best = b;
		}
	}
	return bestD <= BONES.hitRadius * s ? best : null;
}

function distToSegment(px, py, x1, y1, x2, y2) {
	const dx = x2 - x1;
	const dy = y2 - y1;
	const l2 = dx * dx + dy * dy;
	if (l2 === 0) return Math.hypot(px - x1, py - y1);
	let t = ((px - x1) * dx + (py - y1) * dy) / l2;
	t = Math.max(0, Math.min(1, t));
	return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

/** Rotasi world (radian) dari sebuah bone, dari matriks world-nya. */
function boneWorldAngle(b) {
	const w = boneWorld(b);
	return w ? w.angle : 0;
}

/**
 * Set rotasi bone supaya ujungnya menunjuk ke titik world (x, y).
 * Menyimpan sebagai rotasi LOKAL (derajat), karena itu yang dibaca runtime.
 */
function aimBoneAt(b, x, y) {
	const w = boneWorld(b);
	if (!w) return;
	const parent = b.parent;
	// sudut world yang diinginkan, dari pangkal bone ke kursor
	const worldAngle = Math.atan2(y - w.y, x - w.x);
	// sudut world parent (0 kalau tidak ada parent)
	const parentAngle = parent ? boneWorldAngle(parent) : 0;
	// rotasi lokal = world - parent, dalam derajat
	let deg = (worldAngle - parentAngle) * (180 / Math.PI);
	deg = ((deg + 180) % 360 + 360) % 360 - 180; // normalisasi -180..180
	b.rotation = deg;
	writeBoneEdit(b.data.name, { rotation: deg });
}

/**
 * Geser tulang: ubah x/y LOKAL sebesar selisih kursor dalam satuan lokal.
 * Dibagi skala world supaya gerakan 1 px di layar tetap terasa 1 px walau
 * zoom berbeda.
 */
function moveBoneTo(b, dxWorld, dyWorld) {
	const base = BONES.dragBase;
	if (!base) return;
	const sx = world.scale.x || 1;
	const sy = world.scale.y || 1;
	let nx = base.x + dxWorld / sx;
	let ny = base.y + dyWorld / sy;
	b.x = nx;
	b.y = ny;
	writeBoneEdit(b.data.name, { x: nx, y: ny });
}

/** Skala tulang dari jarak kursor ke pangkalnya, relatif saat seret mulai. */
function scaleBoneTo(b, px, py) {
	const base = BONES.dragBase;
	const start = BONES.dragStart;
	if (!base || !start) return;
	const w = boneWorld(b);
	if (!w) return;
	// Rasio jarak kursor sekarang vs saat mulai, diukur dari pangkal tulang.
	const d0 = Math.max(8, Math.hypot(start.x - w.x, start.y - w.y));
	const d1 = Math.hypot(px - w.x, py - w.y);
	const k = Math.max(0.05, Math.min(20, d1 / d0));
	const sx = +(base.scaleX * k).toFixed(4);
	const sy = +(base.scaleY * k).toFixed(4);
	b.scaleX = sx;
	b.scaleY = sy;
	writeBoneEdit(b.data.name, { scaleX: sx, scaleY: sy });
}

/** Terapkan nilai absolut ke satu properti (dipakai input angka & nudge). */
function setBoneValue(b, prop, value) {
	if (!b || !Number.isFinite(value)) return;
	if (prop === "rotation") {
		let v = ((value + 180) % 360 + 360) % 360 - 180;
		b.rotation = v;
		writeBoneEdit(b.data.name, { rotation: v });
	} else {
		b[prop] = value;
		writeBoneEdit(b.data.name, { [prop]: value });
	}
}

/** Reset semua rotasi bone ke pose setup animasi saat ini. */
/* --- Riwayat pose (undo/redo) -----------------------------------------
 * Yang disimpan adalah SNAPSHOT seluruh BONES.edits, bukan satu tulang.
 * Map-nya kecil (puluhan entri), jadi menyalin utuh jauh lebih sederhana
 * dan tidak bisa salah dibanding mencatat operasi per tulang. Riwayat
 * direset tiap kali model berganti.
 */
const BONE_UNDO = { stack: [], index: -1, max: 40 };

/** Salin BONES.edits jadi struktur biasa yang aman disimpan. */
function snapshotEdits() {
	const out = {};
	for (const [name, raw] of BONES.edits) {
		out[name] = typeof raw === "number" ? { rotation: raw } : { ...raw };
	}
	return out;
}

function restoreEdits(snap) {
	// Bone yang kehilangan edit harus dikembalikan ke nilai SETUP (data),
	// bukan dibiarkan pada nilai hasil edit terakhir: applyBoneEdits hanya
	// menulis bone yang punya edit, jadi tanpa ini undo terlihat tidak
	// berefek sampai animasi kebetulan menimpanya.
	const skel = spine?.skeleton;
	if (skel) {
		// Kembalikan SELURUH field transform ke setup untuk setiap tulang yang
		// sedang diedit, lalu snapshot dipasang di atasnya. Hanya mengembalikan
		// field yang hilang tidak cukup: snapshot lama tidak memuat scaleX,
		// sehingga nilai skala dari aksi berikutnya tertinggal saat undo.
		for (const b of skel.bones) {
			if (!BONES.edits.has(b.data.name)) continue;
			b.rotation = b.data.rotation;
			b.x = b.data.x;
			b.y = b.data.y;
			b.scaleX = b.data.scaleX;
			b.scaleY = b.data.scaleY;
		}
	}
	BONES.edits.clear();
	for (const [name, rec] of Object.entries(snap || {})) {
		BONES.edits.set(name, { ...rec });
	}
}

/** Catat keadaan SEBELUM sebuah aksi diubah. Panggil sebelum mengubah edits. */
function pushBoneUndo() {
	if (!spine?.skeleton) return;
	const snap = snapshotEdits();
	// Jangan menumpuk keadaan yang identik: pola "catat sebelum, ubah, catat
	// sesudah" akan mencatat dua kali keadaan yang sama di antara aksi.
	const top = BONE_UNDO.stack[BONE_UNDO.index];
	if (top && JSON.stringify(top) === JSON.stringify(snap)) return;
	// Buang cabang redo kalau pengguna beraksi setelah undo.
	BONE_UNDO.stack.length = BONE_UNDO.index + 1;
	BONE_UNDO.stack.push(snap);
	if (BONE_UNDO.stack.length > BONE_UNDO.max) BONE_UNDO.stack.shift();
	BONE_UNDO.index = BONE_UNDO.stack.length - 1;
	bonesUndoUI();
}

/** Aksi "kosong" tidak perlu masuk riwayat: semua toolbar memanggil ini dulu. */
function boneUndoBegin() {
	// Snapshot hanya berguna kalau memang akan ada perubahan; pemanggil yang
	// tahu pasti. Di sini kita hanya memastikan tidak menumpuk snapshot sama.
	pushBoneUndo();
}

function boneUndoSync() {
	applyBoneEdits();
	spine?.skeleton?.updateWorldTransform?.();
	drawBones();
	updateBoneUI();
	bonesUndoUI();
}

function boneUndo() {
	if (BONE_UNDO.index <= 0) {
		toast("Tidak ada langkah untuk dibatalkan.");
		return;
	}
	BONE_UNDO.index -= 1;
	restoreEdits(BONE_UNDO.stack[BONE_UNDO.index]);
	boneUndoSync();
}

function boneRedo() {
	if (BONE_UNDO.index >= BONE_UNDO.stack.length - 1) {
		toast("Tidak ada langkah untuk diulang.");
		return;
	}
	BONE_UNDO.index += 1;
	restoreEdits(BONE_UNDO.stack[BONE_UNDO.index]);
	boneUndoSync();
}

/** Segarkan status tombol undo/redo. */
function bonesUndoUI() {
	const u = document.getElementById("bone-undo");
	const r = document.getElementById("bone-redo");
	if (u) u.disabled = BONE_UNDO.index <= 0;
	if (r) r.disabled = BONE_UNDO.index >= BONE_UNDO.stack.length - 1;
}

/** Model berganti: riwayat lama tidak berlaku lagi. */
function boneUndoReset() {
	BONE_UNDO.stack.length = 0;
	BONE_UNDO.index = -1;
	pushBoneUndo(); // keadaan awal jadi titik nol
}

function resetBonePose() {
	if (!spine?.skeleton) return;
	pushBoneUndo();
	BONES.edits.clear();
	const skel = spine.skeleton;
	// Setup pose = nilai dari data (bukan dari animasi yang sedang jalan).
	for (const b of skel.bones) {
		b.rotation = b.data.rotation;
		b.x = b.data.x;
		b.y = b.data.y;
		b.scaleX = b.data.scaleX;
		b.scaleY = b.data.scaleY;
	}
	skel.updateWorldTransform();
	drawBones();
	updateBoneUI();
	toast("Pose bone direset ke setup pose.");
}

/** Ekspor pose sekarang (hanya bone yang diubah dari setup). */
function exportBonePose() {
	if (!spine?.skeleton || !current) return;
	const out = { model: current.id, bones: {} };
	for (const [name, raw] of BONES.edits) {
		const e = typeof raw === "number" ? { rotation: raw } : raw;
		const rec = {};
		for (const k of ["rotation", "x", "y", "scaleX", "scaleY"]) {
			if (e[k] != null) rec[k] = +Number(e[k]).toFixed(4);
		}
		if (Object.keys(rec).length) out.bones[name] = rec;
	}
	const n = Object.keys(out.bones).length;
	if (!n) {
		toast("Belum ada tulang yang diubah.");
		return;
	}
	const blob = new Blob([JSON.stringify(out, null, 1)], { type: "application/json" });
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = `${String(current.id).replace(/[^\w.-]+/g, "_")}-pose.json`;
	a.click();
	URL.revokeObjectURL(a.href);
	toast(`Pose diekspor: ${n} tulang.`);
}

/** Muat pose dari berkas JSON (hasil exportBonePose). */
async function importBonePose(file) {
	if (!spine?.skeleton) return;
	let obj;
	try {
		obj = JSON.parse(await file.text());
	} catch (e) {
		toast("Berkas pose bukan JSON yang valid.");
		return;
	}
	pushBoneUndo();
	BONES.edits.clear();
	const known = new Set(spine.skeleton.bones.map((b) => b.data.name));
	let n = 0;
	for (const [name, rec] of Object.entries(obj.bones || {})) {
		if (!known.has(name)) continue;
		// Bentuk lama: nilai angka = rotasi saja. Bentuk baru: objek.
		const e = typeof rec === "number" ? { rotation: rec } : rec || {};
		const clean = {};
		for (const k of ["rotation", "x", "y", "scaleX", "scaleY"]) {
			if (e[k] != null && Number.isFinite(Number(e[k]))) clean[k] = Number(e[k]);
		}
		if (!Object.keys(clean).length) continue;
		BONES.edits.set(name, clean);
		n++;
	}
	applyBoneEdits();
	spine.skeleton.updateWorldTransform();
	drawBones();
	updateBoneUI();
	toast(`Pose dimuat: ${n} tulang.`);
}

/* --- Ekspor skeleton JSON ---------------------------------------------
 * Menulis ulang berkas skeleton JSON asli dengan rotasi/posisi/skala hasil
 * editan, lalu mengunduhnya. Hanya berlaku untuk model yang skeleton-nya
 * JSON; model .skel (binary) tidak bisa ditulis balik tanpa encoder binary,
 * jadi tombolnya dinonaktifkan dengan penjelasan.
 *
 * Yang diubah HANYA blok "bones" pada setup pose. Animasi, slot, ikatan mesh,
 * dan skin dibiarkan apa adanya — file hasilnya tetap bisa dibuka Spine.
 */
let skeletonJsonCache = null; // { id, data }

async function loadSkeletonJson(model) {
	if (skeletonJsonCache && skeletonJsonCache.id === model.id) return skeletonJsonCache.data;
	const dirPath = String(model.id || "").split("#")[0];
	const base = "/assets/" + dirPath.split("/").map(encodeURIComponent).join("/") + "/";
	const name = model.skeletonFile;
	if (!name || !/\.json$/i.test(name)) return null;
	const res = await fetch(base + encodeURIComponent(name));
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	const data = await res.json();
	skeletonJsonCache = { id: model.id, data };
	return data;
}

/** Apakah model ini bisa diekspor sebagai skeleton JSON? */
function canExportSkeleton() {
	const n = current?.skeletonFile || "";
	return /\.json$/i.test(n);
}

async function exportSkeleton() {
	if (!spine?.skeleton || !current) return;
	if (!canExportSkeleton()) {
		toast("Skeleton model ini .skel (binary) — tidak bisa ditulis balik. Pakai Ekspor pose.");
		return;
	}
	let data;
	try {
		data = await loadSkeletonJson(current);
	} catch (e) {
		toast(`Gagal membaca skeleton: ${e.message || e}`);
		return;
	}
	if (!data || !Array.isArray(data.bones)) {
		toast("Struktur skeleton tidak dikenal.");
		return;
	}
	// Nilai setup pose diambil dari DATA bone (bukan state runtime, yang
	// sedang memutar animasi). Edit diterapkan di atasnya.
	let changed = 0;
	for (const bd of data.bones) {
		const e = BONES.edits.get(bd.name);
		if (!e) continue;
		const rec = typeof e === "number" ? { rotation: e } : e;
		let touched = false;
		for (const k of ["rotation", "x", "y", "scaleX", "scaleY"]) {
			if (rec[k] == null) continue;
			bd[k] = +Number(rec[k]).toFixed(4);
			touched = true;
		}
		if (touched) changed++;
	}
	// Vertex mesh: tulis balik daftar titiknya.
	let vtxChanged = 0;
	for (const item of vtxExportData()) {
		for (const skin of data.skins || []) {
			const atts = skin.attachments?.[item.slot];
			const rec = atts?.[item.attachment];
			if (!rec) continue;
			rec.vertices = item.vertices;
			vtxChanged++;
			break;
		}
	}

	// Attachment (region/mesh): tulis balik kotaknya. Struktur JSON Spine
	// menaruh satu objek per slot per skin di bawah "skins".
	let attChanged = 0;
	const edits = Object.values(BOUNDS.edits || {});
	if (edits.length && Array.isArray(data.skins)) {
		for (const skin of data.skins) {
			for (const [slotName, atts] of Object.entries(skin.attachments || {})) {
				for (const [attName, rec] of Object.entries(atts)) {
					const e = edits.find((x) => x.slot === slotName && x.attachment === attName);
					if (!e || !rec) continue;
					// Mesh: hanya width/height yang aman ditulis; x/y/rotation
					// tidak dipakai mesh dan akan mengotori file.
					if (e.mesh) {
						if (rec.width != null) rec.width = e.width;
						if (rec.height != null) rec.height = e.height;
					} else {
						if (e.x != null) rec.x = e.x;
						if (e.y != null) rec.y = e.y;
						rec.width = e.width;
						rec.height = e.height;
						if (rec.rotation != null || rec.type === "region") rec.rotation = e.rotation;
					}
					attChanged++;
				}
			}
		}
	}

	if (!changed && !attChanged && !vtxChanged) {
		toast("Belum ada tulang atau bounds yang diubah.");
		return;
	}
	const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	const stem = String(current.id).split("/").pop().replace(/[^\w.-]+/g, "_");
	a.download = `${stem}-edited.json`;
	// Anchor harus menempel di DOM agar kliknya memicu unduhan di semua
	// browser (dan agar bisa diuji otomatis).
	a.style.display = "none";
	document.body.append(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(a.href), 4000);
	toast(`Skeleton diekspor: ${changed} tulang, ${attChanged} attachment, ${vtxChanged} mesh.`);
}

/* --- Pustaka pose -----------------------------------------------------
 * Menyimpan pose bernama di localStorage, dikelompokkan per MODEL supaya
 * pose "duduk" milik satu karakter tidak muncul di karakter lain (nama
 * tulangnya beda dan akan diabaikan saat dimuat).
 */
const POSE_LIB_KEY = "spineStage.poseLib.v1";

function poseLibAll() {
	try {
		return JSON.parse(localStorage.getItem(POSE_LIB_KEY) || "{}");
	} catch {
		return {};
	}
}

function poseLibSave(obj) {
	try {
		localStorage.setItem(POSE_LIB_KEY, JSON.stringify(obj));
	} catch {
		toast("Penyimpanan penuh — pose tidak tersimpan.");
	}
}

/** Daftar pose untuk model yang sedang dibuka. */
function poseLibForCurrent() {
	const lib = poseLibAll();
	return lib[current?.id] || {};
}

function poseLibRefresh() {
	const sel = document.getElementById("pose-lib-select");
	const del = document.getElementById("pose-lib-delete");
	if (!sel) return;
	const list = poseLibForCurrent();
	const names = Object.keys(list).sort();
	sel.innerHTML = "";
	const opt0 = document.createElement("option");
	opt0.value = "";
	opt0.textContent = names.length ? `Pose tersimpan (${names.length})` : "Belum ada pose";
	sel.append(opt0);
	for (const n of names) {
		const o = document.createElement("option");
		o.value = n;
		o.textContent = n;
		sel.append(o);
	}
	sel.disabled = !names.length;
	if (del) del.disabled = true;
}

/** Simpan pose sekarang dengan nama. */
function poseLibStore() {
	if (!spine?.skeleton || !current) return;
	const inp = document.getElementById("pose-lib-name");
	const name = (inp?.value || "").trim();
	if (!name) {
		toast("Beri nama pose dulu.");
		return;
	}
	if (!BONES.edits.size) {
		toast("Belum ada tulang yang diubah.");
		return;
	}
	const lib = poseLibAll();
	lib[current.id] = lib[current.id] || {};
	lib[current.id][name] = snapshotEdits();
	poseLibSave(lib);
	if (inp) inp.value = "";
	poseLibRefresh();
	toast(`Pose "${name}" disimpan.`);
}

/** Muat pose tersimpan berdasarkan nama. */
function poseLibLoad(name) {
	if (!name) return;
	const rec = poseLibForCurrent()[name];
	if (!rec) return;
	pushBoneUndo();
	BONES.edits.clear();
	const known = new Set(spine.skeleton.bones.map((b) => b.data.name));
	let n = 0;
	for (const [bone, e] of Object.entries(rec)) {
		if (!known.has(bone)) continue;
		BONES.edits.set(bone, { ...e });
		n++;
	}
	boneUndoSync();
	pushBoneUndo();
	toast(`Pose "${name}" dimuat: ${n} tulang.`);
}

function poseLibDelete(name) {
	if (!name || !current) return;
	const lib = poseLibAll();
	if (!lib[current.id] || !lib[current.id][name]) return;
	delete lib[current.id][name];
	if (!Object.keys(lib[current.id]).length) delete lib[current.id];
	poseLibSave(lib);
	poseLibRefresh();
	toast(`Pose "${name}" dihapus.`);
}

/* --- Editor vertex mesh -----------------------------------------------
 * Menarik titik mesh langsung. Ini satu-satunya cara mengubah BENTUK kain:
 * kotak attachment hanya memindahkan titik acuan, sedangkan bentuknya
 * ditentukan daftar vertex.
 *
 * Dua bentuk data yang harus dibedakan:
 *   unweighted  vertices = [x0,y0, x1,y1, ...]           -> mudah
 *   weighted    vertices = [b0,n0, w,x,y, w,x,y, ..., b1,n1, ...]
 *               tiap vertex punya beberapa bone + bobot, jadi satu titik
 *               dibuat dari beberapa pasangan (x,y,w) yang harus digeser
 *               bersama-sama supaya bentuknya berubah, bukan tercabik.
 * Struktur weighted dideteksi dari adanya array `bones` pada attachment.
 */
const VTX = {
	on: false,
	slot: null,
	att: null,
	/** Indeks vertex terpilih (bukan indeks mentah pada array). */
	sel: -1,
	dragging: false,
	start: null,
	base: null,
	hit: 10,
	/** Vertex hasil edit, per attachment: { [name]: Float32Array }. */
	edits: new Map(),
};

/** Jumlah vertex logis dari sebuah mesh. */
function vtxCount(att) {
	if (!att) return 0;
	if (att.bones) return att.worldVerticesLength >> 1;
	return (att.vertices?.length || 0) >> 1;
}

/** Posisi lokal semua vertex (mengabaikan bobot: diambil rata-rata). */
function vtxPoints(att) {
	const n = vtxCount(att);
	const v = att.vertices;
	const out = new Array(n);
	if (!att.bones) {
		for (let i = 0; i < n; i++) out[i] = { x: v[i * 2], y: v[i * 2 + 1] };
		return out;
	}
	// Weighted: jumlah pengaruh per vertex ada di array `bones` (pola
	// [count, idx, idx, ...]), sedangkan `vertices` hanya deretan (x,y,w)
	// tanpa pemisah. Salah membaca count dari `vertices` menghasilkan
	// koordinat tak masuk akal (terukur ribuan sampai puluhan ribu).
	let k = 0; // penunjuk vertices
	let bi = 0; // penunjuk bones
	for (let i = 0; i < n; i++) {
		const cnt = att.bones[bi++];
		let sx = 0;
		let sy = 0;
		for (let j = 0; j < cnt; j++) {
			sx += v[k] * v[k + 2];
			sy += v[k + 1] * v[k + 2];
			k += 3;
		}
		bi += cnt;
		out[i] = { x: sx, y: sy };
	}
	return out;
}

/** Geser vertex ke-i sebesar (dx, dy) dalam satuan lokal attachment. */
function vtxMove(att, i, dx, dy) {
	const v = att.vertices;
	if (!att.bones) {
		v[i * 2] += dx;
		v[i * 2 + 1] += dy;
		return;
	}
	// Hitung offset pengaruh vertex ke-i dari array `bones`.
	let bi = 0;
	let infl = 0; // jumlah (x,y,w) sebelum vertex ini
	for (let idx = 0; idx < i; idx++) {
		const c = att.bones[bi++];
		infl += c;
		bi += c;
	}
	const cnt = att.bones[bi];
	let k = infl * 3;
	for (let j = 0; j < cnt; j++) {
		v[k] += dx;
		v[k + 1] += dy;
		k += 3;
	}
}

/** Posisi world semua vertex, untuk menggambar dan hit-test. */
function vtxWorldPoints(att, slot) {
	const n = vtxCount(att);
	if (!n) return null;
	const buf = new Float32Array(n * 2);
	try {
		att.computeWorldVertices(slot, 0, n, buf, 0, 2);
	} catch {
		return null;
	}
	const out = new Array(n);
	for (let i = 0; i < n; i++) out[i] = { x: buf[i * 2], y: buf[i * 2 + 1] };
	return out;
}

function setVtxMode(on) {
	VTX.on = !!on && !!spine?.skeleton;
	if (!VTX.on) {
		VTX.slot = null;
		VTX.att = null;
		VTX.sel = -1;
		VTX.dragging = false;
	}
	el.vtxBtn?.setAttribute("aria-pressed", String(VTX.on));
	if (el.vtxBtn) el.vtxBtn.dataset.on = String(VTX.on);
	el.vtxPanel?.toggleAttribute("hidden", !VTX.on);
	vtxSyncUI();
	drawVtxOverlay();
}

function vtxSyncUI() {
	const nm = document.getElementById("vtx-name");
	const cnt = document.getElementById("vtx-count");
	const sel = document.getElementById("vtx-sel");
	if (nm) nm.textContent = VTX.att ? `${VTX.slot?.data?.name || "?"} / ${VTX.att.name || "?"}` : "klik mesh";
	if (cnt) cnt.textContent = VTX.att ? `${vtxCount(VTX.att)} vertex` : "—";
	if (sel) {
		sel.disabled = VTX.sel < 0;
		if (document.activeElement === sel) return;
		sel.value = VTX.sel < 0 ? "" : String(VTX.sel);
	}
}

/** Pilih mesh dari titik layar; kalau ada vertex dekat kursor, pilih vertex. */
function vtxPick(clientX, clientY) {
	const hit = slotAtClient(clientX, clientY);
	if (!hit) return null;
	const att = hit.attachment;
	if (!/Mesh/i.test(att?.constructor?.name || "")) return null;
	return { slot: hit.slot, att };
}

/** Gambar titik-titik mesh; vertex terpilih lebih besar dan berwarna beda. */
function drawVtxOverlay() {
	const g = vtxGfx;
	if (!g) return;
	g.clear();
	if (!VTX.on || !VTX.att) return;
	const pts = vtxWorldPoints(VTX.att, VTX.slot);
	if (!pts) return;
	const sc = 1 / (state.zoom || 1);
	// Isi dropdown vertex sekali per mesh (bukan tiap frame).
	const selEl = document.getElementById("vtx-sel");
	if (selEl && selEl.dataset.for !== (VTX.att.name || "")) {
		selEl.dataset.for = VTX.att.name || "";
		selEl.innerHTML = "";
		for (let i = 0; i < pts.length; i++) {
			const o = document.createElement("option");
			o.value = String(i);
			o.textContent = `#${i}`;
			selEl.append(o);
		}
		selEl.disabled = false;
	}
	for (let i = 0; i < pts.length; i++) {
		const on = i === VTX.sel;
		g.beginFill(on ? 0xffb02e : 0x7ad1ff, on ? 1 : 0.75);
		g.drawCircle(pts[i].x, pts[i].y, (on ? 6 : 3.4) * sc);
		g.endFill();
	}
}

/** Simpan/ambil salinan vertex asli supaya bisa direset. */
function vtxOriginal(att) {
	const key = att.name || "";
	if (!VTX.orig) VTX.orig = new Map();
	if (!VTX.orig.has(key)) {
		VTX.orig.set(key, Float32Array.from(att.vertices || []));
	}
	return VTX.orig.get(key);
}

function vtxReset() {
	if (!VTX.att) return;
	const orig = VTX.orig?.get(VTX.att.name || "");
	if (!orig) return;
	VTX.att.vertices.set(orig);
	try {
		spine.skeleton.updateWorldTransform();
	} catch {
		/* frame berikutnya */
	}
	drawVtxOverlay();
	toast("Vertex mesh dikembalikan.");
}

/** Kumpulkan edit vertex untuk ekspor skeleton. */
function vtxExportData() {
	const out = [];
	for (const [key, arr] of VTX.edits) {
		const [slotName, attName] = key.split("/");
		out.push({ slot: slotName, attachment: attName, vertices: Array.from(arr) });
	}
	return out;
}

/* --- Editor bounds attachment -----------------------------------------
 * Region/mesh attachment punya kotak (x, y, width, height, rotation) relatif
 * terhadap slot. Mode ini menampilkan kotak itu, bisa digeser dan diubah
 * ukurannya langsung di kanvas, dan hasilnya ikut tertulis di Ekspor
 * skeleton.
 *
 * Batasan yang perlu diketahui: untuk MESH, nilai x/y/width/height tidak
 * menentukan bentuk kain — yang menentukan adalah daftar vertex. Mengubah
 * kotak mesh hanya memindahkan titik acuan; bentuk mesh tetap. Untuk REGION
 * (mayoritas ikon/partikel/prop) kotak inilah yang menentukan tampilan.
 */
const BOUNDS = {
	on: false,
	slot: null,
	att: null,
	dragging: false,
	/** "move" | corner index 0..3 */
	grip: null,
	start: null,
	base: null,
	hit: 12,
};

/** Attachment terpilih beserta kotak lokalnya (koordinat slot). */
function boundsBox(att) {
	if (!att) return null;
	let w = Number(att.width) || 0;
	let h = Number(att.height) || 0;
	// Mesh attachment: width/height hanya metadata kotak asal (sering 32x32).
	// Yang benar-benar menentukan bentuk adalah daftar vertex, jadi untuk
	// mesh kita pakai sebaran vertex sebagai kotak acuan.
	if (!w || !h) {
		const v = att.vertices;
		if (v && v.length >= 2) {
			let minX = Infinity;
			let maxX = -Infinity;
			let minY = Infinity;
			let maxY = -Infinity;
			for (let i = 0; i + 1 < v.length; i += 2) {
				minX = Math.min(minX, v[i]);
				maxX = Math.max(maxX, v[i]);
				minY = Math.min(minY, v[i + 1]);
				maxY = Math.max(maxY, v[i + 1]);
			}
			if (Number.isFinite(minX)) {
				w = Math.max(w, maxX - minX);
				h = Math.max(h, maxY - minY);
			}
		}
	}
	const x = Number(att.x) || 0;
	const y = Number(att.y) || 0;
	const r = ((Number(att.rotation) || 0) * Math.PI) / 180;
	return { x, y, w, h, rot: r };
}

/** Empat sudut kotak di koordinat world. */
function boundsCorners(slot, att) {
	const box = boundsBox(att);
	if (!box) return null;
	const c = Math.cos(box.rot);
	const sn = Math.sin(box.rot);
	const out = [];
	// Sudut kotak relatif terhadap pusat attachment (Spine memakai pusat).
	for (const [sx, sy] of [
		[-1, -1],
		[1, -1],
		[1, 1],
		[-1, 1],
	]) {
		const lx = box.x + (sx * box.w) / 2;
		const ly = box.y + (sy * box.h) / 2;
		const v = { x: c * lx - sn * ly, y: sn * lx + c * ly };
		try {
			slot.bone.localToWorld(v);
		} catch {
			return null;
		}
		out.push(v);
	}
	return out;
}

/** Pilih attachment dari sebuah titik layar. */
function boundsPick(clientX, clientY) {
	const hit = slotAtClient(clientX, clientY);
	if (!hit) return null;
	const att = hit.attachment;
	// Hanya attachment yang punya kotak (region/mesh).
	if (att.width == null && att.height == null) return null;
	return hit;
}

function setBoundsMode(on) {
	BOUNDS.on = !!on && !!spine?.skeleton;
	if (!BOUNDS.on) {
		BOUNDS.slot = null;
		BOUNDS.att = null;
		BOUNDS.dragging = false;
		BOUNDS.grip = null;
	}
	if (boundsGfx) boundsGfx.visible = BOUNDS.on;
	if (vtxGfx) vtxGfx.visible = false;
	// vtxGfx dipakai oleh drawVtxOverlay(); nyalakan saat mode vertex aktif.
	if (vtxGfx && typeof VTX !== "undefined") vtxGfx.visible = VTX.on;
	el.boundsBtn?.setAttribute("aria-pressed", String(BOUNDS.on));
	if (el.boundsBtn) el.boundsBtn.dataset.on = String(BOUNDS.on);
	el.boundsPanel?.toggleAttribute("hidden", !BOUNDS.on);
	boundsSyncUI();
	drawBoundsOverlay();
}

function boundsSyncUI() {
	const name = document.getElementById("bounds-name");
	const x = document.getElementById("bounds-x");
	const y = document.getElementById("bounds-y");
	const w = document.getElementById("bounds-w");
	const h = document.getElementById("bounds-h");
	const rot = document.getElementById("bounds-rot");
	const a = BOUNDS.att;
	if (name) name.textContent = a ? `${BOUNDS.slot?.data?.name || "?"} / ${a.name || "?"}` : "klik model";
	for (const [inp, v] of [
		[x, a?.x],
		[y, a?.y],
		[w, a?.width],
		[h, a?.height],
		[rot, a?.rotation],
	]) {
		if (!inp) continue;
		inp.disabled = !a;
		if (document.activeElement === inp) continue;
		inp.value = v == null ? "" : String(+Number(v).toFixed(2));
	}
}

/** Terapkan nilai kotak ke attachment, catat untuk ekspor. */
function boundsApply(patch) {
	const a = BOUNDS.att;
	if (!a) return;
	for (const [k, v] of Object.entries(patch)) {
		if (k === "width") a.width = v;
		else if (k === "height") a.height = v;
		else a[k] = v;
	}
	const key = `${BOUNDS.slot?.data?.name || ""}/${a.name || ""}`;
	const isMesh = /Mesh/i.test(a.constructor?.name || "");
	BOUNDS.edits[key] = {
		slot: BOUNDS.slot?.data?.name || null,
		attachment: a.name || null,
		mesh: isMesh,
		x: isMesh ? null : +Number(a.x || 0).toFixed(4),
		y: isMesh ? null : +Number(a.y || 0).toFixed(4),
		width: +Number(a.width || 0).toFixed(4),
		height: +Number(a.height || 0).toFixed(4),
		rotation: isMesh ? null : +Number(a.rotation || 0).toFixed(4),
	};
	// Region attachment menyimpan quad hasil hitung; tanpa updateOffset()
	// gambarnya tidak ikut berubah walau lebarnya sudah diubah.
	try {
		if (typeof a.updateOffset === "function") a.updateOffset();
	} catch {
		/* mesh: tidak perlu */
	}
	try {
		spine.skeleton.updateWorldTransform();
	} catch {
		/* biarkan frame berikutnya */
	}
	boundsSyncUI();
	drawBoundsOverlay();
}

BOUNDS.edits = {};

/** Gambar kotak bounds + pegangan sudut. */
function drawBoundsOverlay() {
	const g = boundsGfx;
	if (!g) return;
	g.clear();
	if (!BOUNDS.on || !BOUNDS.att) return;
	const pts = boundsCorners(BOUNDS.slot, BOUNDS.att);
	if (!pts) return;
	const sc = 1 / (state.zoom || 1);
	g.lineStyle(2 * sc, 0x33ff99, 0.95);
	g.moveTo(pts[0].x, pts[0].y);
	for (let i = 1; i < 4; i++) g.lineTo(pts[i].x, pts[i].y);
	g.lineTo(pts[0].x, pts[0].y);
	for (const p of pts) {
		g.beginFill(0xffb02e, 1);
		g.drawCircle(p.x, p.y, 5 * sc);
		g.endFill();
	}
	// Titik tengah = pegangan geser.
	const c = { x: 0, y: 0 };
	for (const p of pts) {
		c.x += p.x / 4;
		c.y += p.y / 4;
	}
	g.beginFill(0x7ad1ff, 1);
	g.drawCircle(c.x, c.y, 4.5 * sc);
	g.endFill();
}

/* --- Cermin kiri-kanan -------------------------------------------------
 * Menyalin pose satu sisi ke sisi lainnya. Konvensi penamaan yang didukung:
 *   arm_L_01  <-> arm_R_01     (Ark Re:Code, banyak rig Unity)
 *   arm.L     <-> arm.R
 *   L_arm     <-> R_arm
 *   _left     <-> _right
 *   Left      <-> Right
 * Rotasi dicerminkan (tanda dibalik), posisi X dibalik, skala X dibalik;
 * itu yang membuat pose benar-benar simetris, bukan sekadar disalin.
 */
const MIRROR_PAIRS = [
	[/(^|[_.\-])L(?=[_.\-]|$)/, "$1R"],
	[/(^|[_.\-])R(?=[_.\-]|$)/, "$1L"],
	[/left/i, "__RIGHT__"],
	[/right/i, "__LEFT__"],
];

/** Nama tulang pasangan cermin, atau null kalau tidak ada. */
function mirrorName(name) {
	const out = new Set();
	// 1) penanda L/R berdiri sendiri
	for (const re of [/(^|[_.\-])L(?=[_.\-]|$)/g, /(^|[_.\-])R(?=[_.\-]|$)/g]) {
		const m = re.exec(name);
		if (m) {
			const beda = m[0].includes("L") || m[0].toLowerCase().endsWith("l") ? "R" : "L";
			const idx = m.index + m[0].length - 1;
			out.add(name.slice(0, idx) + beda + name.slice(idx + 1));
		}
	}
	// 2) kata left/right
	if (/left/i.test(name)) out.add(name.replace(/left/gi, (t) => (t[0] === "L" ? "Right" : "right")));
	if (/right/i.test(name)) out.add(name.replace(/right/gi, (t) => (t[0] === "R" ? "Left" : "left")));
	const known = new Set((spine?.skeleton?.bones || []).map((b) => b.data.name));
	for (const c of out) if (known.has(c)) return c;
	return null;
}

/** Berapa tulang yang punya pasangan cermin pada model ini. */
function mirrorStats() {
	const rows = boneTreeRows();
	let n = 0;
	for (const r of rows) if (mirrorName(r.name)) n++;
	return { pairs: Math.floor(n / 2), total: rows.length };
}

/**
 * Cerminkan pose. Arah "ltr" menyalin L -> R, "rtl" sebaliknya.
 * Hanya tulang yang sudah diubah (punya edit) yang disalin, supaya pose
 * setengah jadi tidak menghapus sisi lain yang belum disentuh.
 */
function mirrorPose(dir) {
	if (!spine?.skeleton) return;
	pushBoneUndo();
	const from = dir === "rtl" ? /(^|[_.\-])R(?=[_.\-]|$)/ : /(^|[_.\-])L(?=[_.\-]|$)/;
	let n = 0;
	for (const [name, raw] of [...BONES.edits]) {
		if (!from.test(name)) continue;
		const twin = mirrorName(name);
		if (!twin) continue;
		const e = typeof raw === "number" ? { rotation: raw } : { ...raw };
		const rec = {};
		if (e.rotation != null) rec.rotation = -e.rotation;
		if (e.x != null) rec.x = -e.x;
		if (e.y != null) rec.y = e.y;
		if (e.scaleX != null) rec.scaleX = -e.scaleX;
		if (e.scaleY != null) rec.scaleY = e.scaleY;
		BONES.edits.set(twin, rec);
		n++;
	}
	boneUndoSync();
	pushBoneUndo();
	toast(n ? `Pose dicerminkan: ${n} tulang.` : "Tidak ada tulang bercermin yang sudah diubah.");
}

/* --- Input angka & mode transform ------------------------------------- */

const BONE_NUM_IDS = {
	rotation: "bone-num-rotation",
	x: "bone-num-x",
	y: "bone-num-y",
	scaleX: "bone-num-scale",
};

/** Tulis nilai tulang terpilih ke kotak angka (tanpa mengganggu fokus). */
function syncBoneNums() {
	const b = BONES.selected;
	for (const [prop, id] of Object.entries(BONE_NUM_IDS)) {
		const inp = document.getElementById(id);
		if (!inp) continue;
		// Jangan timpa kotak yang sedang diketik pengguna.
		if (document.activeElement === inp) continue;
		inp.disabled = !b;
		if (!b) {
			inp.value = "";
			continue;
		}
		const v = prop === "rotation" ? b.rotation : b[prop];
		inp.value = Number.isFinite(v) ? String(+Number(v).toFixed(2)) : "";
	}
}

/** Terapkan nilai dari kotak angka. */
function applyBoneNum(prop, raw) {
	const b = BONES.selected;
	if (!b) return;
	const v = Number(raw);
	if (!Number.isFinite(v)) return;
	pushBoneUndo();
	setBoneValue(b, prop, v);
	boneUndoSync();
	pushBoneUndo();
}

/** Nudge nilai tulang terpilih dengan panah atas/bawah. */
function nudgeBone(prop, delta) {
	const b = BONES.selected;
	if (!b) return;
	const cur = prop === "rotation" ? b.rotation : b[prop];
	if (!Number.isFinite(cur)) return;
	pushBoneUndo();
	setBoneValue(b, prop, cur + delta);
	boneUndoSync();
	pushBoneUndo();
}

/** Ganti mode seret tulang. */
function setBoneMode(mode) {
	BONES.mode = mode === "move" || mode === "scale" ? mode : "rotate";
	for (const el2 of document.querySelectorAll(".bone-mode")) {
		const on = el2.dataset.mode === BONES.mode;
		el2.classList.toggle("is-on", on);
		el2.dataset.on = String(on);
	}
	el.canvasWrap.style.cursor = BONES.mode === "move" ? "move" : BONES.mode === "scale" ? "nwse-resize" : "";
}

/* --- Pohon tulang -----------------------------------------------------
 * Daftar datar dengan indentasi sesuai kedalaman parent. Untuk rig 180+
 * tulang, pohon berjenjang penuh (dengan lipat) lebih merepotkan daripada
 * membantu; pencarian yang bekerja + baris yang bisa diklik sudah cukup.
 */

/** Daftar tulang + kedalaman, dihitung sekali per model. */
let boneTreeCache = null;

function boneTreeRows() {
	if (boneTreeCache) return boneTreeCache;
	if (!spine?.skeleton) return [];
	const rows = [];
	const depth = new Map();
	for (const b of spine.skeleton.bones) {
		const d = b.parent ? (depth.get(b.parent) ?? 0) + 1 : 0;
		depth.set(b, d);
		rows.push({
			bone: b,
			name: b.data.name,
			depth: d,
			edited: () => BONES.edits.has(b.data.name),
		});
	}
	boneTreeCache = rows;
	return rows;
}

function renderBoneTree() {
	const list = document.getElementById("bone-tree");
	const count = document.getElementById("bone-tree-count");
	if (!list) return;
	const q = (document.getElementById("bone-search")?.value || "").trim().toLowerCase();
	const rows = boneTreeRows();
	const shown = q ? rows.filter((r) => r.name.toLowerCase().includes(q)) : rows;
	if (count) count.textContent = `${shown.length}/${rows.length}`;
	list.innerHTML = "";
	// Batasi 400 baris yang dirender; di atas itu pencarian yang dipakai.
	for (const r of shown.slice(0, 400)) {
		const li = document.createElement("li");
		li.className = "bone-tree-item";
		li.dataset.name = r.name;
		li.style.paddingLeft = `${6 + Math.min(r.depth, 12) * 9}px`;
		if (BONES.selected === r.bone) li.classList.add("is-sel");
		const nm = document.createElement("span");
		nm.className = "bone-tree-name";
		nm.textContent = r.name;
		li.append(nm);
		if (BONES.edits.has(r.name)) {
			const dot = document.createElement("span");
			dot.className = "bone-tree-dot";
			dot.title = "sudah diubah";
			li.append(dot);
		}
		li.addEventListener("click", () => {
			BONES.selected = r.bone;
			updateBoneUI();
			drawBones();
			renderBoneTree();
			// Sorot tulangnya di kanvas tanpa mengubah kamera.
			focusBoneIfOffscreen(r.bone);
		});
		list.append(li);
	}
}

/** Kalau tulang terpilih di luar pandangan, geser kamera supaya terlihat. */
function focusBoneIfOffscreen(b) {
	const w = boneWorld(b);
	if (!w) return;
	const wrap = el.canvasWrap;
	if (!wrap) return;
	const sx = w.x * (world.scale.x || 1) + world.position.x;
	const sy = w.y * (world.scale.y || 1) + world.position.y;
	const m = 80;
	if (sx > m && sy > m && sx < wrap.clientWidth - m && sy < wrap.clientHeight - m) return;
	state.panX = wrap.clientWidth / 2 - w.x * state.zoom;
	state.panY = wrap.clientHeight / 2 - w.y * state.zoom;
	applyTransform();
}

/** Pilih tulang dari panel: sorot baris yang sedang terpilih saja. */
function syncBoneTreeSelection() {
	const list = document.getElementById("bone-tree");
	if (!list) return;
	for (const li of list.children) {
		li.classList.toggle("is-sel", BONES.selected && li.dataset.name === BONES.selected.data.name);
	}
}

/** Nyalakan/matikan mode edit bone. */
function setBoneEdit(on) {
	BONES.on = !!on;
	if (on) {
		boneTreeCache = null;
		renderBoneTree();
		if (!BONE_UNDO.stack.length) boneUndoReset();
		poseLibRefresh();
		const info = document.getElementById("bone-mirror-info");
		if (info) {
			const st = mirrorStats();
			info.textContent = st.pairs ? `${st.pairs} pasang` : "tidak ada pasangan L/R";
		}
	}
	if (on) {
		// Editor butuh overlay bones terlihat supaya bisa diklik.
		if (!state.showBones) {
			state.showBones = true;
			bonesGfx.visible = true;
			el.bonesBtn?.setAttribute("aria-pressed", "true");
			if (el.bonesBtn) el.bonesBtn.dataset.on = "true";
		}
	} else {
		BONES.selected = null;
		BONES.hover = null;
		BONES.dragging = false;
		el.canvasWrap.style.cursor = "";
	}
	el.boneEditBtn?.setAttribute("aria-pressed", String(BONES.on));
	if (el.boneEditBtn) el.boneEditBtn.dataset.on = String(BONES.on);
	el.bonePanel?.toggleAttribute("hidden", !BONES.on);
	drawBones();
	updateBoneUI();
}

/** Segarkan panel editor (nama bone terpilih, jumlah yang berubah). */
function updateBoneUI() {
	if (!el.bonePanel) return;
	const sel = BONES.selected;
	const nameEl = el.bonePanel.querySelector("[data-bone-name]");
	if (nameEl) {
		nameEl.textContent = sel ? sel.data.name || `bone_${sel.data.index}` : "—";
	}
	const rotEl = el.bonePanel.querySelector("[data-bone-rot]");
	if (rotEl) rotEl.textContent = sel ? `${sel.rotation.toFixed(1)}°` : "—";
	const cntEl = el.bonePanel.querySelector("[data-bone-count]");
	if (cntEl) cntEl.textContent = String(BONES.edits.size);
	syncBoneTreeSelection();
	syncBoneNums();
}

function drawBones() {
	bonesGfx.clear();
	// Live2D has no bones; guard so a bones-overlay toggle cannot dereference
	// `undefined.bones` while a Cubism model is on the stage.
	if (!spine?.skeleton || !state.showBones) return;
	const s = 1 / state.zoom;
	bonesGfx.lineStyle(2 * s, 0xff8a5c, 0.95);
	for (const b of spine.skeleton.bones) {
		const w = boneWorld(b);
		if (!w) continue;
		// Bone tanpa panjang hanya digambar sebagai titik pangkal.
		const len = w.len > 0.01 ? w.len : 0;
		bonesGfx.moveTo(w.x, w.y);
		if (len) bonesGfx.lineTo(w.x + Math.cos(w.angle) * len, w.y + Math.sin(w.angle) * len);
		bonesGfx.drawCircle(w.x, w.y, 3 * s);
	}
	if (!BONES.on) return;
	// Sorotan: hover tipis, terpilih tebal + titik ujung.
	if (BONES.hover && BONES.hover !== BONES.selected) {
		const w = boneWorld(BONES.hover);
		if (w && w.len > 0.01) {
			bonesGfx.lineStyle(3 * s, 0x7ad1ff, 0.85);
			bonesGfx.moveTo(w.x, w.y);
			bonesGfx.lineTo(w.x + Math.cos(w.angle) * w.len, w.y + Math.sin(w.angle) * w.len);
		}
	}
	if (BONES.selected) {
		const w = boneWorld(BONES.selected);
		if (w) {
			const len = w.len > 0.01 ? w.len : 0;
			const ex = w.x + Math.cos(w.angle) * len;
			const ey = w.y + Math.sin(w.angle) * len;
			bonesGfx.lineStyle(4 * s, 0x33ff99, 1);
			if (len) {
				bonesGfx.moveTo(w.x, w.y);
				bonesGfx.lineTo(ex, ey);
			}
			bonesGfx.beginFill(0x33ff99, 1);
			bonesGfx.drawCircle(ex, ey, 5 * s);
			bonesGfx.endFill();
		}
	}
}

/* ------------------------------------------------------------------ *
 * IK: rantai dua tulang yang ujungnya bisa digeser
 *
 * Cara pakai: nyalakan IK, klik satu tulang (mis. tangan), lalu geser titik
 * ujungnya. Tulang itu dan induknya diputar supaya ujungnya mengikuti kursor.
 *
 * Kenapa CCD dan bukan rumus dua-tulang tertutup: runtime ini TIDAK
 * menyegarkan matriks world saat dipanggil di luar render loop — sudah diuji
 * `skeleton.updateWorldTransform()`, `bone.updateWorldTransform()`,
 * `spine.update(0)`, `spine.updateTransform()`, dan `autoUpdateTransform()`;
 * semuanya menghasilkan 0 px pergeseran walau rotasi lokal diubah 45°.
 * Matriks hanya segar di dalam ticker, SESUDAH `updateWorldTransform()` pada
 * blok edit tulang. Jadi penyelesaian dilakukan satu langkah per frame
 * (Cyclic Coordinate Descent): tiap frame memutar satu tulang ke arah target,
 * frame berikutnya mengukur ulang dari matriks yang sudah segar. Konvergen
 * dalam beberapa frame (~50-100 ms), tidak terasa.
 *
 * Rotasi disimpan di BONES.edits supaya dipasang ulang tiap frame — animasi
 * menulis ulang `bone.rotation`, jadi nilai di bone sendiri akan hilang.
 * ------------------------------------------------------------------ */
const IK = {
	on: false,
	/** Tulang yang ujungnya dipegang (titik pegangan menggantung di ujungnya). */
	tip: null,
	/** Tulang yang diputar, dari pangkal ke ujung: [induk, tip]. */
	chain: [],
	handle: null,
	dragging: false,
	target: null,
	hitRadius: 16,
};

/** Titik ujung (handle) tulang IK dalam koordinat world. */
function ikTipPoint() {
	const b = IK.tip;
	if (!b) return null;
	const v = { x: b.data.length || 0, y: 0 };
	try {
		b.localToWorld(v);
	} catch {
		return null;
	}
	return v;
}

/** Rantai untuk sebuah tulang: tulang itu + induknya (dua tulang). */
function ikSelect(bone) {
	if (!bone) return;
	IK.tip = bone;
	IK.chain = [bone.parent, bone].filter(Boolean);
	IK.handle = ikTipPoint();
	ikSyncUI();
	drawBones();
}

/**
 * Satu langkah CCD: untuk tiap tulang dari ujung ke pangkal, putar supaya
 * ujung rantai menuju target. Rotasi world bertambah sebesar selisih sudut,
 * jadi rotasi lokal cukup ditambah selisih yang sama (gain 1) — asumsi ini
 * berlaku untuk tulang tanpa skala negatif, dan seluruh model diuji tidak
 * memakai skala negatif pada rantai lengan.
 */
function ikStep() {
	if (!IK.dragging || !IK.target) return;
	let tipP = ikTipPoint();
	if (!tipP) return;
	// Deadzone: kalau ujung sudah hampir di target, berhenti. Tanpa ini CCD
	// terus mengoreksi dan rantai bergetar 0 <-> 30 px tiap frame.
	// Deadzone 6 px: animasi tetap berjalan sambil pengguna menyeret, jadi
	// tulang lain terus bergerak dan ujung bergeser sedikit tiap frame.
	// Ambang terlalu kecil membuat IK mengoreksi terus -> bergetar.
	if (Math.hypot(tipP.x - IK.target.x, tipP.y - IK.target.y) < 6) return;
	for (let i = IK.chain.length - 1; i >= 0; i--) {
		const b = IK.chain[i];
		const w = boneWorld(b);
		if (!w) continue;
		const a1 = Math.atan2(tipP.y - w.y, tipP.x - w.x);
		const a2 = Math.atan2(IK.target.y - w.y, IK.target.x - w.x);
		let d = a2 - a1;
		while (d > Math.PI) d -= Math.PI * 2;
		while (d < -Math.PI) d += Math.PI * 2;
		// Batasi langkah + redam: tanpa redaman, langkah besar membuat rantai
		// berayun melewati target dan berhenti di sisa galat ~60 px.
		// Langkah penuh (tanpa redaman). CCD mengoreksi sudut ke arah target
		// secara eksak untuk tulang terakhir, jadi meredamnya justru membuat
		// rantai merayap dan berayun di sekitar target. Dibatasi 0,5 rad
		// hanya untuk mencegah lompatan liar saat target jauh.
		// Tanpa batas: gain sudah ±1 (terukur -0,83..-0,94), jadi satu
		// koreksi penuh langsung menaruh ujung di target. Membatasi langkah
		// membuat rantai merayap puluhan frame sebelum sampai.
		d = Math.max(-Math.PI, Math.min(Math.PI, d));
		// Tanda minus: pada runtime ini rotasi lokal bertambah BERLAWANAN
		// dengan sudut world (terukur: rot -90.2 -> world 84.9, dan rot +40
		// menurunkan sudut world). Menambah positif membuat ujung menjauh
		// dari target, jadi delta world dikurangkan.
		let deg = (b.rotation || 0) - (d * 180) / Math.PI;
		deg = (((deg + 180) % 360) + 360) % 360 - 180;
		b.rotation = deg;
		writeBoneEdit(b.data.name, { rotation: deg });
		// Matriks world belum tersegarkan di dalam frame ini, jadi ujung
		// perkiraan diputar manual mengelilingi pangkal tulang sebesar
		// perubahan world-nya (gain ±1, tanda negatif seperti di atas).
		// Tanpa ini, koreksi tulang berikutnya memakai ujung yang sudah
		// basi dan justru membatalkan koreksi sebelumnya — hasilnya rantai
		// merayap beberapa persen per frame.
		const ca = Math.cos(d);
		const sa = Math.sin(d);
		const vx = tipP.x - w.x;
		const vy = tipP.y - w.y;
		tipP = { x: w.x + vx * ca - vy * sa, y: w.y + vx * sa + vy * ca };
	}
}

/** Gambar pegangan + garis ke target. Dipanggil tiap frame. */
function drawIk() {
	if (!IK.on) return;
	const p = ikTipPoint();
	IK.handle = p;
	if (!p) return;
	const s = 1 / (state.zoom || 1);
	if (IK.dragging && IK.target) {
		bonesGfx.lineStyle(2 * s, 0x7ad1ff, 0.6);
		bonesGfx.moveTo(p.x, p.y);
		bonesGfx.lineTo(IK.target.x, IK.target.y);
	}
	bonesGfx.beginFill(IK.dragging ? 0x33ff99 : 0x7ad1ff, 1);
	bonesGfx.drawCircle(p.x, p.y, 6 * s);
	bonesGfx.endFill();
	bonesGfx.lineStyle(2 * s, 0x0b0e14, 0.9);
	bonesGfx.drawCircle(p.x, p.y, 6 * s);
}

function setIkMode(on) {
	IK.on = !!on && !!spine?.skeleton;
	if (IK.on && !state.showBones) {
		// Sama seperti editor tulang: overlay harus terlihat supaya tulang
		// bisa diklik dan pegangan IK tergambar.
		state.showBones = true;
		bonesGfx.visible = true;
		el.bonesBtn?.setAttribute("aria-pressed", "true");
		if (el.bonesBtn) el.bonesBtn.dataset.on = "true";
	}
	if (!IK.on) {
		if (IK.dragging && IK.wasPlaying) setPlaying(true);
		IK.wasPlaying = false;
		IK.dragging = false;
		IK.target = null;
		IK.tip = null;
		IK.chain = [];
		IK.handle = null;
	}
	el.ikBtn?.setAttribute("aria-pressed", String(IK.on));
	if (el.ikBtn) el.ikBtn.dataset.on = String(IK.on);
	el.ikPanel?.toggleAttribute("hidden", !IK.on);
	ikSyncUI();
	drawBones();
}

function ikSyncUI() {
	const out = document.getElementById("ik-chain");
	if (!out) return;
	if (!IK.tip) {
		out.textContent = "klik tulang";
		return;
	}
	out.textContent = IK.chain.map((b) => b.data.name).join(" → ") || IK.tip.data.name;
}

function ikReset() {
	for (const b of IK.chain) BONES.edits.delete(b.data.name);
	BONES.edits.clear();
	drawBones();
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

	// Mode A/B: seek KEDUA model dari SATU clock.
	//
	// Seek-nya memakai PROPORSI siklus, bukan detik mentah. Durasi A dan B
	// nyaris selalu beda (5,33 s vs 2,5 s pada pengujian), jadi meneruskan
	// detik yang sama membuat B berputar dua kali lebih cepat dari A —
	// perbandingan jadi meaningless. Proporsi membuat keduanya selalu berada
	// di titik siklus yang sama, dan satu clock menjamin mereka tidak pernah
	// melenceng.
	if (AB.on && AB.second?.skeleton) {
		const dA = duration || 1;
		const dB = AB.dur.B || 1;
		const prop = (state.trackTime / dA) % 1;
		poseAt(AB.second, AB.anim.B, prop * dB);
	}

	// Onion skin: tetap dipanggil walau nilainya 0, supaya bayangan yang
	// sudah ada dibuang saat pengguna mematikannya (dulu early-return di
	// dalam plus syarat onion>0 di sini membuat 3 bayangan menempel terus).
	if (AB.on) updateOnionGhosts();

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

	// Mode edit tulang: animasi baru saja menulis ulang SEMUA rotasi bone, jadi
	// pose hasil edit harus dipasang SESUDAH update() — kalau tidak, rotasi
	// yang digeser pengguna langsung kembali ke nilai animasi tiap frame.
	if ((BONES.on || IK.on) && BONES.edits.size) {
		applyBoneEdits();
		spine.skeleton.updateWorldTransform();
		drawBones();
	}
	if (IK.on) {
		ikStep();
		drawIk();
	}

	// Panel B punya renderer sendiri, jadi harus digambar sendiri juga —
	// ticker utama hanya menggambar `app`.
	if (appB && AB.on && AB.second) appB.renderer.render(appB.stage);

	// pixi-spine membuat ulang mesh saat animasi berganti attachment; container
	// per-slot kita biarkan tapi pastikan visibility-nya tetap sesuai pilihan
	// pengguna (murah, dan hanya saat ada yang disembunyikan).
	if (insp.hidden.size) applySlotVisibility();
	// Sorotan slot ikut mesh yang bergerak, jadi harus digambar ulang tiap
	// frame — posisinya bukan nilai tetap.
	if (SLOTHILITE.index >= 0) drawSlotHilite();

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
	// Live2D: the motion manager owns the clock, so read it back instead of the
	// (absent) Spine track. The bar and the "current" readout then advance.
	if (isLive2D(current) && spine) {
		// Backfill the length once the (asynchronously queued) motion is known,
		// otherwise the very first clip shows "—" until a manual switch.
		if (!duration) live2dUpdateDuration();
		const t = live2DMotionTime(spine);
		if (t === null) return;
		// A looping clip keeps counting past its length, so wrap the readout into
		// [0, duration]; without this the bar pins at 100% and "cur" exceeds "dur".
		let tt = Math.max(0, t);
		if (duration > 0 && tt > duration) tt = tt % duration;
		if (!state.scrubbing) state.trackTime = tt;
		el.scrub.value = String(duration ? Math.min(1, tt / duration) * 1000 : 0);
		el.timeCur.textContent = tt.toFixed(2) + "s";
		return;
	}
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
/** Pusatkan dan sesuaikan zoom panel B berdasarkan kanvas modelnya. */
function fitModelB() {
	const inst = AB.second;
	if (!inst) return;
	const pane = document.getElementById("ab-pane-b");
	const w = AB.layout === "split" ? (pane?.clientWidth || el.canvasWrap.clientWidth / 2) : (pane?.clientWidth || el.canvasWrap.clientWidth);
	const h = pane?.clientHeight || el.canvasWrap.clientHeight;
	let bw = 512;
	let bh = 512;
	try {
		const d = inst.skeleton?.data;
		if (d) {
			bw = d.width || d.height || 512;
			bh = d.height || d.width || 512;
		} else if (inst.width) {
			bw = inst.width;
			bh = inst.height || inst.width;
		}
	} catch {
		/* pakai default */
	}
	camB.zoom = Math.min((w * 0.82) / bw, (h * 0.82) / bh);
	camB.panX = 0;
	camB.panY = 0;
}

function fitModel() {
	if (!spine) return;
	const w = el.canvasWrap.clientWidth;
	const h = el.canvasWrap.clientHeight;
	// Saat A/B aktif, tiap panel hanya separuh lebar panggung. Tanpa ini
	// fitModel() menghitung zoom untuk lebar PENUH, lalu applyTransform()
	// mengecilkannya 0,5 lagi — dan karena fitModel() dipanggil berulang
	// (setiap selesai memuat, tiap resize, tiap "Pas"), state.zoom menyusut
	// terus sampai model tinggal setitik.
	const half = !!(AB.on && AB.second && AB.layout === "split");
	const fitW = half ? w * 0.5 : w;
	// Tanda bahwa zoom ini SUDAH dihitung untuk lebar panel. applyTransform()
	// memakainya supaya tidak menskalakan dua kali.
	AB.zoomForHalf = half;
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

		// Pusatkan berdasarkan KOTAK MODEL, bukan titik origin.
		//
		// applyTransform() menaruh world di (w/2, h/2), yaitu titik origin
		// skeleton. Rangka Spine hampir selalu ber-origin di KAKI, jadi
		// seluruh badan memanjang ke ATAS dari garis tengah dan kepalanya
		// terpotong tepi atas panggung — sementara separuh bawah panggung
		// kosong. Terukur pada 1440x900: CZN, Epic Seven, dan Ark Re:Code
		// semuanya terpotong di atas; hanya Live2D yang tidak (anchor-nya
		// memang di tengah).
		//
		// getLocalBounds() memberi kotak isi sebenarnya dalam satuan lokal,
		// jadi zoom dihitung dari situ dan origin digeser sebesar pusat
		// kotak dikali zoom.
		let lb = null;
		try {
			lb = spine.getLocalBounds();
		} catch {
			lb = null;
		}
		if (lb && lb.width > 0 && lb.height > 0 && Number.isFinite(lb.width) && Number.isFinite(lb.height)) {
			state.zoom = Math.min((fitW * 0.82) / lb.width, (h * 0.82) / lb.height);
			state.panX = -(lb.x + lb.width / 2) * state.zoom;
			state.panY = -(lb.y + lb.height / 2) * state.zoom;
		} else {
			// Cadangan: bounds isi tidak terbaca. Pusatkan KOTAK deklarasinya
			// (bukan pojoknya) supaya model tidak terdorong ke satu sudut.
			state.zoom = Math.min((fitW * 0.82) / bw, (h * 0.82) / bh);
			state.panX = -(bw / 2) * state.zoom;
			state.panY = -(bh / 2) * state.zoom;
		}
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
	// true = pusat ARTWORK sudah diketahui, jadi origin container sudah
	// mewakili tengah model dan pan harus 0. false = hanya ukuran deklarasi
	// yang kita punya, jadi kotaknya yang harus dipusatkan.
	let artworkCentred = !!live2dCentre;
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
			artworkCentred = true;
		}
	}
	// Fall back to the declared size when the artwork bounds are unavailable.
	const bw = b?.width || spine.width || 512;
	const bh = b?.height || spine.height || 512;
	state.zoom = Math.min((w * 0.82) / bw, (h * 0.82) / bh);
	if (artworkCentred) {
		state.panX = 0;
		state.panY = 0;
	} else {
		// Cubism memakai pojok kiri-atas sebagai origin, bukan tengah. Model
		// yang bounds-nya gagal diukur (mis. dipanggil sebelum frame pertama
		// dirender) jadi menggantung di kuadran kanan-bawah dan terpotong.
		// Menggeser setengah kotak deklarasi menaruhnya di tengah panggung.
		state.panX = -(bw / 2) * state.zoom;
		state.panY = -(bh / 2) * state.zoom;
	}
	applyTransform();
}

function rendererDensity() {
	// Explicit override from the toolbar; "auto" keeps the old behaviour
	// (devicePixelRatio, capped at 2 so 4K/retina screens don't explode).
	if (state.density !== "auto") {
		const n = Number(state.density);
		if (Number.isFinite(n) && n > 0) return Math.min(4, n);
	}
	return Math.min(window.devicePixelRatio || 1, 2);
}

function resizeRenderer() {
	try {
		app.renderer.resolution = rendererDensity();
	} catch {
		/* renderer may not allow live resolution on some backends */
	}
	// Saat A/B aktif, panel A hanya separuh lebar panggung.
	const w = AB.on && AB.second && AB.layout === "split"
		? el.canvasWrap.clientWidth / 2
		: el.canvasWrap.clientWidth;
	app.renderer.resize(w, el.canvasWrap.clientHeight);
	const pane = document.getElementById("ab-pane-b");
	if (appB && pane) {
		try {
			appB.renderer.resize(Math.max(1, pane.clientWidth), Math.max(1, pane.clientHeight));
		} catch {
			/* belum siap */
		}
	}
}

function applyTransform() {
	const w = el.canvasWrap.clientWidth;
	const h = el.canvasWrap.clientHeight;
	world.position.set(w / 2 + state.panX, h / 2 + state.panY);
	world.scale.set(state.zoom * (state.flip ? -1 : 1), state.zoom);
	// Mode A/B: panggung dibagi dua. Skala diperkecil supaya model tidak
	// meluber ke panel sebelahnya, dan B digeser ke kanan.
	if (AB.on && AB.second) {
		const half = AB.layout === "split";
		// Dua kanvas: tiap panel punya lebar sendiri, jadi A dipusatkan di
		// panel kirinya dan B memakai kamera B (bukan kamera A).
		const aw = half ? w / 2 : w;
		world.position.set(aw / 2 + state.panX, h / 2 + state.panY);
		// Skala A murni dari state — tidak ada faktor 0,5 yang bisa
		// menumpuk, karena applyTransform() dipanggil berulang saat menyeret.
		world.scale.set(state.zoom * (state.flip ? -1 : 1), state.zoom);

		// B: kamera dan ukurannya sendiri.
		if (abSecondRoot) {
			const inst = AB.second;
			const bw = half ? w / 2 : w;
			const paneW = bw;
			const paneH = h;
			abSecondRoot.position.set(paneW / 2 + camB.panX + AB.offset.x, paneH / 2 + camB.panY + AB.offset.y);
			abSecondRoot.scale.set(camB.zoom * (camB.flip ? -1 : 1), camB.zoom);
			// Geseran terasa sama berapa pun zoom panel B.
			void inst;
		}
		// Label di sini, bukan cuma di abSyncUI(): seretan memanggil
		// applyTransform() berkali-kali dan abSyncUI() tidak ikut jalan, jadi
		// angka geserannya akan tetap "0, 0" selama mouse bergerak.
		if (el.abOffset) {
			el.abOffset.textContent = AB.offset.x || AB.offset.y
				? `geser ${Math.round(AB.offset.x)}, ${Math.round(AB.offset.y)}`
				: "";
		}
		// Kunci: A ikut bergerak, jadi yang berubah hanya posisi RELATIF
		// A-B — berguna untuk menyejajarkan tanpa mengubah framing.
		if (AB.lock) {
			world.position.x += AB.offset.x;
			world.position.y += AB.offset.y;
		}
	}
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
	// 3.7 (JSON) is read by the 3.7 package; it has no SkeletonBinary of its
	// own, so BINARY 3.7 models are still routed to 3.8 below (see pickRuntime).
	"3.7": () => markRuntime(runtime37, "3.7"),
	"3.8": () => markRuntime(runtime38, "3.8"),
	"4.0": () => markRuntime(runtime40, "4.0"),
	"4.1": () => markRuntime(runtime41, "4.1"),
	// Genuine Spine 4.2. Stellar Affinity ships 4.2.35; neither 4.1 nor 4.3
	// can read that layout (see the import note above).
	"4.2": () => markRuntime(runtime42, "4.2"),
	// Genuine Spine 4.3 (e.g. 4.3.39-beta — 深蓝终末录).
	"4.3": () => markRuntime(runtime43, "4.3"),
};

// `runtime42` is the namespace we fall back to for version tagging, but the
// PARSERS must be the exact classes the renderer compares against with
// `instanceof` — see the import note. Override them per-key here.
//
// 3.7 mirrors the 4.2 situation: pixi-spine's `Spine` builds its 3.7 skeleton
// from a nested `@pixi-spine/runtime-3.7` copy, so the parser must be that
// exact copy or the renderer's `attachment instanceof RegionAttachment` tests
// fail and nothing is drawn.
const PARSER_OVERRIDES = {
	"3.7": { SkeletonBinary: null, SkeletonJson: runtime37.SkeletonJson },
	"4.2": { SkeletonBinary: SkeletonBinary42, SkeletonJson: SkeletonJson42 },
	"4.3": { SkeletonBinary: SkeletonBinary43, SkeletonJson: SkeletonJson43 },
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
	"3.7": (atlas) => new runtime37.AtlasAttachmentLoader(atlas),
	"3.8": (atlas) => new runtime38.AtlasAttachmentLoader(atlas),
	"4.0": (atlas) => new runtime40.AtlasAttachmentLoader(atlas),
	"4.1": (atlas) => new AtlasAttachmentLoader41(atlas),
	"4.2": (atlas) => new AtlasAttachmentLoader42(atlas),
	"4.3": (atlas) => new AtlasAttachmentLoader43(atlas),
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
	if (key === "4.3") return new Spine43({ skeletonData });
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
	// errors. So 4.2 (and 4.3, same API) gets its pages assigned afterwards,
	// per page.
	if (key === "4.2" || key === "4.3") {
		const TA = key === "4.3" ? TextureAtlas43 : TextureAtlas42;
		const Wrap = key === "4.3" ? SpineTexture43 : SpineTexture42;
		const ta = new TA(atlasText);
		for (const page of ta.pages) {
			const bt = pageCache.get(page.name);
			if (!bt) throw new Error(`Halaman atlas “${page.name}” tidak tersedia.`);
			// The official renderer reads `region.texture.texture` — i.e. the
			// Pixi texture inside the SpineTexture wrapper. A bare BaseTexture
			// leaves every mesh with `texture === undefined`, which draws
			// absolutely nothing and throws no error.
			page.setTexture(Wrap.from(bt));
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
	let wanted = pickRuntime(detected);
	// pickRuntime maps every 3.7-and-older model onto 3.8 because the 3.7
	// package has no SkeletonBinary. That is right for BINARY, but WRONG for
	// JSON: the 3.7 package DOES ship a SkeletonJson, and the 3.8 JSON parser
	// errors on a "3.7.94" header, silently half-parses the file and then dies
	// on mesh attachments ("Cannot read properties of undefined length").
	// Route JSON 3.7 (and the rare 3.3–3.6 exports) to the real 3.7 runtime.
	if (!isBinary && detected && detected.major === 3 && detected.minor <= 7) {
		wanted = "3.7";
	}
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
			//
			// JANGAN jalankan pada runtime 3.7: normalizer mengubah `skins`
			// dari objek ke larik (format 3.8+), padahal parser 3.7 justru
			// mengharapkan bentuk objek lama. Menjalankannya membuat 3.7
			// gagal dengan "Slot not found: <name>".
			if (!isBinary && typeof rawSkeleton === "object" && key !== "3.7") {
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

	// Cari skeleton JSON dan atlas di direktori model.
	// Validasi DULU, tekan stage BELAKANGAN: dulu stage dihancurkan lebih dulu,
	// jadi model .skel-yang-belum-dikonversi menghapus model lama lalu gagal —
	// HUD masih menampilkan nama model yang sudah tidak ada di panggung.
	let json = model.skeletonFile;
	// Sebagian folder menyimpan ekspor JSON 2.x DI SEBELAH .skel biner (pairer
	// server memilih .skel). Renderer legacy 2.1 butuh JSON-nya, jadi pakai
	// sibling itu bila ada sebelum menyerah.
	if (json && !json.toLowerCase().endsWith(".json")) {
		const stem = json.replace(/\.(skel|json)$/i, "");
		const sib = (model.files || []).find((f) => f.toLowerCase() === (stem + ".json").toLowerCase());
		if (sib) json = sib;
	}
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

	// Barulah sekarang model lama dilepas — file yang dibutuhkan sudah pasti ada.
	destroyCurrent();
	teardownSpine21();
	current = model;

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
	// Hitung kegagalan per model: tanpa inisialisasi di sini, `undefined < 5`
	// bernilai false dan frame pertama tidak akan pernah dijadwalkan.
	spine21.errors = 0;
	const frame = () => {
		try {
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
		} catch (err) {
			// Vendor runtime 2.1 bisa melempar pada data tertentu. Tanpa penjaga,
			// satu throw mematikan loop rAF di frame PERTAMA: kanvas kosong, HUD
			// tetap bilang model dimuat, dan tidak ada pesan apa pun (dulu: seluruh
			// model Epic Seven begitu).
			spine21.errors = (spine21.errors || 0) + 1;
			if (spine21.errors === 1) console.error("[spine21] frame gagal:", err);
			if (spine21.errors >= 5) {
				console.error("[spine21] loop dihentikan setelah 5 kegagalan berturut-turut:", err);
				showError("Model 2.1 gagal dirender: " + (err?.message || err));
			}
		} finally {
			// Jadwalkan frame berikutnya DI SINI, bukan di akhir badan: itulah
			// yang membuat loop tetap hidup walau ada kegagalan.
			if (spine21.active && spine21.state && spine21.errors < 5) {
				spine21.rafId = requestAnimationFrame(frame);
			}
		}
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
		expressionFiles: model.expressions || [],
		physicsFile: (model.files || []).find((f) => /\.physics3\.json$/i.test(f)) || null,
	});

	// Drop any previous model before putting this one on the stage. This single
	// call also disposes the previous Cubism model — a Live2D model is `spine`
	// AND `live2dDispose`, and destroying each handle separately is what threw
	// "Cannot read properties of undefined (reading 'destroy')".
	destroyCurrent();
	// Remember the (idempotent) disposer so the NEXT teardown can release
	// this Cubism model even if it is reached without going through load.
	live2dDispose = dispose;
	// New model, so its centring offset must be measured afresh.
	live2dCentre = null;

	// Auto blink / breath / physics from the moment it appears ("living" look).
	live2dLiveApply(live2d);
	if (el.l2dExtra) el.l2dExtra.hidden = false;
	if (el.l2dLiveBtn) el.l2dLiveBtn.dataset.on = String(live2dLiveOn);
	if (el.l2dRandomBtn) el.l2dRandomBtn.dataset.on = String(live2dRandomOn);
	if (el.l2dAutoBtn) el.l2dAutoBtn.dataset.on = String(live2dAutoNext);
	if (el.l2dTouchBtn) el.l2dTouchBtn.dataset.on = String(live2dTouchOn);
	live2dAutoNextAt = performance.now() + 3000;

	spine = live2d;
	stageRoot.addChildAt(live2d, 0);
	bonesGfx.visible = false;
	stageRoot.addChild(bonesGfx);

	current = model;
	atlas = null;
	atlasSaysPMA = false;
	current.atlasPagesFlags = [];

	// Cubism has no Spine tracks; each motion is an independent clip. Group the
	// list into categories so a 30–140 entry dropdown stays usable, and start on
	// an idle clip (the natural resting motion) rather than whatever sorts first.
	const anims = model.animations && model.animations.length ? model.animations : ["(diam)"];
	fillLive2DAnimSelect(anims);
	const start = anims.find((n) => /^idle/i.test(n)) || anims[0];
	el.animSelect.value = start;
	animName = start;
	duration = 0;
	el.timeDur.textContent = "0.00s";
	// Start the resting motion so the timeline/scrubber have something to show,
	// then read its length back from the Cubism motion manager.
	playLive2DMotion(spine, start);
	// The motion is queued asynchronously (the manager loads the json), so its
	// length is not known this tick — poll briefly until it is, then set the
	// label. Otherwise the readout stays "—" until the first manual switch.
	live2dUpdateDuration();
	setTimeout(live2dUpdateDuration, 400);
	setTimeout(live2dUpdateDuration, 1500);

	// Cubism has no Spine skins — what the Skin dropdown should offer is the
	// expression set. `(diam)` resets to the neutral expression.
	const exprs = live2DExpressions(live2d, model.expressions);
	const skinList = exprs.length ? ["(diam)", ...exprs] : [];
	fillSelect(el.skinSelect, skinList, skinList[0] || null);
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

/**
 * Play a plain video file (Lost Sword cutscene). The PIXI canvas is hidden by
 * the `is-video` class on the wrap; a native <video> takes over the stage.
 * Skeleton-only controls are disabled — they have nothing to drive here.
 */
async function loadVideoModel(model) {
	const vid = loadVideo({ wrap: el.canvasWrap, url: model.videoFile });
	if (!vid) throw new Error("Tidak bisa menyiapkan pemutar video.");

	// A previous Spine/Live2D model must be released, not orphaned — setting
	// `spine = null` here used to leak it (still on the stage, no handle).
	destroyCurrent();
	current = model;
	atlas = null;
	atlasSaysPMA = false;

	// No skeleton: hide the timeline and disable the model controls. The play
	// button stays live — it toggles this <video>.
	if (el.timeline && !el.timeline.hidden) el.timeline.hidden = true;
	if (el.animSelect) {
		el.animSelect.innerHTML = "";
		el.animSelect.disabled = true;
	}
	if (el.skinSelect) {
		el.skinSelect.innerHTML = "";
		el.skinSelect.disabled = true;
	}
	el.playBtn.disabled = false;
	el.playBtn.dataset.playing = "true";
	const syncPlayBtn = () => {
		const playing = !vid.paused && !vid.ended;
		el.playBtn.dataset.playing = String(playing);
		el.playBtn.setAttribute("aria-label", playing ? "Jeda" : "Mainkan");
		el.playBtn.querySelector(".icon").innerHTML = playing ? ICON.pause : ICON.play;
	};
	vid.addEventListener("play", syncPlayBtn);
	vid.addEventListener("pause", syncPlayBtn);
	renderVariants(model);
	renderAudio(model);

	vid.addEventListener("error", () => {
		showError(new Error("Gagal memutar video (kode " + (vid.error?.code ?? "?") + ")."));
	});
	// A clip that plays clears any stale error (e.g. from a previous format
	// the browser could not decode).
	vid.addEventListener("canplay", () => showError(null));
	vid.addEventListener("playing", () => showError(null));

	const dur = () => (Number.isFinite(vid.duration) ? vid.duration : 0);
	el.timeDur.textContent = dur().toFixed(2) + "s";
	vid.addEventListener("loadedmetadata", () => {
		el.timeDur.textContent = dur().toFixed(2) + "s";
	});
	vid.addEventListener("timeupdate", () => {
		const d = dur();
		el.timeCur.textContent = vid.currentTime.toFixed(2) + "s";
		el.scrub.value = String(d ? (vid.currentTime / d) * 1000 : 0);
	});

	el.empty.hidden = true;
	setActive(model.id);
	renderHud();
	if (fps.on) fpsResetStats();
	el.loading.hidden = true;
}

/**
 * CG / illust stills. No skeleton: mount the PNG on the stage, hide the
 * timeline and disable the skeleton dropdowns. The play button is disabled
 * too — there is nothing to animate.
 */
async function loadImageModel(model) {
	await loadImage({ wrap: el.canvasWrap, url: model.imageFile });

	// Release the previous Spine/Live2D model instead of orphaning it.
	destroyCurrent();
	current = model;
	atlas = null;
	atlasSaysPMA = false;

	if (el.timeline && !el.timeline.hidden) el.timeline.hidden = true;
	if (el.animSelect) {
		el.animSelect.innerHTML = "";
		el.animSelect.disabled = true;
	}
	if (el.skinSelect) {
		el.skinSelect.innerHTML = "";
		el.skinSelect.disabled = true;
	}
	el.playBtn.disabled = true;
	if (el.timeCur) el.timeCur.textContent = "0.00s";
	if (el.timeDur) el.timeDur.textContent = "CG";
	if (el.scrub) el.scrub.value = "0";
	renderVariants(model);
	renderAudio(model);
	el.empty.hidden = true;
	setActive(model.id);
	renderHud();
	if (fps.on) fpsResetStats();
	el.loading.hidden = true;
}

/* Pemuatan dimasukkan antrean, bukan ditumpuk.
 *
 * Dulu dua klik cepat memicu dua `loadModel` yang berjalan bersamaan, dan
 * modelnya saling menimpa — yang PALING LAMBAT selesai justru yang menang,
 * jadi klik terakhir yang diabaikan (terukur: klik nikke/777 lalu
 * nikke/absolute, enam detik kemudian yang tampil tetap nikke/777). Selain
 * itu `finally` dari pemuatan pertama mematikan indikator "Memuat..." milik
 * pemuatan kedua yang masih berjalan.
 *
 * Dengan antrean: satu pemuatan pada satu waktu, dan klik terakhir selalu
 * jadi yang terakhir dijalankan.
 */
let loadBusy = false;
let pendingModel = null;

/* Objek model yang sudah dilengkapi detail penuhnya. WeakSet sengaja
 * dipakai, BUKAN Set berisi id: dua objek berbeda bisa punya id yang sama
 * (mis. objek sintetis yang dikirim ke abStart dari permalink), dan objek
 * baru otomatis dianggap belum lengkap tanpa perlu di-clear di refresh(). */
const detailedModels = new WeakSet();

/**
 * Lengkapi satu entri indeks ringan dengan field yang hanya dipakai saat
 * model dibuka (skeleton/atlas, daftar animasi, skin, ukuran, …).
 *
 * Hasilnya digabungkan ke OBJEK YANG SAMA, bukan diganti: `switchVariant()`,
 * A/B, dan permalink semuanya mencari model dengan `models.find(m => m.id)`,
 * jadi mengganti referensinya akan membuat mereka memegang entri lama yang
 * masih ringan. Id boleh memuat '#', makanya dipakai encodeURIComponent.
 */
async function ensureModelDetail(model) {
	if (!model || detailedModels.has(model)) return model;
	const res = await fetch("/api/models/" + encodeURIComponent(model.id));
	if (!res.ok) throw new Error(`Detail model tidak tersedia (HTTP ${res.status})`);
	const data = await res.json();
	if (!data.model) throw new Error("Detail model kosong");
	Object.assign(model, data.model);
	detailedModels.add(model);
	return model;
}

async function loadModel(model) {
	if (loadBusy) {
		pendingModel = model;
		return;
	}
	loadBusy = true;
	try {
		await ensureModelDetail(model);
		await loadModelBody(model);
	} catch (err) {
		// loadModelBody menangani errornya sendiri; ini untuk kegagalan
		// mengambil detail, yang terjadi sebelum overlay loading muncul.
		showError(`Gagal memuat “${model?.name || model?.id}”: ${err?.message || err}`);
	} finally {
		loadBusy = false;
		if (pendingModel) {
			const next = pendingModel;
			pendingModel = null;
			loadModel(next);
		}
	}
}

/**
 * Muat seluruh halaman atlas ke dalam cache BaseTexture.
 *
 * Dulu blok ini hanya hidup di dalam loadModelBody, jalur pembanding di
 * panggung harus menulisnya ulang (atau memakai halaman stub yang tidak bisa
 * digambar). Dipecah keluar supaya keduanya memakai jalur yang SAMA — termasuk
 * semua pengamannya: deteksi halaman resolusi setengah (koordinat atlas penuh
 * tapi file lebih kecil -> "frame does not fit"), uji overflow region per
 * halaman, dan aturan aspect-ratio yang mencegah file salah jadi serpihan.
 *
 * @param {string} atlasText  isi berkas .atlas
 * @param {string} atlasBase  URL dasar halaman (berakhir "/")
 * @returns {Promise<Map<string, BaseTexture>>} per nama halaman
 */
async function loadAtlasPageCache(atlasText, atlasBase) {
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
	return pageCache;
}


/**
 * Ambil + parse satu model menjadi skeletonData, untuk panggung ATAU B.
 *
 * Ini jalur yang sama persis dengan yang menggerakkan panggung utama:
 * mengendus isi file (JSON yang dikirim sebagai .skel membuat parser biner
 * mati dengan "Offset outside bounds of DataView"), memuat semua halaman atlas
 * dengan jaring pengaman resolusinya, lalu melewati dispatcher versi.
 *
 * @param {object} model  entri model dari /api/models
 * @returns {Promise<{data, runtime, version, atlas}>}
 */
async function loadSkeletonDataFor(model) {
	const dirPath = String(model.id || "").split("#")[0];
	const base = "/assets/" + dirPath.split("/").map(encodeURIComponent).join("/") + "/";
	const skelUrl = `${base}/${encodeURIComponent(model.skeletonFile)}`;
	const atlasUrl = `${base}/${encodeURIComponent(model.atlasFile)}`;

	const [atlasText, skelBuf] = await Promise.all([
		fetch(atlasUrl).then((r) => {
			if (!r.ok) throw new Error(`HTTP ${r.status} untuk ${model.atlasFile}`);
			return r.text();
		}),
		fetch(skelUrl).then((r) => {
			if (!r.ok) throw new Error(`HTTP ${r.status} untuk ${model.skeletonFile}`);
			return r.arrayBuffer();
		}),
	]);
	const skelHead = new Uint8Array(skelBuf, 0, Math.min(4, skelBuf.byteLength));
	const isBinary = skeletonIsBinary(skelHead);
	const rawSkeleton = isBinary ? skelBuf : JSON.parse(new TextDecoder().decode(skelBuf));

	if (typeof atlasText !== "string" || !atlasText.trim()) {
		throw new Error(`Berkas atlas “${model.atlasFile}” kosong atau tidak bisa dibaca.`);
	}

	// Resolve texture pages relative to the atlas URL.
	const atlasBase = atlasUrl.slice(0, atlasUrl.lastIndexOf("/") + 1);

	const pageCache = await loadAtlasPageCache(atlasText, atlasBase);

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
	return parsed;
}


/* --- Model 3D (glTF/GLB) ---------------------------------------------------
 * Runtime-nya three.js, dibangun terpisah di public/dist/model3d.js dan
 * dimuat lewat <script> SEKALI saat model 3D pertama dibuka. Dengan begitu
 * bundle viewer.js (4,1 MB) tidak ikut membawa three.js dan 43 ribu model
 * 2D tidak terpengaruh. Lihat src/model3d-stage.js.
 */
const is3D = (m) => !!m && m.format === "model3d";
let model3dScriptPromise = null;

function ensure3DScript() {
	if (window.Model3DStage) return Promise.resolve(window.Model3DStage);
	if (!model3dScriptPromise) {
		model3dScriptPromise = new Promise((resolve, reject) => {
			const s = document.createElement("script");
			s.src = "/dist/model3d.js";
			s.async = true;
			s.onload = () => window.Model3DStage
				? resolve(window.Model3DStage)
				: reject(new Error("Runtime 3D gagal diinisialisasi"));
			s.onerror = () => {
				model3dScriptPromise = null;
				reject(new Error("Gagal memuat runtime 3D (/dist/model3d.js)"));
			};
			document.head.appendChild(s);
		});
	}
	return model3dScriptPromise;
}

function dispose3D() {
	// Jika 3D sedang dijeda, jangan biarkan model 2D berikutnya ikut ter-jeda:
	// state.playing itu global, sedangkan dispose3D dipanggil tiap ganti model.
	const wasPaused3D = !!window.model3dStage && !state.playing;
	try { window.Model3DStage?.dispose(); } catch { /* already gone */ }
	window.model3dStage = null;
	el.canvasWrap?.classList.remove("is-3d");
	if (wasPaused3D) setPlaying(true);
}

/** Render satu model .glb + clip animasinya. Mirip loadImageModel(), tapi
 *  dropdown animasi tetap hidup karena clip-nya nyata (bukan stub). */
async function load3DModel(model) {
	const Stage = await ensure3DScript();
	const base = "/assets/" + String(model.id).split("#")[0]
		.split("/").map(encodeURIComponent).join("/");
	const anims = {};
	for (const a of model.animationFiles || []) {
		if (a && a.name && a.file) anims[a.name] = `${base}/anims/${encodeURIComponent(a.file)}`;
	}
	const info = await Stage.mount({
		wrap: el.canvasWrap,
		modelUrl: `${base}/${encodeURIComponent(model.modelFile || "model.glb")}`,
		anims,
		id: model.id,
	});

	destroyCurrent();
	current = model;
	atlas = null;
	atlasSaysPMA = false;

	if (el.timeline && !el.timeline.hidden) el.timeline.hidden = true;
	// mount() sudah memutar clip idle otomatis — UI harus mengikuti, jangan
	// memaksa kembali ke "Bind pose" (itulah yang bikin model terlihat diam).
	const activeAnim = info.current && info.animations.includes(info.current)
		? info.current : "Bind pose";
	if (el.animSelect) {
		el.animSelect.innerHTML = "";
		for (const name of info.animations) {
			const o = document.createElement("option");
			o.value = name;
			o.textContent = name;
			el.animSelect.appendChild(o);
		}
		el.animSelect.disabled = info.animations.length <= 1;
		el.animSelect.value = activeAnim;
	}
	if (el.skinSelect) {
		el.skinSelect.innerHTML = "";
		el.skinSelect.disabled = true;
	}
	// Tombol Play kini aktif untuk 3D: jeda/lanjut AnimationMixer.
	if (el.playBtn) {
		el.playBtn.disabled = false;
		setPlaying(true);
	}
	if (el.scrub) el.scrub.disabled = true;
	if (el.timeDur) el.timeDur.textContent = "3D";
	if (el.timeCur) el.timeCur.textContent = "0.00s";
	window.model3dStage = {
		id: model.id, animations: info.animations,
		current: activeAnim, ready: true,
		meshes: info.meshes, triangles: info.triangles,
	};
	renderVariants(model);
	renderAudio(model);
	el.empty.hidden = true;
	setActive(model.id);
	renderHud();
	if (fps.on) fpsResetStats();
	el.loading.hidden = true;
	return info;
}

async function loadModelBody(model) {
	showError(null);
	// A previous video left the play button (and selects) disabled; a skeleton
	// model needs them live again.
	el.playBtn.disabled = false;
	if (el.skinSelect) el.skinSelect.disabled = false;
	if (el.animSelect) el.animSelect.disabled = false;
	// Model dibuka berarti sudah dilihat — hapus badge NEW-nya (dan simpan).
	// Muat daftar id karakter ber-kartu sekali, lalu segarkan tombol.
	ensureCznCharIds();
	syncCardsButton(model);
	// Model baru: riwayat undo, cache pohon tulang, dan cache skeleton JSON
	// milik model sebelumnya tidak berlaku lagi.
	BONE_UNDO.stack.length = 0;
	BONE_UNDO.index = -1;
	pushBoneUndo();
	boneTreeCache = null;
	skeletonJsonCache = null;
	BOUNDS.edits = {};
	VTX.edits.clear();
	VTX.orig = new Map();
	VTX.slot = null;
	VTX.att = null;
	VTX.sel = -1;
	BOUNDS.slot = null;
	BOUNDS.att = null;
	if (BONES.on) renderBoneTree();
	markSeen(model.id);
	el.loading.hidden = false;
	el.loading.textContent = "Memuat " + model.name + "…";
	// Live2D-only controls; each loader turns them back on as needed.
	if (el.l2dExtra) el.l2dExtra.hidden = true;
	// Mode A/B tidak bisa bertahan lintas model: B adalah instance yang
	// terikat pada model A saat ini.
	if (AB.on || AB.second) abTeardown();

	try {
		// Any previous Spine 2.x model left an iframe over the stage; clear it
		// before deciding how to render this one. Also drop a previous video.
		teardownLegacyViewer();
		disposeVideo();
		disposeImage();
		dispose3D();

		// Lost Sword cutscene movies are plain .mp4/.m4v files — no skeleton.
		if (model.format === "video") {
			return await loadVideoModel(model);
		}

		// CG / illust stills (deep-blue "-cg" galleries) are plain PNGs — no
		// skeleton and no atlas either.
		if (model.format === "image") {
			return await loadImageModel(model);
		}

		// Model 3D glTF/GLB: runtime three.js terpisah, bukan pixi-spine.
		if (is3D(model)) {
			return await load3DModel(model);
		}

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
		// Skeleton may be JSON or binary regardless of the file extension
		// (Muv-Luv ships JSON inside ".skel"; Azur Lane ships binary ".skel").
		// Sniff the first byte — '{\" (0x7b) or a UTF-8 BOM — instead of
		// trusting the extension, or a JSON-in-.skel model is fed to the
		// binary parser and dies with "Offset outside bounds of DataView".
		const parsed = await loadSkeletonDataFor(model);
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

		// Dispose the previous model (Spine OR Cubism) through the single-shot
		// path, then mount the new one.
		destroyCurrent();
		spine = next;
		stageRoot.addChildAt(spine, 0);
		bonesGfx.visible = state.showBones;
		stageRoot.addChild(bonesGfx); // keep overlay on top

		// A Spine model must not inherit a Cubism centring offset.
		live2dCentre = null;

		current = model;

		// Apply any saved PMA override for THIS model before reading the atlas flag.
		syncPmaToModel(model.id);

		// Remember the game's own default, then read the atlas's `pma:` flags.
		// Both feed "Auto": an explicit atlas flag wins, otherwise we fall back
		// to what this game's assets are known to ship with.
		gameDefaultMode = normalizePmaMode(model.pmaDefault);
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
		insp.hidden.clear(); // model baru = tanpa slot tersembunyi
		insp.prevVisible.clear();
		// Indeks slot hanya bermakna untuk model sebelumnya — sorotan dan
		// fokus harus ikut direset, kalau tidak baris slot nomor sama di
		// model baru akan tersorot tanpa alasan.
		insp.focus = -1;
		hiliteSlot(-1);
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

		// Nyalakan mesin interaksi kalau model ini punya data aksi.
		// Sengaja tidak di-await: katalog 0,36 MB dan kegagalannya tidak
		// boleh menggagalkan pemuatan model.
		cciAttach(model).catch(() => {});
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

/**
 * Live2D motion dropdown with <optgroup> categories. A model can ship 100+
 * motions; grouping keeps the list navigable without changing how the value is
 * read elsewhere (option.value stays the bare motion name).
 */
function fillLive2DAnimSelect(names) {
	const sel = el.animSelect;
	if (!sel) return;
	sel.innerHTML = "";
	const list = (names || []).filter(Boolean);
	if (!list.length) {
		sel.innerHTML = '<option value="">—</option>';
		sel.disabled = true;
		return;
	}
	sel.disabled = false;
	const groups = live2DMotionGroups(spine, list);
	// Degenerate case (no category matched): flat list.
	const source = groups.length ? groups : [{ label: "Gerakan", names: list }];
	for (const g of source) {
		const og = document.createElement("optgroup");
		og.label = g.label;
		for (const n of g.names) {
			const o = document.createElement("option");
			o.value = n;
			o.textContent = n;
			og.appendChild(o);
		}
		sel.appendChild(og);
	}
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
 * Character and skin of a BD2 model.
 *
 * The asset tree is mirrored from `/spine/character/<Karakter>/<Nama Skin>`,
 * so on disk it is `assets/bd2-char/<Karakter>/<Nama Skin>[/<Jenis>]`. The id
 * may carry a `#<stem>` suffix for several skeletons sharing one folder, so
 * strip that before splitting.
 */
function bd2CharSkin(id) {
	const parts = String(id || "").split("#")[0].split("/");
	return { character: parts[1] || "", skin: parts[2] || "" };
}

const VARIANT_MAIN = "Utama";

let variantPopupOpen = false;
/** Klik chip "N varian" di kartu: buka picker begitu model selesai dimuat. */
let pendingVariantOpen = false;

function setVariantPopup(open) {
	if (!el.variantPopup) return;
	variantPopupOpen = !!open && !el.variantBtn?.hidden;
	el.variantPopup.hidden = !variantPopupOpen;
	el.variantBtn?.setAttribute("aria-expanded", String(variantPopupOpen));
	if (!variantPopupOpen) hideVariantPreview();
}

/** Collation for names that mix ASCII, digits and CJK asset folder names. */
const variantCollator = new Intl.Collator("id", { sensitivity: "base", numeric: true });

/**
 * Sort order for the popup: character name first, then skin, then "Utama"
 * before the sibling variants of that skin (Skill Cutscene, Interaction, …).
 */
function compareVariants(a, b) {
	const byChar = variantCollator.compare(a.character, b.character);
	if (byChar) return byChar;
	const bySkin = variantCollator.compare(a.skin, b.skin);
	if (bySkin) return bySkin;
	if (a.label === VARIANT_MAIN) return -1;
	if (b.label === VARIANT_MAIN) return 1;
	return variantCollator.compare(a.label, b.label);
}

/**
 * Fills the shared right-edge variant picker with this model's siblings.
 *
 * Every game with a family uses this popup now; the inline <select> is kept
 * populated but hidden, because the permalink reader, the change handler and
 * the keyboard path all resolve the chosen variant through it.
 *
 * BD2 sorts by character › skin (its folder path carries that context);
 * other games keep the order the server put in family.members, which is
 * already meaningful (Lobby / Combat / Skill 1..5, Utama / Skin / …).
 *
 * Each row shows the model's thumbnail plus a small badge for non-Spine
 * formats or rigs with many animations — no extra API call, both come from
 * the lean library payload and /api/thumbnails already loaded at boot.
 */
/**
 * Group header untuk daftar popup yang panjang (>3 varian). CZN bisa punya
 * 7 saudara; tanpa pengelompokan semuanya jadi deretan teks yang sama bentuknya.
 * BD2 sengaja tidak digrup supaya urutan karakter › skin-nya tidak berubah.
 */
const VARIANT_GROUPS = ["Model", "Aksi", "Potret", "Latar", "Varian"];
function variantGroup(m) {
	const s = String(m.label || "");
	if (/^(Utama|Lobby|Spine|Interaksi|Model)\b/i.test(s)) return "Model";
	if (/^(Combat|Battle|Aim|Cover|Skill|Cutscene|Interaction|Activity|Live Event|Battle Ready)/i.test(s)) return "Aksi";
	if (/^(Portrait|Potret)/i.test(s)) return "Potret";
	if (/^(Wallpaper|Latar)/i.test(s)) return "Latar";
	return "Varian";
}

function variantBadge(full) {
	if (!full) return "";
	if (full.format === "video") return "Video";
	if (full.format === "image") return "Gambar";
	const n = full.animCount || 0;
	return n >= 5 ? `${n} animasi` : "";
}

function hideVariantPreview() {
	if (el.variantPreview) el.variantPreview.hidden = true;
}

/** Preview gambar besar saat kursor/hover berada di baris varian. */
function showVariantPreview(m, full) {
	if (!el.variantPreview) return;
	const src = full ? thumbPathOf(full) : "";
	if (!src) return hideVariantPreview();
	el.variantPreviewImg.src = src;
	el.variantPreviewLabel.textContent = m.label || m.id;
	el.variantPreview.hidden = false;
}

/** Tab segmented untuk model dengan sedikit varian: satu klik, tanpa popup. */
function renderVariantTabs(model, fam) {
	el.variantTabs.innerHTML = "";
	for (const m of fam.members) {
		const b = document.createElement("button");
		b.type = "button";
		b.className = "variant-tab";
		b.dataset.id = m.id;
		b.textContent = m.label || m.id;
		b.title = m.id;
		b.setAttribute("aria-pressed", String(m.id === model.id));
		if (m.id === model.id) b.classList.add("is-active");
		b.addEventListener("click", () => switchVariant(m.id));
		el.variantTabs.append(b);
	}
}

function renderVariantPopup(model, fam) {
	const game = model?.game || "";
	const isBd2 = game === "bd2";
	let members = isBd2
		? fam.members.map((m) => ({ ...m, ...bd2CharSkin(m.id) })).sort(compareVariants)
		: fam.members.slice();
	const grouped = !isBd2 && members.length > 3;
	if (grouped) {
		members.sort((a, b) =>
			VARIANT_GROUPS.indexOf(variantGroup(a)) - VARIANT_GROUPS.indexOf(variantGroup(b)));
	}
	const ctx = isBd2 ? bd2CharSkin(model.id) : { character: model?.name || "", skin: "" };
	el.variantPopTitle.textContent = ctx.skin
		? `${ctx.character} › ${ctx.skin}`
		: ctx.character || "Varian";
	el.variantCount.textContent = String(members.length);
	el.variantBtn.title = `${members.length} varian untuk model ini — klik untuk memilih`;
	el.variantList.innerHTML = "";
	const byId = new Map(models.map((m) => [m.id, m]));
	let lastGroup = null;
	for (const m of members) {
		if (grouped) {
			const g = variantGroup(m);
			if (g !== lastGroup) {
				const head = document.createElement("div");
				head.className = "variant-group-head";
				head.textContent = g;
				el.variantList.append(head);
				lastGroup = g;
			}
		}
		const item = document.createElement("button");
		item.type = "button";
		item.className = "variant-item";
		item.dataset.id = m.id;
		item.setAttribute("role", "option");
		item.title = m.id;
		if (m.id === model.id) {
			item.classList.add("is-active");
			item.setAttribute("aria-selected", "true");
		}

		const full = byId.get(m.id);
		const thumbBox = document.createElement("span");
		thumbBox.className = "variant-item-thumb";
		const src = full ? thumbPathOf(full) : "";
		if (src) {
			const img = document.createElement("img");
			img.src = src;
			img.alt = "";
			img.loading = "lazy";
			thumbBox.append(img);
		} else {
			thumbBox.classList.add("is-empty");
			thumbBox.textContent = String(m.label || m.id).slice(0, 1).toUpperCase();
		}

		const text = document.createElement("span");
		text.className = "variant-item-text";
		const label = document.createElement("span");
		label.className = "variant-item-label";
		label.textContent = m.label || m.id;
		const meta = document.createElement("span");
		meta.className = "variant-item-meta";
		meta.textContent = isBd2
			? [m.character, m.skin].filter(Boolean).join(" › ")
			: m.id;
		text.append(label, meta);

		item.append(thumbBox, text);
		const badge = variantBadge(full);
		if (badge) {
			const chip = document.createElement("span");
			chip.className = "variant-item-badge";
			chip.textContent = badge;
			item.append(chip);
		}
		item.addEventListener("click", () => {
			hideVariantPreview();
			setVariantPopup(false);
			switchVariant(m.id);
		});
		item.addEventListener("mouseenter", () => showVariantPreview(m, full));
		item.addEventListener("mouseleave", hideVariantPreview);
		item.addEventListener("focus", () => showVariantPreview(m, full));
		item.addEventListener("blur", hideVariantPreview);
		el.variantList.append(item);
	}
}

/**
 * Id varian model aktif, dipakai shortcut keyboard.
 */
function currentVariantIds() {
	return current?.family?.members?.map((m) => m.id) || [];
}

function goToVariant(index) {
	const ids = currentVariantIds();
	if (!ids.length) return;
	switchVariant(ids[((index % ids.length) + ids.length) % ids.length]);
}

/**
 * Fills the "Varian" control. <=3 varian: tab segmented inline (satu klik).
 * >3: popup di tepi stage. <select> selalu diisi sebagai state holder
 * (permalink, change handler, keyboard).
 */
function renderVariants(model) {
	const fam = model?.family;
	if (!fam || !fam.members?.length) {
		el.variantWrap.hidden = true;
		el.variantSelect.innerHTML = "";
		el.variantBtn.hidden = true;
		el.variantTabs.hidden = true;
		el.variantTabs.innerHTML = "";
		el.variantList.innerHTML = "";
		setVariantPopup(false);
		pendingVariantOpen = false;
		return;
	}
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
	const useTabs = fam.members.length <= 3;
	el.variantWrap.hidden = true;
	el.variantTabs.hidden = !useTabs;
	el.variantBtn.hidden = useTabs;
	if (useTabs) renderVariantTabs(model, fam);
	else el.variantTabs.innerHTML = "";
	renderVariantPopup(model, fam);
	setVariantPopup(false);
	if (pendingVariantOpen && !useTabs) {
		pendingVariantOpen = false;
		setVariantPopup(true);
	} else {
		pendingVariantOpen = false;
	}
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
	/** Indeks slot yang barisnya sedang disorot dari klik di kanvas. */
	focus: -1,
	// Slot yang disembunyikan (indeks slot) — "isolasi bagian". Indeks, bukan
	// nama, supaya tahan terhadap slot bernama duplikat. Di-reset tiap model.
	hidden: new Set(),
	// Nilai `visible` ASLI container sebelum kita sembunyikan, supaya saat
	// ditampilkan lagi kita pulihkan apa adanya. PENTING: pixi-spine sendiri
	// menyetel sebagian container `visible=false` (slot tanpa mesh), jadi
	// menimpanya dengan `true` akan memunculkan 100+ container kosong.
	prevVisible: new Map(),
};

/**
 * Sembunyikan/tampilkan SATU slot.
 *
 * pixi-spine membuat satu Container per slot di `spine.slotContainers[i]`
 * (slot bermesh menaruh `SpineMesh` di dalamnya). Menyetel `.visible=false`
 * menyembunyikan seluruh isi slot tanpa mengubah data skeleton, jadi urutan
 * gambar, warna, dan animasi tetap utuh.
 *
 * Kita HANYA menyentuh slot yang diminta: nilai asli `visible` disimpan agar
 * slot yang memang sudah tersembunyi oleh pixi-spine (slot kosong) tidak ikut
 * "menyala" saat pengguna menampilkan kembali slot lain.
 */
function setSlotHidden(i, hide) {
	const c = spine && spine.slotContainers ? spine.slotContainers[i] : null;
	if (!c) return;
	if (hide) {
		if (!insp.hidden.has(i)) {
			insp.prevVisible.set(i, c.visible);
			insp.hidden.add(i);
		}
		c.visible = false;
	} else if (insp.hidden.has(i)) {
		c.visible = insp.prevVisible.has(i) ? insp.prevVisible.get(i) : true;
		insp.prevVisible.delete(i);
		insp.hidden.delete(i);
	}
}

/** Tegakkan kembali slot yang tersembunyi (dipanggil tiap frame, murah). */
function applySlotVisibility() {
	if (!spine || !spine.slotContainers) return;
	for (const i of insp.hidden) {
		const c = spine.slotContainers[i];
		if (c) c.visible = false;
	}
}

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
 * The attachment currently shown by a slot.
 * Spine 4.1 (pixi-spine) stores it on the slot itself (`slot.getAttachment()`);
 * the official 4.2/4.3 runtime moved it to `slot.pose` (`slot.pose.getAttachment()`).
 * Try both so PA/slot inspection works across runtimes.
 */
function slotAttachment(slot) {
	if (!slot) return null;
	if (typeof slot.getAttachment === "function") return slot.getAttachment();
	if (slot.pose && typeof slot.pose.getAttachment === "function") return slot.pose.getAttachment();
	return slot.attachment || null;
}

/**
 * Current attachment shown in a slot.
 * `slot.attachment` is null until a skin is applied; the setup pose lives on
 * slot.data.attachmentName, so fall back to that — otherwise every slot reads
 * as empty on models whose skins aren't named "default".
 */
function slotAttachmentName(slot) {
	return slotAttachment(slot)?.name || slot?.data?.attachmentName || "";
}

function renderSlots() {
	if (!el.slotList || !spine?.skeleton) return;
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
		// Dipakai focusSlot() untuk menemukan baris ini saat slot diklik di
		// kanvas; atribut, bukan indeks array, supaya tahan terhadap filter
		// pencarian yang mengubah urutan tampil.
		li.dataset.slotIndex = String(i);
		if (insp.focus === i) li.classList.add("is-focus");
		li.addEventListener("click", (ev) => {
			// Jangan rebut klik dari tombol mata / dropdown attachment.
			if (ev.target.closest(".slot-eye, .slot-pick")) return;
			insp.focus = i;
			for (const r of el.slotList.querySelectorAll(".slot.is-focus")) r.classList.remove("is-focus");
			li.classList.add("is-focus");
			hiliteSlot(i);
		});

		const nm = document.createElement("span");
		nm.className = "slot-name";
		nm.textContent = name;
		nm.title = `slot ${i} · ${name}`;

		const att = document.createElement("span");
		att.className = "slot-att" + (current ? "" : " is-none");
		att.textContent = current || "(kosong)";
		att.title = current || "tidak ada attachment aktif";

		li.append(nm, att);

		// Tombol mata: sembunyikan/tampilkan slot ini (isolasi bagian). Tidak
		// memanggil renderSlots() — itu akan membangun ulang daftar dan
		// menutup dropdown <select> yang mungkin sedang dibuka, padahal
		// visibility-nya cukup diterapkan langsung + ganti kelas barisnya.
		const eye = document.createElement("button");
		eye.type = "button";
		eye.className = "slot-eye";
		const hidden0 = insp.hidden.has(i);
		eye.dataset.off = String(hidden0);
		eye.textContent = hidden0 ? "◌" : "◉";
		eye.title = hidden0 ? "Tampilkan bagian ini" : "Sembunyikan bagian ini";
		eye.setAttribute("aria-pressed", String(hidden0));
		eye.addEventListener("click", (ev) => {
			ev.stopPropagation();
			const off = !insp.hidden.has(i);
			setSlotHidden(i, off);
			eye.dataset.off = String(off);
			eye.textContent = off ? "◌" : "◉";
			eye.title = off ? "Tampilkan bagian ini" : "Sembunyikan bagian ini";
			eye.setAttribute("aria-pressed", String(off));
			li.classList.toggle("is-hidden", off);
			spine.update(0);
		});
		if (hidden0) li.classList.add("is-hidden");
		li.append(eye);

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
	// Live2D models have no `spine.skeleton.data` (their Skin dropdown holds
	// expressions, rendered elsewhere) — guard so opening the inspector on one
	// does not throw "Cannot read properties of undefined (reading 'data')".
	if (!el.slotSkin || !spine?.skeleton?.data) return;
	const names = (spine.skeleton.data.skins || []).map((s) => s.name);
	// Not every game ships a skin called "default" (Lost Sword uses "Daily" /
	// "None"), so offer whatever exists plus a no-skin entry.
	fillSelect(el.slotSkin, ["(tanpa skin)", ...names], "(tanpa skin)");
	el.slotSkin.value = names.includes(insp.skin) ? insp.skin : "(tanpa skin)";
	insp.skin = el.slotSkin.value;
}

/** Fill the compare tab's model pickers with the current library listing. */
/**
 * Isi picker pembanding.
 *
 * Dulu kedua <select> diisi dengan SEMUA model di cakupan. Dibuka dari tampilan
 * akar (tanpa game dipilih) itu berarti 34.698 <option> di masing-masing —
 * 69.396 node dan 903 ms thread utama terblokir hanya untuk membuka sebuah tab.
 * Sekarang: cakupannya dibatasi, dan daftar dibentuk dengan DocumentFragment
 * sekali jalan.
 */
const CMP_LIMIT = 500;

function cmpScope() {
	// Satu game: daftar game itu. Tanpa game terpilih: hanya model yang
	// cocok dengan kotak pencarian (kalau kosong, tampilkan peringatan).
	if (browse.game) {
		const list = models.filter((m) => (m.game || "lainnya") === browse.game);
		return { list, note: "" };
	}
	const q = el.search.value.trim().toLowerCase();
	if (!q) return { list: [], note: "Pilih sebuah game, atau ketik di kotak pencarian dulu." };
	const list = models.filter(
		(m) => m.id.toLowerCase().includes(q) || (m.name || "").toLowerCase().includes(q),
	);
	return { list: list.slice(0, CMP_LIMIT), note: list.length > CMP_LIMIT ? ` (${CMP_LIMIT} pertama)` : "" };
}

function renderCompareOptions() {
	if (!el.cmpA || !el.cmpB) return;
	const { list, note } = cmpScope();
	const prevA = el.cmpA.value;
	const prevB = el.cmpB.value;

	for (const sel of [el.cmpA, el.cmpB]) {
		const frag = document.createDocumentFragment();
		if (!list.length) {
			const o = document.createElement("option");
			o.value = "";
			o.textContent = note || "—";
			frag.append(o);
		} else {
			for (const m of list) {
				const o = document.createElement("option");
				o.value = m.id;
				o.textContent = modelLabel(m) + " · " + m.id;
				frag.append(o);
			}
		}
		sel.replaceChildren(frag);
	}
	el.cmpNote && (el.cmpNote.textContent = note);
	const opts = list.map((m) => m.id);
	el.cmpA.value = opts.includes(prevA) ? prevA : opts[0] || "";
	el.cmpB.value = opts.includes(prevB) ? prevB : opts[Math.min(1, opts.length - 1)] || "";
}

/**
 * Apakah buffer skeleton ini JSON atau biner Spine?
 *
 * Memeriksa byte pertama saja TIDAK cukup: skeleton biner Spine dimulai
 * dengan hash string (panjang + byte acak), dan hash itu bisa kebetulan
 * berawalan 0x7b ('{') — mis. A0374 Ark Re:Code. Model seperti itu lalu
 * salah dianggap JSON dan mati dengan "Expected property name or '}' in
 * JSON at position 1".
 *
 * JSON sungguhan selalu '{' diikuti whitespace, kutip, atau '}'. Biner
 * tidak. Jadi periksa dua byte, bukan satu.
 */
function skeletonIsBinary(bytes) {
	if (!bytes || bytes.length === 0) return false;
	const b0 = bytes[0];
	const b1 = bytes.length > 1 ? bytes[1] : 0;
	if (b0 === 0xef && b1 === 0xbb) return false; // UTF-8 BOM -> teks
	if (b0 !== 0x7b) return true; // bukan '{' -> pasti biner
	return !(b1 === 0x20 || b1 === 0x09 || b1 === 0x0a || b1 === 0x0d || b1 === 0x22 || b1 === 0x7d);
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

	const atlasText = await fetch(atlasUrl).then((r) => {
		if (!r.ok) throw new Error(`HTTP ${r.status} untuk ${model.atlasFile}`);
		return r.text();
	});
	// Pages are stubbed — we only need structure, never pixels.
	const atlas = new TextureAtlas(atlasText, (line, cb) => {
		cb({ width: 2048, height: 2048, valid: true, scaleMode: 1, setSize() {}, dispose() {} });
	});
	const skelBuf = await fetch(skelUrl).then((r) => {
		if (!r.ok) throw new Error(`HTTP ${r.status} untuk ${model.skeletonFile}`);
		return r.arrayBuffer();
	});
	// Sniff content (Muv-Luv ships JSON inside ".skel").
	const head = new Uint8Array(skelBuf, 0, Math.min(4, skelBuf.byteLength));
	const isBinary = skeletonIsBinary(head);
	const raw = isBinary ? skelBuf : JSON.parse(new TextDecoder().decode(skelBuf));

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

/**
 * Bayangan onion skin: pose N frame sebelumnya, digambar lebih redup.
 *
 * Hanya merekam pose (bukan piksel), jadi biayanya satu update skeleton per
 * bayangan. Dipakai untuk melihat timing antar frame tanpa mengedit apa pun.
 */
function updateOnionGhosts() {
	if (!AB.ghostRoot || !spine?.skeleton) return;
	const want = AB.onion;
	// Samakan jumlah bayangan dengan yang diminta.
	while (AB.ghosts.length > want) {
		const g = AB.ghosts.pop();
		try {
			// JANGAN destroy(true): bayangan berbagi atlas dengan model A,
			// dan destroy(true) membuang base texture-nya — model utama lalu
			// ikut rusak ("Cannot read properties of null (reading 'width')").
			// Cukup lepas dari panggung.
			AB.ghostRoot.removeChild(g);
			g.destroy?.({ children: false, texture: false, baseTexture: false });
		} catch {
			/* sudah hilang */
		}
	}
	while (AB.ghosts.length < want) {
		const g = makeSpine(spineRuntime, spine.skeleton.data);
		g.autoUpdate = false;
		try {
			g.alpha = AB.opacity;
		} catch {
			/* bukan DisplayObject yang punya alpha */
		}
		AB.ghostRoot.addChild(g);
		AB.ghosts.push(g);
	}
	if (!want) return;   // daftar sudah dikosongkan di atas

	const fps = Number(el.exportFps?.value) || 30;
	const dur = duration || 1;
	const step = 1 / Math.max(1, fps);
	for (let i = 0; i < AB.ghosts.length; i++) {
		const t = state.trackTime - step * (i + 1);
		const wrapped = ((t % dur) + dur) % dur;
		poseAt(AB.ghosts[i], animName, wrapped);
		try {
			AB.ghosts[i].alpha = AB.opacity * (1 - i / (AB.ghosts.length + 1));
		} catch {
			/* abaikan */
		}
	}
}

/** Samakan tampilan panel A/B dengan keadaan AB. */
function abSyncUI() {
	const on = AB.on;
	if (el.abToggle) el.abToggle.dataset.on = String(on);
	if (el.abBar) el.abBar.hidden = !on;
	if (el.abLayout) el.abLayout.value = AB.layout;
	if (el.abOnion) el.abOnion.value = String(AB.onion);
	if (el.abLock) el.abLock.checked = !!AB.lock;
	// Tampilkan geseran saat ini: tanpa angka, posisi tidak bisa
	// direproduksi dan "reset" terasa seperti menebak.
	if (el.abOffset) {
		el.abOffset.textContent = AB.on && (AB.offset.x || AB.offset.y)
			? `geser ${Math.round(AB.offset.x)}, ${Math.round(AB.offset.y)}`
			: "";
	}
	if (el.abLabel) {
		el.abLabel.textContent = on
			? `A: ${modelLabel(AB.model.A)} · B: ${modelLabel(AB.model.B)}`
			: "";
	}
	// Panel kedua hanya tampil saat A/B aktif.
	const split = document.getElementById("ab-split");
	if (split) {
		split.hidden = !on;
		split.classList.toggle("is-overlay", on && AB.layout === "overlay");
	}
	if (on) {
		ensureAppB();
	} else {
		destroyAppB();
	}
	applyTransform();
}

/** Matikan mode A/B dan buang instance model B. */
function abTeardown() {
	AB.on = false;
	if (AB.ghostRoot) {
		try {
			// children:false + texture:false — bayangan memakai atlas milik
			// model A, jadi menghancurkan teksturnya akan merusak model utama.
			AB.ghostRoot.destroy({ children: false, texture: false, baseTexture: false });
		} catch {
			/* sudah hilang */
		}
	}
	AB.ghostRoot = null;
	AB.ghosts = [];
	AB.offset = { x: 0, y: 0 };
	abDrag = null;
	const s = AB.second;
	const sr = abSecondRoot;
	AB.second = null;
	abSecondRoot = null;
	AB.model = { A: null, B: null };
	if (sr) {
		try {
			// children:false karena `s` dihancurkan sendiri di bawah;
			// texture:false supaya atlas milik A tidak ikut terbuang.
			sr.destroy({ children: false, texture: false, baseTexture: false });
		} catch {
			/* sudah hilang */
		}
	}
	if (s) {
		try {
			app.stage.removeChild(s);
		} catch {
			/* bukan anak */
		}
	} else if (s) {
		try {
			stageRoot.removeChild(s);
		} catch {
			/* bukan anak */
		}
		try {
			s.destroy?.(true);
		} catch {
			/* sudah hilang */
		}
	}
	// Panggung kembali memakai satu viewport penuh — hitung ulang zoom-nya,
	// atau model A tetap berukuran setengah setelah B dibuang.
	fitModel();
	abSyncUI();   // ini juga menutup renderer panel B
	destroyAppB();
}

/**
 * Muat model B dan nyalakan mode A/B.
 *
 * Diantre seperti loadModel: klik cepat pada dua model berurutan dulu
 * memicu dua pemuatan bersamaan, dan yang paling lambat menang.
 */
async function abStart(modelB) {
	if (!spine?.skeleton) {
		toast("Buka model A dulu sebelum membandingkan.");
		return;
	}
	if (AB.busy) {
		AB.pending = modelB;
		return;
	}
	AB.busy = true;
	const seq = ++AB.seq;
	try {
		// Model B bisa berasal dari game lain (permalink / klik-kanan kartu),
		// jadi detailnya belum tentu sudah diambil seperti model A.
		await ensureModelDetail(modelB);
		const parsed = await loadSkeletonDataFor(modelB);
		if (seq !== AB.seq) return;
		if (!parsed?.data?.bones?.length) throw new Error("Data skeleton tidak berisi tulang.");

		// Simpan dulu: abTeardown() menolkan offset, dan kalau A/B dipulihkan
		// dari permalink, offset yang baru saja dibaca akan hilang begitu saja
		// (terukur: setelah reload, geseran kembali ke 0,0 walau URL
		// membawanya).
		const keepOffset = { ...AB.offset };
		const keepLayout = AB.layout;
		const keepOnion = AB.onion;
		const keepLock = AB.lock;
		abTeardown();
		AB.offset = keepOffset;
		AB.layout = keepLayout;
		AB.onion = keepOnion;
		AB.lock = keepLock;
		AB.second = makeSpine(parsed.runtime, parsed.data);
		AB.second.autoUpdate = false;
		// B hidup di container SENDIRI yang dipasang di app.stage — BUKAN di
		// dalam stageRoot. stageRoot adalah anak `world`, jadi kalau B
		// ditaruh di situ, posisinya ikut kena transform world dan offset
		// yang kita atur jadi dobel (model B justru melenceng jauh).
		abSecondRoot = new Container();
		abSecondRoot.addChild(AB.second);
		// Masuk ke renderer panel B kalau ada; kalau tidak, ke panggung utama
		// sebagai jatuh-balik.
		const targetB = ensureAppB();
		if (targetB) targetB.stage.addChild(abSecondRoot);
		else app.stage.addChildAt(abSecondRoot, 0);

		AB.model = { A: current, B: modelB };
		AB.runtime = parsed.runtime;
		AB.on = true;

		// Pilih animasi: pakai yang sama kalau ada di kedua model, supaya
		// perbandingannya adil. Kalau tidak ada yang cocok, pakai milik B.
		const animsB = (parsed.data.animations || []).map((a) => a.name);
		const curA = AB.anim.A || animName;
		const pick = (name) => (animsB.includes(name) ? name : animsB[0] || null);
		AB.anim.A = curA;
		AB.anim.B = pick(curA);
		AB.dur.A = duration || 0;
		AB.dur.B = parsed.data.animations?.find((a) => a.name === AB.anim.B)?.duration || 0;

		AB.ghostRoot = new Container();
		stageRoot.addChild(AB.ghostRoot);

		// Dua panel berarti zoom yang pas berubah: hitung ulang supaya kedua
		// model muat di panel masing-masing.
		fitModel();
		fitModelB();
		abSyncUI();
		toast(`A/B: ${modelLabel(AB.model.A)} ⟷ ${modelLabel(modelB)}`);
	} catch (err) {
		if (seq === AB.seq) {
			console.error("[ab] gagal memuat model B:", err);
			toast("Gagal memuat model B: " + (err?.message || err));
		}
	} finally {
		AB.busy = false;
		if (AB.pending) {
			const next = AB.pending;
			AB.pending = null;
			abStart(next);
		}
	}
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
	// Panel A/B ikut tersinkron saat tabnya dibuka (mis. setelah reload
	// permalink yang menyimpan mode A/B).
	abSyncUI();
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
	} else if (spine?.skeleton) {
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
	// Sembunyikan/tampilkan SEMUA bagian sekaligus. Kalau ada yang masih
	// tampil -> sembunyikan semua; kalau semua sudah sembunyi -> tampilkan.
	el.slotToggleAll?.addEventListener("click", () => {
		if (!spine?.skeleton) return;
		const total = spine.skeleton.slots.length;
		const allHidden = insp.hidden.size >= total;
		if (allHidden) {
			for (const i of [...insp.hidden]) setSlotHidden(i, false);
		} else {
			for (let i = 0; i < total; i++) setSlotHidden(i, true);
		}
		renderSlots();
		spine.update(0);
	});
	el.cmpRun?.addEventListener("click", runCompare);
el.abToggle?.addEventListener("click", () => {
	if (AB.on) {
		abTeardown();
		toast("Mode A/B dimatikan.");
		return;
	}
	const idB = el.cmpB.value;
	const mB = models.find((m) => m.id === idB);
	if (!mB) {
		toast("Pilih model B dulu di dropdown.");
		return;
	}
	abStart(mB);
});
el.abLayout?.addEventListener("change", () => {
	AB.layout = el.abLayout.value === "overlay" ? "overlay" : "split";
	// Posisi yang disimpan untuk tata letak lama tidak masuk akal di tata
	// letak baru (offset setengah layar di split = jauh sekali di overlay).
	AB.offset = { x: 0, y: 0 };
	applyTransform();
});
el.abReset?.addEventListener("click", () => {
	AB.offset = { x: 0, y: 0 };
	applyTransform();
	toast("Posisi B dikembalikan.");
});
el.abLock?.addEventListener("change", () => {
	AB.lock = !!el.abLock.checked;
	applyTransform();
});
// Klik-kanan di panggung dipakai untuk menyeret model B, jadi menu
// konteks browser harus diblokir — tanpa ini seretan berakhir dengan menu
// yang menutupi panggung.
el.canvasWrap?.addEventListener("contextmenu", (e) => {
	if (AB.on && AB.second) e.preventDefault();
});
el.abOnion?.addEventListener("change", () => {
	AB.onion = Number(el.abOnion.value) || 0;
	// Panggil sekarang juga: kalau mode A/B sedang dijeda, ticker tidak
	// berjalan dan bayangan lama akan menempel.
	updateOnionGhosts();
});
}

function setSkin(name) {
	if (!spine?.skeleton) return;
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
	// Lost Sword movies have no `spine` object at all, so they must be handled
	// BEFORE the skeleton guard below (which would otherwise hide the HUD).
	if (current && current.format === "video") {
		const mb = current.bytes ? (current.bytes / 1048576).toFixed(1) : "?";
		el.hud.hidden = false;
		$("#hud-model").textContent = current.name;
		$("#hud-stats").innerHTML =
			`<span><b>${mb}</b> MB</span>` +
			`<span><b>Video</b></span>` +
			(current.family ? `<span><b>${current.family.members.length}</b> varian</span>` : "");
		$("#title-model").textContent = current.name;
	document.title = current.name + " — Spine Stage";
	el.gridLink.hidden = false;
		return;
	}
	// CG / illust stills: report the pixel size the browser actually decoded.
	if (current && current.format === "image") {
		const mb = current.bytes ? (current.bytes / 1048576).toFixed(1) : "?";
		const im = imageStageActive() ? imageElement() : null;
		const dim = im && im.naturalWidth ? `<span><b>${im.naturalWidth}×${im.naturalHeight}</b></span>` : "";
		el.hud.hidden = false;
		$("#hud-model").textContent = current.name;
		$("#hud-stats").innerHTML = `<span><b>${mb}</b> MB</span><span><b>CG</b></span>` + dim;
		$("#title-model").textContent = current.name;
		document.title = current.name + " — Spine Stage";
		el.gridLink.hidden = false;
		return;
	}
	// Model 3D glTF: HUD menampilkan ukuran aset + jumlah mesh/triangle,
	// bukan versi Spine (model ini tidak punya skeleton Spine sama sekali).
	if (is3D(current)) {
		const mb = current.bytes ? (current.bytes / 1048576).toFixed(1) : "?";
		const st = window.Model3DStage?.state?.() || {};
		el.hud.hidden = false;
		$("#hud-model").textContent = current.name;
		$("#hud-stats").innerHTML =
			`<span><b>${mb}</b> MB</span><span><b>3D · glTF</b></span>` +
			`<span><b>${st.meshes || 0}</b> mesh</span>` +
			`<span><b>${(st.triangles || 0).toLocaleString("id-ID")}</b> tris</span>` +
			(current.family ? `<span><b>${current.family.members.length}</b> varian</span>` : "");
		$("#title-model").textContent = current.name;
		document.title = current.name + " — Spine Stage";
		el.gridLink.hidden = false;
		return;
	}
	// Model 2.1 (Epic Seven, Project QT) tidak pernah mengisi `spine` — yang
	// ada `spine21`. Tanpa cabang ini, renderHud (termasuk yang dipanggil dari
	// dropdown PMA, yang berlaku untuk SEMUA model) menyembunyikan HUD yang
	// barusan diisi loadLegacyModel, dan dia tidak pernah muncul lagi walau
	// PMA dikembalikan ke "Otomatis".
	if (spine21.active && spine21.state && current) {
		el.hud.hidden = false;
		$("#hud-model").textContent = current.name;
		$("#hud-stats").innerHTML =
			`<span class="hud-dbg"><b>Spine ${current.spine || "2.1.27"}</b></span>` +
			`<span class="hud-dbg"><b>runtime 2.1</b></span>`;
		$("#title-model").textContent = current.name;
		document.title = current.name + " — Spine Stage";
		if (el.gridLink) el.gridLink.hidden = false;
		return;
	}
	if (!current || !spine) {
		el.hud.hidden = true;
		if (el.gridLink) el.gridLink.hidden = true;
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
			`<span class="hud-dbg"><b>Live2D Cubism 4</b></span>` +
			(current.family ? `<span><b>${current.family.members.length}</b> varian</span>` : "");
		$("#title-model").textContent = current.name;
	document.title = current.name + " — Spine Stage";
	el.gridLink.hidden = false;
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
		`<span class="hud-dbg" data-pma="${resolvedMode() === PMA_MODES.upload ? "upload" : pmaActive() ? "on" : "off"}"><b>PMA ${resolvedMode() === PMA_MODES.upload ? "upload" : pmaActive() ? "aktif" : "nonaktif"}</b></span>` +
		// Show the variant count when there is a family, so it's obvious the
		// model has siblings even before the dropdown is noticed.
		(current.family
			? `<span><b>${current.family.members.length}</b> varian</span>`
			: "") +
		// Show the real Spine version + which runtime parsed it. When these
		// disagree with what the file claims (older models), it's the fastest
		// way to see why a model loaded — or didn't.
		(spineVersion
			? `<span class="hud-dbg"><b>Spine ${spineVersion}</b></span>`
			: current.spine ? `<span class="hud-dbg"><b>${current.spine}</b></span>` : "") +
		(spineRuntime && spineRuntime !== "4.1"
			? `<span class="hud-dbg"><b>runtime ${spineRuntime}</b></span>`
			: "");
	$("#title-model").textContent = current.name;
	document.title = current.name + " — Spine Stage";
	el.gridLink.hidden = false;
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
	if (!parts.on || !spine?.skeleton) {
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

/* ------------------------------------------------------------------ *
 * Slot hover tooltip
 *
 * Menampilkan nama slot (dan nama attachment-nya) di dekat kursor untuk
 * bagian model yang sedang ditunjuk. Berbeda dari mode "Bagian" yang
 * memakai bounding-box: di sini yang diuji adalah MESH yang benar-benar
 * digambar, lewat `spine.slotContainers[i]` — satu Container Pixi per slot,
 * diurutkan sama dengan `skeleton.slots`.
 *
 * Urutan pencarian dibalik (slot terakhir dulu) karena slot yang digambar
 * belakangan menutupi yang lebih awal — yang terlihat pengguna adalah yang
 * paling atas, jadi itulah yang harus dilaporkan.
 * ------------------------------------------------------------------ */
const SLOTTIP = {
	el: null,
	slot: null,
	clientX: 0,
	clientY: 0,
	raf: 0,
};

function slotTooltipEl() {
	if (SLOTTIP.el) return SLOTTIP.el;
	const d = document.createElement("div");
	d.id = "slot-tip";
	d.className = "slot-tip";
	d.setAttribute("role", "status");
	d.setAttribute("aria-live", "polite");
	d.hidden = true;
	document.body.appendChild(d);
	SLOTTIP.el = d;
	return d;
}

/**
 * Slot mana yang ada di bawah titik viewport (clientX/clientY)?
 * Mengembalikan {slot, attachment} atau null.
 *
 * Kenapa lewat triangle dan bukan `containsPoint`: Container Pixi yang dibuat
 * pixi-spine untuk tiap slot TIDAK punya `containsPoint` (itu hanya ada di
 * kelas Graphics/Sprite). Yang bisa dipercaya adalah geometri asli slot:
 * `attachment.computeWorldVertices()` menghasilkan koordinat world dari mesh
 * yang benar-benar digambar, lalu diuji dengan point-in-triangle memakai
 * `attachment.triangles`. Hasilnya tepat mengikuti bentuk mesh, termasuk
 * bagian transparan yang bukan bagian dari segitiga mana pun.
 */
function slotAtClient(clientX, clientY) {
	if (!spine?.skeleton) return null;
	const stage = toStagePoint(clientX, clientY);
	const slots = spine.skeleton.slots;
	const verts = SLOTTIP.scratch || (SLOTTIP.scratch = new Float32Array(4096));
	// Slot terakhir dicari lebih dulu: slot yang digambar belakangan menutupi
	// yang lebih awal, jadi yang terlihat pengguna adalah urutan teratas.
	for (let i = slots.length - 1; i >= 0; i--) {
		const slot = slots[i];
		const att = slot?.attachment;
		if (!att) continue;
		const c = spine.slotContainers?.[i];
		if (c && c.visible === false) continue;
		try {
			const n = att.worldVerticesLength || 0;
			if (!n || n > verts.length) continue;
			// Runtime 4.x: computeWorldVertices(slot, start, count, out, offset, stride)
			att.computeWorldVertices(slot, 0, n, verts, 0, 2);
			if (pointInAttachment(verts, n, att.triangles, stage.x, stage.y)) {
				return { slot, attachment: att };
			}
		} catch {
			/* attachment tanpa geometri — lewati */
		}
	}
	return null;
}

/** Uji point-in-triangle terhadap mesh attachment (triangles = indeks vertex). */
function pointInAttachment(verts, count, triangles, px, py) {
	const nv = count / 2;
	if (triangles && triangles.length >= 3) {
		for (let t = 0; t + 2 < triangles.length; t += 3) {
			const i0 = triangles[t];
			const i1 = triangles[t + 1];
			const i2 = triangles[t + 2];
			if (i0 >= nv || i1 >= nv || i2 >= nv) continue;
			if (
				pointInTriangle(
					px,
					py,
					verts[i0 * 2],
					verts[i0 * 2 + 1],
					verts[i1 * 2],
					verts[i1 * 2 + 1],
					verts[i2 * 2],
					verts[i2 * 2 + 1],
				)
			) {
				return true;
			}
		}
		return false;
	}
	// Tanpa triangles (mis. region 4 titik): pakai kotak pembatas.
	if (nv >= 4) {
		let minX = Infinity,
			minY = Infinity,
			maxX = -Infinity,
			maxY = -Infinity;
		for (let i = 0; i < nv; i++) {
			const x = verts[i * 2];
			const y = verts[i * 2 + 1];
			if (x < minX) minX = x;
			if (x > maxX) maxX = x;
			if (y < minY) minY = y;
			if (y > maxY) maxY = y;
		}
		return px >= minX && px <= maxX && py >= minY && py <= maxY;
	}
	return false;
}

function pointInTriangle(px, py, ax, ay, bx, by, cx, cy) {
	const d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by);
	const d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy);
	const d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay);
	const hasNeg = d1 < 0 || d2 < 0 || d3 < 0;
	const hasPos = d1 > 0 || d2 > 0 || d3 > 0;
	return !(hasNeg && hasPos);
}

function hideSlotTip() {
	if (SLOTTIP.slot) {
		SLOTTIP.slot = null;
		const d = slotTooltipEl();
		d.hidden = true;
	}
}

function showSlotTip(hit, clientX, clientY) {
	const d = slotTooltipEl();
	const name = hit.slot?.data?.name || "?";
	const att = hit.attachment;
	const attName = att?.name || att?.constructor?.name || "";
	d.textContent = attName && attName !== name ? `${name} · ${attName}` : name;
	d.hidden = false;
	// Geser 14px dari kursor, dan balik arah kalau mentok tepi kanan/bawah.
	const pad = 14;
	const w = d.offsetWidth;
	const h = d.offsetHeight;
	let x = clientX + pad;
	let y = clientY + pad;
	if (x + w > window.innerWidth - 6) x = clientX - w - pad;
	if (y + h > window.innerHeight - 6) y = clientY - h - pad;
	d.style.transform = `translate(${Math.max(4, x)}px, ${Math.max(4, y)}px)`;
}

/** Perbarui tooltip untuk posisi kursor terakhir (dipanggil per frame). */
function tickSlotTip() {
	SLOTTIP.raf = 0;
	if (!SLOTTIP.enabled) return;
	if (!spine?.skeleton) return hideSlotTip();
	const hit = slotAtClient(SLOTTIP.clientX, SLOTTIP.clientY);
	if (!hit) return hideSlotTip();
	SLOTTIP.slot = hit.slot;
	showSlotTip(hit, SLOTTIP.clientX, SLOTTIP.clientY);
}

function scheduleSlotTip() {
	if (SLOTTIP.raf) return;
	SLOTTIP.raf = requestAnimationFrame(tickSlotTip);
}

/* ------------------------------------------------------------------ *
 * Sorotan slot (dari klik / dari daftar inspector)
 *
 * Menggambar ulang garis tepi mesh slot terpilih ke Graphics tersendiri, di
 * atas model. Dipakai untuk dua arah: klik slot di kanvas -> baris inspector
 * tersorot, dan klik baris inspector -> mesh-nya tersorot di kanvas.
 * ------------------------------------------------------------------ */
const SLOTHILITE = { index: -1, gfx: null };

function slotHiliteGfx() {
	if (SLOTHILITE.gfx) return SLOTHILITE.gfx;
	const g = new Graphics();
	g.visible = false;
	// Segaris dengan bonesGfx: sama-sama di stageRoot, jadi koordinat mesh
	// world tidak perlu diterjemahkan lagi.
	stageRoot.addChild(g);
	SLOTHILITE.gfx = g;
	return g;
}

/** Sorot satu slot (indeks), atau -1 untuk menghapus sorotan. */
function hiliteSlot(index) {
	SLOTHILITE.index = Number.isInteger(index) ? index : -1;
	drawSlotHilite();
}

function drawSlotHilite() {
	const g = slotHiliteGfx();
	g.clear();
	const i = SLOTHILITE.index;
	const skel = spine?.skeleton;
	if (i < 0 || !skel || !skel.slots?.[i]) {
		g.visible = false;
		return;
	}
	const slot = skel.slots[i];
	const att = slot.attachment;
	if (!att?.worldVerticesLength) {
		g.visible = false;
		return;
	}
	const verts = SLOTTIP.scratch || (SLOTTIP.scratch = new Float32Array(4096));
	const n = att.worldVerticesLength;
	if (n > verts.length) {
		g.visible = false;
		return;
	}
	try {
		att.computeWorldVertices(slot, 0, n, verts, 0, 2);
	} catch {
		g.visible = false;
		return;
	}
	const s = 1 / (state.zoom || 1);
	const nv = n / 2;
	// Garis tepi mengikuti triangles supaya bentuknya tepat, bukan sekadar
	// kotak pembatas.
	const tris = att.triangles;
	g.lineStyle(1.5 * s, 0x33ff99, 0.9);
	if (tris && tris.length >= 3) {
		for (let t = 0; t + 2 < tris.length; t += 3) {
			const i0 = tris[t];
			const i1 = tris[t + 1];
			const i2 = tris[t + 2];
			if (i0 >= nv || i1 >= nv || i2 >= nv) continue;
			g.moveTo(verts[i0 * 2], verts[i0 * 2 + 1]);
			g.lineTo(verts[i1 * 2], verts[i1 * 2 + 1]);
			g.lineTo(verts[i2 * 2], verts[i2 * 2 + 1]);
			g.lineTo(verts[i0 * 2], verts[i0 * 2 + 1]);
		}
	} else {
		let first = true;
		for (let k = 0; k < nv; k++) {
			if (first) {
				g.moveTo(verts[k * 2], verts[k * 2 + 1]);
				first = false;
			} else {
				g.lineTo(verts[k * 2], verts[k * 2 + 1]);
			}
		}
		if (nv > 2) g.lineTo(verts[0], verts[1]);
	}
	g.visible = true;
}

/**
 * Fokuskan satu slot: buka inspector (kalau perlu), pindah ke tab slot,
 * gulir barisnya ke tengah, dan sorot baris + mesh-nya.
 */
function focusSlot(index) {
	if (!spine?.skeleton) return;
	const slot = spine.skeleton.slots?.[index];
	if (!slot) return;
	insp.focus = index;
	hiliteSlot(index);
	setInspectorVisible(true);
	setInspectorTab("slots");
	// renderSlots() baru saja dijalankan lewat setInspectorTab; tandai baris.
	const row = el.slotList?.querySelector(`[data-slot-index="${index}"]`);
	if (row) {
		for (const r of el.slotList.querySelectorAll(".slot.is-focus")) r.classList.remove("is-focus");
		row.classList.add("is-focus");
		row.scrollIntoView({ block: "center", behavior: "smooth" });
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

// Live2D sit-and-watch tick: the Spine tick above bails for Cubism models, so
// the auto-advance / random-clip behaviour runs here instead.
app.ticker.add(() => {
	if (!isLive2D(current) || !spine) return;
	if (document.hidden) return; // no busywork in a background tab
	// The time readout belongs to the Cubism motion manager; keep it fresh even
	// when the random/auto features are off (the Spine tick above bails here).
	updateScrubUI();
	if (!live2dRandomOn && !live2dAutoNext) return;
	const now = performance.now();
	if (now < live2dAutoNextAt) return;
	const names = (current.animations || []).filter(Boolean);
	// Auto-advance waits until the current clip actually ends; random fires on a
	// timer but never cuts a clip short (it also waits for "done").
	const done = live2dMotionDone();
	if (!done && !live2dRandomOn) return;
	if (!names.length) return;
	let next = animName;
	if (live2dRandomOn) {
		// Prefer resting poses, then anything: random purely across 100+ touch
		// clips feels chaotic, so weight towards idle when idle exists.
		const idle = names.filter((n) => /^idle/i.test(n));
		const pool = Math.random() < 0.6 && idle.length ? idle : names;
		next = pool[Math.floor(Math.random() * pool.length)];
	} else {
		const i = names.indexOf(animName);
		next = names[(i + 1) % names.length];
	}
	if (next) {
		playLive2DMotion(spine, next);
		animName = next;
		live2dUpdateDuration();
		if (el.animSelect) el.animSelect.value = next;
	}
	// Random: pause a few seconds between clips. Auto: check again shortly; the
	// next clip starts as soon as the current one finishes.
	live2dAutoNextAt = now + (live2dRandomOn ? 4000 + Math.random() * 4000 : 700);
});

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
/**
 * Jumlah kartu per halaman saat mode galeri. Lebih besar dari mode daftar
 * karena tiap kartu jauh lebih pendek (gambar + satu baris nama), jadi 120
 * kartu galeri masih lebih ringkas daripada 60 baris daftar.
 */
const PAGE_SIZE_GRID = 120;
const browse = {
	view: "games", game: null, page: 1, favOnly: false,
	// Galeri (petak) jadi default: thumbnail CZN 260x460 jauh lebih berguna
	// daripada baris 44px. Preferensi "list" pengguna tetap dipulihkan.
	layout: "grid",
	// Filter khusus CZN: tab jenis karakter + atribut dari wiki.
	cznGroup: "all", cznEgo: "", cznJob: "", cznRarity: "",
};

/**
 * Games, A→Z by display label.
 *
 * Was sorted biggest-library-first, which is nice for discovery but makes a
 * known title impossible to find by eye once there are 20+ games. Alphabetical
 * sort uses localeCompare with numeric: true so "Epic Seven 2" doesn't land
 * before "Epic Seven", and sensitivity: "base" so accents don't reorder.
 */
function gameBuckets() {
	// Grouping + pengurutan 46k model dipindah ke src/library-index.js dan
	// di-cache per array `models`. Yang dinamis (favorit, NEW, pencarian)
	// diterapkan di atasnya oleh pemanggil.
	return libraryIndex(models).buckets;
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
const summaryCache = new WeakMap();
function gameSummary(items) {
	// `items` dari indeks itu array yang sama tiap render, jadi hasilnya
	// bisa di-cache; array baru (mode Favorit) dihitung ulang wajar.
	const cached = summaryCache.get(items);
	if (cached !== undefined) return cached;
	const roots = items.filter((m) => !m.family || m.family.root === m.id);
	const variants = items.length - roots.length;
	const out = variants
		? `${roots.length} model · +${variants} varian`
		: `${roots.length} model`;
	summaryCache.set(items, out);
	return out;
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
	// Filter CZN tidak boleh terbawa dari game sebelumnya.
	resetCznFilters();
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
	resetCznFilters();
	// Leaving a game must stop any playing video: a <video> keeps downloading
	// and decoding off-screen, which stalls the library render.
	if (videoStageActive()) {
		disposeVideo();
		destroyCurrent({ removeFromStage: false });
		current = null;
		el.empty.hidden = false;
		el.hud.hidden = true;
		el.playBtn.disabled = false;
	}
	if (imageStageActive()) {
		disposeImage();
		destroyCurrent({ removeFromStage: false });
		current = null;
		el.empty.hidden = false;
		el.hud.hidden = true;
		el.playBtn.disabled = false;
	}
	renderLibrary();
}

/** Models of the current game, filtered by the search box + CZN filters. */
function modelsInScope(group = browse.cznGroup) {
	const idx = libraryIndex(models);
	const q = el.search.value.trim().toLowerCase();
	// Daftar akar per game sudah dihitung sekali di src/library-index.js.
	const base = browse.game ? idx.rootsByGame.get(browse.game) || [] : idx.rootsAll;
	// "Favorit" filter: narrow to starred models before anything else, so it
	// works from either the game grid or a single game's list.
	const scoped = browse.favOnly ? base.filter((m) => favorites.has(m.id)) : base;
	// Model baru mengapung ke atas (terbaru dulu), sisanya alfabetis. `base`
	// SUDAH terurut per id, jadi cukup pisahkan yang ber-badge dan urutkan
	// grup itu — hasilnya identik dengan comparator lama tanpa menyortir
	// ulang ribuan entri pada setiap ketikan/render.
	const fresh = [];
	const rest = [];
	const newSet = loadNewSet();
	for (const m of scoped) {
		const ts = newSet[m.id] || 0;
		if (ts) fresh.push([m, ts]);
		else rest.push(m);
	}
	if (fresh.length) fresh.sort((a, b) => b[1] - a[1] || a[0].id.localeCompare(b[0].id));
	const list = fresh.map((x) => x[0]).concat(rest);
	// Teks pencarian sudah diturunkan ke huruf kecil dan digabung per model.
	let out = q ? list.filter((m) => (idx.search.get(m.id) || "").includes(q)) : list;
	if (browse.game === "chaoszero") {
		if (group !== "all") {
			const want = group === "combatant" ? "CHAR_COMBATANT" : "CHAR_SUPPORTER";
			out = out.filter((m) => m.charType === want);
		}
		if (browse.cznEgo) out = out.filter((m) => m.ego === browse.cznEgo);
		if (browse.cznJob) out = out.filter((m) => m.job === browse.cznJob);
		if (browse.cznRarity) out = out.filter((m) => String(m.rarity) === browse.cznRarity);
		// Urutan CZN: rarity tertinggi dulu, lalu nama. Ini menggantikan
		// urutan "NEW dulu / alfabet id" yang dipakai game lain.
		out = out.slice().sort((a, b) =>
			(Number(b.rarity) || 0) - (Number(a.rarity) || 0) ||
			String(a.name || a.id).localeCompare(String(b.name || b.id), undefined, { numeric: true }) ||
			a.id.localeCompare(b.id));
	}
	return out;
}

/** How many variants are hidden from the grid for the current game. */
function hiddenVariantCount() {
	const idx = libraryIndex(models);
	if (browse.game) return idx.variantsByGame.get(browse.game) || 0;
	let total = 0;
	for (const n of idx.variantsByGame.values()) total += n;
	return total;
}

const CZN_ICON = "/thumbs/czn-ui/";
const EGO_ORDER = ["instinct", "norms", "love", "creed", "narcissism"];
const JOB_ORDER = ["striker", "vanguard", "ranger", "hunter", "psionic", "controller"];
const capWord = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());

/**
 * Siapkan tab Combatants/Partner + filter IKON untuk game CZN.
 *
 * Filter-nya meniru baris `.filter-cell` di wiki e7bot: badge ego (latar
 * gradien + ikon), badge job, dan deretan bintang untuk rarity — bukan
 * dropdown teks. Aset ikon ada di public/thumbs/czn-ui (tools/czn/fetch-icons.py).
 * Klik ikon yang sama lagi = matikan filter itu.
 */
function syncCznFilters() {
	const box = el.cznFilters;
	if (!box) return;
	const show = browse.view === "models" && browse.game === "chaoszero";
	box.hidden = !show;
	if (!show) return;

	// Nilai diambil dari seluruh akar game (bukan hasil filter) supaya memilih
	// satu ego tidak menghilangkan pilihan ego lainnya.
	const roots = libraryIndex(models).rootsByGame.get("chaoszero") || [];
	const values = (field, order) => {
		const have = new Set(roots.map((m) => m[field]).filter(Boolean));
		return [...order.filter((v) => have.has(v)),
			...[...have].filter((v) => !order.includes(v)).sort()];
	};
	const rarities = [...new Set(roots.map((m) => m.rarity).filter((v) => v != null))]
		.sort((a, b) => b - a).map(String);
	const rows = [
		["ego", values("ego", EGO_ORDER), browse.cznEgo],
		["job", values("job", JOB_ORDER), browse.cznJob],
		["rarity", rarities, browse.cznRarity],
	];
	for (const [kind, vals, active] of rows) {
		const row = box.querySelector(`.czn-icon-row[data-kind="${kind}"]`);
		if (!row) continue;
		const sig = `${kind}:${vals.join(",")}`;
		if (row.dataset.sig !== sig) {
			row.innerHTML = "";
			for (const v of vals) {
				const b = document.createElement("button");
				b.type = "button";
				b.className = "czn-icon";
				b.dataset.kind = kind;
				b.dataset.value = v;
				const label = kind === "rarity" ? `${v} bintang` : capWord(v);
				b.title = label;
				b.setAttribute("aria-label", label);
				if (kind === "ego") {
					b.innerHTML = `<span class="czn-ego" style="--ego-bg:url('${CZN_ICON}ego_bg_${v}.webp')"><img src="${CZN_ICON}ego_${v}.webp" alt="" /></span>`;
				} else if (kind === "job") {
					b.innerHTML = `<span class="czn-job"><img src="${CZN_ICON}job_${v}.webp" alt="" /></span>`;
				} else {
					b.innerHTML = `<span class="czn-stars">${`<img src="${CZN_ICON}star.png" alt="" />`.repeat(Number(v))}</span>`;
				}
				row.appendChild(b);
			}
			row.dataset.sig = sig;
		}
		for (const b of row.querySelectorAll(".czn-icon")) {
			const on = b.dataset.value === active;
			b.classList.toggle("is-on", on);
			b.setAttribute("aria-pressed", String(on));
		}
	}

	// Jumlah per tab dihitung dengan filter LAIN tetap aktif, tapi tanpa
	// membatasi group — jadi angkanya tidak berbohong saat user mencari.
	const all = modelsInScope("all");
	const counts = {
		all: all.length,
		combatant: all.filter((m) => m.charType === "CHAR_COMBATANT").length,
		partner: all.filter((m) => m.charType === "CHAR_SUPPORTER").length,
	};
	for (const btn of box.querySelectorAll(".czn-tab")) {
		const on = btn.dataset.group === browse.cznGroup;
		btn.classList.toggle("is-on", on);
		btn.setAttribute("aria-selected", String(on));
	}
	for (const span of box.querySelectorAll(".czn-tab-count"))
		span.textContent = String(counts[span.dataset.count] ?? 0);
}

/** Kosongkan filter CZN saat berpindah game. */
function resetCznFilters() {
	browse.cznGroup = "all";
	browse.cznEgo = browse.cznJob = browse.cznRarity = "";
}

function renderModels() {
	const list = modelsInScope();
	const perPage = browse.layout === "grid" ? PAGE_SIZE_GRID : PAGE_SIZE;
	const pages = Math.max(1, Math.ceil(list.length / perPage));
	// Clamp so deleting a model or narrowing a search can't strand us off-list.
	if (browse.page > pages) browse.page = pages;
	if (browse.page < 1) browse.page = 1;

	const start = (browse.page - 1) * perPage;
	const slice = list.slice(start, start + perPage);

	// Bentuk wadah mengikuti layout: baris penuh untuk daftar, petak untuk
	// galeri. Dipasang di <ul> supaya CSS tidak perlu tahu mode lewat kelas
	// di elemen lain.
	const gallery = browse.layout === "grid";
	el.list.classList.toggle("is-gallery", gallery);
	// Sidebar ikut melebar di mode galeri (lihat --sidebar-w-gallery).
	el.layoutEl?.classList.toggle("is-gallery", gallery);

	el.list.innerHTML = "";
	if (!slice.length) {
		const filtered = browse.game === "chaoszero" && (
			browse.cznGroup !== "all" || browse.cznEgo || browse.cznJob || browse.cznRarity
		);
		el.list.innerHTML = `<li class="list-empty">Tidak ada model yang cocok.${filtered ? " Coba Reset filter." : ""}</li>`;
	}
	for (const m of slice) {
		el.list.appendChild(browse.layout === "grid" ? galleryCard(m) : listCard(m));
	}

	el.count.textContent = String(list.length);
	renderPager(pages, list.length, start, slice.length);
	// Jumlah per tab ikut berubah saat pencarian / filter lain berubah.
	syncCznFilters();
	if (current) setActive(current.id);
}

/** Path thumbnail untuk sebuah model, atau "" kalau tidak ada. */
function thumbPathOf(m) {
	if (m.format === "image") return m.imageFile || "";
	const file = thumbs[m.id];
	if (!file) return "";
	// The manifest value is "<game>/<file>" (older Nikke entries ship a
	// bare filename), so encode per segment: encoding the slash turned
	// "azurlane/x.png" into one opaque segment and 404'd.
	return "/thumbs/" + String(file).split("/").map(encodeURIComponent).join("/");
}

/** Chip jumlah varian di kartu pustaka (family sudah ada di payload lean). */
function variantChip(m) {
	const n = m.family?.members?.length || 0;
	return n > 1
		? `<span class="variant-chip" title="${n} varian — klik untuk membuka daftar">${n} varian</span>`
		: "";
}

/** Satu baris daftar (layout lama): gambar kecil + nama + meta. */
function listCard(m) {
	const li = document.createElement("li");
	const btn = document.createElement("button");
	btn.className = "model";
	btn.dataset.id = m.id;
	// Show the real asset id — with 2000+ models an auto-titlecased name
	// ("Char000101") is far less useful than the id itself.
	const src = thumbPathOf(m);
	const art = src
		? `<img class="model-thumb" src="${escapeHtml(src)}" alt="" loading="lazy" decoding="async" width="128" height="128" />`
		: `<span class="model-thumb model-thumb-none" aria-hidden="true">${escapeHtml(initials(m))}</span>`;
	// Tooltip carries the full id + character details; the card itself
	// can only fit the short label.
	const details = modelSubLabel(m);
	btn.title = modelTooltip(m);
	const newTag = isNewModel(m) ? `<span class="badge-new" title="Baru ditambahkan">NEW</span>` : "";
	// Indeks ringan hanya membawa animCount; entri yang sudah dimuat detailnya
	// punya daftar animations yang sebenarnya.
	const anims = typeof m.animCount === "number" ? m.animCount : (m.animations || []).length;
	btn.innerHTML = `
		${art}
		<span class="model-text">
			<span class="model-name">${escapeHtml(modelLabel(m))}${newTag}</span>
			<span class="model-meta">${details ? escapeHtml(details) + " · " : ""}${anims ? anims + " animasi" : "—"}</span>
		</span>
		${variantChip(m)}
		`;
	wireCard(btn, m);
	li.appendChild(btn);
	li.appendChild(favStar(m));
	return li;
}

/**
 * Satu kartu galeri: gambar besar, nama di bawahnya.
 *
 * Sengaja memakai <img> yang dimuat lazy milik browser, bukan canvas atau
 * render ulang model: 120 kartu per halaman akan jauh terlalu berat kalau
 * tiap kartu merender skeleton sungguhan.
 */
function galleryCard(m) {
	const li = document.createElement("li");
	const btn = document.createElement("button");
	btn.className = "gcard";
	btn.dataset.id = m.id;
	btn.title = modelTooltip(m);
	const src = thumbPathOf(m);
	const art = src
		? `<img class="gcard-img" src="${escapeHtml(src)}" alt="" loading="lazy" decoding="async" width="160" height="160" />`
		: `<span class="gcard-img gcard-none" aria-hidden="true">${escapeHtml(initials(m))}</span>`;
	const newTag = isNewModel(m) ? `<span class="badge-new" title="Baru ditambahkan">NEW</span>` : "";
	btn.innerHTML = `
		<span class="gcard-art">${art}${newTag}</span>
		<span class="gcard-name">${escapeHtml(modelLabel(m))}</span>
		${variantChip(m)}
		`;
	wireCard(btn, m);
	li.appendChild(btn);
	li.appendChild(favStar(m));
	return li;
}

/** Pasang klik muat-model + klik kanan panggung A/B pada sebuah kartu. */
function wireCard(btn, m) {
	btn.addEventListener("click", () => loadModel(m));
	// Chip varian: muat modelnya lalu langsung buka daftar varian, supaya
	// pengguna tidak perlu klik kartu dulu baru cari tombol Varian di stage.
	const chip = btn.querySelector(".variant-chip");
	if (chip) chip.addEventListener("click", (e) => {
		e.stopPropagation();
		pendingVariantOpen = true;
		loadModel(m);
	});
	// Klik kanan (atau Alt+klik) memuat model ini sebagai B di panggung A/B.
	btn.addEventListener("contextmenu", (e) => {
		if (!AB.on && !e.altKey) return; // hanya saat mode A/B sudah aktif
		e.preventDefault();
		abStart(m);
	});
}

/** Tombol bintang favorit — saudara kartu, bukan anaknya, agar klik tidak memuat model. */
function favStar(m) {
	const star = document.createElement("button");
	const on = isFavorite(m.id);
	star.className = "model-fav" + (on ? " is-on" : "");
	star.type = "button";
	star.setAttribute("aria-pressed", String(on));
	star.setAttribute("aria-label", on ? "Hapus dari favorit" : "Tambah ke favorit");
	star.title = on ? "Hapus dari favorit" : "Tambah ke favorit";
	// Build a real <svg> element — assigning the bare <path> markup from
	// ICON.star renders nothing, because innerHTML parses it as an unknown
	// top-level element instead of an SVG graphic.
	star.innerHTML = `<svg viewBox="0 0 24 24" class="icon" aria-hidden="true">${ICON.star}</svg>`;
	star.addEventListener("click", (ev) => {
		ev.stopPropagation();
		toggleFavorite(m.id);
	});
	return star;
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
	// Panel filter CZN ikut hilang saat kembali ke daftar game.
	syncCznFilters();
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
	crosscore: "/api/update/crosscore",
	catshinobi: "/api/update/catshinobi",
	bd2: "/api/update/bd2",
	azurlane: "/api/update/azurlane",
	// Azur Lane Live2D: sumbernya CDN resmi lewat gate TCP game, bukan repo
	// komunitas. Lihat tools/update-azurlane-l2d.py.
	"azurlane-l2d": "/api/update/azurlane-l2d",
	nikke: "/api/update/nikke",
	ivntight: "/api/update/ivntight",
	arknights: "/api/update/arknights",
	zonenova: "/api/update/zonenova",
	stellasora: "/api/update/stellasora",
	"stellasora-l2d": "/api/update/stellasora",
	"stellasora-3d": "/api/update/stellasora-3d",
	girlwars: "/api/update/girlwars",
	lostsword: "/api/update/lostsword",
	"lostsword-video": "/api/update/lostsword-video",
	dragontravelers: "/api/update/dragontravelers",
	// 贤者同盟 / Alliance Sages: model karakter + CG dari CDN euwv.0577ai.com.
	alliancesages: "/api/update/alliancesages",
	// 禁果便利店 (mcs18): bundle karakter spine dari Addressables terbuka.
	mcs18: "/api/update/mcs18",
	// Epic Seven: satu pembaru untuk lobby + combat + skill + wallpaper
	// (semua dari e7codex). Lihat tools/update-epic7.py.
	epic7: "/api/update/epic7",
	// Chaos Zero Nightmare: aset game-side assets/chaoszero/. Updater-nya
	// menyegarkan metadata wiki (ikon / kartu / thumbnail), bukan model.
	chaoszero: "/api/update/chaoszero",
	// Make Drama: pustaka komunitas anyabot/MAD-Viewer.
	"mad-drama": "/api/update/mad-drama",
	pokerfate: "/api/update/pokerfate",
	muvluv: "/api/update/muvluv",
	eroera: "/api/update/eroera",
	// Otherworld Mercenary Corps (Cryptect): XAPK APKPure via HTTP Range.
	mercenary: "/api/update/mercenary",
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

/* --- Log proses pembaruan ---------------------------------------------
 * Server mengalirkan stdout/stderr pembaru lewat /api/update/<game>/status,
 * jadi panel ini menampilkan prosesnya secara live, bukan hanya hasil akhir.
 *
 * Dua poller jalan bersamaan (interval 2 dtk + loop apply 3 dtk) dan `--check`
 * juga membawa field `log`. Respons yang datang terlambat sempat menimpa
 * baris yang sudah tampil dengan array kosong — itulah keluhan "log hilang
 * sebelum selesai". Penjaganya:
 *  - tiap sesi log punya `logEpoch`; respons dari sesi lama dibuang;
 *  - sekali log terisi, respons tanpa / ber-`log` kosong TIDAK mengosongkannya;
 *  - polling berhenti hanya saat server bilang `running:false`, bukan saat
 *    satu request gagal atau body-nya kosong.
 */
let logEpoch = 0;
let logBuffer = [];
let applyInFlight = false;

function updateLogSet(lines, epoch = logEpoch) {
	if (!el.updateLogView || epoch !== logEpoch) return;
	// Jangan pernah mengganti isi yang sudah ada dengan respons kosong/basi.
	if (Array.isArray(lines) && (lines.length || !logBuffer.length)) {
		logBuffer = lines.slice();
	}
	const atBottom =
		el.updateLogView.scrollTop + el.updateLogView.clientHeight >= el.updateLogView.scrollHeight - 24;
	el.updateLogView.textContent = logBuffer.join("\n");
	if (atBottom) el.updateLogView.scrollTop = el.updateLogView.scrollHeight;
}

function resetLogSession() {
	logEpoch += 1;
	logBuffer = [];
	updateLogSet([], logEpoch);
}

function updateLogStatus(text, kind) {
	if (!el.updateLogStatus) return;
	el.updateLogStatus.textContent = text || "";
	el.updateLogStatus.className = "update-log-status" + (kind ? " is-" + kind : "");
}

function openUpdateLog(fetchStatus = true) {
	if (!el.updateLogModal) return;
	el.updateLogModal.hidden = false;
	if (!fetchStatus) return;
	const epoch = logEpoch;
	fetchLog(epoch).then((st) => {
		if (epoch === logEpoch && st?.running) startLogPolling(epoch);
	});
}

function closeUpdateLog() {
	if (el.updateLogModal) el.updateLogModal.hidden = true;
}

let logPollTimer = null;

/** Ambil status; kembalikan null kalau request gagal (itu BUKAN "selesai"). */
async function fetchLog(epoch = logEpoch) {
	if (!updaterBase || epoch !== logEpoch) return null;
	try {
		const st = await fetchUpdateJSON(`${updaterBase}/status`);
		if (epoch !== logEpoch) return null;
		updateLogSet(st.log, epoch);
		if (st.running) {
			updateLogStatus(`Berjalan… (${st.game || ""})`, "running");
		} else if (st.result?.error) {
			updateLogStatus(`Gagal: ${st.result.error}`, "fail");
		} else if (st.result) {
			updateLogStatus("Selesai.", "done");
		} else if (!logBuffer.length) {
			updateLogStatus("Belum ada proses pembaruan di sesi ini.", "");
		}
		return st;
	} catch {
		return null; // biarkan isi terakhir, jangan kosongkan panel
	}
}

function startLogPolling(epoch = logEpoch) {
	stopLogPolling();
	if (epoch !== logEpoch) return;
	logPollTimer = setInterval(async () => {
		if (epoch !== logEpoch) {
			stopLogPolling();
			return;
		}
		const st = await fetchLog(epoch);
		if (epoch !== logEpoch) return;
		// Satu request gagal / body kosong BUKAN berarti job selesai.
		if (st && st.running === false) stopLogPolling();
	}, 2000);
}

function stopLogPolling() {
	if (logPollTimer) {
		clearInterval(logPollTimer);
		logPollTimer = null;
	}
}

function initUpdateLog() {
	el.updateLogBtn?.addEventListener("click", openUpdateLog);
	el.updateLogClose?.addEventListener("click", closeUpdateLog);
	el.updateLogClose2?.addEventListener("click", closeUpdateLog);
	el.updateLogModal?.addEventListener("click", (e) => {
		if (e.target?.dataset?.close) closeUpdateLog();
	});
	el.updateLogClear?.addEventListener("click", () => {
		logBuffer = [];
		updateLogSet([], logEpoch);
	});
}

/* --- Updater Health Dashboard ---------------------------------------------
 * Satu meja untuk semua pembaru. Data dari /api/updaters/health (di-cache
 * 5 menit di server). "Terapkan yang berubah" memanggil endpoint apply yang
 * SUDAH ADA per game secara berurutan, sambil mengikuti /status untuk log —
 * tidak ada jalur apply baru, jadi aturan rescan/forceModelRescan tetap sama.
 */
let healthData = null;
let healthBusy = false;
let healthLogLines = [];

const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g,
	(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function healthTime(ts) {
	if (!ts) return "—";
	return new Date(ts).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function healthStateOf(r) {
	if (!r.ok) return { cls: "is-fail", text: "Gagal" };
	if (r.extractor) return { cls: "is-idle", text: "Ekstraktor" };
	if (r.changed || (r.new || 0) > 0) {
		return { cls: "is-warn", text: (r.new || 0) > 0 ? `${r.new} model baru` : "Versi berubah" };
	}
	return { cls: "", text: "Aktif" };
}

function healthTargets() {
	return (healthData?.games || []).filter((r) =>
		r.ok && !r.extractor && (r.changed || (r.new || 0) > 0));
}

function healthStatus(text, kind) {
	if (!el.healthStatus) return;
	el.healthStatus.textContent = text || "";
	el.healthStatus.className = "update-log-status" + (kind ? " is-" + kind : "");
}

function healthLogPush(line) {
	healthLogLines.push(line);
	if (healthLogLines.length > 200) healthLogLines.shift();
	if (!el.healthLog) return;
	el.healthLog.hidden = false;
	el.healthLog.textContent = healthLogLines.join("\n");
	el.healthLog.scrollTop = el.healthLog.scrollHeight;
}

function renderHealth(data) {
	healthData = data;
	if (!el.healthRows) return;
	const s = data.summary || {};
	const pills = [
		`${s.total ?? 0} updater`, `${s.ok ?? 0} ok`,
		`${s.changed ?? 0} berubah`, `${s.pending ?? 0} model baru`,
	];
	el.healthSummary.innerHTML =
		pills.map((t, i) => `<span class="health-pill${i === 2 && s.changed ? " is-warn" : ""}">${escHtml(t)}</span>`).join("") +
		(s.failed ? `<span class="health-pill is-fail">${s.failed} gagal</span>` : "") +
		(s.mirrorLag ? `<span class="health-pill is-warn">${s.mirrorLag} sumber tertinggal</span>` : "");
	el.healthRows.innerHTML = (data.games || []).map((r) => {
		const st = healthStateOf(r);
		const note = r.error ? escHtml(r.error)
			: r.mirrorLag ? '<span class="health-badge">sumber tertinggal</span>'
				: r.extractor ? "tanpa --check" : escHtml(r.source || "");
		return `<tr data-game="${escHtml(r.game)}">
			<td>${escHtml(r.label)}<br><span class="mono" style="opacity:.6">${escHtml(r.game)}</span></td>
			<td><span class="health-state ${st.cls}"><i></i>${st.text}</span></td>
			<td class="mono" title="${escHtml(r.version || "")}">${escHtml(String(r.version || "—").slice(0, 18))}</td>
			<td>${r.new ?? "—"}</td>
			<td>${r.have ?? "—"}${r.expected != null ? " / " + r.expected : ""}</td>
			<td>${healthTime(r.checkedAt)}</td>
			<td>${note}</td>
		</tr>`;
	}).join("");
	const dot = document.getElementById("health-dot");
	if (dot) dot.hidden = !(s.failed || s.changed || s.pending || s.mirrorLag);
	if (el.healthApply) el.healthApply.disabled = healthTargets().length === 0 || healthBusy;
}

function healthSetBusy(on) {
	healthBusy = on;
	if (el.healthRefresh) el.healthRefresh.disabled = on;
	if (el.healthApply) el.healthApply.disabled = on || healthTargets().length === 0;
}

async function loadHealth(url) {
	if (healthBusy) return;
	healthSetBusy(true);
	healthStatus("Memeriksa…", "running");
	try {
		const data = await fetchUpdateJSON(url);
		if (data.error) throw new Error(data.error);
		renderHealth(data);
		healthStatus(`Selesai · ${healthTime(data.at)}`, "done");
	} catch (err) {
		healthStatus(`Gagal: ${err.message}`, "fail");
	} finally {
		healthSetBusy(false);
	}
}

function openHealth() {
	if (!el.healthModal) return;
	el.healthModal.hidden = false;
	// Panel pertama kali pakai cache; "Cek semua" yang memaksa refresh.
	if (!healthData) loadHealth("/api/updaters/health");
}

function closeHealth() {
	if (el.healthModal) el.healthModal.hidden = true;
}

/** Terapkan semua game dengan changed/new lewat endpoint apply existing. */
async function applyPendingUpdaters() {
	const targets = healthTargets();
	if (!targets.length || healthBusy) return;
	// Apply itu operasi berat (bisa ratusan model). Minta konfirmasi eksplisit
	// supaya klik tidak sengaja tidak langsung menjalankan belasan updater.
	const names = targets.map((t) => `${t.label} (${t.new || 0} baru)`).join("\n");
	if (!confirm(`Terapkan pembaruan untuk ${targets.length} game secara berurutan?\n\n${names}\n\nProses ini bisa makan waktu lama.`)) return;
	healthSetBusy(true);
	healthLogLines = [];
	for (const r of targets) {
		const base = `/api/update/${encodeURIComponent(r.game)}`;
		healthLogPush(`▶ ${r.label} (${r.game})`);
		try {
			const start = await fetchUpdateJSON(`${base}?mode=apply`);
			if (!start.started) {
				healthLogPush(`  dilewati: ${start.reason || "pembaruan lain masih berjalan"}`);
				continue;
			}
			for (;;) {
				await new Promise((res) => setTimeout(res, 1200));
				const st = await fetchUpdateJSON(`${base}/status`);
				const lines = st.log || [];
				if (lines.length) healthLogPush(`  ${lines[lines.length - 1]}`);
				if (!st.running) {
					healthLogPush(st.result?.error
						? `  ✗ ${st.result.error}` : "  ✓ selesai");
					break;
				}
			}
		} catch (err) {
			healthLogPush(`  ✗ ${err.message}`);
		}
	}
	healthLogPush("Menyegarkan ringkasan…");
	healthSetBusy(false);
	await loadHealth("/api/updaters/health?refresh=1");
	// Apply massal juga menulis aset: muat ulang pustaka supaya model baru
	// langsung tampil tanpa menunggu reload halaman berikutnya.
	refresh().then(syncNewFromServer).then(() => renderLibrary()).catch(() => {});
}

function initUpdaterHealth() {
	el.healthBtn?.addEventListener("click", openHealth);
	el.healthClose?.addEventListener("click", closeHealth);
	el.healthClose2?.addEventListener("click", closeHealth);
	el.healthModal?.addEventListener("click", (e) => {
		if (e.target?.dataset?.close) closeHealth();
	});
	el.healthRefresh?.addEventListener("click",
		() => loadHealth("/api/updaters/health?refresh=1"));
	el.healthApply?.addEventListener("click", applyPendingUpdaters);
}

/* --- "NEW" badge -------------------------------------------------------
 * Models added by the updater. Kept in localStorage (same store as
 * favorites) so it survives a reload, and cleared for a model AS SOON AS it
 * is opened ("seen"). Older entries fade after NEW_TTL_MS so a model can't
 * stay flagged forever.
 */
const NEW_KEY = "spine-stage:new-models";
const NEW_TTL_MS = 7 * 24 * 60 * 60 * 1000; // seminggu

/**
 * In-memory mirror of the localStorage new-set.
 *
 * loadNewSet() used to JSON.parse localStorage on EVERY call — and the model
 * list's sort comparator calls isNewModel() per comparison. Sorting 31k models
 * fires ~930k localStorage reads, which is what made entering a game (and
 * every render after a new download) visibly laggy. The set changes only via
 * saveNewSet/markNew/markSeen, so caching it and invalidating on write keeps
 * it exact. `null` means "not loaded yet".
 */
let newSetCache = null;

function loadNewSet() {
	if (newSetCache) return newSetCache;
	try {
		const raw = JSON.parse(localStorage.getItem(NEW_KEY) || "{}");
		// { id: timestamp }
		const cutoff = Date.now() - NEW_TTL_MS;
		const out = {};
		for (const [id, ts] of Object.entries(raw)) {
			if (ts && ts > cutoff) out[id] = ts;
		}
		newSetCache = out;
		return out;
	} catch {
		newSetCache = {};
		return newSetCache;
	}
}

function saveNewSet(set) {
	newSetCache = set || {};
	try {
		localStorage.setItem(NEW_KEY, JSON.stringify(newSetCache));
	} catch {
		/* penyimpanan penuh — badge hanya hilang setelah muat ulang */
	}
}

/** Tarik daftar "baru" dari server (sumber kebenaran) dan gabung ke cache
 *  localStorage. Ini yang membuat model yang ditambahkan updater CLI tetap
 *  mendapat badge, walau updater-nya tidak dijalankan dari browser ini.
 *
 *  Server juga membawa `rev`, yang naik setiap ada badge yang di-dismiss di
 *  mana pun. Kalau rev berubah, salinan lokal diganti utuh dengan milik
 *  server — tanpa itu, badge yang sudah dihapus tetap nangkring di browser ini
 *  sampai TTL seminggu habis. */
const NEW_REV_KEY = "spine-stage:new-models-rev";

async function syncNewFromServer() {
	try {
		const r = await fetch("/api/new-models");
		if (!r.ok) return;
		const d = await r.json();
		const srv = d && d.new && typeof d.new === "object" ? d.new : null;
		if (!srv) return;
		const rev = Number.isFinite(d.rev) ? d.rev : null;
		let localRev = null;
		try {
			localRev = Number(localStorage.getItem(NEW_REV_KEY));
		} catch {
			/* penyimpanan diblokir — anggap rev tak dikenal */
		}
		if (rev !== null && localRev !== rev) {
			// Ada dismissal di tempat lain: server menang, ganti seluruhnya.
			saveNewSet(srv);
			try {
				localStorage.setItem(NEW_REV_KEY, String(rev));
			} catch {
				/* badge tetap benar untuk sesi ini */
			}
			return;
		}
		// Server menang untuk apa yang ditandainya, tapi entri lokal yang belum
		// sempat dipindai tetap dipertahankan (union).
		saveNewSet({ ...loadNewSet(), ...srv });
	} catch {
		/* offline — pakai localStorage yang ada */
	}
}

function markNew(ids) {
	if (!ids?.length) return;
	const cur = loadNewSet();
	const now = Date.now();
	for (const id of ids) cur[id] = now;
	saveNewSet(cur);
}

/** Buang badge NEW untuk satu model (dipanggil saat model dibuka). */
function unmarkNew(id) {
	if (!id) return;
	const cur = loadNewSet();
	if (!(id in cur)) return;
	delete cur[id];
	saveNewSet(cur);
}

/** Apakah id termasuk "baru" (untuk badge di kartu). */
function isNewModel(m) {
	return !!loadNewSet()[m.id];
}

/** Hapus badge dari kartu yang terlihat sekarang, tanpa render ulang. */
function removeNewBadgeFromList(id) {
	if (!el.list) return;
	const btn = el.list.querySelector(`.model[data-id="${CSS.escape(id)}"]`);
	btn?.querySelector(".badge-new")?.remove();
}

/** Model dibuka = sudah dilihat: hapus badge NEW-nya.
 *
 *  Id terkadang ber-suffix varian ("<folder>#<stem>") sementara yang ditandai
 *  cuma bagian dasarnya (atau sebaliknya), jadi kalau id persis tidak ketemu,
 *  cocokkan lewat bagian sebelum "#". */
function markSeen(id) {
	if (!id) return;
	const cur = loadNewSet();
	const base = String(id).split("#")[0];
	let hit = false;
	for (const k of Object.keys(cur)) {
		if (k === id || k.split("#")[0] === base) {
			delete cur[k];
			hit = true;
		}
	}
	if (!hit) return;
	saveNewSet(cur);
	// Beri tahu server supaya badge tetap hilang di browser/perangkat lain.
	fetch("/api/new-models/dismiss", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ id }),
	}).catch(() => {
		/* server opsional — lokal sudah cukup */
	});
	// Sudah dilihat -> kembali ke urutan abjad: render ulang supaya model ini
	// turun dari puncak daftar ke posisi alfabetisnya (model "baru" lain tetap
	// di atas).
	if (browse.view === "models") renderModels();
	else removeNewBadgeFromList(id);
}

/** Show the button only for games that have an updater, then auto-check. */
function syncUpdater(game) {
	const btn = document.getElementById("update-check");
	if (!btn) return;
	const base = game && UPDATABLE[game];
	btn.hidden = !base;
	if (el.updateLogBtn) el.updateLogBtn.hidden = !base;
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

/**
 * Ambil JSON dari endpoint updater dengan aman.
 *
 * r.json() melempar "Unexpected end of JSON input" kalau server / proxy
 * membalas BODY KOSONG — 304 Not Modified dari ETag Express, 502/504 tunnel,
 * atau koneksi putus di tengah jalan. Baca dulu sebagai teks supaya pesannya
 * jelas, dan paksa no-store supaya browser tidak pernah revalidasi cache.
 */
async function fetchUpdateJSON(url, opts = {}) {
	const r = await fetch(url, { cache: "no-store", ...opts });
	const text = await r.text();
	let data = null;
	if (text) {
		try { data = JSON.parse(text); } catch { /* ditangani di bawah */ }
	}
	if (!data || typeof data !== "object") {
		const hint = text ? `: ${text.slice(0, 60)}` : ", body kosong";
		throw new Error(`Server tidak mengirim JSON (HTTP ${r.status}${hint}). Coba lagi sebentar.`);
	}
	if (!r.ok && !data.error) data.error = `HTTP ${r.status}`;
	return data;
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
		const info = await fetchUpdateJSON(`${updaterBase}?mode=check`);
		if (info.error) return;
		// Ada yang belum diunduh kalau versinya berubah ATAU masih tersisa
		// model/berkas baru. Shoujou Kaisen pernah melapor versi sama
		// (0.820.48) tetapi masih punya 14 model yang belum diambil, jadi
		// jangan hanya mengandalkan `changed`.
		const hasNew = !!info.changed || ("previous" in info && !info.previous) || pendingCount(info) > 0;
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
		info = await fetchUpdateJSON(`${updaterBase}?mode=check`);
		// Tampilkan log pemeriksaan (server mengirimnya di field `log`) supaya
		// pengguna bisa melihat langkah apa yang dilewati saat check.
		// Jangan timpa log apply yang masih berjalan dengan log --check.
		if (!applyInFlight && Array.isArray(info.log) && info.log.length) {
			resetLogSession();
			openUpdateLog(false);
			updateLogSet(info.log, logEpoch);
			updateLogStatus("Pemeriksaan selesai.", "done");
		}
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

	const hasNew = !!info.changed || ("previous" in info && !info.previous) || pendingCount(info) > 0;
	updatePending = hasNew;
	setUpdateDot(updatePending);

	if (!hasNew) {
		// Sebagian pembaru tidak punya nomor versi (Epic Seven memakai
		// katalog daring, bukan versi rilis), jadi jangan tampilkan
		// "undefined".
		const v = info.version ?? info.catalog;
		toast?.(v ? `Sudah versi terbaru (${v}).` : "Sudah versi terbaru.");
		return;
	}
	// Ada yang baru: tanya dulu sebelum mengunduh (bisa ratusan MB).
	const n = pendingCount(info);
	const what = ["shoujoukaisen", "mitao-utopia", "lostsword", "pokerfate", "nikke", "mad-drama", "eroera"].includes(updaterGame) ? "model" : "berkas";
	const detail = n > 0 ? `${n} ${what} baru` : "versi baru";
	const label = info.version ?? info.catalog;
	if (!confirm(`${label ? `Versi ${label}: ` : ""}${detail}. Unduh sekarang?`)) return;
	applyUpdate();
}

async function applyUpdate() {
	if (!updaterBase) return;
	const btn = document.getElementById("update-check");
	btn.classList.add("is-checking");
	btn.disabled = true;
	toast?.("Mengunduh pembaruan… ini bisa beberapa menit.");
	// Buka panel log + pantau prosesnya supaya pengguna bisa melihat apa
	// yang sedang dikerjakan (unduh/ekstrak) alih-alih menunggu buta.
	openUpdateLog(false);
	resetLogSession();
	applyInFlight = true;
	const epoch = logEpoch;
	updateLogStatus("Memulai…", "running");
	try {
		const started = await fetchUpdateJSON(`${updaterBase}?mode=apply`);
		if (!started.started) {
			toast?.(started.reason || "Tidak bisa memulai unduhan.");
			updateLogStatus(started.reason || "Tidak bisa memulai.", "fail");
			btn.disabled = false;
			btn.classList.remove("is-checking");
			applyInFlight = false;
			return;
		}
		startLogPolling(epoch);
		for (let i = 0; i < 600; i++) {
			await new Promise((r) => setTimeout(r, 3000));
			let st;
			try {
				st = await fetchUpdateJSON(`${updaterBase}/status`);
			} catch {
				continue; // request gagal != job selesai
			}
			if (st.running) {
				updateLogSet(st.log, epoch);
				continue;
			}
			updateLogSet(st.log, epoch);
			const res = st.result || {};
			updatePending = false;
			setUpdateDot(false);
			// Tandai model hasil unduhan supaya diberi badge NEW. Sebagian
			// pembaru (mis. Brown Dust 2) menaruh model di beberapa root
			// (bd2/ dan bd2-char/), jadi mereka mengirim id LENGKAP-nya
			// (`new_ids`); sisanya cukup stem dan prefix ditebak dari game.
			const added = res.new_ids || res.new_models || [];
			if (added.length) {
				// Prefix harus sama dengan id model di library (“<game>/<folder>”).
				const NEW_PREFIX = { shoujoukaisen: "shoujoukaisen", "mitao-utopia": "mitao-utopia", crosscore: "crosscore", catshinobi: "catshinobi", bd2: "bd2", ivntight: "ivntight", arknights: "arknights", zonenova: "zonenova", stellasora: "stellasora", "stellasora-l2d": "stellasora-l2d", "stellasora-3d": "stellasora-3d", lostsword: "lostsword", dragontravelers: "dragontravelers", nikke: "nikke", alliancesages: "alliancesages", mcs18: "mcs18", pokerfate: "pokerfate", eroera: "eroera", mercenary: "mercenary" };
				const prefix = NEW_PREFIX[updaterGame] || "arkrecode";
				// new_ids sudah lengkap ("bd2/Alec/..." atau "bd2-char/..."),
				// jadi jangan ditambahi prefix lagi.
				markNew(res.new_ids ? added : added.map((n) => `${prefix}/${n}`));
			}
			// Muat ulang daftar model SETELAH apply sukses. Server kini
			// menyegarkan indeks sebelum menurunkan `running`, jadi refresh()
			// pertama sudah menerima daftar yang benar. Jangan lagi syaratkan
			// pada daftar id baru atau jumlah ekstraksi: banyak updater
			// melaporkan hasil dengan field lain, dan model tetap bisa
			// bertambah walau laporan hasilnya kosong.
			if (!res.error) {
				refresh()
					.then(syncNewFromServer)
					.then(() => renderLibrary())
					.catch(() => {});
			}
			toast?.(
				res.error
					? `Gagal: ${res.error}`
					: `Selesai: ${res.downloaded ?? 0} berkas diunduh` +
						(res.failed ? `, ${res.failed} gagal` : "") +
						(res.extracted ? ` · ${res.extracted} model baru` : "") +
						(res.already_had ? ` · ${res.already_had} sudah ada` : "") +
						(res.extracted ? "." : ". Muat ulang untuk melihatnya.")
			);
			btn.disabled = false;
			btn.classList.remove("is-checking");
			applyInFlight = false;
			stopLogPolling();
			updateLogStatus(
				res.error ? `Gagal: ${res.error}` : "Selesai.",
				res.error ? "fail" : "done"
			);
			return;
		}
		toast?.("Masih berjalan — cek lagi nanti.");
	} catch (err) {
		toast?.(`Gagal mengunduh: ${err.message}`);
		updateLogStatus(`Gagal: ${err.message}`, "fail");
	}
	applyInFlight = false;
	stopLogPolling();
	btn.disabled = false;
	btn.classList.remove("is-checking");
}

function renderLibrary() {
	syncPanes();
	if (browse.view === "models" && browse.game) renderModels();
	else renderGames(el.search.value);
}

function setActive(id) {
	// .gcard ikut disertakan: mode galeri memakai kelas itu, dan tanpa ini
	// kartu model yang sedang dimuat tidak pernah tersorot.
	for (const b of el.list.querySelectorAll(".model, .gcard"))
		b.classList.toggle("is-active", b.dataset.id === id);
}

async function refresh() {
	try {
		// Index ringan: field yang cuma dipakai saat model dibuka diambil
		// terpisah lewat ensureModelDetail(). Lihat src/models-payload.js.
		const res = await fetch("/api/models?lean=1");
		// /api/models memakai ETag + Cache-Control: no-cache. Kalau tidak ada
		// perubahan, server menjawab 304 tanpa body; res.json() saat itu
		// melempar "Unexpected end of JSON input" dan seluruh refresh gagal
		// diam-diam. 304 memang berarti daftar lama masih berlaku.
		if (res.status !== 304) {
			const data = await res.json();
			models = data.models || [];
		}
		// Ambil daftar "baru" dari server lebih dulu supaya badge muncul pada
		// render pertama, bukan setelah satu putaran lagi.
		await syncNewFromServer();
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
		// Cari kartu lewat data-id, bukan kelas .model: mode galeri memakai
		// .gcard, dan querySelector(".model") tidak akan menemukannya
		// sehingga bintang tidak ikut berubah sampai render berikutnya.
		const card = el.list.querySelector(`.model[data-id="${CSS.escape(id)}"], .gcard[data-id="${CSS.escape(id)}"]`);
		if (card) {
			const star = card.parentElement.querySelector(".model-fav");
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
el.playBtn.addEventListener("click", () => {
	// Video models drive their own <video> element; the Spine clock is unused.
	if (videoStageActive()) {
		const v = videoElement();
		if (v) {
			if (v.paused) v.play().catch(() => {});
			else v.pause();
		}
		return;
	}
	// 3D: jeda/lanjut AnimationMixer, jangan masuk setAnimation() Spine.
	if (is3D(current)) {
		const next = !state.playing;
		setPlaying(next);
		window.Model3DStage?.setPaused(!next);
		return;
	}
	setPlaying(!state.playing);
});
el.loopBtn.addEventListener("click", () => {
	state.loop = !state.loop;
	el.loopBtn.dataset.on = String(state.loop);
	// Video punya flag loop sendiri; tanpa ini tombol Loop tidak berpengaruh
	// pada model video (atribut `loop` di-set sekali saat elemen dibuat).
	if (videoStageActive()) {
		const v = videoElement();
		if (v) v.loop = state.loop;
		return;
	}
	// `spine` pada model Cubism ada, tetapi .state-nya tidak — tanpa ?.
	const track = spine?.state?.tracks?.[0];
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
	if (!spine?.skeleton) return;
	const anims = spine.skeleton.data.animations.map((a) => a.name);
	if (!anims.length) return;
	const i = anims.indexOf(animName);
	const next = anims[(i + dir + anims.length) % anims.length];
	el.animSelect.value = next;
	setAnimation(next, true);
	if (!state.playing) setPlaying(true);
}

el.animSelect.addEventListener("change", () => {
	// Model 3D memakai AnimationMixer three.js; clip-nya dimuat dari
	// anims/*.glb terpisah, jadi jangan pernah masuk setAnimation() Spine.
	if (is3D(current)) {
		const pick = el.animSelect.value;
		setPlaying(true);
		window.Model3DStage?.play(pick === "Bind pose" ? null : pick)
			.catch((err) => toast?.(`Clip 3D gagal: ${err.message}`));
		if (window.model3dStage) window.model3dStage.current = pick;
		return;
	}
	// Cubism motions are played by the Cubism motion manager, not by a Spine
	// AnimationState. Cubism models must never reach setAnimation() — they
	// have no spine.state, so it would throw.
	if (isLive2D(current)) {
		animName = el.animSelect.value;
		playLive2DMotion(spine, animName);
		live2dUpdateDuration();
		// A full clip now owns the stage; hold off the random/auto-advance timer.
		live2dAutoNextAt = performance.now() + 10000;
		return;
	}
	setAnimation(el.animSelect.value, true);
	renderTimeline();
});

// --- Live2D extras: living effects, random clip, auto-advance, touch --------
function l2dToggle(btn, get, set) {
	if (!btn) return;
	btn.dataset.on = String(get());
	btn.addEventListener("click", () => {
		set(!get());
		btn.dataset.on = String(get());
	});
}
l2dToggle(
	el.l2dLiveBtn,
	() => live2dLiveOn,
	(v) => {
		live2dLiveOn = v;
		live2dLiveApply(spine);
	},
);
l2dToggle(
	el.l2dRandomBtn,
	() => live2dRandomOn,
	(v) => {
		live2dRandomOn = v;
		live2dAutoNextAt = performance.now() + 2000;
	},
);
l2dToggle(
	el.l2dAutoBtn,
	() => live2dAutoNext,
	(v) => {
		live2dAutoNext = v;
		live2dAutoNextAt = performance.now() + 1500;
	},
);
l2dToggle(
	el.l2dTouchBtn,
	() => live2dTouchOn,
	(v) => {
		live2dTouchOn = v;
	},
);
el.skinSelect.addEventListener("change", () => {
	// Live2D Cubism has no Spine skins; the dropdown drives expressions.
	if (isLive2D(current)) {
		const v = el.skinSelect.value;
		// "(diam)" is the placeholder for the default/neutral expression.
		if (v && v !== "(diam)") setLive2DExpression(spine, v);
		else if (spine?.internalModel?.motionManager?.expressionManager) {
			try {
				spine.internalModel.motionManager.expressionManager.resetExpression();
			} catch {
				/* no expressions loaded */
			}
		}
		return;
	}
	setSkin(el.skinSelect.value);
});
el.variantSelect.addEventListener("change", () => {
	const opt = el.variantSelect.selectedOptions[0];
	switchVariant(opt?.dataset?.id);
});

// BD2 variant popup: the button toggles it, an item switches variant (and the
// popup closes), Esc or a click outside closes it. Capture phase on Esc so the
// global Esc handler (close dialog / leave fullscreen) doesn't also fire.
//
// pointerdown must not reach #canvas-wrap: that handler starts drag-to-pan and
// takes a pointer capture, which re-targets the following `click` to the canvas
// — the button then looks like it does nothing.
el.variantBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
el.variantPopup.addEventListener("pointerdown", (e) => e.stopPropagation());
// Tab segmented punya masalah yang sama: tanpa ini kliknya dicuri canvas.
el.variantTabs.addEventListener("pointerdown", (e) => e.stopPropagation());
el.variantTabs.addEventListener("click", (e) => e.stopPropagation());
el.variantBtn.addEventListener("click", (e) => {
	e.stopPropagation();
	setVariantPopup(!variantPopupOpen);
});
el.variantPopClose.addEventListener("click", () => setVariantPopup(false));
document.addEventListener(
	"pointerdown",
	(e) => {
		if (!variantPopupOpen) return;
		if (el.variantPopup.contains(e.target) || el.variantBtn.contains(e.target)) return;
		setVariantPopup(false);
	},
	true
);
document.addEventListener(
	"keydown",
	(e) => {
		if (e.key !== "Escape" || !variantPopupOpen) return;
		e.stopPropagation();
		setVariantPopup(false);
	},
	true
);
el.rateSelect.addEventListener("change", () => (state.rate = parseFloat(el.rateSelect.value)));

el.scrub.addEventListener("pointerdown", () => (state.scrubbing = true));
window.addEventListener("pointerup", () => (state.scrubbing = false));
el.scrub.addEventListener("input", () => {
	// Video: seek langsung ke elemen <video>. Dulu handler ini keluar lebih
	// awal karena `spine` null untuk model video, jadi scrub bar di panel
	// tidak melakukan apa pun — itu sebabnya kontrol bawaan browser
	// (controls=true) terasa perlu. Sekarang kontrol bawaan dimatikan, jadi
	// jalur ini yang harus bekerja.
	if (videoStageActive()) {
		const v = videoElement();
		if (!v || !Number.isFinite(v.duration) || v.duration <= 0) return;
		const t = (parseFloat(el.scrub.value) / 1000) * v.duration;
		v.currentTime = t;
		el.timeCur.textContent = t.toFixed(2) + "s";
		return;
	}
	if (!duration || !spine) return;
	state.trackTime = (parseFloat(el.scrub.value) / 1000) * duration;
	// Live2D: the motion manager has no trackTime, so seek by shifting the
	// playing entry's start time. Reading it back on the next frame confirms it.
	if (isLive2D(current)) {
		if (live2DSeekMotion(spine, state.trackTime)) {
			el.timeCur.textContent = state.trackTime.toFixed(2) + "s";
			return;
		}
	}
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
	// world membawa zoom/pan/flip. Flip mencerminkan satu sumbu, dan
	// mengabaikannya membuat hit-test benar di satu sisi model dan
	// tercermin di sisi lain.
	const wx = (sx - world.position.x) / (world.scale.x || 1);
	const wy = (sy - world.position.y) / (world.scale.y || 1);
	// spine sits inside stageRoot inside world; both are untransformed
	// relative to world except for world's own transform, so this is enough
	// for hit testing against the skeleton's own bounds. bonesGfx lives in
	// the SAME space as spine, so bone coordinates need no extra offset.
	const p = { x: wx, y: wy };
	if (spine) {
		p.x -= spine.x;
		p.y -= spine.y;
	}
	return p;
}

/** Kebalikan dari toStagePoint: titik stage/skeleton -> koordinat viewport. */
function fromStagePoint(x, y) {
	const r = el.canvasWrap.getBoundingClientRect();
	let px = x;
	let py = y;
	if (spine) {
		px += spine.x;
		py += spine.y;
	}
	return {
		x: r.left + px * (world.scale.x || 1) + world.position.x,
		y: r.top + py * (world.scale.y || 1) + world.position.y,
	};
}

// ── Interaksi CrossCore ────────────────────────────────────────────────
// Model CrossCore interaktif punya daftar aksi dengan kotak sentuh
// (areas) dalam koordinat model. Klik pada area menjalankan animasi
// yang sesuai. Mesin state-nya ada di src/interaction-core.js (port
// dari ArtHub), di sini hanya bagian renderer + input.
//
// Nonaktif secara default supaya tidak mengganggu alur klik yang sudah
// ada (pan, vertex, bounds, IK). Menyala hanya kalau model yang dimuat
// punya data interaksi.
const CCI = {
	on: false,
	catalog: null,        // {models: [...]} dari /api/interaction/crosscore
	byPrefab: new Map(),  // prefab -> {idle, actions}
	controller: null,
	lastEvent: null,
	// Bounding box model dalam koordinat stage, dipakai untuk memetakan
	// titik sentuh (koordinat area memakai ruang model, bukan piksel).
	bounds: null,
};

/** Muat katalog interaksi sekali saja (0,36 MB, di-cache browser). */
async function cciLoadCatalog() {
	if (CCI.catalog) return CCI.catalog;
	const res = await fetch("/api/interaction/crosscore");
	if (!res.ok) throw new Error(`katalog interaksi ${res.status}`);
	const data = await res.json();
	CCI.catalog = data;
	CCI.byPrefab = new Map();
	for (const m of data.models || []) {
		// idle default: aksi bernama "in", kalau tidak ada pakai aksi pertama
		const idleAction = (m.actions || []).find((a) => a.sName === "in");
		CCI.byPrefab.set(String(m.prefab || "").toLowerCase(), {
			id: m.id,
			name: m.name,
			title: m.title,
			idle: idleAction?.sName || null,
			actions: m.actions || [],
		});
	}
	return data;
}

/** Nama model saat ini -> data interaksi, atau null. */
function cciEntryFor(model) {
	if (!model || !CCI.byPrefab.size) return null;
	// id model di viewer: <game>/<folder>. Folder interaktif dibuat dari
	// nama prefab, jadi cocokkan lewat basis nama folder.
	const folder = String(model.id || "").split("/").pop().toLowerCase();
	if (CCI.byPrefab.has(folder)) return CCI.byPrefab.get(folder);
	// prefab bisa punya akhiran lain; coba pencocokan longgar sekali
	for (const [k, v] of CCI.byPrefab) {
		if (folder.startsWith(k) || k.startsWith(folder)) return v;
	}
	return null;
}

/** Hit-test titik stage terhadap area aksi. */
function cciHitAt(clientX, clientY) {
	if (!CCI.on || !CCI.controller) return null;
	const p = toStagePoint(clientX, clientY);
	// Area dinyatakan dalam ruang model dengan y menghadap ke atas,
	// sedangkan toStagePoint memberi koordinat y ke bawah -> balik.
	return CCI.controller.hit(p.x, -p.y);
}

/** Jalankan aksi pada indeks tertentu. */
function cciTrigger(index) {
	if (!CCI.on || !CCI.controller) return null;
	return CCI.controller.trigger(index, performance.now() / 1000);
}

/** Pasang/lepas interaksi ketika model berganti. */
async function cciAttach(model) {
	CCI.on = false;
	CCI.controller = null;
	CCI.lastEvent = null;
	try {
		await cciLoadCatalog();
	} catch {
		return;
	}
	const entry = cciEntryFor(model);
	if (!entry || !entry.actions.length) return;
	CCI.controller = new InteractionController({ actions: entry.actions, idle: entry.idle }, (ev) => {
		CCI.lastEvent = ev;
		cciApplyEvent(ev);
	});
	CCI.on = true;
}

/** Terapkan hasil aksi ke viewer (mainkan animasi). */
function cciApplyEvent(ev) {
	if (!ev || !spine) return;
	if (ev.kind === "action" || ev.kind === "guide" || ev.kind === "idle") {
		const name = ev.name || ev.kind === "idle" ? ev.name : null;
		if (!name) return;
		const names = current?.animations || [];
		if (!names.includes(name)) return;
		animName = name;
		if (el.animSelect) el.animSelect.value = name;
		try {
			spine.state.setAnimation(0, name, true);
			spine.state.timeScale = 1;
		} catch {
			/* animasi tidak cocok dengan runtime ini; abaikan */
		}
	}
}

// Vertex mesh: klik mesh untuk memilih, klik titik untuk memilih vertex,
// lalu tarik untuk memindahkannya.
el.canvasWrap.addEventListener(
	"pointerdown",
	(e) => {
		if (CCI.on && e.button === 0) {
			const hit = cciHitAt(e.clientX, e.clientY);
			if (hit) {
				cciTrigger(hit.index);
				return; // jangan lanjut ke pan/vertex
			}
		}
		if (!VTX.on || !spine || e.button !== 0) return;
		const p = toStagePoint(e.clientX, e.clientY);
		const sc = 1 / (state.zoom || 1);
		const r = VTX.hit * sc;

		// 1) titik pada mesh terpilih?
		if (VTX.att) {
			const pts = vtxWorldPoints(VTX.att, VTX.slot);
			if (pts) {
				let best = -1;
				let bd = Infinity;
				for (let i = 0; i < pts.length; i++) {
					const d = Math.hypot(p.x - pts[i].x, p.y - pts[i].y);
					if (d < bd) {
						bd = d;
						best = i;
					}
				}
				if (best >= 0 && bd <= r) {
					VTX.sel = best;
					VTX.dragging = true;
					VTX.start = p;
					vtxOriginal(VTX.att);
					el.canvasWrap.setPointerCapture?.(e.pointerId);
					vtxSyncUI();
					drawVtxOverlay();
					e.stopPropagation();
					e.preventDefault();
					return;
				}
			}
		}

		// 2) pilih mesh baru
		const hit = vtxPick(e.clientX, e.clientY);
		if (hit) {
			VTX.slot = hit.slot;
			VTX.att = hit.att;
			VTX.sel = -1;
			vtxOriginal(hit.att);
			vtxSyncUI();
			drawVtxOverlay();
			e.stopPropagation();
			e.preventDefault();
		}
	},
	true,
);

window.addEventListener("pointermove", (e) => {
	if (!VTX.dragging || !VTX.att || VTX.sel < 0) return;
	const p = toStagePoint(e.clientX, e.clientY);
	// Selisih world -> lokal slot.
	let lx = p.x - VTX.start.x;
	let ly = p.y - VTX.start.y;
	try {
		const v = { x: lx, y: ly };
		VTX.slot.bone.worldToLocal(v);
		const v0 = { x: 0, y: 0 };
		VTX.slot.bone.worldToLocal(v0);
		lx = v.x - v0.x;
		ly = v.y - v0.y;
	} catch {
		/* pakai selisih mentah */
	}
	vtxMove(VTX.att, VTX.sel, lx, ly);
	VTX.start = p; // geser bertahap, bukan absolut
	// Catat hasil untuk ekspor.
	const key = `${VTX.slot.data.name}/${VTX.att.name || ""}`;
	VTX.edits.set(key, Float32Array.from(VTX.att.vertices));
	try {
		spine.skeleton.updateWorldTransform();
	} catch {
		/* frame berikutnya */
	}
	drawVtxOverlay();
});

function vtxEndDrag() {
	if (!VTX.dragging) return;
	VTX.dragging = false;
	drawVtxOverlay();
}
window.addEventListener("pointerup", vtxEndDrag);
window.addEventListener("pointercancel", vtxEndDrag);

// Bounds attachment: klik untuk memilih, tarik sudut untuk mengubah ukuran,
// tarik tengah untuk memindahkan. Ditangkap lebih dulu daripada pan kanvas.
el.canvasWrap.addEventListener(
	"pointerdown",
	(e) => {
		if (!BOUNDS.on || !spine || e.button !== 0) return;
		const p = toStagePoint(e.clientX, e.clientY);
		const sc = 1 / (state.zoom || 1);
		const r = BOUNDS.hit * sc;

		// 1) Sudut kotak yang sedang dipilih -> mulai resize
		if (BOUNDS.att) {
			const pts = boundsCorners(BOUNDS.slot, BOUNDS.att);
			if (pts) {
				for (let i = 0; i < 4; i++) {
					if (Math.hypot(p.x - pts[i].x, p.y - pts[i].y) <= r) {
						BOUNDS.dragging = true;
						BOUNDS.grip = i;
						BOUNDS.start = p;
						const a = BOUNDS.att;
						BOUNDS.base = { x: a.x, y: a.y, width: a.width, height: a.height };
						el.canvasWrap.setPointerCapture?.(e.pointerId);
						e.stopPropagation();
						e.preventDefault();
						return;
					}
				}
				// 2) Tengah kotak -> pindahkan
				const c = {
					x: (pts[0].x + pts[1].x + pts[2].x + pts[3].x) / 4,
					y: (pts[0].y + pts[1].y + pts[2].y + pts[3].y) / 4,
				};
				if (Math.hypot(p.x - c.x, p.y - c.y) <= r * 1.4) {
					BOUNDS.dragging = true;
					BOUNDS.grip = "move";
					BOUNDS.start = p;
					const a = BOUNDS.att;
					BOUNDS.base = { x: a.x, y: a.y, width: a.width, height: a.height };
					el.canvasWrap.setPointerCapture?.(e.pointerId);
					e.stopPropagation();
					e.preventDefault();
					return;
				}
			}
		}

		// 3) Selain itu: pilih attachment di bawah kursor
		const hit = boundsPick(e.clientX, e.clientY);
		if (hit) {
			BOUNDS.slot = hit.slot;
			BOUNDS.att = hit.attachment;
			boundsSyncUI();
			drawBoundsOverlay();
			e.stopPropagation();
			e.preventDefault();
		}
	},
	true,
);

window.addEventListener("pointermove", (e) => {
	if (!BOUNDS.dragging || !BOUNDS.att || !BOUNDS.base) return;
	const p = toStagePoint(e.clientX, e.clientY);
	// Selisih kursor diubah ke satuan lokal slot (bone).
	const dx = p.x - BOUNDS.start.x;
	const dy = p.y - BOUNDS.start.y;
	let lx = dx;
	let ly = dy;
	try {
		const v = { x: dx, y: dy };
		// worldToLocal mengubah vektor world -> lokal; offset pangkal ikut
		// terpakai, jadi kurangi dulu supaya murni arah.
		BOUNDS.slot.bone.worldToLocal(v);
		const v0 = { x: 0, y: 0 };
		BOUNDS.slot.bone.worldToLocal(v0);
		lx = v.x - v0.x;
		ly = v.y - v0.y;
	} catch {
		/* pakai selisih mentah */
	}
	if (BOUNDS.grip === "move") {
		boundsApply({ x: BOUNDS.base.x + lx, y: BOUNDS.base.y + ly });
	} else {
		// Resize: sudut yang ditarik menentukan tanda. Lebar/tinggi minimal 1
		// supaya tidak pernah nol (region nol tidak bisa dipilih lagi).
		const sx = BOUNDS.grip === 0 || BOUNDS.grip === 3 ? -1 : 1;
		const sy = BOUNDS.grip === 0 || BOUNDS.grip === 1 ? -1 : 1;
		boundsApply({
			width: Math.max(1, BOUNDS.base.width + sx * lx * 2),
			height: Math.max(1, BOUNDS.base.height + sy * ly * 2),
		});
	}
});

function boundsEndDrag() {
	if (!BOUNDS.dragging) return;
	BOUNDS.dragging = false;
	BOUNDS.grip = null;
	BOUNDS.base = null;
	drawBoundsOverlay();
}
window.addEventListener("pointerup", boundsEndDrag);
window.addEventListener("pointercancel", boundsEndDrag);

// IK: klik tulang untuk memilih rantai, lalu geser pegangan di ujungnya.
// Ditangkap di fase capture supaya tidak ikut menggeser kamera (pan).
el.canvasWrap.addEventListener(
	"pointerdown",
	(e) => {
		if (!IK.on || !spine || e.button !== 0) return;
		const p = toStagePoint(e.clientX, e.clientY);
		const r = IK.hitRadius / (state.zoom || 1);
		// 1) pegangan yang sudah ada -> mulai geser
		if (IK.handle && Math.hypot(p.x - IK.handle.x, p.y - IK.handle.y) <= r) {
			IK.dragging = true;
			IK.target = { x: p.x, y: p.y };
			// Bekukan animasi selama menyeret. Tanpa ini tulang lain terus
			// bergerak oleh animasi dan ujung yang ditahan bergetar ~30 px,
			// karena rantai IK hanya memutar dua tulang, bukan seluruh badan.
			IK.wasPlaying = state.playing;
			if (state.playing) setPlaying(false);
			el.canvasWrap.setPointerCapture?.(e.pointerId);
			e.stopPropagation();
			e.preventDefault();
			drawIk();
			return;
		}
		// 2) tulang lain -> pilih sebagai ujung rantai baru
		const b = boneAt(p.x, p.y);
		if (b) {
			ikSelect(b);
			e.stopPropagation();
			e.preventDefault();
		}
	},
	true,
);

window.addEventListener("pointermove", (e) => {
	if (!IK.dragging) return;
	const p = toStagePoint(e.clientX, e.clientY);
	IK.target = { x: p.x, y: p.y };
});

function ikEndDrag() {
	if (!IK.dragging) return;
	IK.dragging = false;
	IK.target = null;
	pushBoneUndo();
	if (IK.wasPlaying) setPlaying(true);
	IK.wasPlaying = false;
	drawIk();
}
window.addEventListener("pointerup", ikEndDrag);
window.addEventListener("pointercancel", ikEndDrag);

// Bone editor: hover + klik-pilih + drag untuk memutar bone. Hanya aktif saat
// mode edit menyala, dan selalu mendahului pan kanvas supaya drag bone tidak
// ikut menggeser kamera.
el.canvasWrap.addEventListener("pointermove", (e) => {
	if (!BONES.on || !spine || BONES.dragging) return;
	const p = toStagePoint(e.clientX, e.clientY);
	const b = boneAt(p.x, p.y);
	if (b !== BONES.hover) {
		BONES.hover = b;
		el.canvasWrap.style.cursor = b ? "crosshair" : "";
		drawBones();
	}
});

el.canvasWrap.addEventListener(
	"pointerdown",
	(e) => {
		if (!BONES.on || !spine || e.button !== 0) return;
		const p = toStagePoint(e.clientX, e.clientY);
		const b = boneAt(p.x, p.y);
		if (!b) return;
		// Tangkap pointer supaya drag tetap jalan walau kursor keluar kanvas.
		BONES.selected = b;
		// Snapshot SEBELUM diubah: satu drag = satu langkah undo.
		pushBoneUndo();
		BONES.dragStart = { x: p.x, y: p.y };
		BONES.dragBase = {
			rotation: b.rotation,
			x: b.x,
			y: b.y,
			scaleX: b.scaleX,
			scaleY: b.scaleY,
		};
		BONES.dragging = true;
		e.stopPropagation();
		e.preventDefault();
		el.canvasWrap.setPointerCapture?.(e.pointerId);
		updateBoneUI();
		drawBones();
	},
	true, // capture: menang atas handler pan di fase bubble
);

window.addEventListener("pointermove", (e) => {
	if (!BONES.dragging || !BONES.selected || !spine) return;
	const p = toStagePoint(e.clientX, e.clientY);
	const st = BONES.dragStart;
	if (BONES.mode === "move" && st) {
		moveBoneTo(BONES.selected, p.x - st.x, p.y - st.y);
	} else if (BONES.mode === "scale") {
		scaleBoneTo(BONES.selected, p.x, p.y);
	} else {
		aimBoneAt(BONES.selected, p.x, p.y);
	}
	spine.skeleton.updateWorldTransform();
	drawBones();
	updateBoneUI();
});

function boneEndDrag() {
	if (!BONES.dragging) return;
	BONES.dragging = false;
	BONES.dragStart = null;
	BONES.dragBase = null;
	// Simpan keadaan SESUDAH aksi, supaya redo bisa kembali ke sini.
	pushBoneUndo();
	updateBoneUI();
}
window.addEventListener("pointerup", boneEndDrag);
window.addEventListener("pointercancel", boneEndDrag);

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
	// Live2D "Sentuh": a TAP (not a drag/pan) on the model triggers a touch
	// motion for the tapped height. Track press/release so panning never fires it.
	if (isLive2D(current) && live2dTouchOn && e.button === 0) {
		const sx = e.clientX;
		const sy = e.clientY;
		const t0 = performance.now();
		// `up` dulu hanya dilepas dari dalam pointerup. pointercancel (gestur
		// browser yang mengambil alih, ganti aplikasi, scroll) membiarkannya
		// menumpuk, dan tiap sisa listener itu tetap menjalankan live2dTouchAt
		// dengan t0/sx/sy lawas — muncul sentuhan hantu dari tekanan sebelumnya.
		const cleanup = () => {
			el.canvasWrap.removeEventListener("pointerup", up);
			el.canvasWrap.removeEventListener("pointercancel", cleanup);
		};
		const up = (ue) => {
			cleanup();
			if (ue.button !== 0) return;
			if (performance.now() - t0 > 450) return; // held = drag, not tap
			if (Math.hypot(ue.clientX - sx, ue.clientY - sy) > 12) return; // moved = pan
			live2dTouchAt(ue);
		};
		el.canvasWrap.addEventListener("pointerup", up);
		el.canvasWrap.addEventListener("pointercancel", cleanup);
		return;
	}
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

// Tooltip nama slot: nyala/mati, plus pelacakan kursor.
function setSlotTip(on) {
	SLOTTIP.enabled = !!on;
	el.slotTipBtn?.setAttribute("aria-pressed", String(SLOTTIP.enabled));
	if (el.slotTipBtn) el.slotTipBtn.dataset.on = String(SLOTTIP.enabled);
	if (!SLOTTIP.enabled) hideSlotTip();
}
el.slotTipBtn?.addEventListener("click", () => setSlotTip(!SLOTTIP.enabled));

// Kursor bergerak -> jadwalkan pembaruan (dibatasi satu per frame, karena
// hit-test menyapu seluruh slot dan itu terlalu mahal untuk tiap event).
el.canvasWrap?.addEventListener("pointermove", (e) => {
	if (!SLOTTIP.enabled) return;
	SLOTTIP.clientX = e.clientX;
	SLOTTIP.clientY = e.clientY;
	scheduleSlotTip();
});
el.canvasWrap?.addEventListener("pointerleave", () => hideSlotTip());

// Klik slot di kanvas -> fokus ke barisnya di inspector. Hanya saat tooltip
// menyala, supaya klik untuk pan/zoom tidak tiba-tiba membuka panel.
el.canvasWrap?.addEventListener(
	"click",
	(e) => {
		if (!SLOTTIP.enabled || !spine?.skeleton) return;
		// Jangan bentrok dengan mode edit tulang: di sana klik berarti pilih bone.
		if (BONES.on) return;
		if (e.button !== 0) return;
		const hit = slotAtClient(e.clientX, e.clientY);
		if (!hit) return;
		const idx = spine.skeleton.slots.indexOf(hit.slot);
		if (idx >= 0) focusSlot(idx);
	},
	false,
);

// Bone editor: toggle, reset, ekspor, impor.
el.boneEditBtn?.addEventListener("click", () => setBoneEdit(!BONES.on));
el.bonePanel?.querySelector("#bone-reset")?.addEventListener("click", resetBonePose);
el.bonePanel?.querySelector("#bone-export")?.addEventListener("click", exportBonePose);
const boneImportInput = el.bonePanel?.querySelector("#bone-import-file");
boneImportInput?.addEventListener("change", () => {
	const f = boneImportInput.files?.[0];
	if (f) importBonePose(f);
	boneImportInput.value = "";
});

// Render pixel density ("Tajam"). Higher = sharper on-screen render, at the
// cost of GPU fill rate. The PNG export is unaffected (it always targets the
// atlas' native resolution), so this only tunes what you see live.
const DENSITY_KEY = "spine-stage:density";
el.densitySelect?.addEventListener("change", () => {
	state.density = el.densitySelect.value;
	try { localStorage.setItem(DENSITY_KEY, state.density); } catch { /* private mode */ }
	resizeRenderer();
	applyTransform();
});

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

/* --- gambar latar (backdrop) -------------------------------------------
 * Berbeda dengan #bg-select yang cuma mengganti WARNA polos untuk diagnostik
 * tepi/PMA, ini gambar suasana penuh di belakang model. Kanvas Pixi memakai
 * backgroundAlpha 0, jadi lapisan CSS di z-index 0 langsung terlihat tanpa
 * menyentuh rendering skeleton. Tombolnya murni on/off; scene terakhir tetap
 * diingat supaya dinyalakan lagi bisa langsung balik ke suasana sebelumnya.
 */
const BACKDROP_SCENES = ["aurora", "studio", "night"];
const BACKDROP_LABEL = { aurora: "Aurora", studio: "Studio", night: "Malam" };

function setBackdrop(on, scene = state.backdrop, { persist = true } = {}) {
	const picked = BACKDROP_SCENES.includes(scene) ? scene : "aurora";
	state.backdropOn = !!on;
	state.backdrop = picked;
	el.stageBackdrop.dataset.scene = picked;
	el.stageBackdrop.hidden = !on;
	el.backdropSelect.value = picked;
	el.backdropBtn.dataset.on = String(!!on);
	el.backdropBtn.setAttribute("aria-label", on ? "Matikan gambar latar" : "Nyalakan gambar latar");
	el.backdropBtn.title = `${on ? "Matikan" : "Nyalakan"} gambar latar (Shift+L)`;
	if (!persist) return;
	try {
		localStorage.setItem("stageBackdrop", JSON.stringify({ on: !!on, scene: picked }));
	} catch {
		/* private mode — preference just won't stick */
	}
	// Shortcut Shift+L tidak memicu event "click", jadi tulis ?v= di sini
	// supaya tautan yang dibagikan ikut membawa suasana latar.
	schedulePermalinkWrite?.();
}

function toggleBackdrop() {
	setBackdrop(!state.backdropOn);
	toast(state.backdropOn ? `Backdrop: ${BACKDROP_LABEL[state.backdrop]}` : "Backdrop: mati");
}

el.backdropBtn.addEventListener("click", toggleBackdrop);
el.backdropSelect.addEventListener("change", () => {
	setBackdrop(true, el.backdropSelect.value);
	toast(`Backdrop: ${BACKDROP_LABEL[el.backdropSelect.value] || el.backdropSelect.value}`);
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
	// The dropdown shows what the USER picked (Auto stays Auto); the title and
	// data-modes describe what that pick actually resolves to.
	el.pmaSelect.value = pmaMode;
	const mode = resolvedMode();
	const effective = pmaActive();
	el.pmaSelect.dataset.effective = String(effective);
	el.pmaSelect.dataset.mode = mode;
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
	if (mode === PMA_MODES.upload) {
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
		// Kursor di atas panel B -> yang berubah kamera B, bukan kamera A.
		// Dua kanvas ada justru supaya keduanya bisa di-zoom sendiri-sendiri.
		const paneB = document.getElementById("ab-pane-b");
		if (AB.on && AB.second && paneB && !paneB.hidden && AB.layout === "split") {
			const rb = paneB.getBoundingClientRect();
			const inB =
				e.clientX >= rb.left && e.clientX <= rb.right &&
				e.clientY >= rb.top && e.clientY <= rb.bottom;
			if (inB) {
				const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
				camB.zoom = Math.min(12, Math.max(0.05, camB.zoom * f));
				applyTransform();
				schedulePermalinkWrite?.();
				return;
			}
		}
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
	// Mode A/B: seret posisi model B. Tombol KANAN (atau Alt) dipakai supaya
	// geser kamera yang sudah ada tidak berubah — kalau tidak, pengguna tidak
	// bisa lagi memindahkan kamera saat dua model tampil.
	if (AB.on && AB.second && e.button === 2) {
		e.preventDefault();
		abDrag = { x: e.clientX, y: e.clientY };
		el.canvasWrap.classList.add("is-dragging");
		try {
			el.canvasWrap.setPointerCapture(e.pointerId);
		} catch {
			/* pointer sudah hilang */
		}
		return;
	}
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
		dragPane = paneUnder(e.clientX, e.clientY);
		el.canvasWrap.classList.add("is-dragging");
	} else if (pointers.size === 2) {
		// second finger down: stop panning, start pinching
		dragging = null;
		pinchPane = paneUnder(e.clientX, e.clientY);
		const r = el.canvasWrap.getBoundingClientRect();
		const c = pinchCenter();
		pinch = { dist: pinchDist(), cx: c.x - r.left, cy: c.y - r.top };
	}
});

el.canvasWrap.addEventListener("pointermove", (e) => {
	// Seretan A/B harus diperiksa SEBELUM pemeriksaan pointers: handler
	// pointerdown A/B return sebelum mencatat pointerId ke map (tombol kanan
	// sengaja tidak ikut gesture pan/pinch), jadi `pointers.has()` selalu
	// false dan gerakan mouse diabaikan — offset tidak pernah berubah.
	if (abDrag) {
		AB.offset.x += e.clientX - abDrag.x;
		AB.offset.y += e.clientY - abDrag.y;
		abDrag = { x: e.clientX, y: e.clientY };
		applyTransform();
		return;
	}
	if (!pointers.has(e.pointerId)) return;
	pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

	if (pointers.size >= 2 && pinch) {
		const dist = pinchDist();
		if (pinch.dist > 0 && dist > 0) {
			const f = dist / pinch.dist;
			if (pinchPane === "B" || pinchPane === "BOTH") {
				camB.zoom = Math.min(12, Math.max(0.05, camB.zoom * f));
				applyTransform();
			} else {
				zoomBy(f, pinch.cx, pinch.cy);
			}
			pinch.dist = dist;
		}
		return;
	}

	if (!dragging) return;
	const dx = e.clientX - dragging.x;
	const dy = e.clientY - dragging.y;
	const pane = dragPane || "A";
	// Geser kamera panel yang diseret, bukan selalu kamera A. Dulu seretan
	// di atas panel B tetap menggerakkan model A, jadi model B sama sekali
	// tidak bisa dipindah dengan drag — yang jalan cuma zoom (roda), karena
	// itu memang sudah diarahkan per panel.
	if (pane === "B" || pane === "BOTH") {
		camB.panX += dx;
		camB.panY += dy;
	}
	if (pane === "A" || pane === "BOTH") {
		state.panX += dx;
		state.panY += dy;
	}
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
		dragPane = null;
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
	// aria-hidden saja TIDAK mengeluarkan kontrol dari tab order: saat
	// sidebar disembunyikan pakai transform, 195 tombol/kartu tetap bisa
	// difokus keyboard (dan cincin fokusnya tergambar di luar layar).
	// `inert` mematikan keduanya sekaligus.
	if (el.sidebar) el.sidebar.inert = hidden;
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

/* Fullscreen toolbar reveal: the bar is fully hidden (max-height 0). A mousemove
   in the bottom zone (or onto the bar itself) adds .fs-peek to slide it up; a
   move back into the stage removes it. Keeps the Chrome-like "move to the edge"
   gesture while showing no chrome at rest. */
function fsPointerZone(ev) {
	if (!fsEl()) return;
	const t = document.querySelector(".transport");
	if (!t) return;
	const zone = Math.min(110, window.innerHeight * 0.2);
	const inZone = ev.clientY >= window.innerHeight - zone;
	// Keep it open while the pointer is over the (now tall) bar itself, so
	// clicking a control does not yank the bar away mid-interaction.
	const overBar = t.getBoundingClientRect().height > 4 && ev.target && t.contains(ev.target);
	t.classList.toggle("fs-peek", inZone || overBar);
}

function syncFullscreenUI() {
	const on = !!fsEl();
	if (el.fullscreenBtn) {
		el.fullscreenBtn.dataset.on = String(on);
		const label = on ? "Keluar layar penuh" : "Layar penuh";
		el.fullscreenBtn.setAttribute("aria-label", label);
		el.fullscreenBtn.setAttribute("title", `${label} (F)`);
	}
	// Show the floating exit button only while fullscreen.
	if (el.fsExit) el.fsExit.hidden = !on;
	// Drop the reveal state when leaving fullscreen, or the bar stays slid up.
	if (!on) document.querySelector(".transport")?.classList.remove("fs-peek");
	// The stage just changed size; let the model settle into the new frame.
	// Re-fit twice: the grid/flex reflow (topbar + sidebar removed) is not always
	// reflected in the very next frame, so a single fit can measure the old box
	// and leave the model off-centre.
	clearTimeout(fsFitTimer);
	fsFitTimer = setTimeout(() => {
		fsFitTimer = 0;
		resizeRenderer();
		if (spine) fitModel();
		setTimeout(() => {
			resizeRenderer();
			if (spine) fitModel();
		}, 220);
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
	el.fsExit?.addEventListener("click", exitFullscreen);
	// Reveal/hide the toolbar as the pointer moves toward the bottom edge.
	window.addEventListener("mousemove", fsPointerZone, { passive: true });
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
	// Model Cubism tidak punya .skeleton; dialog export memanggil ini untuk
	// semua tipe model.
	if (!sp?.skeleton) return 0;
	const scales = [];
	for (const slot of sp.skeleton.slots) {
		const att = slotAttachment(slot);
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
	if (!sp?.skeleton) return { x: 0, y: 0, w: 512, h: 512 };
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
	// three.js tidak punya jalur ekstraksi frame-by-frame PIXI; arahkan ke
	// tombol PNG yang menangkap kanvas WebGL langsung.
	if (is3D(current)) {
		toast("Ekspor video belum didukung untuk model 3D — pakai tombol PNG.");
		return;
	}
	// CG / illust stills are not animated, so the frame-by-frame exporter is
	// meaningless — just save the PNG itself.
	if (current && current.format === "image") {
		const a = document.createElement("a");
		a.href = current.imageFile;
		a.download = ((current.name || "cg").replace(/[^\w.-]+/g, "_") || "cg") + ".png";
		document.body.appendChild(a);
		a.click();
		a.remove();
		toast("CG diunduh.");
		return;
	}
	if (!spine) {
		toast("Pilih model dulu sebelum mengekspor.");
		return;
	}
	// Ekspor frame-by-frame membutuhkan skeleton Spine sungguhan. Pada model
	// Cubism, `spine` ada tetapi spine.skeleton dan spine.state tidak ada,
	// sehingga modelBounds() melempar SEBELUM blok try: status busy sudah
	// terpasang, ticker sudah berhenti, dan tombol tutup menolak (EXPORT_STATE
	// masih busy) — dialog terkunci sampai reload. Inilah satu-satunya
	// unhandled promise rejection yang tercatat di seluruh audit frontend.
	if (!spine?.skeleton) {
		toast("Live wallpaper hanya bisa diekspor dari model Spine.");
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

	// Di-deklarasikan di LUAR try: catch/finally tidak bisa melihat binding
	// yang dibuat di dalam blok try, sedangkan keduanya memakainya (finally
	// bahkan akan melempar ReferenceError kalau tidak — dan ReferenceError di
	// finally membatalkan pengembalian status busy/ticker-nya sendiri).
	let ok = false;
	let holder = null;
	let rt = null;
	let wasPlaying = false;
	let wasTrackTime = 0;
	// Ikut di-deklarasikan di luar try supaya blok catch bisa membatalkan
	// job-nya; frame yang sudah terlanjur terunggah ditinggalkan begitu saja
	// kalau ekspor gagal (dulu hanya dibersihkan sweeper 2 jam kemudian).
	let job = "";
	try {
		EXPORT_STATE.busy = true;
		EXPORT_STATE.cancel = false;
		el.exportRun.disabled = true;
		el.exportRun.textContent = "Mengekspor…";
		el.exportProgress.hidden = false;
		el.exportResult.hidden = true;
		setExportProgress(0, frames);

		// Freeze the live view so the user's playback state can't interfere and
		// we can restore it exactly when we're done.
	 wasPlaying = state.playing;
	 wasTrackTime = spine.state?.tracks?.[0]?.trackTime ?? 0;
		setPlaying(false);

		// Stop the render ticker for the duration. Every await below yields to
		// the event loop, which otherwise lets the ticker redraw the whole live
		// stage between frames — pure waste, since we're rendering into our own
		// RenderTexture, and it competes for the same GPU/CPU.
		app.ticker.stop();

		job = exportJobId();
		const bounds = modelBounds(spine);
		const outH = Math.max(2, Math.round(effHeight / 2) * 2);
		const outW = Math.max(2, Math.round((bounds.w / Math.max(bounds.h, 1)) * outH / 2) * 2);

	 holder = new Container();
		const snapshot = new Container();
		holder.addChild(snapshot);

		// Render into a RenderTexture sized to the OUTPUT, not to the model's
		// native bounds. Extracting a full-size frame and downscaling costs a
		// glReadPixels + CPU flip over the whole source (measured: ~2.7s/frame on
		// a 2242x2239 model); rendering at target size is ~58ms/frame.
	 rt = RenderTexture.create({ width: outW, height: outH });
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

			// Unggah bingkai. Server memberi tier rate-limit tersendiri untuk
			// /api/export/frame, tapi kalau toh kena 429 (mis. beberapa tab
			// mengekspor bersamaan) jangan langsung gagal — hormati Retry-After
			// lalu coba lagi.
			const frameUrl = `/api/export/frame?job=${job}&i=${i}&n=${frames}`;
			let r;
			for (let attempt = 0; ; attempt++) {
				r = await fetch(frameUrl, { method: "POST", headers: { "Content-Type": mime }, body: blob });
				if (r.status !== 429 || attempt >= 5) break;
				const wait = Number(r.headers.get("Retry-After") || 2) * 1000;
				await new Promise((r2) => setTimeout(r2, Math.min(wait, 10_000) + 200));
			}
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
		if (job) {
			fetch("/api/export/cancel", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ job }),
			}).catch(() => {});
		}
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
		const track = spine?.state?.tracks?.[0];
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
	// Kanvas three.js punya preserveDrawingBuffer, jadi cukup toDataURL().
	// Tidak boleh masuk jalur app.renderer.extract() karena yang terekam di
	// sana adalah kanvas PIXI yang sedang disembunyikan.
	if (is3D(current)) {
		const url = window.Model3DStage?.capture();
		if (!url) {
			toast("Model 3D belum siap diekspor.");
			return;
		}
		const a = document.createElement("a");
		a.href = url;
		a.download = ((current.name || "model3d").replace(/[^\w.-]+/g, "_") || "model3d") + ".png";
		document.body.appendChild(a);
		a.click();
		a.remove();
		toast("Tangkapan 3D diunduh.");
		return;
	}
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

/* Debounce pencarian.
 *
 * Tanpa jeda, SETIAP ketikan menyaring 38.515 model: filter per game, filter
 * roots, sort dengan isNewModel() di tiap pembanding, plus sampai tiga kali
 * gameBuckets(). Terukur 9-28 ms per ketikan (bisa lebih di katalog yang
 * lebih besar) — di ponsel itu satu frame hilang untuk tiap huruf. */
let searchTimer = 0;
el.search.addEventListener("input", () => {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(() => {
		// Searching resets to page 1 — staying on page 7 of a 2-page result is a
		// dead end the user has to notice and recover from.
		browse.page = 1;
		if (browse.view === "models" && browse.game) renderModels();
		else renderGames(el.search.value);
	}, 140);
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

/* Bentuk tampilan daftar model: daftar (baris) atau galeri (petak). */
const LAYOUT_KEY = "spine-stage:layout";

function setLayout(layout) {
	const next = layout === "grid" ? "grid" : "list";
	if (browse.layout === next) return;
	browse.layout = next;
	// Nomor halaman menunjuk isi yang berbeda antar layout (120 vs 60 per
	// halaman), jadi kembali ke halaman 1 daripada melompat ke posisi acak.
	browse.page = 1;
	try {
		localStorage.setItem(LAYOUT_KEY, next);
	} catch {
		/* private mode */
	}
	syncLayoutButtons();
	// Saat sedang di daftar game wadah model tersembunyi: jangan render.
	// Kalau dipaksa, 40 ribu model masuk DOM tanpa terlihat — lambat dan
	// boros, padahal renderModels() akan dipanggil lagi saat game dibuka.
	if (browse.view === "models" && browse.game) renderModels();
}

function syncLayoutButtons() {
	const grid = browse.layout === "grid";
	el.viewGridBtn?.classList.toggle("is-on", grid);
	el.viewGridBtn?.setAttribute("aria-pressed", String(grid));
	el.viewListBtn?.classList.toggle("is-on", !grid);
	el.viewListBtn?.setAttribute("aria-pressed", String(!grid));
}

el.viewListBtn?.addEventListener("click", () => setLayout("list"));
el.viewGridBtn?.addEventListener("click", () => setLayout("grid"));

// Pulihkan pilihan terakhir. Dibaca sekali saat mulai, sebelum render
// pertama, supaya daftar tidak sempat tampil dalam bentuk yang salah.
try {
	const saved = localStorage.getItem(LAYOUT_KEY);
	// Default sekarang grid; yang perlu dipulihkan tinggal preferensi "list".
	if (saved === "list") browse.layout = "list";
} catch {
	/* private mode */
}
syncLayoutButtons();

/* --- Filter CZN: tab Combatants/Partner + tombol ikon ------------------- */
el.cznFilters?.addEventListener("click", (e) => {
	const icon = e.target.closest?.(".czn-icon");
	if (icon) {
		const key = icon.dataset.kind === "ego" ? "cznEgo"
			: icon.dataset.kind === "job" ? "cznJob" : "cznRarity";
		const v = icon.dataset.value;
		// Klik ikon yang sama lagi = matikan filter itu.
		browse[key] = browse[key] === v ? "" : v;
		browse.page = 1;
		renderModels();
		return;
	}
	const tab = e.target.closest?.(".czn-tab");
	if (!tab) return;
	browse.cznGroup = tab.dataset.group || "all";
	browse.page = 1;
	renderModels();
});
el.cznReset?.addEventListener("click", () => {
	resetCznFilters();
	renderModels();
});

/** Tutup dialog yang sedang terbuka. true = ada yang ditutup. */
function closeTopmostModal() {
	// Menu Alat adalah lapisan paling atas secara visual, jadi ditutup dulu
	// sebelum modal mana pun — Escape terasa seperti "tutup yang terdekat".
	const toolsPop = document.getElementById("tools-pop");
	const toolsBtn = document.getElementById("tools-btn");
	if (toolsPop && !toolsPop.hidden) {
		setToolsOpen(false);
		toolsBtn?.focus();
		return true;
	}
	if (el.cardsModal && !el.cardsModal.hidden) {
		closeCards();
		return true;
	}
	if (el.exportModal && !el.exportModal.hidden) {
		closeExport();
		return true;
	}
	const link = document.getElementById("link-modal");
	if (link && !link.hidden) {
		document.getElementById("link-close")?.click();
		return true;
	}
	const health = document.getElementById("updater-health-modal");
	if (health && !health.hidden) {
		closeHealth();
		return true;
	}
	const log = document.getElementById("update-log-modal");
	if (log && !log.hidden) {
		document.getElementById("update-log-close")?.click();
		return true;
	}
	return false;
}

window.addEventListener("keydown", (e) => {
	if (e.target instanceof HTMLElement && e.target.matches("input, select, textarea")) return;
	// Angka 1-9 lompat ke varian ke-N. Kalau model tidak ber-family, jangan
	// rebut tombolnya supaya shortcut/browser lain tetap bekerja.
	if (/^[1-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey &&
		currentVariantIds().length) {
		e.preventDefault();
		goToVariant(Number(e.key) - 1);
		return;
	}
	switch (e.key) {
		case "[":
			if (currentVariantIds().length) {
				e.preventDefault();
				goToVariant(currentVariantIds().indexOf(current.id) - 1);
			}
			break;
		case "]":
			if (currentVariantIds().length) {
				e.preventDefault();
				goToVariant(currentVariantIds().indexOf(current.id) + 1);
			}
			break;
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
		case "x":
		case "X":
			// Ganti bentuk tampilan pustaka: daftar <-> galeri. Dulu ini
			// memakai "v", duplikat dengan case editor vertex di bawah, dan
			// aturan pertama yang menang — jadi vertex tak pernah tercapai.
			// Sesuaikan README: X = layout, V/U/J = vertex/bounds/IK.
			e.preventDefault();
			setLayout(browse.layout === "grid" ? "list" : "grid");
			break;
		case "l":
		case "L":
			// L = ganti WARNA latar (diagnostik tepi/PMA), Shift+L = on/off
			// GAMBAR latar. Keduanya sengaja berpasangan di tombol yang berdekatan.
			if (e.shiftKey) toggleBackdrop();
			else el.bgBtn.click();
			break;
		case "f":
		case "F":
			e.preventDefault();
			toggleFullscreen();
			break;
		case "e":
		case "E":
			e.preventDefault();
			// E = export, Shift+E = edit tulang (sesuai README). Dulu ini dua
			// case terpisah dengan kunci sama, jadi yang kedua tak pernah jalan.
			if (e.shiftKey) el.boneEditBtn?.click();
			else el.exportBtn?.click();
			break;
		case "z":
		case "Z":
			// Undo/redo pose tulang. Hanya saat editor tulang menyala, supaya
			// tidak merebut Ctrl+Z browser di tempat lain.
			if ((e.ctrlKey || e.metaKey) && BONES.on) {
				e.preventDefault();
				if (e.shiftKey) boneRedo();
				else boneUndo();
			}
			break;
		case "v":
		case "V":
			e.preventDefault();
			setVtxMode(!VTX.on);
			break;
		case "u":
		case "U":
			e.preventDefault();
			setBoundsMode(!BOUNDS.on);
			break;
		case "j":
		case "J":
			// IK: pilih tulang lalu geser ujungnya.
			e.preventDefault();
			setIkMode(!IK.on);
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
		case "k":
		case "K":
			// Tooltip tombol Kartu sudah lama menjanjikan "K", tapi case-nya
			// tidak pernah ada. Jangan memaksa buka kalau tombolnya tersembunyi
			// (model bukan CZN / belum punya kartu).
			e.preventDefault();
			if (el.cardsBtn && !el.cardsBtn.hidden) el.cardsBtn.click();
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
		case "y":
		case "Y":
			// Toggle nama slot. Dulu memakai "t", duplikat dengan timeline,
			// sehingga shortcut ini tidak pernah aktif. README: Y = nama slot.
			e.preventDefault();
			el.slotTipBtn?.click();
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
			// Tiga dialog memakai judul tombol "Tutup (Esc)", jadi Escape harus
			// benar-benar menutupnya — dan JANGAN jatuh ke cabang "keluar dari
			// daftar model" di belakang dialog yang masih terbuka (dulu: Esc pada
			// dialog tautan/log tidak menutup apa pun, malah pustaka pindah
			// tampilan di belakangnya).
			if (closeTopmostModal()) {
				e.preventDefault();
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
		destroyCurrent();
		current = null;
		animName = null;
		duration = 0;
		el.empty.hidden = false;
		el.hud.hidden = true;
		el.delBtn.hidden = true;
		el.gridLink.hidden = true;
		$("#title-model").textContent = "—";
		document.title = "Spine Stage — Penampil Skeleton 2D";
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
			gameDefaultMode,
			source: pmaSource(),
			active: pmaActive(),
			alphaMode: currentAlphaMode(),
		};
	},
	// Mode A/B (dua model, satu jam) — diekspos supaya uji dan konsol bisa
	// memastikan keadaannya tanpa menebak dari DOM.
	get ab() {
		return {
			on: AB.on,
			second: AB.second,
			anim: { ...AB.anim },
			dur: { ...AB.dur },
			layout: AB.layout,
			onion: AB.onion,
			offset: { ...AB.offset },
			lock: AB.lock,
			camB: { ...camB },
			appB: !!appB,
			ghosts: AB.ghosts,
			model: { A: AB.model.A, B: AB.model.B },
		};
	},
	abStart,
	abTeardown,
	get stageRoot() {
		return stageRoot;
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
	resizeRenderer();
	applyTransform();
});
ro.observe(el.canvasWrap);

/* ------------------------------------------------------------------ *
 * Permalink — encode the current view into the URL, restore it on load
 *
 * The URL is the single source of truth for "a shared view": model, clip,
 * skin/variant, the whole camera (zoom/pan/flip), playback rate, the toggles
 * (bone/grid/FPS/part, timeline open, inspector tab, sidebar), the backdrop
 * and the clock position. Writing it is debounced so dragging the model does
 * not spam history.replaceState; reading it never throws on a mangled query.
 *
 * The playhead is honest about intent: if playback was paused (or scrubbed)
 * the link reopens paused at that instant, otherwise it reopens playing.
 * ------------------------------------------------------------------ */

/** Base64url of a JSON payload — never throws, returns "" on bad input. */
function b64urlEncode(str) {
	try {
		return btoa(unescape(encodeURIComponent(str)))
			.replace(/\+/g, "-")
			.replace(/\//g, "_")
			.replace(/=+$/, "");
	} catch {
		return "";
	}
}
function b64urlDecode(str) {
	try {
		const p = String(str).replace(/-/g, "+").replace(/_/g, "/");
		return decodeURIComponent(escape(atob(p + "===".slice((p.length + 3) % 4))));
	} catch {
		return null;
	}
}

const round2 = (n) => Math.round((Number(n) || 0) * 100) / 100;

/** Snapshot of everything shareable in the current view. */
function permalinkState() {
	const s = {
		v: 1,
		g: browse.game || undefined,
		m: current?.id || undefined,
	};
	if (current) {
		if (animName) s.a = animName;
		if (el.skinSelect?.value) s.k = el.skinSelect.value;
		// Variant options carry the model id on dataset.id (their value is the
		// human label), so that is what travels in the link.
		const vopt = el.variantSelect?.selectedOptions?.[0];
		if (vopt?.dataset?.id) s.va = vopt.dataset.id;
	}
	if (state.rate !== 1) s.r = state.rate;
	if (!state.playing) s.p = 0;
	if (state.trackTime > 0.001) s.t = round2(state.trackTime);
	if (state.flip) s.f = 1;
	if (state.showBones) s.b = 1;
	if (!state.showGrid) s.gr = 0;
	if (fps.on) s.fps = 1;
	if (parts.on) s.pt = 1;
	if (state.bg !== "dark") s.bg = state.bg;
	// Gambar latar: cukup simpan scene-nya; tidak ada kunci = mati.
	if (state.backdropOn) s.bk = state.backdrop;
	if (!el.timeline?.hidden) s.tl = 1;
	if (!el.inspector?.hidden) s.insp = insp.tab;
	if (document.querySelector(".layout")?.classList.contains("sidebar-hidden")) s.sb = 0;
	// Mode A/B: model B, tata letak, onion skin, dan geserannya. Offset
	// ikut tersimpan supaya hasil penyejajaran bisa dibagikan, bukan cuma
	// terlihat di layar sendiri.
	if (AB.on && AB.model.B) {
		s.ab = AB.model.B.id;
		if (AB.layout !== "split") s.abl = AB.layout;
		if (AB.onion) s.abo = AB.onion;
		if (AB.lock) s.abk = 1;
		if (Math.abs(camB.zoom - 1) > 1e-4) s.cbz = round2(camB.zoom);
		if (camB.panX || camB.panY) {
			s.cbx = round2(camB.panX);
			s.cby = round2(camB.panY);
		}
		if (AB.offset.x || AB.offset.y) {
			s.abx = round2(AB.offset.x);
			s.aby = round2(AB.offset.y);
		}
	}
	// Skip zoom/pan when the camera is at its untouched defaults — the restore
	// side treats a missing pair as "run fitModel()".
	if (Math.abs(state.zoom - 1) > 1e-4 || Math.abs(state.panX) > 0.5 || Math.abs(state.panY) > 0.5) {
		s.z = round2(state.zoom);
		s.x = round2(state.panX);
		s.y = round2(state.panY);
	}
	return s;
}

/** Build the shareable URL for the current view. */
function buildPermalink() {
	let qs = "";
	try {
		qs = b64urlEncode(JSON.stringify(permalinkState()));
	} catch {
		/* fall through with an empty payload */
	}
	const u = new URL(location.href);
	u.hash = "";
	if (qs) u.searchParams.set("v", qs);
	else u.searchParams.delete("v");
	return u.toString();
}

/** Decode a ?v= payload (raw base64url or a whole pasted URL) into an object. */
function parsePermalink(search) {
	let raw = "";
	try {
		raw = new URLSearchParams(search ?? location.search).get("v") || "";
	} catch {
		return null;
	}
	if (!raw) {
		// The caller may have pasted a full URL; pull the v= out of it.
		const m = String(search).match(/[?&]v=([A-Za-z0-9\-_]+)/);
		if (!m) return null;
		raw = m[1];
	}
	const json = b64urlDecode(raw);
	if (!json) return null;
	try {
		const o = JSON.parse(json);
		return o && typeof o === "object" ? o : null;
	} catch {
		return null;
	}
}

// Coalesces a burst of edits into one history entry.
let permalinkTimer = null;
function schedulePermalinkWrite(delay = 400) {
	// Never clobber the address bar while a permalink is still being restored:
	// the model loads asynchronously, and an early write would omit it.
	if (permalinkRestoring) return;
	if (permalinkTimer) clearTimeout(permalinkTimer);
	permalinkTimer = setTimeout(() => {
		permalinkTimer = null;
		writePermalinkNow();
	}, delay);
}

function writePermalinkNow() {
	if (permalinkRestoring) return;
	try {
		history.replaceState(history.state, "", buildPermalink());
	} catch {
		/* sandboxed iframe / file: — the dialog still builds URLs on demand */
	}
}

/** Open the "Tautan tampilan" dialog with a freshly built URL. */
function openPermalink() {
	if (!el.linkModal) return;
	el.linkUrl.value = buildPermalink();
	if (el.linkNote) {
		el.linkNote.hidden = true;
		el.linkNote.textContent = "";
	}
	el.linkModal.hidden = false;
	// The shared URL reloads the view on open, so start the field selected.
	el.linkUrl.focus();
	el.linkUrl.select();
}
function closePermalink() {
	if (el.linkModal) el.linkModal.hidden = true;
}

async function copyPermalink() {
	const url = el.linkUrl?.value || buildPermalink();
	let ok = false;
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(url);
			ok = true;
		}
	} catch {
		/* fall through to the legacy path below */
	}
	if (!ok) {
		try {
			el.linkUrl.select();
			ok = document.execCommand("copy");
		} catch {
			ok = false;
		}
	}
	toast(ok ? "Tautan disalin ke papan klip." : "Tidak bisa menyalin otomatis — salin manual dari kotak URL.");
}

/** True while a permalink is being applied — blocks URL writes until the model
 *  it names has finished loading. */
let permalinkRestoring = false;

/**
 * Apply a decoded permalink to the live viewer and load the model it names.
 * Instant toggles first, the model last, then the deferred bits (skin /
 * variant / playhead) which only exist once the skeleton is live.
 */
async function applyPermalink(s) {
	if (!s || typeof s !== "object") return false;
	// A shared view is a fresh start: don't let the last session's sidebar,
	// timeline, FPS or backdrop choices bleed into what the link describes.
	permalinkRestoring = true;

	browse.favOnly = false;
	el.favFilter?.classList.remove("is-on");
	if (s.g) {
		browse.view = "models";
		browse.game = s.g;
		browse.page = 1;
	}
	// Camera, playback rate and the panel toggles — cheap and independent of
	// whether the named model still exists.
	state.rate = s.r > 0 ? s.r : 1;
	if (el.rateSelect?.querySelector(`option[value="${state.rate}"]`)) {
		el.rateSelect.value = String(state.rate);
	}
	state.flip = !!s.f;
	el.flipBtn.dataset.on = String(state.flip);
	setTimelineVisible(!!s.tl);
	setPartsVisible(!!s.pt);
	setFpsVisible(!!s.fps);
	if (el.inspector) setInspectorVisible(!!s.insp);
	if (s.insp === "slots" || s.insp === "compare") setInspectorTab(s.insp);
	if (typeof s.b === "boolean" || typeof s.b === "number") {
		state.showBones = !!s.b;
		bonesGfx.visible = state.showBones;
		el.bonesBtn.dataset.on = String(state.showBones);
		drawBones();
	}
	if (typeof s.gr === "boolean" || typeof s.gr === "number") {
		state.showGrid = !!s.gr;
		el.grid.classList.toggle("is-on", state.showGrid);
		el.gridBtn.dataset.on = String(state.showGrid);
	}
	// A permalink that omits the backdrop means the default (dark) — reset it,
	// so a shared link keeps its own look instead of inheriting a saved one.
	setStageBg(s.bg && BG_ORDER.includes(s.bg) ? s.bg : "dark", { persist: false });
	// Sama seperti warna latar: tautan tanpa `bk` berarti backdrop MATI, supaya
	// tampilan yang dibagikan tidak mewarisi preferensi sesi sebelumnya.
	setBackdrop(!!s.bk, s.bk || "aurora", { persist: false });
	if (typeof s.sb === "boolean" || typeof s.sb === "number") setSidebarHidden(!s.sb, { persist: false });

	// Load the model, if the link names one that still exists.
	const model = s.m ? models.find((m) => m.id === s.m) : null;
	if (model) {
		await loadModel(model);
		// The sidebar must follow the game the link opened.
		renderLibrary();
		// Animation / skin / variant are per-skeleton, so only now are they safe.
		// Variant goes first: switching it reloads the skeleton, which would
		// wipe an animation or skin applied before it.
		if (s.va) {
			const opt = [...(el.variantSelect?.options || [])].find((o) => o.dataset.id === s.va);
			if (opt && s.va !== current?.id) await switchVariant(s.va);
		}
		if (s.a && [...(el.animSelect?.options || [])].some((o) => o.value === s.a)) {
			el.animSelect.value = s.a;
			el.animSelect.dispatchEvent(new Event("change"));
		}
		if (s.k && [...(el.skinSelect?.options || [])].some((o) => o.value === s.k)) {
			el.skinSelect.value = s.k;
			el.skinSelect.dispatchEvent(new Event("change"));
		}
		// Camera: rebuild it exactly, or fall back to fitting the art.
		if (Number.isFinite(Number(s.z))) {
			state.zoom = Number(s.z);
			state.panX = Number(s.x) || 0;
			state.panY = Number(s.y) || 0;
			applyTransform();
		} else {
			fitModel();
		}
		// The playhead goes last, once animation/skin/variant have settled.
		if (Number.isFinite(Number(s.t))) {
			state.trackTime = Number(s.t);
			if (spine?.state?.tracks?.[0]) spine.state.tracks[0].trackTime = state.trackTime;
			clock.syncTo(state.trackTime);
			updateScrubUI();
			updateTimelinePlayhead();
		}
		if (s.p === 0 || s.p === false || s.p === "0") setPlaying(false);
		// A/B terakhir: model A sudah dimuat, jadi B bisa menyusul.
		if (typeof s.ab === "string") {
			const mB = models.find((m) => m.id === s.ab);
			if (mB) {
				if (s.abl) AB.layout = s.abl === "overlay" ? "overlay" : "split";
				if (Number.isFinite(Number(s.abo))) AB.onion = Number(s.abo);
				AB.lock = !!s.abk;
				AB.offset = {
					x: Number(s.abx) || 0,
					y: Number(s.aby) || 0,
				};
				await abStart(mB);
				// Kamera B di-set SETELAH abStart: fitModelB() di dalamnya
				// menimpa zoom/pan B, jadi nilai dari tautan akan hilang
				// kalau dipasang sebelumnya.
				if (Number.isFinite(Number(s.cbz))) camB.zoom = Number(s.cbz);
				camB.panX = Number(s.cbx) || 0;
				camB.panY = Number(s.cby) || 0;
				abSyncUI();
			}
		}
	} else if (s.m) {
		toast(`Model “${s.m}” dari tautan tidak ada di pustaka.`);
	}

	// Keep the address bar in sync with what the link actually produced (it may
	// have dropped a variant that no longer exists), then resume live writes.
	permalinkRestoring = false;
	writePermalinkNow();
	return true;
}

function initPermalink() {
	el.gridLink?.addEventListener("click", openPermalink);
	el.linkClose?.addEventListener("click", closePermalink);
	el.linkCopy?.addEventListener("click", copyPermalink);
	el.linkRefresh?.addEventListener("click", () => {
		el.linkUrl.value = buildPermalink();
		toast("URL disegarkan.");
	});
	el.linkModal?.addEventListener("click", (e) => {
		if (e.target instanceof Element && e.target.closest("[data-close]")) closePermalink();
	});
	// Ctrl/Cmd-Shift-C copies the current view link from anywhere.
	window.addEventListener("keydown", (e) => {
		if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "c" || e.key === "C")) {
			e.preventDefault();
			copyPermalink();
		}
	});
	// Mirror every view change into the URL (debounced). Toggles persist their
	// own keys inside their setters, so a generic listener is enough here.
	document.addEventListener("click", () => schedulePermalinkWrite());
	document.addEventListener("input", () => schedulePermalinkWrite());
	window.addEventListener("pointerup", () => schedulePermalinkWrite());
}

/** Restore the view named by ?v= (if any). Runs after refresh() so `models`
 *  is populated. */
async function bootPermalink() {
	const s = parsePermalink(location.search);
	if (!s) return;
	await applyPermalink(s);
	try {
		history.replaceState({ permalink: true }, "", buildPermalink());
	} catch {
		/* ignore */
	}
}

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

// Restore the saved render density (default "auto").
try {
	const saved = localStorage.getItem(DENSITY_KEY);
	if (saved && el.densitySelect && [...el.densitySelect.options].some((o) => o.value === saved)) {
		state.density = saved;
		el.densitySelect.value = saved;
	}
} catch {
	/* private mode */
}

/* Debug handle: lets the smoke tests (and the browser console) inspect the
 * live viewer state without re-deriving it — harmless in production. */
window.__spineStage = {
	get spine() { return spine; },
	get state() { return state; },
	get clock() { return clock; },
	get fps() { return fps; },
	get parts() { return parts; },
	sourcePixelScale: () => (spine ? sourcePixelScale(spine) : 0),
	get ik() { return IK; },
	get bones() { return BONES; },
	pushUndo: () => pushBoneUndo(),
	setBoneMode,
	nudgeBone,
	setBoneValue,
	get bounds() { return BOUNDS; },
	get vtx() { return VTX; },
	setVtxMode,
	vtxPick,
	vtxCount,
	vtxMove,
	vtxPoints,
	vtxWorldPoints,
	vtxExportData,
	setBoundsMode,
	boundsPick,
	boundsApply,
	boundsCorners,
	mirrorName,
	mirrorPose,
	mirrorStats,
	poseLibStore,
	poseLibLoad,
	poseLibRefresh,
	writeEdit: (n, patch) => writeBoneEdit(n, patch),
	applyEdits: () => applyBoneEdits(),
	boneUndo,
	boneRedo,
	renderBoneTree,
	exportSkeleton,
	ikSelect,
	ikTipPoint,
	setIkMode,
	pngOutputSize: () => (spine ? pngOutputSize(spine) : null),
};

initSidebar();
initTimeline();
initInspector();
initFullscreen();
initExport();
initFavorites();
initUpdateLog();
initUpdaterHealth();
/* --- Menu "Alat" ------------------------------------------------------
 * Alat lanjutan (kisi, tulang, bagian, edit tulang, nama slot, FPS, waktu,
 * periksa, PMA, tajam) dikumpulkan di satu popover supaya baris kontrol tidak
 * penuh tombol kecil. Elemennya hanya dipindah di DOM, jadi semua id, data-on,
 * dan pintasan papan-tik tetap bekerja tanpa perubahan.
 */
function setToolsOpen(open) {
	const pop = document.getElementById("tools-pop");
	const btn = document.getElementById("tools-btn");
	if (!pop) return;
	pop.hidden = !open;
	if (btn) {
		btn.dataset.on = String(open);
		btn.setAttribute("aria-expanded", String(open));
	}
}

function initToolsMenu() {
	const pop = document.getElementById("tools-pop");
	const btn = document.getElementById("tools-btn");
	if (!pop || !btn) return;

	btn.addEventListener("click", (ev) => {
		ev.stopPropagation();
		setToolsOpen(pop.hidden);
	});

	// Klik di luar menutup menu. Tombol di dalam popover tidak menutupnya,
	// supaya beberapa alat bisa dinyalakan berturut-turut tanpa membuka ulang.
	document.addEventListener("pointerdown", (ev) => {
		if (pop.hidden) return;
		if (pop.contains(ev.target) || btn.contains(ev.target)) return;
		setToolsOpen(false);
	});

	// Toggle tampilan (Kisi/Tulang/Bagian/Nama Slot/FPS) TIDAK menutup menu:
	// orang biasanya menyalakan beberapa berturut-turut. Hanya tombol yang
	// membuka panel besar (Waktu, Periksa) yang menutupnya, karena panel itu
	// tumbuh di bawah panggung dan akan tertutup popover.
	pop.addEventListener("click", (ev) => {
		const b = ev.target.closest("button");
		if (!b) return;
		if (b.id === "timeline-btn" || b.id === "inspector-btn") setToolsOpen(false);
	});
}

initToolsMenu();

/* --- Editor tulang: undo/redo, pohon, ekspor skeleton ------------------ */
// Pustaka pose + cermin
document.getElementById("pose-lib-save")?.addEventListener("click", () => poseLibStore());
document.getElementById("pose-lib-select")?.addEventListener("change", (e) => {
	const del = document.getElementById("pose-lib-delete");
	if (del) del.disabled = !e.target.value;
	poseLibLoad(e.target.value);
});
document.getElementById("pose-lib-delete")?.addEventListener("click", () => {
	const sel = document.getElementById("pose-lib-select");
	poseLibDelete(sel?.value || "");
	if (sel) {
		sel.value = "";
		const del = document.getElementById("pose-lib-delete");
		if (del) del.disabled = true;
	}
});
document.getElementById("bone-mirror-ltr")?.addEventListener("click", () => mirrorPose("ltr"));
document.getElementById("bone-mirror-rtl")?.addEventListener("click", () => mirrorPose("rtl"));

document.getElementById("bone-undo")?.addEventListener("click", () => boneUndo());
document.getElementById("bone-redo")?.addEventListener("click", () => boneRedo());
document.getElementById("bone-export-skel")?.addEventListener("click", () => exportSkeleton());
document.getElementById("bone-search")?.addEventListener("input", () => renderBoneTree());
for (const btn of document.querySelectorAll(".bone-mode")) {
	btn.addEventListener("click", () => setBoneMode(btn.dataset.mode));
}
for (const [prop, id] of Object.entries(BONE_NUM_IDS)) {
	const inp = document.getElementById(id);
	if (!inp) continue;
	inp.addEventListener("change", () => applyBoneNum(prop, inp.value));
	// Nudge panah saat kotak difokuskan. preventDefault supaya angka di kotak
	// tidak ikut berubah dua kali (browser punya panah bawaan untuk number).
	inp.dataset.boneProp = prop;
	inp.addEventListener("keydown", (e) => {
		if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
		// Hentikan di sini: tanpa stopPropagation, handler global di bawah
		// ikut jalan dan menudge "rotation" juga.
		e.preventDefault();
		e.stopPropagation();
		const step = (e.shiftKey ? 0.1 : 1) * (e.key === "ArrowUp" ? 1 : -1);
		nudgeBone(prop, step);
	});
}
// Panah bekerja juga saat fokus di kanvas (atau di mana pun selain kotak
// angka tulang). Default properti = rotasi.
window.addEventListener("keydown", (e) => {
	if (!BONES.on || !BONES.selected) return;
	if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
	if (e.ctrlKey || e.metaKey || e.altKey) return;
	const ae = document.activeElement;
	if (ae && ae.dataset && ae.dataset.boneProp) return; // sudah ditangani input
	e.preventDefault();
	const step = (e.shiftKey ? 0.1 : 1) * (e.key === "ArrowUp" ? 1 : -1);
	nudgeBone("rotation", step);
});
setBoneMode("rotate");

/* --- Editor vertex ---------------------------------------------------- */
el.vtxBtn?.addEventListener("click", () => setVtxMode(!VTX.on));
document.getElementById("vtx-reset")?.addEventListener("click", () => vtxReset());

// Isi dropdown pilihan vertex setiap kali mesh berubah.
const vtxSelEl = document.getElementById("vtx-sel");
if (vtxSelEl) {
	vtxSelEl.addEventListener("change", () => {
		const i = Number(vtxSelEl.value);
		if (Number.isFinite(i)) {
			VTX.sel = i;
			drawVtxOverlay();
		}
	});
}

/* --- Editor bounds ---------------------------------------------------- */
el.boundsBtn?.addEventListener("click", () => setBoundsMode(!BOUNDS.on));
for (const [prop, id] of [
	["x", "bounds-x"],
	["y", "bounds-y"],
	["width", "bounds-w"],
	["height", "bounds-h"],
	["rotation", "bounds-rot"],
]) {
	const inp = document.getElementById(id);
	if (!inp) continue;
	inp.addEventListener("change", () => {
		const v = Number(inp.value);
		if (Number.isFinite(v)) boundsApply({ [prop]: v });
	});
}

/* --- IK ---------------------------------------------------------------- */
el.ikBtn?.addEventListener("click", () => setIkMode(!IK.on));
document.getElementById("ik-reset")?.addEventListener("click", () => {
	ikReset();
	IK.tip = null;
	IK.chain = [];
	ikSyncUI();
});

initFps();
initParts();
initPermalink();

// Restore the saved backdrop, if any. setStageBg() would also persist it, so
// only call it when we actually have a stored value.
try {
	const savedBg = localStorage.getItem("stageBg");
	if (savedBg && BG_ORDER.includes(savedBg)) setStageBg(savedBg, { persist: false });
} catch {
	/* private mode — keep the default */
}
// Pulihkan gambar latar (on/off + scene terakhir). bootPermalink() yang jalan
// setelah ini akan menimpanya kalau tautan ?v= punya ketentuan sendiri.
try {
	const savedBackdrop = JSON.parse(localStorage.getItem("stageBackdrop") || "null");
	if (savedBackdrop && typeof savedBackdrop === "object")
		setBackdrop(!!savedBackdrop.on, savedBackdrop.scene, { persist: false });
} catch {
	/* private mode / JSON rusak — keep the default */
}

app.renderer.resize(el.canvasWrap.clientWidth, el.canvasWrap.clientHeight);
// Build the library first (so `models` is populated), then restore the view a
// shared ?v= link describes. Async IIFE, not top-level await: the bundle is an
// IIFE and top-level await is not supported in that output format.
(async () => {
	await refresh();
	await bootPermalink();
})();
