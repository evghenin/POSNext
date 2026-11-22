/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/utils/apiWrapper", () => ({ call: vi.fn() }))
vi.mock("@/utils/logger", () => ({
	logger: { create: () => ({ error: vi.fn(), warn: vi.fn(), info: vi.fn() }) },
}))

import { call } from "@/utils/apiWrapper"
import {
	closeMobileScannerSession,
	useScannerPairing,
} from "@/composables/useScannerPairing"
import {
	MOBILE_CLIENT_INSTANCE_KEY,
	MOBILE_SESSION_INSTANCE_KEY,
} from "@/utils/pairingQr"

function memoryStorage() {
	const data = {}
	return {
		getItem: (key) => (key in data ? data[key] : null),
		setItem: (key, value) => {
			data[key] = String(value)
		},
		removeItem: (key) => {
			delete data[key]
		},
		data,
	}
}

describe("useScannerPairing", () => {
	beforeEach(() => {
		vi.clearAllMocks()
		globalThis.__ = (text) => text
	})

	it("registers the till session then creates a one-time challenge", async () => {
		const storage = memoryStorage()
		call.mockImplementation(async (method) => {
			if (method.endsWith("register_session")) {
				return { session_instance_id: "sess-1", resumed: false }
			}
			if (method.endsWith("create_pairing_challenge")) {
				return {
					challenge_id: "ch-1",
					pin: "123456",
					qr_token: "qr-secret",
					ttl_seconds: 120,
					pos_profile: "Main",
				}
			}
			throw new Error(`unexpected ${method}`)
		})

		const pairing = useScannerPairing({ storage })
		await pairing.issueChallenge({
			posProfile: "Main",
			posOpeningShift: "SHIFT-1",
		})

		expect(call).toHaveBeenNthCalledWith(
			1,
			"pos_next.api.mobile_scanner.register_session",
			{
				client_instance_id: storage.data[MOBILE_CLIENT_INSTANCE_KEY],
				pos_profile: "Main",
				pos_opening_shift: "SHIFT-1",
			},
		)
		expect(call).toHaveBeenNthCalledWith(
			2,
			"pos_next.api.mobile_scanner.create_pairing_challenge",
			{ session_instance_id: "sess-1" },
		)
		expect(pairing.challenge.value.pin).toBe("123456")
		expect(pairing.challenge.value.qrPayload).toBe("qr-secret")
		expect(storage.data[MOBILE_SESSION_INSTANCE_KEY]).toBe("sess-1")
		expect(pairing.secondsLeft.value).toBeGreaterThan(0)
		pairing.cancel()
	})

	it("does not create a challenge when the shift profile is missing", async () => {
		const pairing = useScannerPairing({ storage: memoryStorage() })
		await pairing.issueChallenge({ posProfile: "" })
		expect(call).not.toHaveBeenCalled()
		expect(pairing.errorMessage.value).toMatch(/Open a shift/)
	})

	it("surfaces an API failure without a QR payload", async () => {
		call.mockRejectedValue({ message: "Session is closed" })
		const pairing = useScannerPairing({ storage: memoryStorage() })
		await pairing.issueChallenge({ posProfile: "Main" })
		expect(pairing.challenge.value).toBeNull()
		expect(pairing.errorMessage.value).toBe("Session is closed")
		expect(pairing.loading.value).toBe(false)
	})

	it("closes the stored session", async () => {
		const storage = memoryStorage()
		storage.setItem(MOBILE_SESSION_INSTANCE_KEY, "sess-9")
		call.mockResolvedValue({ ok: true })
		await closeMobileScannerSession(storage)
		expect(call).toHaveBeenCalledWith(
			"pos_next.api.mobile_scanner.close_session",
			{
				session_instance_id: "sess-9",
			},
		)
		expect(storage.getItem(MOBILE_SESSION_INSTANCE_KEY)).toBeNull()
	})
})
