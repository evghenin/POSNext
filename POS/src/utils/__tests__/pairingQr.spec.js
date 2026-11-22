import { describe, expect, it } from "vitest"
import {
	MOBILE_CLIENT_INSTANCE_KEY,
	formatPairingCountdown,
	formatPairingPin,
	getOrCreateClientInstanceId,
	pairingQrPayload,
	renderPairingQr,
} from "../pairingQr"

function memoryStorage(initial = {}) {
	const data = { ...initial }
	return {
		getItem: (key) => (key in data ? data[key] : null),
		setItem: (key, value) => {
			data[key] = String(value)
		},
		data,
	}
}

describe("pairing QR payload", () => {
	it("encodes the one-time qr_token and nothing else", () => {
		expect(pairingQrPayload("  abc_token-1  ")).toBe("abc_token-1")
	})

	it("rejects an empty token", () => {
		expect(() => pairingQrPayload("  ")).toThrow(/qr_token is required/)
	})

	it("groups a 6-digit PIN for display", () => {
		expect(formatPairingPin("123456")).toBe("123 456")
		expect(formatPairingPin("12ab3456")).toBe("123 456")
	})

	it("formats the countdown as m:ss", () => {
		expect(formatPairingCountdown(120)).toBe("2:00")
		expect(formatPairingCountdown(5)).toBe("0:05")
		expect(formatPairingCountdown(-3)).toBe("0:00")
	})

	it("encodes the raw qr_token into the QR symbol", async () => {
		const mod = await import("qrcode")
		const QRCode = typeof mod.create === "function" ? mod : mod.default
		const symbol = QRCode.create("tok_en-1", { errorCorrectionLevel: "M" })
		const bytes = symbol.segments.flatMap((segment) =>
			typeof segment.data === "string"
				? [...segment.data].map((ch) => ch.charCodeAt(0))
				: [...segment.data],
		)
		expect(String.fromCharCode(...bytes)).toBe("tok_en-1")

		const url = await renderPairingQr("tok_en-1")
		expect(url.startsWith("data:image/svg+xml")).toBe(true)
		const svg = decodeURIComponent(url.split(",", 2)[1])
		expect(svg).toContain("<svg")
		expect(svg).not.toContain("tok_en-1")
	})

	it("persists the tab client instance id", () => {
		const storage = memoryStorage()
		const first = getOrCreateClientInstanceId(storage, () => "client-1")
		const second = getOrCreateClientInstanceId(storage, () => "client-2")
		expect(first).toBe("client-1")
		expect(second).toBe("client-1")
		expect(storage.data[MOBILE_CLIENT_INSTANCE_KEY]).toBe("client-1")
	})
})
