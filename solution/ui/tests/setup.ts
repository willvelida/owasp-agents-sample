import { vi } from "vitest";

// jsdom does not implement <dialog>.showModal() or close(); Playwright covers the real dialog in Chromium.
HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
  this.open = true;
});
HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
  this.open = false;
});
