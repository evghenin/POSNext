<template>
	<Dialog v-model="show" :options="{ title: __('Scanner connection'), size: 'md' }">
		<template #body-content>
			<div class="flex flex-col items-center gap-4 text-center">
				<p class="text-sm text-gray-600">
					{{
						__("Scan this QR to connect the scanner. The code works once.")
					}}
				</p>
				<p v-if="posProfile" class="text-xs text-gray-500">
					{{ posProfile }}
				</p>

				<div
					v-if="loading"
					class="flex flex-col items-center gap-3 py-10"
					role="status"
				>
					<div
						class="w-8 h-8 rounded-full border-2 border-teal-200 border-t-teal-600 animate-spin"
					></div>
					<p class="text-sm text-gray-600">{{ __("Creating scanner connection…") }}</p>
				</div>

				<div
					v-else-if="errorMessage && !challenge"
					class="w-full bg-red-50 border border-red-200 rounded-lg p-4 text-start"
					role="alert"
				>
					<p class="text-sm text-red-800">{{ errorMessage }}</p>
				</div>

				<template v-else-if="challenge">
					<div class="relative">
						<div
							class="bg-white p-3 rounded-xl border border-gray-200 shadow-sm"
							:class="{ 'opacity-40': expired }"
						>
							<img
								v-if="qrDataUrl"
								:src="qrDataUrl"
								width="240"
								height="240"
								class="block w-60 h-60"
								data-testid="pair-scanner-qr"
								:alt="__('Scanner connection QR')"
							/>
							<div
								v-else
								class="w-60 h-60 flex items-center justify-center bg-gray-50 text-sm text-gray-500 px-4"
							>
								{{ qrDrawError || __("Preparing QR…") }}
							</div>
						</div>
						<div
							v-if="expired"
							class="absolute inset-0 flex items-center justify-center"
						>
							<span
								class="bg-gray-900 text-white text-sm font-semibold px-3 py-1.5 rounded-full"
							>
								{{ __("Code expired") }}
							</span>
						</div>
					</div>

					<p
						class="text-sm"
						:class="expired ? 'text-red-600 font-medium' : 'text-gray-600'"
						role="status"
					>
						{{
							expired
								? __("This code has expired. Create a new one to connect.")
								: __("Expires in {0}", [countdownLabel])
						}}
					</p>
					<p v-if="qrDrawError" class="text-xs text-amber-700">{{ qrDrawError }}</p>
				</template>
			</div>
		</template>
		<template #actions>
			<div class="flex w-full justify-end gap-2">
				<Button variant="subtle" @click="show = false">
					{{ __("Close") }}
				</Button>
				<Button
					v-if="errorMessage && !challenge"
					variant="solid"
					theme="blue"
					@click="requestCode"
				>
					{{ __("Try again") }}
				</Button>
				<Button v-else-if="challenge" variant="solid" theme="blue" @click="requestCode">
					{{ __("New code") }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { useScannerPairing } from "@/composables/useScannerPairing"
import { formatPairingCountdown, renderPairingQr } from "@/utils/pairingQr"
import { Button, Dialog } from "frappe-ui"
import { computed, onBeforeUnmount, ref, watch } from "vue"

const props = defineProps({
	modelValue: Boolean,
	posProfile: {
		type: String,
		default: "",
	},
	posOpeningShift: {
		type: String,
		default: "",
	},
})

const emit = defineEmits(["update:modelValue"])

const show = ref(props.modelValue)
const qrDataUrl = ref("")
const qrDrawError = ref("")
let qrTicket = 0

const {
	loading,
	errorMessage,
	challenge,
	secondsLeft,
	issueChallenge,
	cancel,
} = useScannerPairing()

const countdownLabel = computed(() => formatPairingCountdown(secondsLeft.value))
const expired = computed(
	() => Boolean(challenge.value) && !loading.value && secondsLeft.value <= 0,
)

async function refreshQr(payload) {
	const ticket = ++qrTicket
	qrDataUrl.value = ""
	qrDrawError.value = ""
	if (!payload) return
	try {
		const url = await renderPairingQr(payload)
		if (ticket !== qrTicket) return
		qrDataUrl.value = url
	} catch {
		if (ticket !== qrTicket) return
		qrDrawError.value = __(
			"Could not draw the connection QR. Create a new code and try again.",
		)
	}
}

function requestCode() {
	issueChallenge({
		posProfile: props.posProfile,
		posOpeningShift: props.posOpeningShift,
	})
}

watch(
	() => props.modelValue,
	(val) => {
		show.value = val
		if (val) requestCode()
		else cancel()
	},
	{ immediate: true },
)

watch(show, (val) => {
	emit("update:modelValue", val)
	if (!val) cancel()
})

watch(
	() => challenge.value?.qrPayload,
	(payload) => {
		refreshQr(payload)
	},
)

onBeforeUnmount(() => {
	cancel()
})
</script>
