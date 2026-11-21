import { describe, expect, it } from "vitest";
import {
	buildExcludeDiscountedLineCoupon,
	calculateCartCouponDiscount,
	eligibleCouponSubtotal,
	fixedCouponLineDiscount,
	hasFixedCouponDiscount,
	isCouponLine,
	isLineAlreadyDiscounted,
	preCouponDiscount,
	preCouponLineDiscount,
	restorePreCouponDiscount,
	stashPreCouponDiscount,
} from "../couponLines";

const line = (overrides = {}) => ({
	discount_source: "coupon",
	coupon_code: "SAVE",
	price_list_rate: 200,
	quantity: 3,
	coupon_fixed_discount: 99.99,
	...overrides,
});

describe("couponLines", () => {
	it("recognises coupon lines only with source and code", () => {
		expect(isCouponLine(line())).toBe(true);
		expect(isCouponLine(line({ coupon_code: null }))).toBe(false);
		expect(isCouponLine(line({ discount_source: "manual_discount" }))).toBe(false);
		expect(isCouponLine(null)).toBe(false);
	});

	it("flags fixed coupon lines only when an amount was allocated", () => {
		expect(hasFixedCouponDiscount(line())).toBe(true);
		expect(hasFixedCouponDiscount(line({ coupon_fixed_discount: 0 }))).toBe(true);
		expect(hasFixedCouponDiscount(line({ coupon_fixed_discount: null }))).toBe(false);
		expect(hasFixedCouponDiscount(line({ discount_source: "manual_discount" }))).toBe(false);
	});

	it("keeps the allocated amount when quantity grows", () => {
		expect(fixedCouponLineDiscount(line({ quantity: 10 }))).toBe(99.9);
		expect(fixedCouponLineDiscount(line({ quantity: 3 }))).toBe(99.99);
	});

	it("never exceeds the line itself when quantity shrinks", () => {
		expect(fixedCouponLineDiscount(line({ quantity: 1, price_list_rate: 50 }))).toBe(50);
		expect(fixedCouponLineDiscount(line({ quantity: 0 }))).toBe(0);
	});

	it("applies the percentage cap of a capped percentage coupon", () => {
		const capped = line({ quantity: 1, coupon_fixed_discount: 40, coupon_percentage_cap: 10 });
		expect(fixedCouponLineDiscount(capped)).toBe(20);
	});

	it("rounds down to a whole per-unit amount", () => {
		const amount = fixedCouponLineDiscount(line({ quantity: 7, coupon_fixed_discount: 100 }));
		expect(amount).toBe(99.96);
		expect(Number.isInteger(Math.round((amount / 7) * 100 * 1e6) / 1e6)).toBe(true);
	});

	it("gives a promotion line its discount back when the coupon comes off", () => {
		const item = {
			price_list_rate: 100,
			quantity: 2,
			discount_percentage: 20,
			discount_amount: 40,
			discount_source: "item_level_promotion",
			is_already_discounted: 1,
		};
		stashPreCouponDiscount(item);
		Object.assign(item, { discount_percentage: 28, discount_source: "coupon", coupon_code: "SAVE" });

		expect(preCouponDiscount(item)).toMatchObject({
			discount_percentage: 20,
			discount_source: "item_level_promotion",
			is_already_discounted: 1,
		});
		expect(preCouponLineDiscount(item)).toBe(40);

		restorePreCouponDiscount(item);
		expect(item).toMatchObject({
			discount_percentage: 20,
			discount_amount: 40,
			discount_source: "item_level_promotion",
			is_already_discounted: 1,
			pre_coupon_discount: null,
		});
	});

	it("treats a coupon line without a stash as undiscounted before the coupon", () => {
		const item = line({ discount_percentage: 10 });
		expect(preCouponDiscount(item)).toMatchObject({ discount_percentage: 0, discount_amount: 0 });
		expect(preCouponLineDiscount(item)).toBe(0);
		restorePreCouponDiscount(item);
		expect(item.discount_percentage).toBe(0);
		expect(item.discount_source).toBe("");
	});

	it("shows a line that is not a coupon line as it is", () => {
		const item = { discount_percentage: 5, discount_amount: 0, discount_source: "manual_discount" };
		expect(preCouponDiscount(item)).toMatchObject({ discount_percentage: 5, discount_source: "manual_discount" });
	});

	it("detects already-discounted lines without treating a pure coupon line as one", () => {
		expect(isLineAlreadyDiscounted({ discount_percentage: 10, discount_source: "manual_discount" })).toBe(
			true
		);
		expect(isLineAlreadyDiscounted({ is_free_item: 1 })).toBe(true);
		expect(isLineAlreadyDiscounted(line({ discount_percentage: 10 }))).toBe(false);
		expect(isLineAlreadyDiscounted({ price_list_rate: 50, quantity: 1 })).toBe(false);
	});

	it("builds an eligible coupon subtotal that can skip discounted lines", () => {
		const items = [
			{ item_code: "A", price_list_rate: 100, quantity: 2 },
			{ item_code: "B", price_list_rate: 50, quantity: 1, discount_percentage: 10, discount_source: "manual_discount" },
			{ item_code: "C", price_list_rate: 20, quantity: 1, is_free_item: 1 },
		];
		expect(eligibleCouponSubtotal(items)).toBe(250);
		expect(eligibleCouponSubtotal(items, { excludeDiscounted: true })).toBe(200);
	});

	it("calculates cart coupon discount with min/max clamps", () => {
		const pct = { discount_type: "Percentage", discount_percentage: 10, max_amount: 15, min_amount: 50 };
		expect(calculateCartCouponDiscount(pct, 40)).toMatchObject({ valid: false, discount: 0 });
		expect(calculateCartCouponDiscount(pct, 200)).toMatchObject({ valid: true, discount: 15 });

		const amt = { discount_type: "Amount", discount_amount: 30 };
		expect(calculateCartCouponDiscount(amt, 20)).toMatchObject({ valid: true, discount: 20 });
	});

	it("builds line updates only for undiscounted items when exclude is on", () => {
		const items = [
			{ item_code: "A", price_list_rate: 100, quantity: 1 },
			{
				item_code: "B",
				price_list_rate: 100,
				quantity: 1,
				discount_percentage: 20,
				discount_source: "manual_discount",
			},
			{ item_code: "C", price_list_rate: 50, quantity: 2 },
		];
		const result = buildExcludeDiscountedLineCoupon(
			{ discount_type: "Percentage", discount_percentage: 10 },
			items
		);
		expect(result.valid).toBe(true);
		expect(result.line_updates).toHaveLength(2);
		expect(result.line_updates.map((u) => u.item_code)).toEqual(["A", "C"]);
		expect(result.line_updates.every((u) => u.discount_percentage === 10)).toBe(true);
		expect(result.total_discount).toBe(20);
	});

	it("rejects exclude coupons when every line is already discounted", () => {
		const items = [
			{
				item_code: "B",
				price_list_rate: 100,
				quantity: 1,
				discount_percentage: 20,
				discount_source: "manual_discount",
			},
		];
		const result = buildExcludeDiscountedLineCoupon(
			{ discount_type: "Percentage", discount_percentage: 10 },
			items
		);
		expect(result.valid).toBe(false);
		expect(result.reason).toBe("no_eligible_items");
	});
});
