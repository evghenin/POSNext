import { call } from "@/utils/apiWrapper"
import { parseError } from "@/utils/errorHandler"
import { logger } from "@/utils/logger"
import {
	MOBILE_SESSION_INSTANCE_KEY,
	getOrCreateClientInstanceId,
	pairingQrPayload,
} from "@/utils/pairingQr"
import { ref } from "vue"

const log = logger.create("ScannerPairing")

function browserStorage() {
	if (typeof sessionStorage === "undefined") {
		return {
			getItem: () => null,
			setItem: () => {},
			removeItem: () => {},
		}
	}
	return sessionStorage
}

/**
 * Register (or resume) the till's mobile-scanner session and issue a one-time
 * pairing challenge via pos_next.api.mobile_scanner.
 */
export function useScannerPairing(options = {}) {
	const storage = options.storage || browserStorage()
	const loading = ref(false)
	const errorMessage = ref("")
	const challenge = ref(null)
	const secondsLeft = ref(0)

	let timer = null
	let generation = 0

	function stopCountdown() {
		if (timer) {
			clearInterval(timer)
			timer = null
		}
	}

	function startCountdown(ttlSeconds) {
		stopCountdown()
		const ttl = Number(ttlSeconds)
		const seconds = Number.isFinite(ttl) && ttl > 0 ? Math.floor(ttl) : 120
		const endsAt = Date.now() + seconds * 1000
		const tick = () => {
			secondsLeft.value = Math.max(0, Math.ceil((endsAt - Date.now()) / 1000))
			if (secondsLeft.value <= 0) stopCountdown()
		}
		tick()
		timer = setInterval(tick, 250)
	}

	function cancel() {
		generation += 1
		stopCountdown()
		loading.value = false
		challenge.value = null
		secondsLeft.value = 0
	}

	async function issueChallenge({ posProfile, posOpeningShift } = {}) {
		const ticket = ++generation
		loading.value = true
		errorMessage.value = ""
		challenge.value = null
		secondsLeft.value = 0
		stopCountdown()

		if (!posProfile) {
			loading.value = false
			errorMessage.value = __("Open a shift before connecting a scanner.")
			return
		}

		try {
			const clientInstanceId = getOrCreateClientInstanceId(storage)
			const storedSession =
				storage.getItem(MOBILE_SESSION_INSTANCE_KEY) || undefined
			const sessionArgs = {
				client_instance_id: clientInstanceId,
				pos_profile: posProfile,
			}
			if (posOpeningShift) sessionArgs.pos_opening_shift = posOpeningShift
			if (storedSession) sessionArgs.session_instance_id = storedSession

			const session = await call(
				"pos_next.api.mobile_scanner.register_session",
				sessionArgs,
			)
			if (ticket !== generation) return

			const sessionId = session?.session_instance_id
			if (!sessionId) {
				throw new Error(__("Could not register the POS session."))
			}
			storage.setItem(MOBILE_SESSION_INSTANCE_KEY, sessionId)

			const created = await call(
				"pos_next.api.mobile_scanner.create_pairing_challenge",
				{
					session_instance_id: sessionId,
				},
			)
			if (ticket !== generation) return

			challenge.value = {
				challengeId: created?.challenge_id,
				pin: created?.pin,
				qrPayload: pairingQrPayload(created?.qr_token),
				expiresAt: created?.expires_at,
				ttlSeconds: created?.ttl_seconds,
				sessionInstanceId: sessionId,
				posProfile: created?.pos_profile || posProfile,
			}
			startCountdown(created?.ttl_seconds)
		} catch (error) {
			if (ticket !== generation) return
			log.error("Failed to create pairing challenge", error)
			let message = ""
			try {
				message = parseError(error).message
			} catch {
				message = error?.message || ""
			}
			errorMessage.value =
				message || __("Could not create a scanner connection.")
			challenge.value = null
		} finally {
			if (ticket === generation) loading.value = false
		}
	}

	return {
		loading,
		errorMessage,
		challenge,
		secondsLeft,
		issueChallenge,
		cancel,
	}
}

export const SCANNER_POLL_MS = 1500

const appliedOperationIds = new Set()
let applyTimer = null
let applyBusy = false

export function scannerDevicesConnected(devices) {
	return (devices || []).some((device) => device?.status === "Connected")
}

