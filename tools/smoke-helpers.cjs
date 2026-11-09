/**
 * Shared helpers for the Playwright smoke tests.
 *
 * The "Alat" (Tools) popover groups the advanced controls: #fps-btn,
 * #parts-btn, #bones-btn, #grid-btn, #timeline-btn, #inspector-btn and the
 * render selects all live inside #tools-pop, which is hidden until the menu
 * is opened. Tests that click those buttons directly must call openTools()
 * first, otherwise Playwright waits forever for an element that resolves but
 * is never visible. Keyboard shortcuts are unaffected and need no helper.
 *
 * The retry loop matters right after a reload: the button is in the HTML
 * before initToolsMenu() has attached its click listener, so the first click
 * can be a no-op. Checking visibility after each attempt keeps the helper
 * idempotent (it never closes an already-open menu).
 */
async function openTools(page) {
	const pop = page.locator("#tools-pop");
	await page.waitForSelector("#tools-btn", { state: "attached" });
	for (let i = 0; i < 10; i++) {
		if (await pop.isVisible()) return;
		await page.click("#tools-btn");
		await page.waitForTimeout(150);
	}
	// Surface a clear error instead of letting a later click time out.
	await pop.waitFor({ state: "visible", timeout: 5000 });
}

module.exports = { openTools };
