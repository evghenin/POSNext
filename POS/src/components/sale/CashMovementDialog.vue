<template>
	<Dialog
		v-model="open"
		:options="{ title, size: 'md' }"
		:disable-outside-click-to-close="busy"
	>
		<template #body-header>
			<div class="mb-6 flex items-center">
				<h3 class="text-2xl font-semibold leading-6 text-ink-gray-9">{{ title }}</h3>
			</div>
		</template>
		<template #body-content>
			<div class="text-center">
				<div
					class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
					:class="isCollection ? 'bg-red-100' : 'bg-green-100'"
				>
					<svg
						class="h-6 w-6"
						:class="isCollection ? 'text-red-600' : 'text-green-600'"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
					>
						<path
							v-if="isCollection"
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
						/>
						<path
							v-else
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
						/>
					</svg>
				</div>

				<h3 v-if="step === 'amount'" class="mb-4 text-lg font-medium text-gray-900">
					{{ busy ? operationSentence : promptText }}
				</h3>

				<div v-if="step === 'amount' && !busy" class="mb-4 flex justify-center">
					<Input
						v-model="amount"
						type="number"
						step="0.01"
						min="0"
						placeholder="0.00"
						class="w-[150px] text-base md:text-lg [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
					/>
				</div>

				<div v-else-if="step === 'done'" class="mb-4">
					<h3 class="mb-4 text-lg font-medium text-gray-900">{{ completedText }}</h3>
					<div class="mx-auto mt-4 max-w-sm rounded-lg bg-gray-50 p-4 text-sm text-gray-600">
						<p>
							<strong>{{ __("Amount") }}:</strong>
							{{ money(pending?.amount ?? amount) }}
						</p>
						<div class="h-2"></div>
						<p>
							<strong>{{ __("Cash in drawer") }}:</strong>
							{{ pending?.drawer_amount == null ? "" : money(pending.drawer_amount) }}
						</p>
						<div class="h-2"></div>
						<p>
							<strong>{{ __("Date and time") }}:</strong>
							{{ operationTime }}
						</p>
					</div>
				</div>

				<div v-else-if="step === 'confirm'" class="mb-4 text-sm text-gray-600">
					<p>{{ __("The terminal did not answer. Check whether it printed the receipt.") }}</p>
					<p class="mt-2">{{ __("Was the receipt printed?") }}</p>
					<p class="mt-2 font-semibold text-gray-800">{{ Number(pending?.amount || 0).toFixed(2) }}</p>
				</div>

				<div v-else-if="step === 'choose'" class="mb-4 flex flex-col gap-2 text-start">
					<button
						v-for="row in candidates"
						:key="row.receipt_id"
						type="button"
						class="rounded-lg border border-gray-200 px-3 py-2 hover:bg-gray-50"
						@click="choose(row.receipt_id)"
					>
						<span class="font-semibold">{{ row.number || row.receipt_id }}</span>
						<span class="text-gray-600"> · {{ Number(row.amount || 0).toFixed(2) }}</span>
					</button>
				</div>

				<div v-if="errorText || loadFailed" class="mb-4 rounded-md bg-red-50 p-4 text-start">
					<p class="text-sm text-red-800">
						{{ errorText || __("Could not load the data from the terminal.") }}
					</p>
				</div>

				<p v-if="busy" class="mb-4 text-sm text-gray-500">{{ __("Waiting for the terminal...") }}</p>
			</div>
		</template>
		<template #actions>
			<div class="flex w-full items-center justify-between gap-2">
				<Button variant="subtle" :disabled="busy" @click="open = false">
					{{ __("Close") }}
				</Button>
				<div class="flex gap-2">
					<Button
						v-if="step === 'amount'"
						variant="solid"
						theme="blue"
						:loading="busy"
						@click="submit"
					>
						{{ __("Confirm") }}
					</Button>
					<Button v-if="step === 'confirm'" variant="subtle" :loading="busy" @click="notPrinted">
						{{ __("Not printed") }}
					</Button>
					<Button v-if="step === 'confirm'" variant="solid" theme="blue" :loading="busy" @click="printed">
						{{ __("Printed") }}
					</Button>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { call } from "@/utils/apiWrapper";
import { formatCurrency } from "@/utils/currency";
import { parseError } from "@/utils/errorHandler";
import { Button, Dialog, Input } from "frappe-ui";
import { computed, ref, watch } from "vue";

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	posProfile: { type: String, default: "" },
	openingShift: { type: String, default: "" },
	movementType: { type: String, default: "deposit" },
	currency: { type: String, default: "" },
	pendingReceipt: { type: Object, default: null },
});
const emit = defineEmits(["update:modelValue", "changed"]);

