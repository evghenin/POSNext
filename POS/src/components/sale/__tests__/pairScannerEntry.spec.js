/**
 * Connect scanner must be reachable from the till menu and the empty cart.
 * @vitest-environment node
 */
import { readFileSync } from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

function source(rel) {
	return readFileSync(path.resolve(__dirname, rel), "utf8")
}

describe("Connect scanner entry points", () => {
	it("adds a top-right menu item that opens the connection dialog", () => {
		const page = source("../../../pages/POSSale.vue")
		expect(page).toContain('{{ __("Connect scanner") }}')
		expect(page).toContain("showPairScannerDialog = true")
		expect(page).toContain("<PairScannerDialog")
	})

	it("draws the QR from the existing pairing challenge API", () => {
		const dialog = source("../PairScannerDialog.vue")
		expect(dialog).toContain("__('Scanner connection')")
		expect(dialog).not.toMatch(/__\(["'][^"']*[Pp]air/)
		expect(dialog).toContain("useScannerPairing")
		expect(dialog).toContain("renderPairingQr")
		const composable = source("../../../composables/useScannerPairing.js")
		expect(composable).toContain("pos_next.api.mobile_scanner.register_session")
		expect(composable).toContain(
			"pos_next.api.mobile_scanner.create_pairing_challenge",
		)
	})

	it("adds the same action on the empty cart", () => {
		const cart = source("../InvoiceCart.vue")
		const emptyStart = cart.indexOf('v-if="items.length === 0"')
		const emptyEnd = cart.indexOf("v-else", emptyStart)
		const empty = cart.slice(emptyStart, emptyEnd)
		expect(empty).toContain('__("Connect scanner")')
		expect(empty).toContain("$emit('pair-scanner')")
		expect(cart).toContain('"pair-scanner"')
	})
})
