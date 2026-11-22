/** @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest"

vi.mock("@/utils/apiWrapper", () => ({ call: vi.fn() }))
vi.mock("@/utils/logger", () => ({
	logger: { create: () => ({ error: vi.fn(), warn: vi.fn(), info: vi.fn() }) },
}))

import {
	applyPolledCommands,
	scannerDevicesConnected,
} from "@/composables/useScannerPairing"

describe("scanner command apply loop", () => {
	it("treats only Connected devices as a reason to poll", () => {
		expect(scannerDevicesConnected([{ status: "Disconnected" }])).toBe(false)
		expect(scannerDevicesConnected([{ status: "Connected" }])).toBe(true)
	})

	it("adds the line to the cart and ACKs applied", async () => {
		const addItem = vi.fn(async () => {})
		const ack = vi.fn(async () => {})
		const resolveItem = vi.fn(async () => ({
			item_code: "SKU00012",
			item_name: "Prija",
			rate: 25,
			stock_uom: "Nos",
		}))

		await applyPolledCommands({
			sessionId: "sess-1",
			appliedIds: new Set(),
			resolveItem,
			addItem,
			ack,
			commands: [
				{
					operation_id: "op-1",
					command_type: "add_item",
					payload: { item_code: "SKU00012", qty: 2, uom: "Box" },
				},
			],
		})

		expect(addItem).toHaveBeenCalledTimes(1)
		expect(addItem.mock.calls[0][0].item_code).toBe("SKU00012")
		expect(addItem.mock.calls[0][0].uom).toBe("Box")
		expect(addItem.mock.calls[0][1]).toBe(2)
		expect(ack).toHaveBeenCalledWith("sess-1", "op-1", "applied", {
			item_code: "SKU00012",
			qty: 2,
			uom: "Box",
		})
	})

	it("does not add the same operation twice and still ACKs applied", async () => {
		const appliedIds = new Set(["op-1"])
		const addItem = vi.fn()
		const ack = vi.fn(async () => {})

		await applyPolledCommands({
			sessionId: "sess-1",
			appliedIds,
			resolveItem: vi.fn(),
			addItem,
			ack,
			commands: [
				{
					operation_id: "op-1",
					command_type: "add_item",
					payload: { item_code: "SKU00012", qty: 1 },
				},
			],
		})

		expect(addItem).not.toHaveBeenCalled()
		expect(ack).toHaveBeenCalledWith(
			"sess-1",
			"op-1",
			"applied",
			expect.objectContaining({ already_applied: true }),
		)
	})

	it("ACKs rejected when the item cannot be added", async () => {
		const ack = vi.fn(async () => {})
		await applyPolledCommands({
			sessionId: "sess-1",
			appliedIds: new Set(),
			resolveItem: async () => {
				throw new Error("Item not found")
			},
			addItem: vi.fn(),
			ack,
			commands: [
				{
					operation_id: "op-2",
					command_type: "add_item",
					payload: { item_code: "MISSING", qty: 1 },
				},
			],
		})

		expect(ack).toHaveBeenCalledWith("sess-1", "op-2", "rejected", {
			message: "Item not found",
		})
	})

	it("does not poll the cart while payment is in progress", async () => {
		const addItem = vi.fn()
		const ack = vi.fn()
		const result = await applyPolledCommands({
			sessionId: "sess-1",
			busy: true,
			addItem,
			ack,
			resolveItem: vi.fn(),
			commands: [
				{
					operation_id: "op-3",
					command_type: "add_item",
					payload: { item_code: "SKU1", qty: 1 },
				},
			],
		})
		expect(result.skipped).toBe(true)
		expect(addItem).not.toHaveBeenCalled()
		expect(ack).not.toHaveBeenCalled()
	})
})