export function scannerAddLine(command) {
	const payload =
		command?.payload && typeof command.payload === "object"
			? command.payload
			: {}
	const qty = Number(payload.qty ?? 1)
	return {
		operationId: command?.operation_id || "",
		commandType: command?.command_type || "",
		itemCode: String(payload.item_code || "").trim(),
		qty: Number.isFinite(qty) && qty > 0 ? qty : null,
		uom: payload.uom ? String(payload.uom) : "",
	}
}

/**
 * Apply polled scanner commands to the live cart, then ACK each one.
 * `appliedIds` stops a retry of the same operation_id from adding the line twice.
 */
export async function applyPolledCommands({
	commands,
	sessionId,
	resolveItem,
	addItem,
	ack,
	appliedIds = appliedOperationIds,
	busy = false,
}) {
	if (busy) return { skipped: true }
	for (const command of commands || []) {
		const line = scannerAddLine(command)
		if (!line.operationId) continue
		if (line.commandType !== "add_item" || !line.itemCode || line.qty == null) {
			await ack(sessionId, line.operationId, "rejected", {
				reason:
					line.commandType !== "add_item"
						? "unsupported_command"
						: "invalid_add",
			})
			continue
		}
		if (appliedIds.has(line.operationId)) {
			await ack(sessionId, line.operationId, "applied", {
				already_applied: true,
			})
			continue
		}
		try {
			const resolved = await resolveItem(line)
			const item = resolved?.message || resolved
			if (!item?.item_code) {
				throw new Error("Item not found")
			}
			if (line.uom) item.uom = line.uom
			await addItem(item, line.qty)
			appliedIds.add(line.operationId)
			await ack(sessionId, line.operationId, "applied", {
				item_code: line.itemCode,
				qty: line.qty,
				uom: item.uom || line.uom || null,
			})
		} catch (error) {
			await ack(sessionId, line.operationId, "rejected", {
				message: error?.message || "Could not add item",
			})
		}
	}
	return { skipped: false }
}

export function startScannerApplyLoop() {
	if (applyTimer || typeof window === "undefined") return
	const tick = () => {
		runScannerApplyTick().catch((error) => {
			log.error("Scanner apply tick failed", error)
		})
	}
	tick()
	applyTimer = setInterval(tick, SCANNER_POLL_MS)
}

export function stopScannerApplyLoop() {
	if (applyTimer) {
		clearInterval(applyTimer)
		applyTimer = null
	}
	applyBusy = false
	appliedOperationIds.clear()
}

async function runScannerApplyTick() {
	if (applyBusy) return
	const sessionId = browserStorage().getItem(MOBILE_SESSION_INSTANCE_KEY)
	if (!sessionId) return

	const { usePOSShiftStore } = await import("@/stores/posShift")
	const { usePOSCartStore } = await import("@/stores/posCart")
	const shiftStore = usePOSShiftStore()
	const cartStore = usePOSCartStore()
	if (!shiftStore.hasOpenShift || cartStore.isSubmitting) return

	applyBusy = true
	try {
		const listed = await call("pos_next.api.mobile_scanner.list_devices", {
			session_instance_id: sessionId,
		})
		if (!scannerDevicesConnected(listed?.devices)) return

		const polled = await call("pos_next.api.mobile_scanner.poll_commands", {
			session_instance_id: sessionId,
		})
		await applyPolledCommands({
			commands: polled?.commands || [],
			sessionId,
			resolveItem: (line) =>
				call("pos_next.api.items.get_item_details", {
					item_code: line.itemCode,
					pos_profile: shiftStore.profileName,
					qty: line.qty,
					uom: line.uom || undefined,
				}),
			addItem: (item, qty) =>
				cartStore.addItem(item, qty, true, shiftStore.currentProfile),
			ack: (sid, operationId, status, result) =>
				call("pos_next.api.mobile_scanner.ack_command", {
					session_instance_id: sid,
					operation_id: operationId,
					status,
					result,
				}),
		})
	} finally {
		applyBusy = false
	}
}

/** Close the till session so a phone cannot pair to a finished shift. */
export async function closeMobileScannerSession(storage = browserStorage()) {
	stopScannerApplyLoop()
	const sessionId = storage.getItem(MOBILE_SESSION_INSTANCE_KEY)
	if (!sessionId) return
	storage.removeItem(MOBILE_SESSION_INSTANCE_KEY)
	try {
		await call("pos_next.api.mobile_scanner.close_session", {
			session_instance_id: sessionId,
		})
	} catch (error) {
		log.error("Failed to close mobile scanner session", error)
	}
}
