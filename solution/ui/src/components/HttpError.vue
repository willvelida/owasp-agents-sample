<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ status: number; text: string }>();
defineEmits<{ signIn: [] }>();

const summary = computed(() => {
  switch (props.status) {
    case 401:
      return "Your sign-in is no longer valid (401). Sign in again.";
    case 400:
      return "The server rejected the request (400).";
    case 403:
      return "Access denied (403).";
    default:
      return `The server returned HTTP ${props.status}.`;
  }
});
</script>

<template>
  <div
    class="http-error"
    role="alert"
  >
    <p class="summary">{{ summary }}</p>
    <p
      v-if="text"
      class="detail"
    >{{ text }}</p>
    <button
      v-if="status === 401"
      type="button"
      @click="$emit('signIn')"
    >Sign in again</button>
  </div>
</template>

<style scoped>
.http-error {
  border-left: 4px solid #cf222e;
  padding: 0.25rem 0.75rem;
  margin: 0.5rem 0;
}
.summary {
  font-weight: bold;
  color: #a40e26;
}
.detail {
  font-family: ui-monospace, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
