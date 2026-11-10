/**
 * Model3D stage — renderer glTF/GLB terpisah dari PIXI.
 *
 * Dibangun sebagai IIFE mandiri (public/dist/model3d.js) dan dimuat lewat
 * <script> sekali saja saat model `format: "model3d"` dibuka. Tujuannya:
 * `viewer.js` (4,1 MB, 43 ribu model 2D) TIDAK ikut membawa three.js, dan
 * halaman yang tidak pernah membuka model 3D tidak mengunduhnya sama sekali.
 *
 * PIXI bukan renderer 3D (orthographic sprite batch, tanpa depth/lighting),
 * jadi kanvas WebGL ini ditumpuk di atas #canvas-wrap seperti `image-stage`.
 * Tidak ada satupun jalur Spine/Live2D yang diubah oleh modul ini.
 *
 * Kontrak: window.Model3DStage = { mount, dispose, play, listAnimations,
 *                                  capture, state, resize }
 */
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

let S = null;

function stopLoop() {
	if (!S) return;
	if (S.raf) cancelAnimationFrame(S.raf);
	if (S.ro) S.ro.disconnect();
}

function dispose() {
	if (!S) return;
	stopLoop();
	try {
		if (S.mixer) S.mixer.stopAllAction();
		if (S.controls) S.controls.dispose();
		if (S.scene) {
			S.scene.traverse((o) => {
				if (o.geometry) o.geometry.dispose();
				const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
				for (const m of mats) {
					for (const v of Object.values(m)) {
						if (v && v.isTexture) v.dispose();
					}
					m.dispose();
				}
			});
		}
		if (S.renderer) {
			S.renderer.dispose();
			S.renderer.forceContextLoss?.();
		}
		S.canvas?.remove();
	} catch (err) {
		console.warn("[model3d] gagal dispose:", err);
	}
	S.wrap?.classList.remove("is-3d");
	S = null;
}

function fitCamera(root, camera, controls) {
	const box = new THREE.Box3().setFromObject(root);
	const size = box.getSize(new THREE.Vector3());
	const center = box.getCenter(new THREE.Vector3());
	// Geser lewat Group pembungkus, JANGAN lewat gltf.scene: mixer animasi
	// resolve track berdasarkan nama node di dalam gltf.scene itu.
	S.holder.position.copy(center).multiplyScalar(-1);
	const maxDim = Math.max(size.x, size.y, size.z) || 1;
	const dist = maxDim * 1.8;
	camera.near = Math.max(maxDim / 100, 0.01);
	camera.far = dist * 30;
	camera.position.set(dist * 0.30, dist * 0.16, dist);
	camera.updateProjectionMatrix();
	controls.target.set(0, 0, 0);
	controls.minDistance = maxDim * 0.35;
	controls.maxDistance = dist * 8;
	controls.update();
	S.size = { x: +size.x.toFixed(2), y: +size.y.toFixed(2), z: +size.z.toFixed(2) };
}

function resize() {
	if (!S) return;
	const w = S.wrap.clientWidth || 800;
	const h = S.wrap.clientHeight || 600;
	S.renderer.setSize(w, h, false);
	S.camera.aspect = w / h;
	S.camera.updateProjectionMatrix();
}

function state() {
	if (!S) return { ready: false };
	return {
		ready: true,
		id: S.id,
		current: S.current || "Bind pose",
		animations: ["Bind pose", ...Object.keys(S.animUrls)],
		meshes: S.meshCount,
		triangles: S.triangles,
		size: S.size,
	};
}

function listAnimations() {
	return state().animations;
}

function capture() {
	if (!S) return null;
	S.renderer.render(S.scene, S.camera);
	return S.canvas.toDataURL("image/png");
}

/** Putar clip dari GLB animasi terpisah (retarget ke skeleton model utama). */
async function play(name) {
	if (!S) return false;
	if (!name || name === "Bind pose") {
		S.mixer.stopAllAction();
		S.current = "Bind pose";
		return true;
	}
	const url = S.animUrls[name];
	if (!url) return false;
	const gltf = await S.loader.loadAsync(url);
	const clip = gltf.animations && gltf.animations[0];
	if (!clip) throw new Error(`Clip 3D "${name}" tidak punya animasi`);
	S.mixer.stopAllAction();
	const action = S.mixer.clipAction(clip, S.animatedRoot);
	action.reset().setLoop(THREE.LoopRepeat, Infinity).play();
	S.current = name;
	return true;
}

async function mount({ wrap, modelUrl, anims = {}, id = "" }) {
	dispose();
	const canvas = document.createElement("canvas");
	canvas.className = "model3d-canvas";
	const renderer = new THREE.WebGLRenderer({
		canvas, antialias: true, alpha: true, preserveDrawingBuffer: true,
	});
	renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
	renderer.outputColorSpace = THREE.SRGBColorSpace;
	renderer.toneMapping = THREE.ACESFilmicToneMapping;
	renderer.toneMappingExposure = 1.15;

	const scene = new THREE.Scene();
	const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 1000);
	scene.add(new THREE.HemisphereLight(0xffffff, 0x40506a, 2.1));
	const key = new THREE.DirectionalLight(0xffffff, 2.4);
	key.position.set(1, 2, 3);
	scene.add(key);
	const rim = new THREE.DirectionalLight(0x88aaff, 1.1);
	rim.position.set(-2, 1, -3);
	scene.add(rim);

	const controls = new OrbitControls(camera, canvas);
	controls.enableDamping = true;
	controls.dampingFactor = 0.08;
	controls.enablePan = true;

	wrap.appendChild(canvas);
	wrap.classList.add("is-3d");

	S = {
		wrap, canvas, renderer, scene, camera, controls, id,
		animUrls: anims, loader: new GLTFLoader(), mixer: null,
		animatedRoot: null, holder: null, current: "Bind pose",
		raf: 0, ro: null, meshCount: 0, triangles: 0, size: null,
	};
	resize();
	S.ro = new ResizeObserver(() => resize());
	S.ro.observe(wrap);

	const gltf = await S.loader.loadAsync(modelUrl);
	if (!S) throw new Error("stage 3D dibatalkan");
	S.animatedRoot = gltf.scene;
	S.holder = new THREE.Group();
	S.holder.add(gltf.scene);
	scene.add(S.holder);
	S.mixer = new THREE.AnimationMixer(gltf.scene);
	let tris = 0;
	gltf.scene.traverse((o) => {
		if (!o.isMesh) return;
		S.meshCount++;
		const g = o.geometry;
		if (g) tris += (g.index ? g.index.count : (g.attributes.position?.count || 0)) / 3;
	});
	S.triangles = Math.round(tris);
	fitCamera(gltf.scene, camera, controls);

	const clock = new THREE.Clock();
	const tick = () => {
		if (!S) return;
		S.raf = requestAnimationFrame(tick);
		const dt = Math.min(clock.getDelta(), 0.1);
		if (S.mixer) S.mixer.update(dt);
		controls.update();
		renderer.render(scene, camera);
	};
	tick();
	return state();
}

window.Model3DStage = { mount, dispose, play, listAnimations, capture, state, resize };
