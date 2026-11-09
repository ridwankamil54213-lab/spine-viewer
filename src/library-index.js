/**
 * Derived, read-only index over the model library.
 *
 * The library used to recompute everything from the 46k-entry `models` array
 * on EVERY render: group into game buckets, filter family variants, sort by
 * id, and lower-case four fields per model for the search box. A single
 * keystroke could touch every model several times.
 *
 * None of that depends on the UI state — only on `models` itself. So it is
 * built once per array and cached in a WeakMap: `refresh()` assigns a new
 * array, which is the natural invalidation point, no explicit cache-busting
 * needed. Dynamic state (favorites, NEW badges, search query) is applied on
 * top of these precomputed lists at render time.
 *
 * Extracted from viewer.js so the render functions stay about DOM, not about
 * re-deriving the same grouping thousands of times.
 */

const cache = new WeakMap();

/** Plain comparator — must match the original `a.id.localeCompare(b.id)`. */
const byId = (a, b) => a.id.localeCompare(b.id);

function build(models) {
	const seen = new Map();
	const byGame = new Map();
	const search = new Map();

	for (const m of models) {
		const key = m.game || "lainnya";
		let bucket = seen.get(key);
		if (!bucket) {
			bucket = { key, label: m.gameLabel || "Lainnya", items: [] };
			seen.set(key, bucket);
			byGame.set(key, []);
		}
		bucket.items.push(m);
		byGame.get(key).push(m);
		// Separator keeps a query from matching across two fields.
		search.set(m.id, [m.id, m.name, m.character?.name, m.character?.squad]
			.filter(Boolean).join("\u0001").toLowerCase());
	}

	const buckets = [...seen.values()]
		.filter((g) => !g.items.every((m) => m.hiddenGame))
		.sort((a, b) =>
			(a.label || a.key).localeCompare(b.label || b.key, undefined, {
				numeric: true,
				sensitivity: "base",
			})
		);

	const rootsByGame = new Map();
	const variantsByGame = new Map();
	const rootsAll = [];
	for (const [key, items] of byGame) {
		const roots = items.filter((m) => !m.family || m.family.root === m.id);
		roots.sort(byId);
		rootsByGame.set(key, roots);
		variantsByGame.set(key, items.length - roots.length);
		for (const m of roots) rootsAll.push(m);
	}
	rootsAll.sort(byId);

	return { buckets, rootsByGame, rootsAll, variantsByGame, search };
}

/** Index for this exact `models` array. */
export function libraryIndex(models) {
	let idx = cache.get(models);
	if (!idx) {
		idx = build(models);
		cache.set(models, idx);
	}
	return idx;
}
