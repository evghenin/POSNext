<template>
	<Teleport to="body">
		<div
			v-if="show"
			class="fixed inset-0 z-[9999] flex items-center justify-center"
			role="alertdialog"
			aria-modal="true"
			aria-labelledby="terminal-wait-title"
		>
			<div class="absolute inset-0 bg-black/70"></div>
			<div class="relative z-10 bg-white rounded-2xl shadow-2xl p-10 max-w-md mx-4 text-center">
				<div
					class="mx-auto mb-6 w-16 h-16 rounded-full border-4 border-blue-200 border-t-blue-600 animate-spin"
				></div>
				<h3 id="terminal-wait-title" class="text-xl font-bold text-gray-900 mb-3">
					{{ __("Calling the terminal") }}
				</h3>
				<p class="text-gray-600 leading-relaxed">
					{{ __("The receipt is being sent to the terminal and printed. Please wait.") }}
				</p>
				<p v-if="cardPayment" class="mt-4 text-gray-900 font-medium leading-relaxed">
					{{
						__(
							"Complete the payment on the terminal. Follow the instructions on the terminal."
						)
					}}
				</p>
			</div>
		</div>
	</Teleport>
</template>

<script setup>
defineProps({
	show: {
		type: Boolean,
		default: false,
	},
	cardPayment: {
		type: Boolean,
		default: false,
	},
});
</script>
