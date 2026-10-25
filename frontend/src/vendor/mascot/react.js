import { a as e, i as t } from "./assets-Cy_L-AgE.js";
import { useCallback as n, useEffect as r, useLayoutEffect as i, useMemo as a, useRef as o, useState as s } from "react";
import { Fragment as c, jsx as l, jsxs as u } from "react/jsx-runtime";
import { createPortal as d } from "react-dom";
//#region src/mascot/react/Mascot.tsx
var f = () => import("./VrmRenderer-B1rHzowq.js").then((e) => e.n);
function p({ core: t, renderer: n, className: i, style: a }) {
	let s = o(null);
	return r(() => {
		let r = s.current;
		if (!r) return;
		let i = t ?? e(), a = null, o = !1;
		return f().then(({ VrmRenderer: e }) => {
			o || (a = new e(n), i.attach(a, r));
		}, (e) => console.warn("[mascot] не удалось загрузить рендерер", e)), () => {
			o = !0, a && i.detach(a);
		};
	}, [t]), /* @__PURE__ */ l("div", {
		ref: s,
		className: i,
		style: {
			position: "relative",
			...a
		}
	});
}
//#endregion
//#region src/mascot/react/useMascot.ts
function m(t) {
	let n = a(() => t ?? e(), [t]), [i, o] = s(n.getState()), [c, l] = s(() => n.getRenderer() !== null), [u, d] = s(null), [f, p] = s(!1), [m, h] = s(() => n.isMuted);
	return r(() => {
		let e, t = n.on((t) => {
			t.type === "state" && o(t.state), t.type === "ready" && l(!0), t.type === "detached" && l(!1), t.type === "muted" && h(t.muted), t.type === "say" && (clearTimeout(e), d(t.text), e = setTimeout(() => d(null), 2e3 + t.text.length * 90)), t.type === "speaking" && (p(t.active), t.active || (clearTimeout(e), e = setTimeout(() => d(null), 700)));
		});
		return () => {
			clearTimeout(e), t();
		};
	}, [n]), {
		state: i,
		ready: c,
		bubble: u,
		speaking: f,
		muted: m,
		...a(() => ({
			set: (e) => n.setState(e),
			say: (e) => n.say(e),
			hush: () => n.hush(),
			setMuted: (e) => n.setMuted(e),
			setVoiceOptions: (e) => n.setVoiceOptions(e),
			lookAt: (e, t) => n.lookAt(e, t)
		}), [n]),
		core: n
	};
}
//#endregion
//#region src/mascot/react/window/MenuBar.tsx
function h({ sections: e }) {
	let [t, n] = s(-1), i = o(null), a = o([]), c = o(!1);
	function d(e) {
		return [...i.current?.querySelectorAll(`[data-menu="${e}"] .yumi-item:not(:disabled)`) ?? []];
	}
	r(() => {
		if (t < 0) return;
		let e = i.current?.ownerDocument ?? document, r = (e) => {
			i.current?.contains(e.target) || n(-1);
		};
		return e.addEventListener("pointerdown", r), () => e.removeEventListener("pointerdown", r);
	}, [t]), r(() => {
		t < 0 || !c.current || (c.current = !1, d(t)[0]?.focus());
	}, [t]);
	let f = (e) => {
		n(-1), a.current[e]?.focus();
	}, p = (r, i) => {
		let o = e.length;
		if (r.key === "ArrowRight" || r.key === "ArrowLeft") {
			r.preventDefault();
			let e = (i + (r.key === "ArrowRight" ? 1 : -1) + o) % o;
			a.current[e]?.focus(), t >= 0 && n(e);
		} else r.key === "ArrowDown" || r.key === "Enter" || r.key === " " ? (r.preventDefault(), c.current = !0, t === i ? d(i)[0]?.focus() : n(i)) : r.key === "Escape" && t >= 0 && f(i);
	}, m = (e, t) => {
		let n = d(t), r = n.indexOf(e.target);
		e.key === "ArrowDown" || e.key === "ArrowUp" ? (e.preventDefault(), n[(r + (e.key === "ArrowDown" ? 1 : -1) + n.length) % n.length]?.focus()) : e.key === "Escape" ? (e.preventDefault(), f(t)) : (e.key === "ArrowRight" || e.key === "ArrowLeft") && p(e, t);
	};
	return e.length ? /* @__PURE__ */ l("div", {
		className: "yumi-menubar",
		ref: i,
		role: "menubar",
		children: e.map((e, r) => /* @__PURE__ */ u("div", {
			className: "yumi-menu",
			"data-menu": r,
			children: [/* @__PURE__ */ l("button", {
				ref: (e) => {
					a.current[r] = e;
				},
				className: r === t ? "yumi-menu-btn yumi-menu-btn--open" : "yumi-menu-btn",
				role: "menuitem",
				"aria-haspopup": "menu",
				"aria-expanded": r === t,
				onClick: () => n(r === t ? -1 : r),
				onPointerEnter: () => {
					t >= 0 && n(r);
				},
				onKeyDown: (e) => p(e, r),
				children: e.label
			}), r === t && /* @__PURE__ */ l("div", {
				className: "yumi-dropdown",
				role: "menu",
				"aria-label": e.label,
				children: e.items.map((e, t) => e === null ? /* @__PURE__ */ l("div", {
					className: "yumi-sep",
					role: "separator"
				}, `sep-${t}`) : /* @__PURE__ */ u("button", {
					className: "yumi-item",
					role: e.checked === void 0 ? "menuitem" : "menuitemcheckbox",
					"aria-checked": e.checked,
					disabled: e.disabled,
					onClick: () => {
						f(r), e.onSelect();
					},
					onKeyDown: (e) => m(e, r),
					children: [/* @__PURE__ */ l("span", {
						className: "yumi-check",
						"aria-hidden": "true",
						children: e.checked ? "✓" : ""
					}), e.label]
				}, e.label))
			})]
		}, e.label))
	}) : null;
}
//#endregion
//#region src/mascot/react/window/styles.ts
var g = "\n.yumi-window, .yumi-tab, .yumi-dock {\n  --yumi-border: #9b6b9e;\n  --yumi-border-dark: #7b4f80;\n  --yumi-title: #dfa3d9;\n  --yumi-title-text: #7a4a86;\n  --yumi-menu: #f1a6c2;\n  --yumi-menu-hover: #e58bb0;\n  --yumi-body: #ffffff;\n  --yumi-accent: #f6c1d3;\n  --yumi-font: \"Pixelify Sans\", \"Press Start 2P\", ui-monospace, monospace;\n  --yumi-width: clamp(210px, 22vw, 340px);\n  --yumi-z: 2147483000;\n  font-family: var(--yumi-font);\n  box-sizing: border-box;\n}\n.yumi-window *, .yumi-dock * { box-sizing: border-box; }\n\n/* ─── Рамка ─────────────────────────────────────────────── */\n\n.yumi-window {\n  position: fixed;\n  z-index: var(--yumi-z);\n  width: var(--yumi-width);\n  display: flex; flex-direction: column;\n  border: 3px solid var(--yumi-border);\n  background: var(--yumi-menu);\n  /* Ступенчатая «пиксельная» тень вместо мягкой. */\n  box-shadow: 3px 3px 0 var(--yumi-border-dark), 6px 6px 0 rgba(123, 79, 128, .25);\n  user-select: none;\n  -webkit-user-select: none;\n  touch-action: none;\n}\n.yumi-window--pip {\n  position: static;\n  width: 100vw; height: 100vh;\n  box-shadow: none;\n}\n\n.yumi-titlebar {\n  display: flex; align-items: center; gap: 6px;\n  height: 30px;\n  padding: 0 4px 0 6px;\n  background: var(--yumi-title);\n  border-bottom: 3px solid var(--yumi-border);\n  color: var(--yumi-title-text);\n  cursor: grab;\n}\n.yumi-window--dragging .yumi-titlebar { cursor: grabbing; }\n.yumi-window--pip .yumi-titlebar { cursor: default; }\n\n.yumi-icon {\n  flex: 0 0 18px; height: 14px;\n  border: 2px solid var(--yumi-title-text);\n  border-radius: 2px;\n  background: var(--yumi-accent);\n  box-shadow: inset 0 -3px 0 var(--yumi-title-text);\n}\n.yumi-title {\n  flex: 1; min-width: 0;\n  font-size: 17px; font-weight: 600; letter-spacing: .02em;\n  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;\n}\n\n.yumi-tbtn {\n  flex: 0 0 24px; height: 22px;\n  display: grid; place-items: center;\n  padding: 0;\n  border: 0; background: none;\n  color: var(--yumi-title-text);\n  font: inherit; font-size: 18px; line-height: 1;\n  cursor: pointer;\n}\n.yumi-tbtn:hover { background: rgba(255, 255, 255, .35); }\n.yumi-tbtn:focus-visible, .yumi-menu-btn:focus-visible, .yumi-item:focus-visible,\n.yumi-tab:focus-visible, .yumi-stage:focus-visible { outline: 2px dashed var(--yumi-title-text); outline-offset: -2px; }\n.yumi-tbtn:disabled { opacity: .35; cursor: default; background: none; }\n\n/* Пиктограммы кнопок нарисованы рамками — чёткие на любом масштабе. */\n.yumi-ico-min { width: 12px; height: 4px; background: var(--yumi-accent); border: 2px solid var(--yumi-title-text); }\n.yumi-ico-max {\n  width: 14px; height: 13px;\n  border: 2px solid var(--yumi-title-text);\n  background: linear-gradient(var(--yumi-accent), var(--yumi-accent)) 70% 30% / 5px 5px no-repeat;\n}\n.yumi-ico-close { font-size: 20px; font-weight: 600; margin-top: -2px; }\n\n/* ─── Меню ──────────────────────────────────────────────── */\n\n.yumi-menubar {\n  position: relative;\n  display: flex; gap: 2px;\n  padding: 2px 4px;\n  background: var(--yumi-menu);\n  border-bottom: 3px solid var(--yumi-border);\n}\n.yumi-menu { position: relative; }\n.yumi-menu-btn {\n  padding: 1px 7px;\n  border: 0; background: none;\n  color: var(--yumi-title-text);\n  font: inherit; font-size: 16px;\n  cursor: pointer;\n}\n.yumi-menu-btn:hover, .yumi-menu-btn--open { background: var(--yumi-menu-hover); color: #fff; }\n\n.yumi-dropdown {\n  position: absolute; left: 0; top: calc(100% + 2px);\n  z-index: 2;\n  min-width: 170px;\n  padding: 3px;\n  border: 3px solid var(--yumi-border);\n  background: var(--yumi-body);\n  box-shadow: 3px 3px 0 var(--yumi-border-dark);\n}\n.yumi-item {\n  display: flex; align-items: center; gap: 6px;\n  width: 100%;\n  padding: 3px 8px 3px 4px;\n  border: 0; background: none;\n  color: var(--yumi-title-text);\n  font: inherit; font-size: 15px; text-align: left;\n  cursor: pointer;\n}\n.yumi-item:hover:not(:disabled) { background: var(--yumi-menu); }\n.yumi-item:disabled { opacity: .4; cursor: default; }\n.yumi-check { flex: 0 0 14px; text-align: center; }\n.yumi-sep { height: 2px; margin: 3px 2px; background: var(--yumi-accent); }\n\n/* ─── Сцена и реплика ───────────────────────────────────── */\n\n.yumi-body {\n  position: relative;\n  margin: 4px;\n  border: 3px solid var(--yumi-border);\n  background: var(--yumi-body);\n  /* Почти квадрат: по пояс, без пустого низа. */\n  aspect-ratio: 1 / 1.04;\n  overflow: hidden;\n}\n.yumi-window--pip .yumi-body { flex: 1; aspect-ratio: auto; }\n.yumi-stage { position: absolute; inset: 0; cursor: pointer; }\n\n/* ─── Фон сцены ─────────────────────────────────────────── */\n\n.yumi-body {\n  /* Где на сцене центр фона (туннеля) и во сколько раз фон больше сцены. */\n  --yumi-bg-x: 50%;\n  --yumi-bg-y: 36%;\n  --yumi-bg-size: 100%;\n  /* Пропорции картинки фона. */\n  --yumi-bg-ratio: 4 / 3;\n}\n/* Фон крупнее сцены и центрирован в точке (--yumi-bg-x, --yumi-bg-y):\n   так центр картинки встаёт за голову Юми. Минимальные размеры — от\n   центра до дальнего края сцены в обе стороны, поэтому края не\n   оголяются при любых значениях переменных и пропорциях окна. */\n.yumi-backdrop {\n  position: absolute;\n  left: var(--yumi-bg-x); top: var(--yumi-bg-y);\n  width: var(--yumi-bg-size);\n  aspect-ratio: var(--yumi-bg-ratio);\n  min-width: calc(2 * max(var(--yumi-bg-x), 100% - var(--yumi-bg-x)));\n  min-height: calc(2 * max(var(--yumi-bg-y), 100% - var(--yumi-bg-y)));\n  transform: translate(-50%, -50%);\n  pointer-events: none;\n  /* Пока картинка грузится или если не загрузилась — тёмная сцена. */\n  background: #0b0626 center / cover no-repeat;\n}\n\n.yumi-bubble {\n  position: absolute; left: 6px; right: 6px; bottom: 6px;\n  padding: 6px 9px;\n  border: 3px solid var(--yumi-border);\n  background: var(--yumi-body);\n  box-shadow: 3px 3px 0 var(--yumi-accent);\n  color: var(--yumi-title-text);\n  font-size: 15px; line-height: 1.25;\n  animation: yumi-pop .18s steps(3) both;\n  pointer-events: none;\n}\n@keyframes yumi-pop { from { transform: translateY(6px); opacity: 0; } to { transform: none; opacity: 1; } }\n\n/* ─── Вкладка свёрнутого окна ───────────────────────────── */\n\n.yumi-dock {\n  position: fixed; left: 0;\n  z-index: var(--yumi-z);\n  display: flex; align-items: flex-start; gap: 8px;\n  pointer-events: none;\n}\n.yumi-note {\n  max-width: min(260px, 60vw);\n  padding: 6px 9px;\n  border: 3px solid var(--yumi-border);\n  background: var(--yumi-body);\n  box-shadow: 3px 3px 0 var(--yumi-accent);\n  color: var(--yumi-title-text);\n  font-size: 15px; line-height: 1.25;\n  animation: yumi-pop .18s steps(3) both;\n}\n.yumi-tab {\n  pointer-events: auto;\n  display: flex; align-items: center; gap: 6px;\n  padding: 6px 10px 6px 8px;\n  border: 3px solid var(--yumi-border);\n  border-left: 0;\n  background: var(--yumi-title);\n  box-shadow: 3px 3px 0 var(--yumi-border-dark);\n  color: var(--yumi-title-text);\n  font-size: 16px; font-weight: 600;\n  cursor: pointer;\n}\n.yumi-tab:hover { background: var(--yumi-menu); }\n.yumi-tab--slim { padding: 10px 4px; }\n\n@media (max-width: 600px) {\n  .yumi-window { --yumi-width: min(64vw, 250px); }\n  .yumi-title { font-size: 15px; }\n  .yumi-menu-btn { font-size: 14px; padding: 1px 5px; }\n}\n\n@media (prefers-reduced-motion: reduce) {\n  .yumi-bubble, .yumi-note { animation: none; }\n}\n", _ = "yumi-window-styles", v = "yumi-window-font", y = "https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@400;600&display=swap";
function b(e, t = !0, n) {
	if (!e.getElementById(_)) {
		let t = e.createElement("style");
		t.id = _, n && (t.nonce = n), t.textContent = g, e.head.appendChild(t);
	}
	if (t && !e.getElementById(v)) {
		let t = e.createElement("link");
		t.id = v, t.rel = "stylesheet", t.href = y, e.head.appendChild(t);
	}
}
//#endregion
//#region src/mascot/react/window/pip.ts
var x = () => globalThis.documentPictureInPicture, S = class {
	win = null;
	onClosed;
	constructor(e) {
		this.onClosed = e;
	}
	static supported() {
		return x() !== void 0;
	}
	get window() {
		return this.win;
	}
	async open(e, t = !0, n) {
		let r = x();
		if (!r) return null;
		if (this.win) return this.win;
		let i = await r.requestWindow({
			width: Math.round(e.width),
			height: Math.round(e.height)
		});
		return b(i.document, t, n), i.document.title = "Юми", Object.assign(i.document.body.style, {
			margin: "0",
			overflow: "hidden",
			background: "#f1a6c2"
		}), i.addEventListener("pagehide", () => {
			this.win === i && (this.win = null, this.onClosed());
		}, { once: !0 }), this.win = i, i;
	}
	close() {
		this.win?.close();
	}
}, C = 8, ee = class {
	key;
	storage;
	constructor(e = "yumi.window.v1", t = w()) {
		this.key = e, this.storage = t;
	}
	initial(e, t) {
		return {
			x: 16,
			y: Math.max(C, e.height - t.height - 24),
			mode: e.width < 600 ? "minimized" : "open",
			muted: !1
		};
	}
	load(e, t) {
		let n = this.initial(e, t);
		try {
			let e = JSON.parse(this.storage?.getItem(this.key) ?? "null");
			if (!e || typeof e != "object") return n;
			let t = [
				"open",
				"minimized",
				"closed"
			].includes(e.mode) ? e.mode : n.mode;
			return {
				x: Number.isFinite(e.x) ? e.x : n.x,
				y: Number.isFinite(e.y) ? e.y : n.y,
				mode: t,
				muted: e.muted === !0,
				...[
					"full",
					"half",
					"portrait"
				].includes(e.fit) ? { fit: e.fit } : {}
			};
		} catch {
			return n;
		}
	}
	save(e) {
		try {
			this.storage?.setItem(this.key, JSON.stringify(e));
		} catch {}
	}
	clamp(e, t, n) {
		let r = Math.max(C, t.width - n.width - C), i = Math.max(C, t.height - n.height - C);
		return {
			x: Math.round(Math.min(Math.max(e.x, C), r)),
			y: Math.round(Math.min(Math.max(e.y, C), i))
		};
	}
};
function w() {
	try {
		return globalThis.localStorage ?? null;
	} catch {
		return null;
	}
}
//#endregion
//#region src/mascot/react/window/backdrop.ts
var T = "bg/room.webp";
function te(e, n = "/mascot/") {
	if (e === !0) return t(T, n);
	let r = typeof e == "string" ? e.trim() : "";
	return r ? t(r, n) : null;
}
function ne(e) {
	return "url(\"" + e.replace(/["\\]/g, (e) => "\\" + e).replace(/[\n\r\f]/g, (e) => "\\" + e.charCodeAt(0).toString(16) + " ") + "\")";
}
//#endregion
//#region src/mascot/react/window/MascotWindow.tsx
var E = {
	width: 300,
	height: 380
}, D = (e) => ({
	width: e.innerWidth,
	height: e.innerHeight
});
function O({ core: t, title: f = "yumi", menu: g, renderer: _, storageKey: v, font: y = !0, nonce: x, backdrop: C = !0, onMascotClick: w }) {
	let T = a(() => t ?? e(), [t]), { bubble: O, muted: k } = m(T), A = a(() => new ee(v), [v]), [j, M] = s(() => A.load(D(window), E)), [N, re] = s(() => D(window)), [P, ie] = s(E), [F, ae] = s(null), [I, L] = s(!1), R = o(null), z = a(() => new S(() => ae(null)), []);
	i(() => {
		b(document, y, x);
	}, [y, x]), r(() => {
		T.setMuted(j.muted);
	}, [T]);
	let B = j.mode === "closed" && !F;
	r(() => (T.setVoiceSuppressed(B), () => T.setVoiceSuppressed(!1)), [T, B]), r(() => {
		I || A.save({
			...j,
			muted: k
		});
	}, [
		A,
		j,
		k,
		I
	]), r(() => {
		let e = () => re(D(window));
		return window.addEventListener("resize", e), () => window.removeEventListener("resize", e);
	}, []), r(() => {
		let e = R.current;
		if (!e) return;
		let t = () => {
			let t = e.getBoundingClientRect();
			ie((e) => Math.abs(t.width - e.width) > 1 || Math.abs(t.height - e.height) > 1 ? {
				width: t.width,
				height: t.height
			} : e);
		};
		t();
		let n = new ResizeObserver(t);
		return n.observe(e), () => n.disconnect();
	}, [j.mode, F]), r(() => () => z.close(), [z]);
	let V = A.clamp(j, N, P), H = o(null), oe = (e) => {
		F || e.button !== 0 || e.target.closest("button") || (H.current = {
			dx: e.clientX - V.x,
			dy: e.clientY - V.y,
			id: e.pointerId
		}, e.currentTarget.setPointerCapture(e.pointerId), L(!0));
	}, se = (e) => {
		let t = H.current;
		if (!t || t.id !== e.pointerId) return;
		let n = A.clamp({
			x: e.clientX - t.dx,
			y: e.clientY - t.dy
		}, N, P);
		M((e) => ({
			...e,
			...n
		}));
	}, U = (e) => {
		H.current?.id === e.pointerId && (H.current = null, L(!1));
	}, W = (e) => M((t) => ({
		...t,
		mode: e
	})), G = async () => {
		try {
			let e = await z.open({
				width: P.width,
				height: P.height
			}, y, x);
			e && ae(e);
		} catch (e) {
			console.warn("[mascot] отдельное окно не открылось", e);
		}
	}, K = n(() => T.getRenderer(), [T]), q = (e) => {
		K()?.setCamera?.({ fit: e }), M((t) => ({
			...t,
			fit: e
		}));
	}, J = a(() => j.fit ? {
		..._,
		fit: j.fit
	} : _, [_, j.fit]), Y = j.fit ?? K()?.getCamera?.().fit, X = [
		{
			label: "Вид",
			items: [
				{
					label: "Во весь рост",
					checked: Y === "full",
					onSelect: () => q("full")
				},
				{
					label: "По пояс",
					checked: Y === "half",
					onSelect: () => q("half")
				},
				{
					label: "Портрет",
					checked: Y === "portrait",
					onSelect: () => q("portrait")
				},
				...S.supported() && !F ? [null, {
					label: "В отдельное окно",
					onSelect: () => void G()
				}] : []
			]
		},
		{
			label: "Звук",
			items: [{
				label: "Говорить вслух",
				checked: !k,
				onSelect: () => T.setMuted(!k)
			}]
		},
		{
			label: "Юми",
			items: [
				{
					label: "Поздороваться",
					onSelect: () => T.setState("welcome")
				},
				{
					label: "Станцевать",
					onSelect: () => T.setState("dance")
				},
				null,
				{
					label: "Свернуть",
					onSelect: () => {
						z.close(), W("minimized");
					}
				}
			]
		}
	], ce = typeof g == "function" ? g(X) : g ?? X, Z = te(C, J?.assetsBase), Q = () => w ? w(T) : T.setState("welcome"), le = (e) => /* @__PURE__ */ u("div", {
		ref: R,
		className: [
			"yumi-window",
			e && "yumi-window--pip",
			I && "yumi-window--dragging"
		].filter(Boolean).join(" "),
		style: e ? void 0 : {
			left: V.x,
			top: V.y
		},
		role: "complementary",
		"aria-label": `Юми — ${f}`,
		children: [
			/* @__PURE__ */ u("div", {
				className: "yumi-titlebar",
				onPointerDown: oe,
				onPointerMove: se,
				onPointerUp: U,
				onPointerCancel: U,
				children: [
					/* @__PURE__ */ l("span", {
						className: "yumi-icon",
						"aria-hidden": "true"
					}),
					/* @__PURE__ */ l("span", {
						className: "yumi-title",
						children: f
					}),
					!e && /* @__PURE__ */ l("button", {
						className: "yumi-tbtn",
						onClick: () => W("minimized"),
						"aria-label": "Свернуть",
						title: "Свернуть",
						children: /* @__PURE__ */ l("span", { className: "yumi-ico-min" })
					}),
					/* @__PURE__ */ l("button", {
						className: "yumi-tbtn",
						onClick: () => e ? z.close() : void G(),
						disabled: !e && !S.supported(),
						"aria-label": e ? "Вернуть на страницу" : "В отдельное окно",
						title: e ? "Вернуть на страницу" : S.supported() ? "В отдельное окно поверх всех" : "Отдельное окно есть только в Chrome и Edge",
						children: /* @__PURE__ */ l("span", { className: "yumi-ico-max" })
					}),
					/* @__PURE__ */ l("button", {
						className: "yumi-tbtn",
						onClick: () => {
							z.close(), W("closed");
						},
						"aria-label": "Закрыть",
						title: "Закрыть",
						children: /* @__PURE__ */ l("span", {
							className: "yumi-ico-close",
							children: "×"
						})
					})
				]
			}),
			/* @__PURE__ */ l(h, { sections: ce }),
			/* @__PURE__ */ u("div", {
				className: "yumi-body",
				children: [
					Z && /* @__PURE__ */ l("div", {
						className: "yumi-backdrop",
						"aria-hidden": "true",
						style: { backgroundImage: ne(Z) }
					}),
					/* @__PURE__ */ l("div", {
						className: "yumi-stage",
						role: "button",
						tabIndex: 0,
						"aria-label": "Юми. Нажмите, чтобы она отреагировала",
						onClick: Q,
						onKeyDown: (e) => {
							(e.key === "Enter" || e.key === " ") && (e.preventDefault(), Q());
						},
						children: /* @__PURE__ */ l(p, {
							core: T,
							renderer: J,
							style: {
								position: "absolute",
								inset: 0
							}
						})
					}),
					O && /* @__PURE__ */ l("div", {
						className: "yumi-bubble",
						role: "status",
						children: O
					})
				]
			})
		]
	}), $ = (e, t, n = !1, r = "Показать Юми") => /* @__PURE__ */ u("div", {
		className: "yumi-dock",
		style: { top: V.y },
		children: [/* @__PURE__ */ u("button", {
			className: n ? "yumi-tab yumi-tab--slim" : "yumi-tab",
			onClick: t,
			"aria-label": r,
			title: r,
			children: [/* @__PURE__ */ l("span", {
				className: "yumi-icon",
				"aria-hidden": "true"
			}), e]
		}), !n && O && /* @__PURE__ */ l("div", {
			className: "yumi-note",
			role: "status",
			children: O
		})]
	}), ue;
	return ue = F ? $("Юми в окне ↩", () => z.close(), !1, "Вернуть Юми на страницу") : j.mode === "minimized" ? $(f, () => W("open")) : j.mode === "closed" ? $(null, () => W("open"), !0) : le(!1), /* @__PURE__ */ u(c, { children: [d(ue, document.body), F && d(le(!0), F.document.body)] });
}
//#endregion
export { p as Mascot, O as MascotWindow, b as ensureWindowStyles, m as useMascot };

//# sourceMappingURL=react.js.map