//#region src/mascot/core/clips.ts
var e = (e, t = "inplace") => ({
	url: "anim/vrma/" + encodeURIComponent(e),
	mask: t
}), t = {
	idle: e("Idle.vrma"),
	happyIdle: e("Happy Idle.vrma"),
	sad: e("Sad Idle.vrma"),
	victory: e("Victory Idle.vrma"),
	wave: e("Waving.vrma"),
	thinking: e("Thinking.vrma"),
	lookAround: e("Look Around.vrma"),
	talking: e("Talking.vrma"),
	thankful: e("Thankful.vrma"),
	dismiss: e("Dismissing Gesture.vrma"),
	nod: e("Head Nod Yes.vrma"),
	dwarfIdle: e("Dwarf Idle.vrma"),
	reacting: e("Reacting.vrma"),
	showBody: e("VRMA_01.vrma"),
	greeting: e("VRMA_02.vrma", "none"),
	peace: e("VRMA_03.vrma"),
	shoot: e("VRMA_04.vrma"),
	spin: e("VRMA_05.vrma"),
	modelPose: e("VRMA_06.vrma"),
	squat: e("VRMA_07.vrma"),
	motionPose: e("001_motion_pose.vrma"),
	airplane: e("CC0animation3airplane05.vrma"),
	bored: e("CC0animationhima01.vrma"),
	idleAlt: e("CC0animationidle04.vrma"),
	twirl: e("CC0animationkurukuru01.vrma"),
	other: e("CC0animationother2.vrma"),
	rotate: e("CC0animationrotate02.vrma"),
	rotateAlt: e("CC0animationrotate7.vrma"),
	turnLeft: e("CC0animationrotate_left1.vrma"),
	turnRight: e("CC0animationrotate_right2.vrma"),
	smallWave: e("CC0animationsmallwve.vrma"),
	stand: e("CC0animationstand01.vrma"),
	unknown3: e("CC0animationunknown3.vrma"),
	unknown4: e("CC0animationunknown4.vrma"),
	unwave: e("CC0animationunwave.vrma"),
	danceKawaii: e("Kawaii Kaiwai.vrma"),
	danceMugi: e("うい麦畑でつかまえて.vrma"),
	danceSynth: e("ハッピーシンセサイザ.vrma"),
	danceScream: e("愛♡スクリ〜ム！.vrma")
}, n = [
	"danceKawaii",
	"danceMugi",
	"danceSynth",
	"danceScream"
];
function r(e) {
	return (Object.prototype.hasOwnProperty.call(t, e) ? t[e] : void 0) || (/\.vrma$/i.test(e) ? {
		url: e,
		mask: "inplace"
	} : null);
}
var i = [
	"idle",
	"thinking",
	"wave"
];
//#endregion
//#region src/mascot/core/faceTrack.ts
function a(e, t) {
	let n = -1;
	for (let r = 0; r < e.length && e[r].at <= t; r++) n = r;
	return n;
}
var o = (e) => [...e].sort((e, t) => e.at - t.at), s = [
	"neutral",
	"happy",
	"angry",
	"sad",
	"relaxed",
	"surprised"
], c = /^(?!__)[\p{L}\p{N}_-]{1,40}$/u, l = (e) => c.test(e), u = (e, t, n, r) => typeof e == "number" && Number.isFinite(e) ? Math.min(n, Math.max(t, e)) : r, d = /^#[0-9a-f]{6}$/i;
function f(e) {
	if (!e || typeof e != "object") return null;
	let t = e;
	if (!s.includes(t.expression)) return null;
	let n = typeof t.action == "string" && t.action || Array.isArray(t.action) && t.action.every((e) => typeof e == "string") && t.action.length ? t.action : void 0, r = t.resetAfterMs === "clip" || t.resetAfterMs === null ? t.resetAfterMs : typeof t.resetAfterMs == "number" ? u(t.resetAfterMs, 100, 6e5, 3e3) : null, i = t.glow && typeof t.glow == "object" ? t.glow : {}, a = m(t.faceTrack), o = p(t.trim);
	return {
		expression: t.expression,
		weight: u(t.weight, 0, 1, .5),
		...n ? { action: n } : {},
		loop: t.loop === !0,
		resetAfterMs: r,
		...t.speakOver === !0 ? { speakOver: !0 } : {},
		...typeof t.rootMotion == "boolean" ? { rootMotion: t.rootMotion } : {},
		...t.followPointer === !0 ? { followPointer: !0 } : {},
		...typeof t.fadeMs == "number" ? { fadeMs: Math.round(u(t.fadeMs, 0, 3e3, 280)) } : {},
		...o ? { trim: o } : {},
		...a.length ? { faceTrack: a } : {},
		glow: {
			color: typeof i.color == "string" && d.test(i.color) ? i.color : "#9ED8BC",
			intensity: u(i.intensity, 0, 1, .4),
			pulseHz: u(i.pulseHz, 0, 5, 0)
		}
	};
}
function p(e) {
	if (!Array.isArray(e) || e.length !== 2) return null;
	let [t, n] = e;
	if (typeof t != "number" || typeof n != "number" || !Number.isFinite(t) || !Number.isFinite(n)) return null;
	let r = Math.round(u(t, 0, 600, 0) * 100) / 100, i = Math.round(u(n, 0, 600, 0) * 100) / 100;
	return i - r >= .05 ? [r, i] : null;
}
function m(e) {
	if (!Array.isArray(e)) return [];
	let t = [];
	for (let n of e.slice(0, 64)) {
		if (!n || typeof n != "object") continue;
		let e = n;
		s.includes(e.expression) && typeof e.at == "number" && Number.isFinite(e.at) && t.push({
			at: Math.round(u(e.at, 0, 600, 0) * 100) / 100,
			expression: e.expression,
			weight: u(e.weight, 0, 1, .5)
		});
	}
	return o(t);
}
function h(e) {
	let t = {};
	if (!e || typeof e != "object" || Array.isArray(e)) return t;
	for (let [n, r] of Object.entries(e)) {
		let e = l(n) ? f(r) : null;
		e && (t[n] = e);
	}
	return t;
}
var g = {
	67: {
		expression: "happy",
		weight: .7,
		action: "anim/vrma/67_hXBrhdpmbtpo6dwf3zVGyw(includeTPose).vrma",
		loop: !0,
		resetAfterMs: null,
		speakOver: !0,
		rootMotion: !1,
		fadeMs: 1500,
		trim: [6.4, 8.5],
		glow: {
			color: "#9ED8BC",
			intensity: 1,
			pulseHz: 0
		}
	},
	victory_demo: {
		expression: "relaxed",
		weight: .7,
		action: "victory",
		loop: !1,
		resetAfterMs: "clip",
		speakOver: !0,
		faceTrack: [{
			at: .81,
			expression: "happy",
			weight: .7
		}, {
			at: 1.3,
			expression: "relaxed",
			weight: .7
		}],
		glow: {
			color: "#9ED8BC",
			intensity: .5,
			pulseHz: 0
		}
	},
	hellow: {
		expression: "neutral",
		weight: 0,
		action: "wave",
		loop: !1,
		resetAfterMs: 3200,
		faceTrack: [{
			at: .3,
			expression: "happy",
			weight: .6
		}, {
			at: .6,
			expression: "neutral",
			weight: .6
		}],
		glow: {
			color: "#9ED8BC",
			intensity: .5,
			pulseHz: 0
		}
	},
	wellcome: {
		expression: "neutral",
		weight: 0,
		action: "wave",
		loop: !1,
		resetAfterMs: 3200,
		faceTrack: [{
			at: .3,
			expression: "happy",
			weight: .6
		}, {
			at: .6,
			expression: "neutral",
			weight: .6
		}],
		glow: {
			color: "#9ED8BC",
			intensity: .5,
			pulseHz: 0
		}
	},
	приветствие_фурина: {
		expression: "neutral",
		weight: 0,
		action: "spin",
		loop: !1,
		resetAfterMs: "clip",
		speakOver: !0,
		faceTrack: [
			{
				at: 2.6,
				expression: "happy",
				weight: .7
			},
			{
				at: 3.98,
				expression: "relaxed",
				weight: .7
			},
			{
				at: 5.31,
				expression: "happy",
				weight: .7
			},
			{
				at: 6,
				expression: "relaxed",
				weight: .7
			}
		],
		glow: {
			color: "#9ED8BC",
			intensity: .5,
			pulseHz: 0
		}
	},
	мир_укороченый: {
		expression: "neutral",
		weight: 0,
		action: "peace",
		loop: !1,
		resetAfterMs: "clip",
		speakOver: !0,
		trim: [0, 2.2],
		faceTrack: [{
			at: 1.2,
			expression: "happy",
			weight: .7
		}],
		glow: {
			color: "#9ED8BC",
			intensity: .5,
			pulseHz: 0
		}
	},
	greeting: {
		expression: "neutral",
		weight: 0,
		action: "greeting",
		loop: !1,
		resetAfterMs: "clip",
		speakOver: !0,
		fadeMs: 1500,
		trim: [1, 7.27],
		glow: {
			color: "#9ED8BC",
			intensity: .5,
			pulseHz: 0
		}
	},
	вращение: {
		expression: "angry",
		weight: .7,
		action: "rotateAlt",
		loop: !0,
		resetAfterMs: null,
		speakOver: !0,
		fadeMs: 1500,
		trim: [1.56, 5.74],
		glow: {
			color: "#9ED8BC",
			intensity: 1,
			pulseHz: 0
		}
	},
	"67-2": {
		expression: "angry",
		weight: .7,
		action: "anim/vrma/67_hXBrhdpmbtpo6dwf3zVGyw(includeTPose).vrma",
		loop: !1,
		resetAfterMs: "clip",
		speakOver: !0,
		trim: [10.6, 12.8],
		glow: {
			color: "#9ED8BC",
			intensity: .5,
			pulseHz: 0
		}
	},
	thinking: {
		expression: "relaxed",
		weight: .4,
		action: "thinking",
		loop: !0,
		resetAfterMs: null,
		glow: {
			color: "#D6457F",
			intensity: .45,
			pulseHz: .5
		}
	},
	welcome: {
		expression: "neutral",
		weight: 0,
		action: "wave",
		loop: !1,
		resetAfterMs: 3200,
		faceTrack: [{
			at: .3,
			expression: "happy",
			weight: .6
		}, {
			at: .6,
			expression: "neutral",
			weight: .6
		}],
		glow: {
			color: "#9ED8BC",
			intensity: .5,
			pulseHz: 0
		}
	}
}, _ = "#9ED8BC", v = "#D6457F", y = "#6C8FD6", b = {
	idle: {
		expression: "neutral",
		weight: 0,
		action: "idle",
		loop: !0,
		resetAfterMs: null,
		followPointer: !0,
		glow: {
			color: _,
			intensity: .25,
			pulseHz: 0
		}
	},
	welcome: {
		expression: "happy",
		weight: .6,
		action: "wave",
		loop: !1,
		resetAfterMs: 3200,
		glow: {
			color: _,
			intensity: .5,
			pulseHz: 0
		}
	},
	curious: {
		expression: "surprised",
		weight: .35,
		action: "reacting",
		loop: !1,
		resetAfterMs: 1500,
		glow: {
			color: _,
			intensity: .4,
			pulseHz: 0
		}
	},
	thinking: {
		expression: "relaxed",
		weight: .4,
		action: "thinking",
		loop: !0,
		resetAfterMs: null,
		glow: {
			color: v,
			intensity: .45,
			pulseHz: .5
		}
	},
	searching: {
		expression: "neutral",
		weight: 0,
		action: "lookAround",
		loop: !0,
		resetAfterMs: null,
		glow: {
			color: v,
			intensity: .4,
			pulseHz: .8
		}
	},
	analyzing: {
		expression: "relaxed",
		weight: .3,
		action: "thinking",
		loop: !0,
		resetAfterMs: null,
		glow: {
			color: v,
			intensity: .5,
			pulseHz: 1.2
		}
	},
	comparing: {
		expression: "relaxed",
		weight: .25,
		action: "lookAround",
		loop: !0,
		resetAfterMs: null,
		glow: {
			color: v,
			intensity: .45,
			pulseHz: .9
		}
	},
	excited: {
		expression: "happy",
		weight: .9,
		action: "victory",
		loop: !1,
		resetAfterMs: 3e3,
		glow: {
			color: v,
			intensity: .8,
			pulseHz: 2.5
		}
	},
	success: {
		expression: "happy",
		weight: .8,
		action: "peace",
		loop: !1,
		resetAfterMs: "clip",
		speakOver: !0,
		glow: {
			color: _,
			intensity: .9,
			pulseHz: 0
		}
	},
	gentle: {
		expression: "relaxed",
		weight: .5,
		action: "thankful",
		loop: !1,
		resetAfterMs: 3e3,
		glow: {
			color: _,
			intensity: .35,
			pulseHz: 0
		}
	},
	error: {
		expression: "sad",
		weight: .7,
		action: "sad",
		loop: !0,
		resetAfterMs: 5e3,
		glow: {
			color: y,
			intensity: .3,
			pulseHz: 0
		}
	},
	retry: {
		expression: "sad",
		weight: .4,
		action: "dismiss",
		loop: !1,
		resetAfterMs: 2800,
		glow: {
			color: y,
			intensity: .4,
			pulseHz: 1.5
		}
	},
	dance: {
		expression: "happy",
		weight: .7,
		action: n,
		loop: !1,
		resetAfterMs: "clip",
		speakOver: !0,
		glow: {
			color: v,
			intensity: .7,
			pulseHz: 2
		}
	},
	speaking: {
		expression: "neutral",
		weight: 0,
		action: "talking",
		loop: !0,
		resetAfterMs: null,
		glow: {
			color: _,
			intensity: .5,
			pulseHz: 0
		}
	}
}, x = Object.assign(Object.create(null), h(g)), S = Object.assign(Object.create(null), b, x), C = (e) => Object.prototype.hasOwnProperty.call(S, e);
function ee(e, t) {
	S[e] = t;
}
function te(e) {
	delete x[e];
	let t = Object.prototype.hasOwnProperty.call(b, e) ? b[e] : void 0;
	t ? S[e] = t : delete S[e];
}
//#endregion
//#region src/mascot/core/transitions.ts
var w = "→", T = (e, t) => `${e}${w}${t}`, ne = /^(?!__)[\p{L}\p{N}_ -]{1,40}$/u, E = (e) => ne.test(e), D = (e) => typeof e == "number" && Number.isFinite(e) ? Math.round(Math.min(3e3, Math.max(0, e))) : null;
function re(e) {
	if (!e || typeof e != "object") return null;
	let t = e;
	if (t.kind !== "state" && t.kind !== "clip" || typeof t.name != "string" || !t.name || t.name.length > 300) return null;
	let n = typeof t.secs == "number" && Number.isFinite(t.secs) ? Math.min(60, Math.max(.5, t.secs)) : 3;
	return {
		kind: t.kind,
		name: t.name,
		mode: t.mode === "secs" ? "secs" : "end",
		secs: n,
		fadeMs: t.fadeMs == null ? null : D(t.fadeMs)
	};
}
function O(e) {
	let t = {
		transitions: {},
		chains: {}
	};
	if (!e || typeof e != "object" || Array.isArray(e)) return t;
	let n = e;
	if (n.transitions && typeof n.transitions == "object") for (let [e, r] of Object.entries(n.transitions)) {
		let n = e.split(w), i = D(r);
		n.length === 2 && n[0] && n[1] && i != null && (t.transitions[e] = i);
	}
	if (n.chains && typeof n.chains == "object") for (let [e, r] of Object.entries(n.chains)) {
		if (!E(e) || !Array.isArray(r)) continue;
		let n = r.map(re).filter((e) => e !== null).slice(0, 50);
		n.length && (t.chains[e] = n);
	}
	return t;
}
//#endregion
//#region src/mascot/core/transitionTable.ts
var k = O({
	transitions: {
		"мир_укороченый→idle": 1500,
		"greeting→idle": 800,
		"приветствие_фурина→idle": 1160,
		"67→idle": 760
	},
	chains: {}
}), A = { ...k.transitions }, j = { ...k.chains };
function M(e, t) {
	return A[T(e, t)];
}
function N(e, t, n) {
	A[T(e, t)] = Math.max(0, n);
}
function P(e, t) {
	delete A[T(e, t)];
}
//#endregion
//#region src/mascot/motion.ts
function F(e = "auto") {
	if (e !== "auto") return e;
	try {
		return globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? !1;
	} catch {
		return !1;
	}
}
//#endregion
//#region src/mascot/voice/AudioLipSync.ts
var I = class {
	analyser = null;
	source = null;
	freq = new Uint8Array(/* @__PURE__ */ new ArrayBuffer(0));
	time = new Uint8Array(/* @__PURE__ */ new ArrayBuffer(0));
	attach(e, t) {
		this.detach();
		let n = t.createAnalyser();
		n.fftSize = 1024, n.smoothingTimeConstant = .55, e.connect(n), this.source = e, this.analyser = n, this.freq = new Uint8Array(new ArrayBuffer(n.frequencyBinCount)), this.time = new Uint8Array(new ArrayBuffer(n.fftSize));
	}
	detach() {
		if (this.source && this.analyser) try {
			this.source.disconnect(this.analyser);
		} catch {}
		this.source = null, this.analyser = null;
	}
	get active() {
		return this.analyser !== null;
	}
	sample() {
		let e = this.analyser;
		if (!e) return {};
		e.getByteTimeDomainData(this.time);
		let t = 0;
		for (let e = 0; e < this.time.length; e++) {
			let n = (this.time[e] - 128) / 128;
			t += n * n;
		}
		let n = Math.sqrt(t / this.time.length), r = Math.min(1, Math.max(0, (n - .012) * 7));
		if (r < .02) return {};
		e.getByteFrequencyData(this.freq);
		let i = 0, a = 0;
		for (let e = 0; e < this.freq.length; e++) i += e * this.freq[e], a += this.freq[e];
		let o = a > 0 ? i / a / this.freq.length : .3, s;
		return s = o < .1 ? "ou" : o < .16 ? "oh" : o < .24 ? "aa" : o < .34 ? "ee" : "ih", { [s]: r };
	}
}, L = (e) => new Promise((t) => setTimeout(t, e)), R = ["Irina"], z = class e {
	name = "browser";
	hasBoundaries = !0;
	opts;
	lastCancelAt = 0;
	generation = 0;
	finishCurrent = null;
	constructor(e = {}) {
		this.opts = e;
	}
	static isAvailable() {
		return typeof window < "u" && "speechSynthesis" in window;
	}
	static async loadVoices(t = 1500) {
		if (!e.isAvailable()) return [];
		let n = speechSynthesis.getVoices();
		return n.length ? n : new Promise((e) => {
			let n = !1, r = () => {
				n || (n = !0, e(speechSynthesis.getVoices()));
			};
			speechSynthesis.addEventListener("voiceschanged", r, { once: !0 }), setTimeout(r, t);
		});
	}
	static async list() {
		return (await e.loadVoices()).map((e) => ({
			name: e.name,
			lang: e.lang,
			local: e.localService,
			isDefault: e.default
		}));
	}
	setOptions(e) {
		this.opts = {
			...this.opts,
			...e
		};
	}
	getOptions() {
		return { ...this.opts };
	}
	static score(e, t) {
		let n = e.name.toLowerCase(), r = t.findIndex((e) => n.includes(e.toLowerCase()));
		if (r >= 0) return 1e3 - r * 10;
		let i = 0;
		return n.includes("google") && (i += 100), (n.includes("natural") || n.includes("neural")) && (i += 80), n.includes("online") && (i += 30), n.includes("microsoft") && !n.includes("natural") && (i -= 25), e.default && (i += 5), i;
	}
	static choose(t, { lang: n = "ru-RU", voiceName: r, prefer: i = R } = {}) {
		if (r) {
			let e = t.find((e) => e.name === r);
			if (e) return e;
		}
		let a = n.slice(0, 2), o = t.filter((e) => e.lang.replace("_", "-").slice(0, 2) === a);
		return o.length ? [...o].sort((t, n) => e.score(n, i) - e.score(t, i))[0] : t.find((e) => e.default) ?? t[0] ?? null;
	}
	pick(t, n) {
		return e.choose(t, {
			...this.opts,
			lang: n
		});
	}
	async speak(t, n) {
		let r = ++this.generation, i = () => r !== this.generation;
		if (!e.isAvailable()) {
			n.onError?.(/* @__PURE__ */ Error("speechSynthesis недоступен в этом браузере")), n.onEnd?.();
			return;
		}
		let a = this.opts.lang ?? "ru-RU", o = await e.loadVoices();
		if (i()) {
			n.onEnd?.();
			return;
		}
		if (!o.length) {
			n.onError?.(/* @__PURE__ */ Error("в системе не найдено ни одного голоса")), n.onEnd?.();
			return;
		}
		speechSynthesis.paused && speechSynthesis.resume(), (speechSynthesis.speaking || speechSynthesis.pending) && (this.finishCurrent?.(), speechSynthesis.cancel(), this.lastCancelAt = performance.now(), await L(120));
		let s = performance.now() - this.lastCancelAt;
		if (s < 120 && await L(120 - s), i()) {
			n.onEnd?.();
			return;
		}
		let c = this.pick(o, a);
		return new Promise((e) => {
			let r = new SpeechSynthesisUtterance(t);
			r.lang = c?.lang ?? a, r.rate = this.opts.rate ?? 1, r.pitch = this.opts.pitch ?? 1.05, c && (r.voice = c);
			let i, o, s = !1, l = () => {
				s || (s = !0, clearTimeout(i), clearInterval(o), this.finishCurrent === l && (this.finishCurrent = null), n.onEnd?.(), e());
			};
			this.finishCurrent = l, r.onstart = () => n.onStart?.(), r.onboundary = (e) => {
				(e.name === "word" || e.name === void 0) && n.onBoundary?.(e.charIndex);
			}, r.onend = l, r.onerror = (e) => {
				let t = e.error;
				t !== "canceled" && t !== "interrupted" && n.onError?.(e), l();
			};
			let u = 1200 + t.length * 110 / (r.rate || 1);
			i = setTimeout(() => {
				speechSynthesis.speaking || l();
			}, u * 1.8), speechSynthesis.speak(r), o = setInterval(() => {
				speechSynthesis.speaking && (speechSynthesis.pause(), speechSynthesis.resume());
			}, 9e3);
		});
	}
	cancel() {
		this.generation++, this.finishCurrent?.(), e.isAvailable() && (speechSynthesis.cancel(), this.lastCancelAt = performance.now());
	}
}, B = {
	а: "aa",
	я: "aa",
	о: "oh",
	ё: "oh",
	у: "ou",
	ю: "ou",
	и: "ih",
	ы: "ih",
	е: "ee",
	э: "ee"
}, V = {
	м: {
		viseme: null,
		weight: 0
	},
	б: {
		viseme: null,
		weight: 0
	},
	п: {
		viseme: null,
		weight: 0
	},
	ш: {
		viseme: "ou",
		weight: .45
	},
	ж: {
		viseme: "ou",
		weight: .45
	},
	щ: {
		viseme: "ou",
		weight: .4
	},
	ч: {
		viseme: "ou",
		weight: .4
	},
	ф: {
		viseme: "ih",
		weight: .3
	},
	в: {
		viseme: "ih",
		weight: .3
	}
}, H = {
	viseme: "ih",
	weight: .22
}, U = 68, W = 1.35, G = 160, K = 330;
function q(e, t = 1) {
	let n = [], r = [], i = 1 / Math.max(t, .1), a = 0, o = (e) => {
		n.push(e), a += e.durationMs;
	};
	for (let t = 0; t < e.length; t++) {
		let n = e[t].toLowerCase();
		if (B[n]) {
			o({
				viseme: B[n],
				weight: 1,
				durationMs: U * W * i,
				charIndex: t
			});
			continue;
		}
		if (/[а-яё]/.test(n)) {
			let e = V[n] ?? H;
			o({
				viseme: e.viseme,
				weight: e.weight,
				durationMs: U * i,
				charIndex: t
			});
			continue;
		}
		if (/[a-z]/.test(n)) {
			o({
				viseme: "aeiou".includes(n) ? "aa" : "ih",
				weight: "aeiou".includes(n) ? .85 : .22,
				durationMs: U * i,
				charIndex: t
			});
			continue;
		}
		if (",;:".includes(n)) {
			o({
				viseme: null,
				weight: 0,
				durationMs: G * i,
				charIndex: t
			}), r.push({
				atCharIndex: t,
				kind: "pause"
			});
			continue;
		}
		if (".!?…".includes(n)) {
			o({
				viseme: null,
				weight: 0,
				durationMs: K * i,
				charIndex: t
			}), r.push({
				atCharIndex: t,
				kind: n === "?" ? "question" : "nod"
			});
			continue;
		}
		n === " " && o({
			viseme: null,
			weight: 0,
			durationMs: U * .6 * i,
			charIndex: t
		});
	}
	return {
		steps: n,
		accents: r,
		totalMs: a
	};
}
//#endregion
//#region src/mascot/voice/Voice.ts
var J = class {
	provider;
	audio = new I();
	sink = null;
	plan = null;
	startedAt = 0;
	driftMs = 0;
	firedAccents = /* @__PURE__ */ new Set();
	seq = 0;
	frame = 0;
	win = window;
	rate;
	gain;
	constructor(e = {}) {
		this.provider = e.provider ?? new z({ rate: e.rate ?? 1 }), this.rate = e.rate ?? 1, this.gain = e.mouthGain ?? .9;
	}
	setSink(e) {
		this.sink = e;
	}
	setFrameSource(e) {
		this.frame &&= (this.win.cancelAnimationFrame(this.frame), 0), this.win = e, this.plan && this.tick();
	}
	setVoiceOptions(e) {
		e.rate != null && (this.rate = e.rate), this.provider.setOptions?.(e);
	}
	setProvider(e) {
		this.seq++, this.provider.cancel(), this.provider = e, this.stop();
	}
	get isSpeaking() {
		return this.plan !== null;
	}
	async say(e) {
		let t = e.trim();
		if (!t) return;
		this.stopLocal();
		let n = ++this.seq, r = () => n === this.seq;
		this.plan = q(t, this.rate), this.firedAccents.clear(), this.driftMs = 0, this.startedAt = performance.now(), this.sink?.speaking(!0), this.tick();
		try {
			await this.provider.speak(t, {
				onStart: () => {
					r() && (this.startedAt = performance.now());
				},
				onBoundary: (e) => {
					r() && this.resync(e);
				},
				onAudio: (e, t) => {
					r() && this.audio.attach(e, t);
				},
				onEnd: () => {
					r() && this.stop();
				},
				onError: () => {
					r() && this.stop();
				}
			});
		} catch (e) {
			throw r() && this.stop(), e;
		}
	}
	cancel() {
		this.seq++, this.provider.cancel(), this.stop();
	}
	stopLocal() {
		this.frame &&= (this.win.cancelAnimationFrame(this.frame), 0), this.plan = null, this.audio.detach();
	}
	stop() {
		let e = this.plan !== null || this.frame !== 0;
		this.stopLocal(), e && (this.sink?.visemes({}), this.sink?.speaking(!1));
	}
	resync(e) {
		let t = this.plan;
		if (!t) return;
		let n = 0;
		for (let r of t.steps) {
			if (r.charIndex >= e) break;
			n += r.durationMs;
		}
		let r = performance.now() - this.startedAt;
		this.driftMs += (n - r - this.driftMs) * .5;
	}
	tick = () => {
		let e = this.plan;
		if (!e) return;
		if (this.frame = this.win.requestAnimationFrame(this.tick), this.audio.active) {
			let e = this.audio.sample();
			this.sink?.visemes(Y(e, this.gain));
			return;
		}
		let t = performance.now() - this.startedAt + this.driftMs, n = 0, r = null;
		for (let i of e.steps) if (n += i.durationMs, t < n) {
			r = i;
			break;
		}
		r ? (this.sink?.visemes(r.viseme ? Y({ [r.viseme]: r.weight }, this.gain) : {}), this.fireAccents(r.charIndex)) : this.sink?.visemes({});
	};
	fireAccents(e) {
		let t = this.plan;
		if (t) for (let n of t.accents) n.atCharIndex <= e && !this.firedAccents.has(n.atCharIndex) && (this.firedAccents.add(n.atCharIndex), this.sink?.accent(n.kind));
	}
}, Y = (e, t) => {
	let n = {};
	for (let [r, i] of Object.entries(e)) n[r] = (i ?? 0) * t;
	return n;
}, ie = {
	initialState: "idle",
	trackPointer: !0,
	blinkRange: [2200, 6500],
	reducedMotion: "auto",
	debug: !1
}, X = class {
	renderer = null;
	pendingRenderer = null;
	stateClip = null;
	lastPicked = null;
	opts;
	listeners = /* @__PURE__ */ new Set();
	state;
	resetTimer = null;
	blinkTimer = null;
	saccadeTimer = null;
	pointer = {
		x: 0,
		y: 0
	};
	saccade = {
		x: 0,
		y: 0
	};
	disposed = !1;
	container = null;
	onPointerMove;
	win = window;
	pointerWin = null;
	muted = !1;
	suppressed = !1;
	lastPointer = null;
	gazeFrame = 0;
	voice;
	stateBeforeSpeech = null;
	constructor(e = {}) {
		this.opts = {
			...ie,
			...e
		}, this.state = C(this.opts.initialState) ? this.opts.initialState : "idle", this.voice = new J(e.voice), this.voice.setSink({
			visemes: (e) => this.renderer?.setVisemes(e),
			accent: (e) => this.renderer?.accent(e),
			speaking: (e) => this.onSpeaking(e)
		});
	}
	onSpeaking(e) {
		if (this.renderer?.setSpeaking(e), this.emit({
			type: "speaking",
			active: e
		}), e) {
			if (S[this.state]?.speakOver) return;
			this.state !== "speaking" && (this.stateBeforeSpeech = this.state), this.setState("speaking");
		} else {
			let e = this.stateBeforeSpeech ?? "idle";
			if (this.stateBeforeSpeech = null, this.state !== "speaking") return;
			let t = S[e], n = t && t.action != null && !t.loop;
			this.setState(t && !n ? e : "idle");
		}
	}
	async attach(e, t) {
		this.detach(), this.pendingRenderer = e;
		try {
			await e.init(t);
		} catch (t) {
			this.pendingRenderer === e && (this.pendingRenderer = null), e.dispose(), this.emit({
				type: "error",
				error: t
			});
			return;
		}
		if (this.disposed || this.pendingRenderer !== e) {
			e.dispose();
			return;
		}
		this.pendingRenderer = null, this.renderer = e, e.onClipEnd = (e) => this.onClipEnd(e), this.container = t, this.win = t.ownerDocument.defaultView ?? window, this.voice.setFrameSource(this.win), S[this.state]?.resetAfterMs === "clip" && this.armReset(this.state), this.showState(this.state), this.startLife(), this.pushGaze(), this.emit({ type: "ready" });
	}
	detach(e) {
		if (e && e !== this.renderer && e !== this.pendingRenderer) {
			e.dispose();
			return;
		}
		let t = this.renderer !== null;
		this.stopLife(), this.container = null, this.pendingRenderer?.dispose(), this.pendingRenderer = null, this.renderer && (this.renderer.onClipEnd = null), this.renderer?.dispose(), this.renderer = null, this.win = window, this.voice.setFrameSource(window), t && S[this.state]?.resetAfterMs === "clip" && this.armReset(this.state), t && this.emit({ type: "detached" });
	}
	setState(e, t = {}) {
		if (!C(e)) {
			this.opts.debug && console.warn("[mascot] неизвестное состояние:", e);
			return;
		}
		let n = this.state;
		this.state = e, this.armReset(e), this.showState(e, t.fadeMs ?? M(n, e)), this.pushGaze(), this.emit({
			type: "state",
			state: e
		});
	}
	getState() {
		return this.state;
	}
	getRenderer() {
		return this.renderer;
	}
	playGesture(e) {
		let t = this.renderer;
		this.stateClip = e, t && (t.playClip(e, {
			loop: !1,
			fadeMs: 280,
			returnTo: this.idleClip()
		}), this.emit({
			type: "clip",
			name: e
		}));
	}
	armReset(e) {
		this.resetTimer &&= (clearTimeout(this.resetTimer), null);
		let t = S[e];
		if (!t) return;
		let n = t.resetAfterMs === "clip" ? this.renderer ? ae : oe : t.resetAfterMs;
		n != null && (this.resetTimer = setTimeout(() => {
			this.resetTimer = null, this.state === e && this.setState("idle");
		}, n));
	}
	showState(e, t) {
		let n = S[e], r = this.renderer;
		if (!r || !n) return;
		let i = (e === "speaking" && this.stateBeforeSpeech ? S[this.stateBeforeSpeech] : void 0) ?? n;
		r.setExpression(i.expression, i.weight), r.setGlow(i.glow), this.stateClip = null;
		let a = this.pickClip(n.action);
		r.setFaceTrack?.(a, n.faceTrack ?? null);
		let o = t ?? n.fadeMs ?? 280;
		if (a) r.playClip(a, {
			loop: n.loop ?? !1,
			fadeMs: o,
			...n.rootMotion == null ? {} : { mask: n.rootMotion ? "none" : "inplace" },
			...n.trim && typeof n.action == "string" ? { range: n.trim } : {},
			...n.loop ? {} : { returnTo: this.idleClip() }
		}), this.stateClip = a, this.emit({
			type: "clip",
			name: a
		});
		else {
			let e = this.idleClip();
			e && r.playClip(e, {
				loop: !0,
				fadeMs: o
			});
		}
	}
	idleClip() {
		let e = S.idle?.action;
		return typeof e == "string" ? e : void 0;
	}
	pickClip(e) {
		if (!e) return null;
		if (typeof e == "string") return e;
		let t = e.length > 1 ? e.filter((e) => e !== this.lastPicked) : e, n = t[Math.floor(Math.random() * t.length)] ?? null;
		return this.lastPicked = n, n;
	}
	onClipEnd(e) {
		e === this.stateClip && S[this.state]?.resetAfterMs === "clip" && (this.voice.isSpeaking ? (this.stateBeforeSpeech = "idle", this.setState("speaking")) : this.setState("idle"));
	}
	say(e) {
		this.emit({
			type: "say",
			text: e
		}), !(this.muted || this.suppressed) && this.voice.say(e).catch((e) => this.emit({
			type: "error",
			error: e
		}));
	}
	setMuted(e) {
		this.muted = e, e && this.voice.cancel(), this.emit({
			type: "muted",
			muted: e
		});
	}
	get isMuted() {
		return this.muted;
	}
	setVoiceSuppressed(e) {
		this.suppressed = e, e && this.voice.cancel();
	}
	hush() {
		this.voice.cancel();
	}
	setVoiceProvider(e) {
		this.voice.setProvider(e);
	}
	setVoiceOptions(e) {
		this.voice.setVoiceOptions(e);
	}
	get isSpeaking() {
		return this.voice.isSpeaking;
	}
	setMouth(e) {
		this.renderer?.setMouth(se(e));
	}
	startLife() {
		this.stopLife(), this.scheduleBlink(), F(this.opts.reducedMotion) || this.scheduleSaccade(), this.opts.trackPointer && this.startPointerTracking();
	}
	stopLife() {
		this.blinkTimer &&= (clearTimeout(this.blinkTimer), null), this.saccadeTimer &&= (clearTimeout(this.saccadeTimer), null), this.onPointerMove &&= (this.pointerWin?.removeEventListener("pointermove", this.onPointerMove), this.pointerWin = null, void 0), this.gazeFrame &&= (this.win.cancelAnimationFrame(this.gazeFrame), 0);
	}
	scheduleBlink() {
		if (this.disposed) return;
		let [e, t] = this.opts.blinkRange, n = e + Math.random() * (t - e);
		this.blinkTimer = setTimeout(() => {
			if (this.renderer?.blink(110), Math.random() < .18) {
				this.blinkTimer = setTimeout(() => {
					this.renderer?.blink(90), this.scheduleBlink();
				}, 190);
				return;
			}
			this.scheduleBlink();
		}, n);
	}
	scheduleSaccade() {
		if (this.disposed) return;
		let e = 900 + Math.random() * 2200;
		this.saccadeTimer = setTimeout(() => {
			this.saccade.x = (Math.random() - .5) * .14, this.saccade.y = (Math.random() - .5) * .1, this.pushGaze(), this.scheduleSaccade();
		}, e);
	}
	startPointerTracking() {
		this.onPointerMove = (e) => {
			this.lastPointer = {
				x: e.clientX,
				y: e.clientY
			}, this.gazeFrame ||= this.win.requestAnimationFrame(() => {
				this.gazeFrame = 0, this.updatePointerGaze();
			});
		}, this.pointerWin = this.win, this.win.addEventListener("pointermove", this.onPointerMove, { passive: !0 });
	}
	updatePointerGaze() {
		let e = this.lastPointer;
		if (!e) return;
		let t = this.renderer?.getHeadScreenPosition?.() ?? this.containerCenter(), n = Math.max(this.win.innerWidth / 2, 1), r = Math.max(this.win.innerHeight / 2, 1);
		this.pointer.x = Z((e.x - t.x) / n), this.pointer.y = Z(-(e.y - t.y) / r), this.pushGaze();
	}
	containerCenter() {
		let e = this.container?.getBoundingClientRect();
		return e ? {
			x: e.left + e.width / 2,
			y: e.top + e.height / 2
		} : {
			x: this.win.innerWidth / 2,
			y: this.win.innerHeight / 2
		};
	}
	lookAt(e, t) {
		this.pointer.x = Z(e), this.pointer.y = Z(t), this.pushGaze();
	}
	pushGaze() {
		let e = !this.opts.trackPointer || S[this.state]?.followPointer === !0, t = e ? this.pointer.x : 0, n = e ? this.pointer.y : 0;
		this.renderer?.setGaze(Z(t + this.saccade.x), Z(n + this.saccade.y));
	}
	on(e) {
		return this.listeners.add(e), () => {
			this.listeners.delete(e);
		};
	}
	emit(e) {
		this.opts.debug && console.debug("[mascot]", e);
		for (let t of this.listeners) try {
			t(e);
		} catch (e) {
			console.error("[mascot] слушатель упал", e);
		}
	}
	dispose() {
		this.disposed = !0, this.resetTimer &&= (clearTimeout(this.resetTimer), null), this.detach(), this.voice.cancel(), this.listeners.clear();
	}
}, ae = 6e4, oe = 3e3, se = (e) => e < 0 ? 0 : e > 1 ? 1 : e, Z = (e) => e < -1 ? -1 : e > 1 ? 1 : e, Q = null;
function ce(e) {
	return Q ? e && console.warn("[mascot] getMascot(options): экземпляр уже создан, опции проигнорированы. Передайте их в самый первый вызов getMascot() или connect().") : Q = new X(e), Q;
}
function le() {
	Q?.dispose(), Q = null;
}
//#endregion
//#region src/mascot/assets.ts
var $ = Symbol.for("mascot.originalFetch"), ue = globalThis.fetch;
function de() {
	let e = ue;
	for (; e[$];) e = e[$];
	return e;
}
async function fe(e) {
	let t = await de().call(globalThis, e);
	if (!t.ok) throw Error(`${t.status} ${t.statusText}: ${e}`);
	return t.arrayBuffer();
}
var pe = (e) => e.slice(0, e.lastIndexOf("/") + 1), me = /^(?:[a-z][a-z\d+.-]*:|\/)/i;
function he(e, t) {
	return me.test(e) ? e : (t.endsWith("/") ? t : t + "/") + e;
}
//#endregion
export { a as A, S as C, s as D, te as E, r as F, t as M, n as N, h as O, i as P, x as S, C as T, P as _, ce as a, T as b, J as c, R as d, I as f, N as g, A as h, he as i, o as j, f as k, q as l, j as m, pe as n, le as o, F as p, fe as r, X as s, $ as t, z as u, M as v, ee as w, b as x, O as y };

//# sourceMappingURL=assets-Cy_L-AgE.js.map