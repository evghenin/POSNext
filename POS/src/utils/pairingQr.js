/**
 * Pairing QR payload for the existing mobile scanner challenge.
 *
 * `create_pairing_challenge` returns a one-time `qr_token`. `redeem_pairing`
 * hashes that exact string, so the QR contains the token and nothing else.
 */

export const MOBILE_CLIENT_INSTANCE_KEY = "pos_next_mobile_client_instance_id"
export const MOBILE_SESSION_INSTANCE_KEY = "pos_next_mobile_session_instance_id"

export function pairingQrPayload(qrToken) {
	const token = String(qrToken ?? "").trim()
	if (!token) {
		throw new Error("qr_token is required")
	}
	return token
}

export function formatPairingPin(pin) {
	const digits = String(pin ?? "").replace(/\D/g, "")
	if (digits.length === 6) {
		return `${digits.slice(0, 3)} ${digits.slice(3)}`
	}
	return String(pin ?? "").trim()
}

export function formatPairingCountdown(seconds) {
	const total = Math.max(0, Math.floor(Number(seconds) || 0))
	const minutes = Math.floor(total / 60)
	const remainder = total % 60
	return `${minutes}:${String(remainder).padStart(2, "0")}`
}

export function getOrCreateClientInstanceId(
	storage,
	createId = () => crypto.randomUUID(),
) {
	const existing = storage.getItem(MOBILE_CLIENT_INSTANCE_KEY)
	if (existing) return existing
	const id = createId()
	storage.setItem(MOBILE_CLIENT_INSTANCE_KEY, id)
	return id
}

export async function renderPairingQr(qrToken) {
	const payload = pairingQrPayload(qrToken)
	const mod = await import("qrcode")
	const QRCode = typeof mod.toString === "function" ? mod : mod.default
	const svg = await QRCode.toString(payload, {
		type: "svg",
		errorCorrectionLevel: "M",
		margin: 1,
		width: 240,
	})
	return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}
