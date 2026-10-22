<script setup lang="ts">
defineProps<{ name: string; args: string }>();
</script>

<template>
  <div class="tool-call">
    <span class="label">&gt; tool</span> <span class="name">{{ name }}</span>(<span class="args">{{ args }}</span>)
  </div>
</template>

<style scoped>
.tool-call {
  font-family: ui-monospace, Consolas, monospace;
  color: #0b5394;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.label {
  font-weight: bold;
}
.args {
  color: #7a4b00;
}
</style>
