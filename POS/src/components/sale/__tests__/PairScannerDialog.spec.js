/** @vitest-environment jsdom */
import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/utils/apiWrapper", () => ({ call: vi.fn() }))
vi.mock("@/utils/logger", () => ({
	logger: { create: () => ({ error: vi.fn(), warn: vi.fn(), info: vi.fn() }) },
}))
vi.mock("frappe-ui", () => ({
	Dialog: {
		name: "Dialog",
		props: ["modelValue", "options"],
		template: `
			<div v-if="modelValue">
				<h2>{{ options.title }}</h2>
				<slot name="body-content" />
				<slot name="actions" />
			</div>
		`,
	},
	Button: {
		name: "Button",
		emits: ["click"],
		template: `<button type="button" @click="$emit('click')"><slot /></button>`,
	},
}))

import { call } from "@/utils/apiWrapper"
import PairScannerDialog from "../PairScannerDialog.vue"

function translate(text, args) {
	if (!args) return text
	const value = Array.isArray(args) ? args[0] : args[0]
	return String(text).replace("{0}", value)
}

function mountDialog(props) {
	return mount(PairScannerDialog, {
		props,
		global: { mocks: { __: translate } },
	})
}

describe("PairScannerDialog", () => {
	beforeEach(() => {
		sessionStorage.clear()
		vi.clearAllMocks()
		globalThis.__ = translate
		let issued = 0
		call.mockImplementation(async (method) => {
			if (method.endsWith("register_session")) {
				return { session_instance_id: "sess-1" }
			}
			if (method.endsWith("create_pairing_challenge")) {
				issued += 1
				return {
					challenge_id: `ch-${issued}`,
					pin: issued === 1 ? "123456" : "654321",
					qr_token: `qr-secret-${issued}`,
					ttl_seconds: 90,
					pos_profile: "Main",
				}
			}
			throw new Error(`unexpected ${method}`)
		})
	})

	it("shows the one-time PIN and a QR of the challenge token", async () => {
		const wrapper = mountDialog({
			modelValue: false,
			posProfile: "Main",
			posOpeningShift: "SHIFT-1",
		})

		await wrapper.setProps({ modelValue: true })
		await flushPromises()
		await vi.waitFor(() => {
			expect(wrapper.find("[data-testid='pair-scanner-qr']").exists()).toBe(true)
		})

		expect(wrapper.text()).toContain("Pair scanner")
		expect(wrapper.get("[data-testid='pair-scanner-pin']").text()).toBe(
			"123 456",
		)
		expect(wrapper.text()).toContain("Expires in")

		const src = wrapper.get("[data-testid='pair-scanner-qr']").attributes("src")
		expect(src.startsWith("data:image/svg+xml")).toBe(true)
		const svg = decodeURIComponent(src.split(",", 2)[1])
		expect(svg).toContain("<svg")

		expect(call).toHaveBeenCalledWith(
			"pos_next.api.mobile_scanner.create_pairing_challenge",
			{ session_instance_id: "sess-1" },
		)

		const newCode = wrapper
			.findAll("button")
			.find((button) => button.text() === "New code")
		await newCode.trigger("click")
		await flushPromises()

		expect(wrapper.get("[data-testid='pair-scanner-pin']").text()).toBe(
			"654 321",
		)
		expect(
			call.mock.calls.filter((args) =>
				String(args[0]).endsWith("create_pairing_challenge"),
			),
		).toHaveLength(2)

		wrapper.unmount()
	})

	it("offers try again when the pairing API fails", async () => {
		call.mockRejectedValue({ message: "Session is closed" })
		const wrapper = mountDialog({ modelValue: true, posProfile: "Main" })
		await flushPromises()

		expect(wrapper.text()).toContain("Session is closed")
		expect(wrapper.text()).toContain("Try again")
		expect(wrapper.find("[data-testid='pair-scanner-qr']").exists()).toBe(false)
		wrapper.unmount()
	})
})
