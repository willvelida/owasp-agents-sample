<script setup lang="ts">
import { computed, inject, onMounted, ref, shallowRef } from "vue";
import { resumeBody, runBody, streamRun, type Decision } from "./agui";
import { AUTH_KEY, identityFromToken } from "./auth";
import ApprovalDialog from "./components/ApprovalDialog.vue";
import ChatLog from "./components/ChatLog.vue";
import IdentityBanner from "./components/IdentityBanner.vue";
import { CONFIG_KEY } from "./config";
import {
  addHttpError,
  addNotice,
  addRunError,
  addUserMessage,
  initialState,
  reduce,
  type ChatState,
} from "./events";
import { ThreadPin } from "./threads";

const auth = inject(AUTH_KEY);
const config = inject(CONFIG_KEY);
if (!auth || !config) throw new Error("auth and config must be provided");

// Reactive state holds display data only: never MSAL objects or tokens.
const signedIn = ref(auth.account() !== null);
const name = ref<string | null>(auth.account()?.name ?? null);
const upn = ref<string | null>(auth.account()?.upn ?? null);
const chat = shallowRef<ChatState>(initialState());
const busy = ref(false);
const draft = ref("");
const decided = ref<Decision[]>([]);
const pin = new ThreadPin();

const current = computed(() => (busy.value ? undefined : chat.value.pending[decided.value.length]));

function showIdentity(token: string): void {
  const claims = identityFromToken(token);
  name.value = claims.name ?? name.value;
  upn.value = claims.upn ?? upn.value;
}

async function run(body: ReturnType<typeof runBody>): Promise<void> {
  busy.value = true;
  try {
    const token = await auth!.getToken();
    showIdentity(token);
    const outcome = await streamRun({
      url: config!.chatApiUrl,
      token,
      body,
      onEvent: (event) => (chat.value = reduce(chat.value, event)),
    });
    if (outcome.kind === "http") chat.value = addHttpError(chat.value, outcome.status, outcome.body);
    else if (outcome.kind === "timeout") chat.value = addRunError(chat.value, "no response for 180 s; the run was stopped");
    else if (outcome.kind === "network") chat.value = addRunError(chat.value, `connection error: ${outcome.message}`);
  } catch {
    chat.value = addRunError(chat.value, "could not get a sign-in token");
  } finally {
    busy.value = false;
  }
}

/** ASI03: a thread belongs to the account that started it, as the CLI checks the oid per user. */
function claimThread(): string | null {
  const account = auth!.account();
  if (!account) {
    void auth!.signIn();
    return null;
  }
  const decision = pin.claim(account.homeAccountId);
  if (!decision.allowed) {
    decided.value = [];
    chat.value = addNotice(
      initialState(),
      "This conversation was started by another account, so it was not sent. A new conversation has started; send again.",
    );
    return null;
  }
  return decision.threadId;
}

async function send(): Promise<void> {
  const text = draft.value.trim();
  if (!text || busy.value || current.value) return;
  const threadId = claimThread();
  if (!threadId) return;
  draft.value = "";
  decided.value = [];
  chat.value = addUserMessage(chat.value, text);
  await run(runBody(threadId, text));
}

async function decide(accepted: boolean): Promise<void> {
  const interrupt = current.value;
  if (!interrupt) return;
  decided.value = [...decided.value, { interruptId: interrupt.interruptId, accepted }];
  if (decided.value.length < chat.value.pending.length) return;
  const decisions = decided.value;
  decided.value = [];
  const threadId = claimThread();
  if (!threadId) return;
  await run(resumeBody(threadId, decisions));
}

function signIn(): void {
  void auth!.signIn();
}

function signOut(): void {
  pin.reset();
  void auth!.signOut();
}

onMounted(async () => {
  if (!signedIn.value) return;
  try {
    showIdentity(await auth.getToken());
  } catch {
    // The banner keeps the account's display name until the first run.
  }
});
</script>

<template>
  <IdentityBanner
    :name="name"
    :upn="upn"
    :signed-in="signedIn"
    @sign-in="signIn"
    @sign-out="signOut"
  />
  <main class="chat">
    <ChatLog
      :items="chat.items"
      @sign-in="signIn"
    />
    <p
      v-if="busy"
      class="busy"
    >
      waiting for the agent...
    </p>
    <ApprovalDialog
      v-if="current"
      :key="current.interruptId"
      :name="current.name"
      :args="current.args"
      @decide="decide"
    />
    <form
      class="composer"
      @submit.prevent="send"
    >
      <label
        for="message"
        class="visually-hidden"
      >Message</label>
      <textarea
        id="message"
        v-model="draft"
        rows="3"
        :disabled="!signedIn || busy"
        placeholder="Ask about your health data"
        @keydown.enter.exact.prevent="send"
      />
      <button
        type="submit"
        :disabled="!signedIn || busy || !draft.trim()"
      >
        Send
      </button>
    </form>
  </main>
</template>
