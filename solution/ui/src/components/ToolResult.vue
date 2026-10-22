<script setup lang="ts">
defineProps<{ content: string }>();
</script>

<template>
  <figure class="tool-result">
    <figcaption>raw tool result; the model receives it inside &lt;untrusted-data&gt;</figcaption>
    <pre>{{ content }}</pre>
  </figure>
</template>

<style scoped>
.tool-result {
  margin: 0.25rem 0 0.75rem;
}
figcaption {
  font-size: 0.8rem;
  color: #57606a;
}
pre {
  max-height: 16rem;
  overflow: auto;
  margin: 0.25rem 0 0;
  padding: 0.5rem;
  background: #f6f8fa;
  border: 1px solid #d0d7de;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
