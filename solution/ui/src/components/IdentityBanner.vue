<script setup lang="ts">
defineProps<{ name: string | null; upn: string | null; signedIn: boolean }>();
defineEmits<{ signIn: []; signOut: [] }>();
</script>

<template>
  <header class="identity-banner">
    <template v-if="signedIn">
      <span>Signed in as <strong class="name">{{ name }}</strong> <span class="upn">({{ upn }})</span></span>
      <button
        type="button"
        @click="$emit('signOut')"
      >Sign out</button>
    </template>
    <template v-else>
      <span>Not signed in</span>
      <button
        type="button"
        @click="$emit('signIn')"
      >Sign in</button>
    </template>
  </header>
</template>

<style scoped>
.identity-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 1rem;
  background: #ddf4ff;
  border-bottom: 1px solid #54aeff;
}
.upn {
  color: #57606a;
}
</style>
