/**
 * Payment utility functions
 */

const TYPE_ICONS = {
	Cash: "💵",
	Card: "💳",
	Bank: "🏦",
	Phone: "📱",
	Wallet: "👛",
	Credit: "💚",
	"Credit Card": "💳",
	"Debit Card": "💳",
	"Mobile Money": "📱",
	Check: "🧾",
	"Gift Card": "🎁",
};

// Mode of Payment.pos_method (Moldova POS). Card stays Bank in ERPNext.
const POS_METHOD_ICONS = {
	cash: "💵",
	card: "💳",
	voucher: "🎟️",
	value_certificate: "🎟️",
	ticket: "🎫",
	electronic_meal_ticket: "🎫",
	subscription: "🔁",
	credit: "💚",
	leasing: "📄",
	advance: "💰",
	earnest: "💰",
	pledge: "💰",
	corporate_value_card: "💳",
	metrology_test: "📏",
	other: "💰",
};

export function isMiaPayment(posMethod) {
	return posMethod === "mia";
}

/**
 * Icon for a payment method. pos_method wins over ERPNext type.
 * @param {string} type
 * @param {string} [posMethod]
 * @returns {string}
 */
export function getPaymentIcon(type, posMethod) {
	if (posMethod && POS_METHOD_ICONS[posMethod]) {
		return POS_METHOD_ICONS[posMethod];
	}
	return TYPE_ICONS[type] || "💰";
}
