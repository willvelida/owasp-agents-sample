// After MSAL has handled a redirect, its OAuth response parameters (for example the post-logout `?state=eyJ...`) can
// stay in the address bar. They are not tokens, but they look like one on screen, so they are removed. Call this only
// after handleRedirectPromise() has resolved; MSAL reads them first.
const AUTH_PARAMS = ["state", "code", "error", "error_description", "error_uri", "session_state", "client_info", "iss"];

/** Returns the URL without OAuth response parameters, or null when there is nothing to remove. */
export function withoutAuthParams(href: string): string | null {
  const url = new URL(href);
  const before = url.search;
  for (const name of AUTH_PARAMS) url.searchParams.delete(name);
  if (url.search === before) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

export function stripAuthParams(location: Location = window.location, history: History = window.history): void {
  const cleaned = withoutAuthParams(location.href);
  if (cleaned !== null) history.replaceState(history.state, "", cleaned);
}