const open = computed({
	get: () => props.modelValue,
	set: (value) => {
		if (!value && busy.value) return;
		emit("update:modelValue", value);
	},
});
const amount = ref("");
const step = ref("amount");
const pending = ref(null);
const candidates = ref([]);
const errorText = ref("");
const loadFailed = ref(false);
const busy = ref(false);

const movementKind = computed(() => pending.value?.movement_type || props.movementType);
const isCollection = computed(() => movementKind.value === "withdrawal");

const title = computed(() => {
	return isCollection.value ? __("Cash collection") : __("Cash deposit");
});

const promptText = computed(() => {
	return isCollection.value
		? __("Enter the cash collection amount")
		: __("Enter the cash deposit amount");
});

const operationSentence = computed(() => {
	const text = money(amount.value);
	return isCollection.value ? __("Cash collection of {0}", [text]) : __("Cash deposit of {0}", [text]);
});

const completedText = computed(() => {
	return isCollection.value ? __("Cash collection completed") : __("Cash deposit completed");
});

function money(value) {
	const number = Number(value);
	if (Number.isNaN(number)) return "";
	return formatCurrency(number, props.currency || undefined);
}

const operationTime = computed(() => {
	const raw = pending.value?.registered_at;
	if (!raw) return "";
	const date = new Date(String(raw).replace(" ", "T"));
	if (Number.isNaN(date.getTime())) return String(raw);
	return date.toLocaleString();
});

watch(
	() => props.modelValue,
	(visible) => {
		if (!visible) return;
		errorText.value = "";
		loadFailed.value = false;
		candidates.value = [];
		if (props.pendingReceipt?.name) {
			pending.value = props.pendingReceipt;
			step.value = "confirm";
			return;
		}
		pending.value = null;
		step.value = "amount";
		amount.value = "";
	},
);

function showRegistered(receipt) {
	pending.value = receipt || pending.value;
	errorText.value = "";
	loadFailed.value = false;
	step.value = "done";
}

function errorMessage(error) {
	const parsed = parseError(error);
	return parsed?.message || parsed?.title || __("The cash movement failed.");
}

async function submit() {
	busy.value = true;
	errorText.value = "";
	try {
		const result = await call(
			"erpnext_moldova_pos.api.pos_service_receipt.submit_cash_movement",
			{
				pos_profile: props.posProfile,
				opening_shift: props.openingShift,
				movement_type: props.movementType,
				amount: amount.value,
			},
		);
		emit("changed");
		if (result.outcome === "registered") {
			showRegistered(result.receipt);
			return;
		}
		if (result.outcome === "rejected") {
			errorText.value = result.message || __("The POS station rejected the cash movement.");
			return;
		}
		pending.value = result.receipt;
		step.value = "confirm";
	} catch (error) {
		errorText.value = errorMessage(error);
	} finally {
		busy.value = false;
	}
}

async function notPrinted() {
	if (!pending.value?.name) return;
	busy.value = true;
	try {
		await call("erpnext_moldova_pos.api.pos_service_receipt.mark_cash_movement_not_printed", {
			receipt: pending.value.name,
		});
		emit("changed");
		pending.value = null;
		step.value = "amount";
		loadFailed.value = false;
	} catch (error) {
		errorText.value = errorMessage(error);
	} finally {
		busy.value = false;
	}
}

async function printed() {
	await load();
}

async function choose(receiptId) {
	await load(receiptId);
}

async function load(receiptId) {
	if (!pending.value?.name) return;
	busy.value = true;
	errorText.value = "";
	try {
		const result = await call(
			"erpnext_moldova_pos.api.pos_service_receipt.load_printed_cash_movement",
			{
				receipt: pending.value.name,
				receipt_id: receiptId || "",
			},
		);
		emit("changed");
		if (result.outcome === "registered") {
			showRegistered(result.receipt);
			return;
		}
		if (result.outcome === "choose") {
			candidates.value = result.candidates || [];
			step.value = "choose";
			loadFailed.value = false;
			return;
		}
		loadFailed.value = true;
		step.value = "confirm";
	} catch (error) {
		loadFailed.value = true;
		step.value = "confirm";
		const parsed = parseError(error);
		errorText.value = parsed.message || parsed.title || __("Could not load the data from the terminal.");
	} finally {
		busy.value = false;
	}
}
</script>
