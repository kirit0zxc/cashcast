import { A as e, F as t, M as n, P as r, i, j as a, n as o, p as s, r as c } from "./assets-Cy_L-AgE.js";
import * as l from "three";
import { VRMHumanBoneList as u, VRMLoaderPlugin as d, VRMUtils as f } from "@pixiv/three-vrm";
import { VRMAnimationLoaderPlugin as p, createVRMAnimationClip as m } from "@pixiv/three-vrm-animation";
import { GLTFLoader as h } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder as g } from "three/examples/jsm/libs/meshopt_decoder.module.js";
//#region \0rolldown/runtime.js
var _ = Object.defineProperty, v = (e, t) => {
	let n = {};
	for (var r in e) _(n, r, {
		get: e[r],
		enumerable: !0
	});
	return t || _(n, Symbol.toStringTag, { value: "Module" }), n;
}, y = /* @__PURE__ */ new Set([
	"leftUpperLeg",
	"leftLowerLeg",
	"leftFoot",
	"leftToes",
	"rightUpperLeg",
	"rightLowerLeg",
	"rightFoot",
	"rightToes"
]);
function b(e, t, n) {
	return n === "none" ? !0 : n === "inplace" ? e !== "hips" || t !== "position" : !(y.has(e) || e === "hips" && (t === "position" || n === "strict"));
}
//#endregion
//#region src/mascot/renderers/vrm/gltf.ts
function x() {
	return new h().setMeshoptDecoder(g);
}
//#endregion
//#region src/mascot/renderers/vrm/loadClip.ts
var S = /* @__PURE__ */ new Map();
function C(e) {
	let t = S.get(e);
	if (!t) {
		t = (async () => {
			let t = x();
			return t.register((e) => new p(e)), (await t.parseAsync(await c(e), o(e))).userData.vrmAnimations?.[0] ?? null;
		})();
		let n = t;
		t.catch(() => {
			S.get(e) === n && S.delete(e);
		}), S.set(e, t);
	}
	return t;
}
function w(e) {
	S.delete(e);
}
async function T(e, t) {
	let n = await C(e.url);
	return n ? E(m(n, t), t, e.mask) : null;
}
function E(e, t, n) {
	if (n === "none") return e;
	let r = t.humanoid;
	if (!r) return e;
	let i = /* @__PURE__ */ new Map();
	for (let e of u) {
		let t = r.getNormalizedBoneNode(e);
		t && i.set(t.name, e);
	}
	let a = e.tracks.filter((e) => {
		let t = e.name.lastIndexOf("."), r = i.get(e.name.slice(0, t));
		return !r || b(r, e.name.slice(t + 1), n);
	});
	return new l.AnimationClip(e.name, e.duration, a);
}
//#endregion
//#region src/mascot/renderers/vrm/trim.ts
function D(e, t, n) {
	let r = Math.max(0, Math.min(t, e.duration)), i = Math.max(r + 1 / 60, Math.min(n, e.duration)), a = e.tracks.map((e) => {
		let t = e.getValueSize(), n = new Float32Array(t), a = e instanceof l.QuaternionKeyframeTrack ? new l.QuaternionLinearInterpolant(e.times, e.values, t, n) : new l.LinearInterpolant(e.times, e.values, t, n), o = (e) => Array.from(a.evaluate(e)), s = [0], c = o(r);
		for (let n = 0; n < e.times.length; n++) {
			let a = e.times[n];
			if (!(a <= r || a >= i)) {
				s.push(a - r);
				for (let r = 0; r < t; r++) c.push(e.values[n * t + r]);
			}
		}
		s.push(i - r), c.push(...o(i));
		let u = e.constructor;
		return new u(e.name, s, c);
	});
	return new l.AnimationClip(e.name, i - r, a);
}
//#endregion
//#region src/mascot/renderers/vrm/camera.ts
var O = {
	fit: "full",
	margin: .08,
	zoom: 1,
	offsetX: 0,
	offsetY: 0,
	yaw: 0,
	pitch: 0,
	fov: 28
}, k = {
	margin: [0, .5],
	zoom: [.3, 4],
	offsetX: [-1, 1],
	offsetY: [-1, 1],
	yaw: [-180, 180],
	pitch: [-60, 60],
	fov: [10, 60]
}, A = [
	"full",
	"half",
	"portrait"
];
function j(e) {
	let t = {};
	if (!e || typeof e != "object" || Array.isArray(e)) return t;
	let n = e;
	A.includes(n.fit) && (t.fit = n.fit);
	for (let e of Object.keys(k)) {
		let r = n[e];
		if (typeof r != "number" || !Number.isFinite(r)) continue;
		let [i, a] = k[e];
		t[e] = Math.round(Math.min(a, Math.max(i, r)) * 1e3) / 1e3;
	}
	return t;
}
function M(e, t = O) {
	let n = {};
	for (let r of Object.keys(e)) e[r] !== t[r] && (n[r] = e[r]);
	return n;
}
var N = {
	fit: "portrait",
	margin: .03,
	zoom: 1.05,
	offsetY: -.04,
	yaw: -4,
	pitch: 12,
	fov: 29
};
//#endregion
//#region src/mascot/renderers/vrm/clipCameras.ts
function P(e) {
	let t = Object.create(null);
	if (!e || typeof e != "object" || Array.isArray(e)) return t;
	for (let [n, r] of Object.entries(e)) {
		if (!n || n.length > 300 || n === "__proto__") continue;
		let e = j(r);
		Object.keys(e).length && (t[n] = e);
	}
	return t;
}
var F = /^file:(.*):(?:none|inplace|legs|strict)$/;
function I(e) {
	return e.split("/").map((e) => {
		let t = e;
		try {
			t = decodeURIComponent(e);
		} catch {}
		return encodeURIComponent(t);
	}).join("/");
}
function L(e, t) {
	let n = F.exec(e);
	if (!n) return e;
	let r = n[1];
	if (/^[a-z][a-z\d+.-]*:/i.test(r)) return r;
	let i = I(r), a = I(t.endsWith("/") ? t : t + "/");
	return i.startsWith(a) ? i.slice(a.length) : i;
}
var R = {
	"anim/vrma/67_hXBrhdpmbtpo6dwf3zVGyw(includeTPose).vrma": { pitch: -20 },
	peace: { pitch: -4 },
	thankful: { pitch: -7 },
	dismiss: { pitch: -9 },
	talking: { yaw: 24 },
	greeting: {
		zoom: .88,
		offsetY: .12,
		pitch: 7
	}
}, z = /* @__PURE__ */ v({
	VrmRenderer: () => q,
	clipOf: () => W
}), B = P(R), V = {
	assetsBase: "/mascot/",
	modelUrl: "model/yumi.vrm",
	headFollow: .35,
	armSpread: 8,
	...O,
	...j(N),
	background: !1,
	reducedMotion: "auto"
}, H = (e, t, n) => e + (t ? `#${t}` : "") + (n ? `@${n[0]}-${n[1]}` : ""), U = /(?:#(?:none|inplace|legs|strict))?(?:@[\d.]+-[\d.]+)?$/, W = (e) => e.replace(U, ""), G = /* @__PURE__ */ new Map();
function K(e) {
	let t = G.get(e);
	return t || (t = c(e), t.catch(() => G.delete(e)), G.set(e, t)), t;
}
var q = class {
	opts;
	scene = new l.Scene();
	camera;
	gl;
	lastTick = 0;
	offscreen = !1;
	visibility = null;
	contextLost = !1;
	vrm = null;
	mixer = null;
	container = null;
	resizeObserver = null;
	frame = 0;
	elapsed = 0;
	actions = /* @__PURE__ */ new Map();
	pending = /* @__PURE__ */ new Map();
	current = null;
	currentName = "";
	clipMeta = /* @__PURE__ */ new Map();
	wantedName = "";
	requestSeq = 0;
	baseName = "";
	disposed = !1;
	expressionTarget = {};
	baseExpression = {
		expression: "neutral",
		weight: 0
	};
	faceTrack = null;
	faceIndex = -2;
	expressionNow = {};
	gazeTarget = new l.Vector2(0, 0);
	gazeNow = new l.Vector2(0, 0);
	lookAtAnchor = new l.Object3D();
	bounds = null;
	gazeBase = new l.Vector3();
	camRight = new l.Vector3(1, 0, 0);
	camUp = new l.Vector3(0, 1, 0);
	gazePoint = new l.Vector3();
	camTarget = new l.Vector3();
	camGoal = null;
	camKey = "";
	tmpVec = new l.Vector3();
	blinkValue = 0;
	blinkUntil = 0;
	blinkDuration = 110;
	visemeTarget = {};
	visemeNow = {};
	speaking = !1;
	accents = [];
	accentExpr = null;
	armSpread = 0;
	win = window;
	reducedMotion = !1;
	offsetBases = /* @__PURE__ */ new Map();
	glow = {
		color: "#9ED8BC",
		intensity: .25,
		pulseHz: 0
	};
	glowColor = new l.Color("#9ED8BC");
	rimMaterials = [];
	constructor(e = {}) {
		this.opts = {
			...V,
			...e
		}, this.armSpread = this.opts.armSpread, this.reducedMotion = s(this.opts.reducedMotion);
	}
	setArmSpread(e) {
		this.armSpread = e;
	}
	getArmSpread() {
		return this.armSpread;
	}
	async init(e) {
		this.container = e, this.win = e.ownerDocument.defaultView ?? window, this.gl = new l.WebGLRenderer({
			alpha: !this.opts.background,
			antialias: !0
		}), this.gl.setPixelRatio(Math.min(this.win.devicePixelRatio, 2)), this.gl.outputColorSpace = l.SRGBColorSpace, this.opts.background || this.gl.setClearAlpha(0), e.appendChild(this.gl.domElement), this.gl.domElement.setAttribute("aria-hidden", "true"), Object.assign(this.gl.domElement.style, {
			width: "100%",
			height: "100%",
			display: "block"
		}), this.camera = new l.PerspectiveCamera(this.opts.fov, 1, .1, 50), this.scene.add(this.lookAtAnchor), this.setupLights(), this.resize();
		let t = this.win.ResizeObserver ?? ResizeObserver;
		this.resizeObserver = new t(() => this.resize()), this.resizeObserver.observe(e);
		let n = this.gl.domElement;
		n.addEventListener("webglcontextlost", this.onContextLost), n.addEventListener("webglcontextrestored", this.onContextRestored), await this.loadModel(), !this.disposed && (this.watchVisibility(e), this.frame || this.loop());
	}
	watchVisibility(e) {
		let t = this.win.IntersectionObserver;
		t && (this.visibility = new t((e) => {
			let t = e.some((e) => e.isIntersecting);
			t !== !this.offscreen && (this.offscreen = !t, t && !this.frame && (this.lastTick = 0, this.loop()));
		}), this.visibility.observe(e));
	}
	setupLights() {
		let e = new l.DirectionalLight(16777215, 1.4);
		e.position.set(1, 1.6, 2.2), this.scene.add(e);
		let t = new l.DirectionalLight(13228287, .5);
		t.position.set(-1.6, .6, 1), this.scene.add(t), this.scene.add(new l.HemisphereLight(16777215, 6978201, .7));
	}
	async loadModel() {
		let e = i(this.opts.modelUrl, this.opts.assetsBase), t = x();
		t.register((e) => new d(e));
		let n = await t.parseAsync(await K(e), o(e)), a = n.userData.vrm;
		if (this.disposed) {
			f.deepDispose(n.scene);
			return;
		}
		f.combineSkeletons(n.scene);
		try {
			f.removeUnnecessaryVertices(n.scene);
		} catch {}
		a.meta?.metaVersion === "0" && f.rotateVRM0(a), a.scene.traverse((e) => {
			e.frustumCulled = !1;
		}), this.scene.add(a.scene), this.vrm = a, this.mixer = new l.AnimationMixer(a.scene), this.mixer.addEventListener("finished", this.onClipFinished), a.lookAt && (a.lookAt.target = this.lookAtAnchor), this.collectRimMaterials(), this.measure(), this.frameCamera(), this.applyGlow();
		for (let e of r) this.ensureClip(e);
	}
	collectRimMaterials() {
		this.rimMaterials = [], this.vrm?.scene.traverse((e) => {
			let t = Array.isArray(e.material) ? e.material : [e.material];
			for (let e of t) e && "parametricRimColorFactor" in e && this.rimMaterials.push(e);
		});
	}
	measure() {
		let e = this.vrm;
		if (!e) return;
		e.scene.updateMatrixWorld(!0);
		let t = new l.Box3().setFromObject(e.scene);
		if (t.isEmpty()) return;
		let n = e.humanoid, r = (e) => {
			let t = n?.getNormalizedBoneNode(e);
			return t ? t.getWorldPosition(new l.Vector3()) : null;
		}, i = r("leftUpperArm"), a = r("rightUpperArm"), o = i && a ? Math.abs(i.x - a.x) : 0, s = o ? Math.min(t.max.x - t.min.x, o * 3) : t.max.x - t.min.x;
		this.bounds = {
			min: t.min.clone(),
			max: t.max.clone(),
			width: s,
			hips: r("hips")?.y ?? null,
			chest: (r("chest") ?? r("spine"))?.y ?? null,
			head: r("head")
		};
	}
	frameCamera(e = !0) {
		let t = this.bounds;
		if (!t) return;
		let n = this.getEffectiveCamera();
		this.camKey = JSON.stringify(n);
		let r = t.min.y;
		n.fit === "half" && (r = t.hips ?? r), n.fit === "portrait" && (r = t.chest ?? r);
		let i = t.max.y, a = 1 + n.margin * 2, o = Math.max(i - r, .1) * a, s = Math.max(t.width, .1) * a, c = n.fov * Math.PI / 180, u = this.camera.aspect || 1, d = o / 2 / Math.tan(c / 2), f = s / 2 / (Math.tan(c / 2) * u), p = Math.max(d, f) / Math.max(n.zoom, .01), m = new l.Vector3(-n.offsetX, (i + r) / 2 - n.offsetY, 0), h = l.MathUtils.degToRad(n.yaw), g = l.MathUtils.degToRad(n.pitch), _ = new l.Vector3(Math.sin(h) * Math.cos(g), Math.sin(g), Math.cos(h) * Math.cos(g)), v = m.clone().addScaledVector(_, p), y = (t.head ?? m).clone().addScaledVector(_, p);
		if (!e) {
			this.camGoal = {
				pos: v,
				target: m,
				fov: n.fov,
				gaze: y
			};
			return;
		}
		this.camGoal = null, this.camera.position.copy(v), this.camTarget.copy(m), this.camera.fov = n.fov, this.gazeBase.copy(y), this.lookAtAnchor.position.copy(y), this.applyCameraPose();
	}
	applyCameraPose() {
		this.camera.lookAt(this.camTarget), this.camera.updateProjectionMatrix(), this.camera.updateMatrixWorld(), this.camRight.setFromMatrixColumn(this.camera.matrixWorld, 0), this.camUp.setFromMatrixColumn(this.camera.matrixWorld, 1);
	}
	moveCamera(e) {
		let t = this.camGoal;
		if (!t) return;
		let n = 1 - Math.exp(-e * 4);
		this.camera.position.lerp(t.pos, n), this.camTarget.lerp(t.target, n), this.gazeBase.lerp(t.gaze, n), this.camera.fov += (t.fov - this.camera.fov) * n, this.camera.position.distanceTo(t.pos) < .001 && Math.abs(t.fov - this.camera.fov) < .01 && (this.camera.position.copy(t.pos), this.camTarget.copy(t.target), this.gazeBase.copy(t.gaze), this.camera.fov = t.fov, this.camGoal = null), this.applyCameraPose();
	}
	followClipCamera() {
		this.bounds && !this.disposed && JSON.stringify(this.getEffectiveCamera()) !== this.camKey && this.frameCamera(this.reducedMotion);
	}
	stats() {
		return {
			elapsed: this.elapsed,
			drawing: !this.offscreen && !this.contextLost && this.frame !== 0
		};
	}
	clipName() {
		let e = L(W(this.currentName), this.opts.assetsBase);
		if (!this.currentName.startsWith("file:")) return e;
		for (let [t, r] of Object.entries(n)) if (r.url === e) return t;
		return e;
	}
	getEffectiveCamera() {
		let e = B[this.clipName()];
		return e ? {
			...this.getCamera(),
			...e
		} : this.getCamera();
	}
	getClipCamera(e) {
		return B[e] ?? null;
	}
	getClipCameras() {
		return { ...B };
	}
	setClipCamera(e, t) {
		let n = t ? j(t) : {};
		Object.keys(n).length ? B[e] = n : delete B[e], this.clipName() === e && this.frameCamera(!0);
	}
	getCamera() {
		let { fit: e, margin: t, zoom: n, offsetX: r, offsetY: i, yaw: a, pitch: o, fov: s } = this.opts;
		return {
			fit: e,
			margin: t,
			zoom: n,
			offsetX: r,
			offsetY: i,
			yaw: a,
			pitch: o,
			fov: s
		};
	}
	setCamera(e) {
		Object.assign(this.opts, j(e)), this.frameCamera();
	}
	resize() {
		if (!this.container) return;
		let e = this.container.clientWidth || 1, t = this.container.clientHeight || 1;
		this.gl.setSize(e, t, !1), this.camera.aspect = e / t, this.camera.updateProjectionMatrix(), this.vrm && this.frameCamera();
	}
	setExpression(e, t) {
		this.baseExpression = {
			expression: e,
			weight: t
		}, this.faceIndex = -2;
	}
	setFaceTrack(e, t) {
		this.faceTrack = e && t?.length ? {
			clip: e,
			keys: a(t)
		} : null, this.faceIndex = -2;
	}
	targetExpression(e, t) {
		for (let e of [
			"happy",
			"angry",
			"sad",
			"relaxed",
			"surprised"
		]) this.expressionTarget[e] = 0;
		e !== "neutral" && (this.expressionTarget[e] = t);
	}
	applyFaceTrack() {
		let t = this.faceTrack, n = t && this.current && W(this.currentName) === t.clip ? e(t.keys, this.current.time + this.offsetOf(this.currentName)) : -1;
		if (n === this.faceIndex) return;
		this.faceIndex = n;
		let r = n >= 0 ? t.keys[n] : this.baseExpression;
		this.targetExpression(r.expression, r.weight);
	}
	offsetOf(e) {
		return this.clipMeta.get(e)?.start ?? 0;
	}
	getClipState() {
		let e = this.current;
		if (!e) return null;
		let t = e.getClip().duration, n = this.clipMeta.get(this.currentName) ?? {
			start: 0,
			end: t,
			full: t
		};
		return {
			name: this.clipName(),
			time: e.time + n.start,
			duration: n.full,
			start: n.start,
			end: n.end,
			paused: e.paused
		};
	}
	setClipPaused(e) {
		this.current && (this.current.paused = e);
	}
	seekClip(e) {
		let t = this.current;
		t && (t.time = Math.min(Math.max(e - this.offsetOf(this.currentName), 0), t.getClip().duration), t.isRunning() || (t.enabled = !0, t.play()));
	}
	setGaze(e, t) {
		this.gazeTarget.set(e, t);
	}
	setMouth(e) {
		this.setVisemes({ aa: e });
	}
	setVisemes(e) {
		this.visemeTarget = e;
	}
	setSpeaking(e) {
		this.speaking = e;
	}
	accent(e) {
		let t = performance.now(), n = e === "pause" ? 320 : e === "emphasis" ? 460 : 380;
		this.accents.push({
			kind: e,
			t0: t,
			dur: n
		}), this.accents.length > 6 && this.accents.shift(), e === "question" ? this.accentExpr = {
			name: "surprised",
			weight: .3,
			t0: t,
			dur: 620
		} : e === "emphasis" && (this.accentExpr = {
			name: "happy",
			weight: .18,
			t0: t,
			dur: 480
		});
	}
	blink(e = 110) {
		this.blinkDuration = e, this.blinkUntil = performance.now() + e;
	}
	setGlow(e) {
		this.glow = e, this.glowColor.set(e.color), this.applyGlow();
	}
	playClip(e, n = {}) {
		let r = t(e), i = r && n.mask && r.mask !== n.mask ? n.mask : void 0, a = r && n.range ? n.range : void 0;
		if (!r || !i && !a) {
			this.request(e, n);
			return;
		}
		this.request(H(e, i, a), n, i ? {
			...r,
			mask: i
		} : r, a);
	}
	request(e, t, n, r) {
		this.wantedName = e, t.loop ? this.baseName = e : t.returnTo && (this.baseName = t.returnTo);
		let i = ++this.requestSeq;
		this.ensureClip(e, n, r).then(() => {
			i === this.requestSeq && this.wantedName === e && this.switchTo(e, t);
		});
	}
	onClipEnd = null;
	onClipFinished = (e) => {
		if (e.action !== this.current) return;
		let t = this.currentName;
		this.baseName && this.baseName !== t && this.request(this.baseName, {
			loop: !0,
			fadeMs: 400
		}), this.onClipEnd?.(W(t));
	};
	playFile(e, t = {}) {
		let n = t.mask ?? "inplace", r = `file:${e}:${n}`;
		t.reload && this.dropFile(e), this.request(r, {
			loop: t.loop ?? !1,
			fadeMs: 250
		}, {
			url: e,
			mask: n
		});
	}
	forgetFile(e) {
		this.dropFile(e), this.followClipCamera();
	}
	dropFile(e) {
		for (let t of [...this.pending.keys()]) t.startsWith(`file:${e}:`) && this.pending.delete(t);
		w(i(e, this.opts.assetsBase));
		for (let t of [...this.actions.keys()]) if (t.startsWith(`file:${e}:`)) {
			let e = this.actions.get(t);
			e && (e.stop(), this.mixer?.uncacheAction(e.getClip()), this.mixer?.uncacheClip(e.getClip())), this.actions.delete(t), this.currentName === t && (this.current = null, this.currentName = ""), this.baseName === t && (this.baseName = "");
		}
	}
	stopClip(e = 250) {
		this.current?.fadeOut(e / 1e3), this.current = null, this.currentName = "", this.wantedName = "", this.baseName = "", this.followClipCamera();
	}
	capabilities() {
		return {
			clips: [...this.actions.keys()],
			expressions: [
				"neutral",
				"happy",
				"angry",
				"sad",
				"relaxed",
				"surprised"
			]
		};
	}
	onContextLost = (e) => {
		e.preventDefault(), this.contextLost = !0, this.win.cancelAnimationFrame(this.frame), this.frame = 0;
	};
	onContextRestored = () => {
		this.disposed || (this.contextLost = !1, this.lastTick = 0, this.loop());
	};
	getHeadScreenPosition() {
		let e = this.vrm?.humanoid?.getNormalizedBoneNode("head"), t = this.container;
		if (!e || !t) return null;
		e.getWorldPosition(this.tmpVec).project(this.camera);
		let n = t.getBoundingClientRect();
		return {
			x: n.left + (this.tmpVec.x + 1) / 2 * n.width,
			y: n.top + (1 - this.tmpVec.y) / 2 * n.height
		};
	}
	dispose() {
		this.disposed || (this.disposed = !0, this.win.cancelAnimationFrame(this.frame), this.gl?.domElement.removeEventListener("webglcontextlost", this.onContextLost), this.gl?.domElement.removeEventListener("webglcontextrestored", this.onContextRestored), this.visibility?.disconnect(), this.visibility = null, this.resizeObserver?.disconnect(), this.resizeObserver = null, this.mixer && (this.mixer.removeEventListener("finished", this.onClipFinished), this.mixer.stopAllAction(), this.vrm && this.mixer.uncacheRoot(this.vrm.scene)), this.vrm && f.deepDispose(this.vrm.scene), this.gl?.forceContextLoss(), this.gl?.dispose(), this.gl?.domElement.remove(), this.actions.clear(), this.clipMeta.clear(), this.pending.clear(), this.offsetBases.clear(), this.rimMaterials = [], this.mixer = null, this.vrm = null, this.container = null);
	}
	ensureClip(e, n, r) {
		if (this.actions.has(e)) return Promise.resolve();
		let a = this.pending.get(e);
		if (a) return a;
		let o = n ?? t(e);
		if (!o || !this.vrm || !this.mixer) return Promise.resolve();
		let s = () => this.pending.get(e) === c, c = T({
			...o,
			url: i(o.url, this.opts.assetsBase)
		}, this.vrm).then((t) => {
			if (!s() || !t || !this.mixer || this.disposed) return;
			let n = t.duration, i = t, a = r && r[0] < n - .05 ? r : void 0;
			r && !a && console.warn(`[mascot] обрезка ${r[0]}–${r[1]} с за пределами клипа «${e}» (${n.toFixed(2)} с) — играю целиком`), a && (i = D(t, a[0], a[1]), this.evictVariants(e));
			let o = a ? Math.max(a[0], 0) : 0;
			this.clipMeta.set(e, {
				start: o,
				end: o + i.duration,
				full: n
			}), this.actions.set(e, this.mixer.clipAction(i));
		}).catch((t) => {
			console.warn(`[mascot] клип "${e}" не загрузился`, t);
		}).finally(() => {
			s() && (this.pending.delete(e), this.wantedName === e && !this.current && !this.actions.has(e) && this.followClipCamera());
		});
		return this.pending.set(e, c), c;
	}
	evictVariants(e) {
		let t = e.replace(/@[\d.]+-[\d.]+$/, "") + "@";
		for (let [n, r] of this.actions) n.startsWith(t) && n !== e && n !== this.currentName && n !== this.baseName && n !== this.wantedName && (r.stop(), this.mixer?.uncacheAction(r.getClip()), this.mixer?.uncacheClip(r.getClip()), this.actions.delete(n), this.clipMeta.delete(n));
	}
	switchTo(e, t) {
		let n = this.actions.get(e);
		if (!n) return;
		let r = (t.fadeMs ?? 280) / 1e3;
		if (this.currentName === e) {
			if (t.loop) {
				n.loop !== l.LoopRepeat && (n.setLoop(l.LoopRepeat, Infinity), n.clampWhenFinished = !1, n.isRunning() || n.reset().play());
				return;
			}
			n.setLoop(l.LoopOnce, Infinity), n.clampWhenFinished = !0, n.reset().play();
			return;
		}
		n.reset(), n.setLoop(t.loop ? l.LoopRepeat : l.LoopOnce, Infinity), n.clampWhenFinished = !t.loop, n.enabled = !0, n.setEffectiveWeight(1), n.fadeIn(r).play(), this.current?.fadeOut(r), this.current = n, this.currentName = e, this.followClipCamera();
	}
	loop = () => {
		if (this.disposed || this.contextLost || this.offscreen) {
			this.frame = 0;
			return;
		}
		this.frame = this.win.requestAnimationFrame(this.loop);
		let e = performance.now(), t = this.lastTick ? Math.min((e - this.lastTick) / 1e3, .1) : 0;
		this.lastTick = e, this.elapsed += t, this.restoreOffsets(), this.mixer?.update(t), this.moveCamera(t), this.applyFaceTrack(), this.applyArmSpread(), this.applyBreathing(), this.applyHeadFollow(t), this.applyAccents(), this.applyExpressions(t), this.pulseGlow(), this.vrm?.update(t), this.gl.render(this.scene, this.camera);
	};
	restoreOffsets() {
		for (let [e, t] of this.offsetBases) e.quaternion.copy(t);
		this.offsetBases.clear();
	}
	addRotation(e, t, n) {
		e && n && (this.offsetBases.has(e) || this.offsetBases.set(e, e.quaternion.clone()), e.rotation[t] += n);
	}
	applyArmSpread() {
		if (!this.armSpread) return;
		let e = this.vrm?.humanoid;
		if (!e) return;
		let t = this.armSpread * Math.PI / 180;
		this.addRotation(e.getNormalizedBoneNode("leftUpperArm"), "z", t), this.addRotation(e.getNormalizedBoneNode("rightUpperArm"), "z", -t);
	}
	applyBreathing() {
		let e = this.vrm?.humanoid;
		if (!e || this.reducedMotion) return;
		let t = e.getNormalizedBoneNode("chest") ?? e.getNormalizedBoneNode("spine");
		this.addRotation(t, "x", Math.sin(this.elapsed * 1.55) * .012);
		let n = e.getNormalizedBoneNode("spine");
		this.addRotation(n, "y", Math.sin(this.elapsed * .42) * .015), this.addRotation(n, "z", Math.cos(this.elapsed * .31) * .008);
	}
	applyHeadFollow(e) {
		let t = 1 - Math.exp(-e * 6);
		this.gazeNow.lerp(this.gazeTarget, t), this.gazePoint.copy(this.gazeBase).addScaledVector(this.camRight, this.gazeNow.x * 1.2).addScaledVector(this.camUp, this.gazeNow.y * .6), this.lookAtAnchor.position.lerp(this.gazePoint, t);
		let n = this.vrm?.humanoid?.getNormalizedBoneNode("neck"), r = this.opts.headFollow;
		this.addRotation(n, "y", this.gazeNow.x * .42 * r), this.addRotation(n, "x", -this.gazeNow.y * .26 * r);
	}
	applyAccents() {
		if (!this.accents.length) return;
		let e = this.vrm?.humanoid?.getNormalizedBoneNode("neck"), t = this.vrm?.humanoid?.getNormalizedBoneNode("head"), n = performance.now();
		this.accents = this.accents.filter((e) => n - e.t0 < e.dur);
		for (let r of this.accents) {
			let i = (n - r.t0) / r.dur, a = Math.sin(i * Math.PI);
			r.kind === "nod" ? this.addRotation(t ?? e, "x", a * .09) : r.kind === "emphasis" ? this.addRotation(t ?? e, "x", a * .14) : r.kind === "question" ? (this.addRotation(t ?? e, "x", -a * .06), this.addRotation(e, "z", a * .04)) : this.addRotation(e, "z", a * .05);
		}
	}
	applyExpressions(e) {
		let t = this.vrm?.expressionManager;
		if (!t) return;
		let n = 1 - Math.exp(-e * 9), r = performance.now(), i = this.speaking ? .55 : 1, a = "", o = 0;
		if (this.accentExpr) {
			let e = (r - this.accentExpr.t0) / this.accentExpr.dur;
			e >= 1 ? this.accentExpr = null : (a = this.accentExpr.name, o = this.accentExpr.weight * Math.sin(e * Math.PI));
		}
		let s = 0;
		for (let e of [
			"happy",
			"angry",
			"sad",
			"relaxed",
			"surprised"
		]) {
			let r = (this.expressionTarget[e] ?? 0) * i;
			e === a && (r = Math.max(r, o));
			let c = this.expressionNow[e] ?? 0, l = c + (r - c) * n;
			this.expressionNow[e] = l, t.setValue(e, l), s = Math.max(s, l);
		}
		let c = this.blinkUntil - performance.now(), l = c > 0 ? Math.min(1, c / (this.blinkDuration * .45)) : 0;
		this.blinkValue += (l - this.blinkValue) * (l > this.blinkValue ? .6 : .25), t.setValue("blink", this.blinkValue * (1 - s * .7));
		for (let n of [
			"aa",
			"ih",
			"ou",
			"ee",
			"oh"
		]) {
			let r = this.visemeTarget[n] ?? 0, i = this.visemeNow[n] ?? 0, a = r > i ? 26 : 17, o = i + (r - i) * (1 - Math.exp(-e * a));
			this.visemeNow[n] = o, t.setValue(n, o);
		}
	}
	applyGlow() {
		this.pulseGlow(!0);
	}
	pulseGlow(e = !1) {
		if (!this.rimMaterials.length) return;
		let t = this.glow.pulseHz > 0 && !this.reducedMotion ? .62 + .38 * Math.sin(this.elapsed * Math.PI * 2 * this.glow.pulseHz) : 1, n = this.glow.intensity * t;
		if (!(!e && Math.abs(n) < 1e-4)) for (let e of this.rimMaterials) e.parametricRimColorFactor?.copy(this.glowColor).multiplyScalar(n), e.parametricRimFresnelPowerFactor = 3.2, e.parametricRimLiftFactor = 0, e.rimLightingMixFactor = 1;
	}
};
//#endregion
export { k as a, O as i, z as n, M as o, P as r, j as s, q as t };

//# sourceMappingURL=VrmRenderer-B1rHzowq.js.map