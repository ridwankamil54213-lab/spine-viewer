"use strict";
/* Auth minimal: satu password bersama, cookie HMAC tanpa dependency.
 * shortcut: satu akun global, tanpa session store / register / reset — cukup
 * untuk viewer pribadi yang diekspos; upgrade ke reverse-proxy SSO kalau butuh
 * multi-user atau audit trail. */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const USER = process.env.SPINE_USER || "admin";
const PASSWORD_FILE = process.env.SPINE_PASSWORD_FILE ||
	path.join(__dirname, "..", "data", "auth-password");
const SECRET_FILE = process.env.SPINE_SECRET_FILE ||
	path.join(__dirname, "..", "data", "auth-secret");

function loadSecret() {
	if (process.env.SPINE_SECRET) return process.env.SPINE_SECRET;
	try { return fs.readFileSync(SECRET_FILE, "utf8").trim(); } catch { return null; }
}

function passwordHash(pw, salt) {
	return crypto.scryptSync(pw, salt, 32).toString("hex");
}

function safeEqual(a, b) {
	const x = Buffer.from(String(a));
	const y = Buffer.from(String(b));
	return x.length === y.length && crypto.timingSafeEqual(x, y);
}

const SECRET = loadSecret() || crypto.randomBytes(32).toString("hex");
if (!fs.existsSync(SECRET_FILE) && !process.env.SPINE_SECRET) {
	fs.writeFileSync(SECRET_FILE, SECRET + "\n", { mode: 0o600 });
}

const COOKIE = "spine_auth";
const PUBLIC_PATHS = ["/login", "/login.css"];
const HEALTH_PATHS = [];

function sign(value) {
	return crypto.createHmac("sha256", SECRET).update(value).digest("base64url");
}

function makeToken() {
	const payload = Buffer.from(JSON.stringify({ u: USER, t: Date.now() })).toString("base64url");
	return payload + "." + sign(payload);
}

function validToken(token) {
	if (!token || typeof token !== "string") return false;
	const [payload, sig] = token.split(".");
	if (!payload || !sig || !safeEqual(sign(payload), sig)) return false;
	try {
		const data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
		return data.u === USER && Number.isFinite(data.t);
	} catch { return false; }
}

function cookies(req) {
	const out = {};
	for (const part of String(req.headers.cookie || "").split(";")) {
		const i = part.indexOf("=");
		if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
	}
	return out;
}

function checkPassword(user, password) {
	if (user !== USER || typeof password !== "string") return false;
	let stored;
	try { stored = fs.readFileSync(PASSWORD_FILE, "utf8").trim(); } catch { return false; }
	// Format: salt:hash. Fallback untuk file plain lama (dibaca sekali).
	if (stored.includes(":")) {
		const [salt, hash] = stored.split(":");
		return safeEqual(passwordHash(password, salt), hash);
	}
	return safeEqual(password, stored);
}

function authorize(req, res, next) {
	const p = req.path;
	if (PUBLIC_PATHS.includes(p) || HEALTH_PATHS.includes(p)) return next();
	if (validToken(cookies(req)[COOKIE])) return next();

	// JSON client (fetch/XHR) -> 401, browser -> redirect ke /login
	if (req.xhr || /application\/json/.test(req.headers.accept || "") ||
		req.path.startsWith("/api/")) {
		return res.status(401).json({ error: "Login diperlukan." });
	}
	return res.redirect(302, "/login?next=" + encodeURIComponent(req.originalUrl));
}

function mount(app) {
	app.get("/login", (req, res) => {
		if (validToken(cookies(req)[COOKIE])) return res.redirect("/");
		res.type("html").send(`<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login — Spine Stage</title>
<link rel="stylesheet" href="/login.css"></head>
<body><main class="card">
<h1>Spine Stage</h1><p class="sub">Masuk untuk melihat pustaka model.</p>
<form method="post" action="/login">
<label>User<input name="user" autocomplete="username" required autofocus value="${USER}"></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>
<button type="submit">Masuk</button>
</form>
</main></body></html>`);
	});

	app.post("/login", (req, res) => {
		const { user, password } = req.body || {};
		if (!checkPassword(user, password)) {
			return res.status(401).type("html").send(`<!doctype html>
<html lang="id"><head><meta charset="utf-8"><title>Login gagal</title>
<link rel="stylesheet" href="/login.css"></head><body><main class="card">
<h1>Gagal</h1><p class="sub">User atau password salah.</p>
<p><a href="/login">Coba lagi</a></p></main></body></html>`);
		}
		res.cookie ? res.cookie(COOKIE, makeToken(), {
			httpOnly: true, sameSite: "lax", secure: process.env.HTTPS === "1",
			maxAge: 7 * 24 * 60 * 60 * 1000, path: "/",
		}) : res.setHeader("Set-Cookie",
			`${COOKIE}=${makeToken()}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800`);
		const next = req.query.next || req.body.next || "/";
		// Hanya izinkan path relatif, bukan URL luar (open redirect).
		const dest = /^\/[^\/]/.test(next) || next === "/" ? next : "/";
		res.redirect(302, dest);
	});

	app.get("/logout", (req, res) => {
		res.setHeader("Set-Cookie", `${COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0`);
		res.redirect("/login");
	});

	app.use(authorize);
}

module.exports = { mount, authorize, passwordHash };
