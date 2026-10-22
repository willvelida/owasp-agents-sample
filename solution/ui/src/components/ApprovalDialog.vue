<script setup lang="ts">
// ASI09: the dialog shows the complete tool call and sends a yes/no decision only. There is no edit field: the
// server rejects edited arguments (400), and the dialog ignores any responseSchema the interrupt carries.
import { onMounted, useTemplateRef } from "vue";

defineProps<{ name: string; args: string }>();
const emit = defineEmits<{ decide: [accepted: boolean] }>();

const dialog = useTemplateRef<HTMLDialogElement>("dialog");

onMounted(() => dialog.value?.showModal());

function decide(accepted: boolean): void {
  dialog.value?.close();
  emit("decide", accepted);
}
</script>

<template>
  <dialog
    ref="dialog"
    class="approval"
    aria-labelledby="approval-title"
    @cancel.prevent
  >
    <h2 id="approval-title">Approve {{ name }}?</h2>
    <p>The agent wants to run this tool with these arguments:</p>
    <pre class="args">{{ args }}</pre>
    <div class="actions">
      <button
        type="button"
        class="approve"
        @click="decide(true)"
      >Approve</button>
      <button
        type="button"
        class="reject"
        @click="decide(false)"
      >Reject</button>
    </div>
  </dialog>
</template>

<style scoped>
.approval {
  max-width: 48rem;
  width: 90vw;
}
.args {
  max-height: 24rem;
  overflow: auto;
  padding: 0.5rem;
  background: #f6f8fa;
  border: 1px solid #d0d7de;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.actions {
  display: flex;
  gap: 1rem;
  justify-content: flex-end;
}
</style>
