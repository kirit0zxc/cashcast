import { A as e, C as t, D as n, E as r, F as i, M as a, N as o, O as s, S as c, T as l, _ as u, a as d, b as f, c as p, d as m, f as h, g, h as _, k as v, l as y, m as b, o as x, s as S, t as C, u as w, v as T, w as E, x as D, y as O } from "./assets-Cy_L-AgE.js";
//#region src/mascot/bridge/normalize.ts
function k(e, t) {
	if (e == null) return;
	let n = e;
	for (let e of t.split(".")) {
		if (typeof n != "object" || !n) return;
		n = n[e];
	}
	return n;
}
function A(e) {
	return {
		raw: e,
		num(t, n = 0) {
			let r = k(e, t), i = typeof r == "string" ? Number(r) : r;
			return typeof i == "number" && Number.isFinite(i) ? i : n;
		},
		str(t, n = "") {
			let r = k(e, t);
			return typeof r == "string" ? r : typeof r == "number" || typeof r == "boolean" ? String(r) : n;
		},
		bool(t, n = !1) {
			let r = k(e, t);
			return typeof r == "boolean" ? r : r === "true" || r === 1 ? !0 : r === "false" || r === 0 ? !1 : n;
		},
		has(t) {
			return k(e, t) !== void 0;
		}
	};
}
function j(e) {
	if (typeof e == "string") {
		let t = e.trim();
		if (!t) return null;
		if (t.startsWith("{") || t.startsWith("[")) try {
			return j(JSON.parse(t));
		} catch {
			return {
				name: t,
				payload: null
			};
		}
		return {
			name: t,
			payload: null
		};
	}
	if (!e || typeof e != "object") return null;
	let t = e;
	for (let e of [
		"type",
		"event",
		"name",
		"action",
		"status",
		"state"
	]) {
		let n = t[e];
		if (typeof n == "string" && n) return {
			name: n,
			payload: t.payload ?? t.data ?? t
		};
	}
	return null;
}
//#endregion
//#region src/mascot/bridge/MascotBridge.ts
var M = (e) => typeof e == "string" ? e : e instanceof URL ? e.href : e.url, N = (e, t) => {
	try {
		return e(t);
	} catch {
		return !1;
	}
}, P = (e) => /^(?:blob|data):/i.test(e), F = Symbol.for("mascot.wrappedBy"), I = (e, t) => Object.prototype.hasOwnProperty.call(e, t), L = class {
	core;
	rules;
	opts;
	lastAt = -Infinity;
	cleanups = /* @__PURE__ */ new Set();
	deferred = null;
	deferTimer = null;
	inFlight = 0;
	batch = {
		failed: !1,
		succeeded: !1,
		status: 0
	};
	constructor(e, t, n = {}) {
		this.core = e, this.rules = t, this.opts = n;
	}
	extend(e) {
		this.rules = {
			...this.rules,
			...e
		};
	}
	handle(e, t) {
		try {
			this.dispatch(e, t);
		} catch (t) {
			console.warn("[mascot/bridge] событие не обработано", e, t);
		}
	}
	handleRaw(e) {
		let t = j(e);
		if (!t) {
			this.opts.debug && console.debug("[mascot/bridge] не понял сообщение", e);
			return;
		}
		this.handle(t.name, t.payload);
	}
	dispatch(e, t) {
		this.opts.debug && console.debug("[mascot/bridge] ←", e, t);
		let n = (I(this.rules, e) ? this.rules[e] : void 0) ?? this.opts.fallback ?? null;
		if (n == null) return;
		let r = this.resolve(n, A(t));
		if (r == null) return;
		let i = performance.now(), a = this.opts.throttleMs ?? 0;
		if (a && i - this.lastAt < a) {
			this.deferred = r, this.deferTimer ??= setTimeout(() => {
				this.deferTimer = null;
				let e = this.deferred;
				this.deferred = null, e && (this.lastAt = performance.now(), this.apply(e));
			}, a - (i - this.lastAt));
			return;
		}
		this.lastAt = i, this.apply(r);
	}
	apply(e) {
		try {
			if (typeof e == "string") {
				this.applyState(e);
				return;
			}
			e.state && this.applyState(e.state), e.clip && this.core.playGesture(e.clip), e.say && this.core.say(e.say);
		} catch (t) {
			console.warn("[mascot/bridge] реакция не выполнена", e, t);
		}
	}
	resolve(e, t, n = 0) {
		if (typeof e != "function") return e;
		if (n >= 3) return console.warn("[mascot/bridge] правило слишком глубоко вложено"), null;
		let r = e(t);
		return r == null ? null : this.resolve(r, t, n + 1);
	}
	applyState(e) {
		if (!l(e)) {
			console.warn("[mascot/bridge] неизвестное состояние:", e);
			return;
		}
		this.core.setState(e);
	}
	subscribe(e, t) {
		let n = Object.entries(t);
		for (let [t, r] of n) e.addEventListener(t, r);
		let r = () => {
			for (let [t, r] of n) e.removeEventListener(t, r);
			this.cleanups.delete(r);
		};
		return this.cleanups.add(r), r;
	}
	listen(e, t) {
		let n = {};
		for (let e of t) n[e] = (t) => this.handle(e, t.detail);
		return this.subscribe(e, n);
	}
	listenWebSocket(e) {
		return this.subscribe(e, {
			message: (e) => this.handleRaw(e.data),
			open: () => this.handle("ws:open"),
			close: (e) => {
				let { code: t, wasClean: n } = e;
				this.handle("ws:close", {
					code: t,
					wasClean: n
				});
			}
		});
	}
	listenEventSource(e, t = []) {
		let n = { message: (e) => this.handleRaw(e.data) };
		for (let e of t) n[e] = (t) => this.handle(e, t.data);
		return this.subscribe(e, n);
	}
	wrapFetch(e = fetch, t = {}) {
		if (e[F] === this) return e;
		let n = e === globalThis.fetch ? e.bind(globalThis) : e, { match: r } = t;
		return Object.assign(async (...e) => {
			let t = M(e[0]);
			if (P(t) || r && !N(r, t)) return n(...e);
			this.inFlight++ === 0 && (this.batch = {
				failed: !1,
				succeeded: !1,
				status: 0
			}, this.handle("request:start"));
			let i;
			try {
				i = await n(...e);
			} catch (e) {
				let t = e instanceof DOMException && e.name === "AbortError";
				throw this.settle(t ? { kind: "abort" } : {
					kind: "error",
					detail: { message: String(e) }
				}), e;
			}
			let a = i.type === "opaque" || i.type === "opaqueredirect";
			return this.settle(i.ok || a ? {
				kind: "ok",
				status: i.status
			} : {
				kind: "error",
				detail: { status: i.status }
			}), i;
		}, {
			[C]: n,
			[F]: this
		});
	}
	settle(e) {
		if (this.inFlight = Math.max(0, this.inFlight - 1), e.kind === "error") {
			this.batch.failed = !0, this.handle("request:error", e.detail);
			return;
		}
		e.kind === "ok" && (this.batch.succeeded = !0, this.batch.status = e.status), !(this.inFlight > 0 || this.batch.failed) && (this.batch.succeeded ? this.handle("request:done", { status: this.batch.status }) : this.handle("request:cancel"));
	}
	dispose() {
		for (let e of [...this.cleanups]) e();
		this.deferTimer &&= (clearTimeout(this.deferTimer), null), this.deferred = null;
	}
}, R = {
	"request:start": "thinking",
	"inference:start": "thinking",
	"predict:start": "thinking",
	loading: "thinking",
	"search:start": "searching",
	"retrieve:start": "searching",
	"analyze:start": "analyzing",
	"compare:start": "comparing",
	"request:done": (e) => {
		if (!e.has("confidence")) return "success";
		let t = e.num("confidence", 1);
		return t < .4 ? {
			state: "curious",
			say: "Я не уверена в этом результате."
		} : t < .7 ? "gentle" : "success";
	},
	"inference:done": (e) => e.num("confidence", 1) < .5 ? "curious" : "success",
	"predict:done": "success",
	done: "success",
	ready: "success",
	"request:error": {
		state: "error",
		say: "Что-то пошло не так. Попробуем ещё раз?"
	},
	error: "error",
	failed: "error",
	"request:retry": "retry",
	"request:cancel": "idle",
	retry: "retry",
	"ws:open": "welcome",
	"ws:close": (e) => e.bool("wasClean") && e.num("code") === 1e3 ? "idle" : "error",
	connected: "welcome",
	disconnected: "error",
	"user:input": "curious",
	"user:submit": "thinking"
};
//#endregion
//#region src/mascot/connect.ts
function z(e = {}) {
	let { rules: t, replaceRules: n, core: r, ...i } = e;
	return new L(d(r), n ? t ?? {} : {
		...R,
		...t
	}, i);
}
//#endregion
export { h as AudioLipSync, D as BUILTIN_STATES, w as BrowserTTS, b as CHAINS, a as CLIPS, o as DANCES, m as DEFAULT_PREFERRED_VOICES, R as DEFAULT_RULES, n as EXPRESSIONS, L as MascotBridge, S as MascotCore, c as PRESETS, t as STATES, _ as TRANSITIONS, p as Voice, z as connect, E as defineState, g as defineTransition, e as faceKeyAt, d as getMascot, A as normalize, j as parseEvent, s as parsePresets, O as parseTransitionsFile, y as planSpeech, r as removeState, u as removeTransition, x as resetMascot, i as resolveClip, v as toStateSpec, T as transitionFade, f as transitionKey };

//# sourceMappingURL=index.js.map