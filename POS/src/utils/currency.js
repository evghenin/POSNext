/**
 * Currency Utility for POS Next
 * Handles formatting and rounding with ERPNext System Settings compatibility
 *
 * Rounding Methods (matches frappe/utils/data.py):
 * - Banker's Rounding: Rounds .5 to nearest even number
 * - Commercial Rounding: Rounds .5 away from zero
 */

// =============================================================================
// Settings (initialized from bootstrap)
// =============================================================================

let settings = {
	currency: 2,
	float: 3,
	rounding_method: "Banker's Rounding",
	number_format: "#,###.##",
	hide_currency_symbol: false,
	currencies: {},
};

/** Initialize settings from bootstrap data */
export function initPrecision(data) {
	if (!data) return;
	settings = {
		currency: data.currency ?? 2,
		float: data.float ?? 3,
		rounding_method: data.rounding_method || "Banker's Rounding",
		number_format: data.number_format || "#,###.##",
		hide_currency_symbol: Boolean(data.hide_currency_symbol),
		currencies: data.currencies || {},
	};
}

/** Get current settings */
export function getPrecision() {
	return { ...settings };
}

// =============================================================================
// Currency Symbols
// =============================================================================

export const DEFAULT_CURRENCY = "USD";
export const DEFAULT_LOCALE = "en-US";

// Fallback symbols used only before Currency docs are loaded from bootstrap.
const SYMBOLS = {
	USD: "$",
	EUR: "€",
	GBP: "£",
	JPY: "¥",
	CNY: "¥",
	INR: "₹",
	EGP: "E£",
	SAR: "\u00EA",
	AED: "د.إ",
	MDL: "MDL",
};

function getCurrencyMeta(currency) {
	const code = currency || DEFAULT_CURRENCY;
	const fromErp = settings.currencies?.[code];
	if (fromErp) return fromErp;
	return {
		symbol: SYMBOLS[code] || code,
		symbol_on_right: false,
	};
}

function getSymbol(currency) {
	return getCurrencyMeta(currency).symbol;
}

export { getSymbol as getCurrencySymbol };

// =============================================================================
// Number Formatting
// =============================================================================

// Same map as frappe.utils.data.number_format_info: [decimal, thousands, default precision]
const NUMBER_FORMAT_INFO = {
	"#,###.##": [".", ",", 2],
	"#.###,##": [",", ".", 2],
	"# ###.##": [".", " ", 2],
	"# ###,##": [",", " ", 2],
	"#'###.##": [".", "'", 2],
	"#, ###.##": [".", ", ", 2],
	"#,##,###.##": [".", ",", 2],
	"#,###.###": [".", ",", 3],
	"#.###": ["", ".", 0],
	"#,###": ["", ",", 0],
	"#.########": [".", "", 8],
};

function getNumberFormatInfo(format) {
	return NUMBER_FORMAT_INFO[format] || NUMBER_FORMAT_INFO["#,###.##"];
}

/**
 * Format a number the same way as frappe.utils.data.fmt_money
 * (grouping, decimal separator, currency symbol side).
 */
function formatAmount(value, precision, currency) {
	const [decimalStr, commaStr] = getNumberFormatInfo(settings.number_format);
	const negative = value < 0;
	const fixed = Math.abs(Number(value) || 0).toFixed(precision);
	const [intRaw, decRaw = ""] = fixed.split(".");

	const parts = [];
	let rest = intRaw;
	if (rest.length > 3) {
		parts.push(rest.slice(-3));
		rest = rest.slice(0, -3);
		const group = settings.number_format === "#,##,###.##" ? 2 : 3;
		while (rest.length > group) {
			parts.push(rest.slice(-group));
			rest = rest.slice(0, -group);
		}
	}
	if (rest) parts.push(rest);
	parts.reverse();

	let amount = parts.join(commaStr);
	if (precision && decimalStr) {
		amount += decimalStr + decRaw;
	}
	if (negative && amount !== "0") {
		amount = `-${amount}`;
	}

	if (!currency || settings.hide_currency_symbol) return amount;

	const { symbol, symbol_on_right } = getCurrencyMeta(currency);
	return symbol_on_right ? `${amount} ${symbol}` : `${symbol} ${amount}`;
}

/** Format value as currency string with symbol */
export function formatCurrency(value, currency = DEFAULT_CURRENCY) {
	if (typeof value !== "number" || Number.isNaN(value)) return "";
	return formatAmount(value, settings.currency, currency);
}

/** Format value as number string (no symbol) */
export function formatCurrencyNumber(value) {
	if (typeof value !== "number" || Number.isNaN(value)) return "0.00";
	return formatAmount(value, settings.currency, null);
}

/** Get CSS class for positive/negative values */
export function getCurrencyClass(value) {
	return value < 0 ? "text-red-600" : "text-gray-900";
}

// =============================================================================
// Rounding (matches frappe/utils/data.py exactly)
// =============================================================================

/**
 * Banker's Rounding - rounds .5 to nearest even
 * Matches frappe _bankers_rounding()
 */
function bankersRound(num, precision) {
	const multiplier = 10 ** precision;
	// Round to 12 decimal places first to handle floating point errors
	let shifted = Number((num * multiplier).toFixed(12));

	if (shifted === 0) return 0;

	const floor = Math.floor(shifted);
	const decimal = shifted - floor;

	// Calculate epsilon for this number's magnitude
	const epsilon = 2 ** (Math.log2(Math.abs(shifted)) - 52);

	if (Math.abs(decimal - 0.5) < epsilon) {
		// Exactly .5 - round to even
		shifted = floor % 2 === 0 ? floor : floor + 1;
	} else {
		shifted = Math.round(shifted);
	}

	return shifted / multiplier;
}

/**
 * Commercial Rounding - .5 rounds away from zero
 * Matches frappe _round_away_from_zero()
 */
function commercialRound(num, precision) {
	if (num === 0) return 0;

	// Calculate epsilon for this number's magnitude
	const epsilon = 2 ** (Math.log2(Math.abs(num)) - 52);

	// Add epsilon in the direction of the sign, then round
	const adjusted = num + Math.sign(num) * epsilon;
	return Number(adjusted.toFixed(precision));
}

/**
 * Round using system rounding method
 * @param {number} value - Value to round
 * @param {number} precision - Decimal places
 * @returns {number} Rounded value
 */
function round(value, precision) {
	if (typeof value !== "number" || Number.isNaN(value)) return 0;

	// Use Frappe's flt() if available in browser context
	if (typeof window !== "undefined" && typeof window.flt === "function") {
		return window.flt(value, precision);
	}

	// Apply rounding based on system setting
	if (settings.rounding_method === "Commercial Rounding") {
		return commercialRound(value, precision);
	}
	return bankersRound(value, precision);
}

// =============================================================================
// Exported Rounding Functions
// =============================================================================

/** Round to 2 decimal places */
export function round2(value) {
	return round(value, 2);
}

/** Round to 3 decimal places */
export function round3(value) {
	return round(value, 3);
}

/** Round using system currency precision */
export function roundCurrency(value) {
	return round(value, settings.currency);
}

/** Round using system float precision */
export function roundFloat(value) {
	return round(value, settings.float);
}
