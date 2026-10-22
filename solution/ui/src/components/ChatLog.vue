<script setup lang="ts">
import type { Item } from "../events";
import HttpError from "./HttpError.vue";
import ToolCall from "./ToolCall.vue";
import ToolResult from "./ToolResult.vue";

defineProps<{ items: readonly Item[] }>();
defineEmits<{ signIn: [] }>();
</script>

<template>
  <ol
    class="chat-log"
    aria-live="polite"
  >
    <li
      v-for="item in items"
      :key="item.id"
      :class="item.kind"
    >
      <template v-if="item.kind === 'user'">
        <span class="who">you&gt;</span> <span class="text">{{ item.text }}</span>
      </template>
      <span
        v-else-if="item.kind === 'assistant'"
        class="text"
      >{{ item.text }}</span>
      <ToolCall
        v-else-if="item.kind === 'tool-call'"
        :name="item.name"
        :args="item.args"
      />
      <ToolResult
        v-else-if="item.kind === 'tool-result'"
        :content="item.content"
      />
      <template v-else-if="item.kind === 'notice'">
        <strong>? {{ item.text }}</strong>
      </template>
      <template v-else-if="item.kind === 'run-error'">
        <strong>run error:</strong> <span class="text">{{ item.text }}</span>
      </template>
      <HttpError
        v-else
        :status="item.status"
        :text="item.text"
        @sign-in="$emit('signIn')"
      />
    </li>
  </ol>
</template>

<style scoped>
.chat-log {
  list-style: none;
  padding: 0;
  margin: 0;
}
li {
  margin: 0.5rem 0;
}
.text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.user .who {
  color: #1a7f37;
  font-weight: bold;
}
.notice {
  color: #9a6700;
}
.run-error {
  color: #a40e26;
}
</style>
