import { createApp } from "vue";
import App from "./App.vue";
import { AUTH_KEY, MsalAuthProvider, type AuthProvider } from "./auth";
import { CONFIG_KEY, loadConfig, type RuntimeConfig } from "./config";
import "./style.css";

function fail(root: HTMLElement, message: string): void {
  root.textContent = message;
}

async function start(): Promise<void> {
  const root = document.getElementById("app");
  if (!root) return;
  let config: RuntimeConfig;
  try {
    config = await loadConfig();
  } catch (error) {
    fail(root, `Configuration error: ${error instanceof Error ? error.message : "config.json is invalid"}`);
    return;
  }
  let provider: AuthProvider;
  try {
    // The provider is chosen before the app exists; components only ever see the AuthProvider interface.
    provider = await MsalAuthProvider.create(config);
  } catch {
    fail(root, "Sign-in could not start. Reload the page to try again.");
    return;
  }
  createApp(App).provide(CONFIG_KEY, config).provide(AUTH_KEY, provider).mount(root);
}

void start();
