// Thread pinning: the browser translation of the CLI's per-user oid check. A thread belongs to the account that
// started it; a send under another account is refused and a new thread starts for that account.
export type ThreadDecision = { allowed: true; threadId: string } | { allowed: false; threadId: string };

export class ThreadPin {
  private threadId: string;
  private owner: string | null = null;

  constructor(private readonly newId: () => string = () => crypto.randomUUID()) {
    this.threadId = newId();
  }

  current(): string {
    return this.threadId;
  }

  /** Call before every send with the signed-in account's homeAccountId. */
  claim(homeAccountId: string): ThreadDecision {
    if (this.owner === null) {
      this.owner = homeAccountId;
      return { allowed: true, threadId: this.threadId };
    }
    if (this.owner === homeAccountId) return { allowed: true, threadId: this.threadId };
    this.reset();
    this.owner = homeAccountId;
    return { allowed: false, threadId: this.threadId };
  }

  reset(): void {
    this.threadId = this.newId();
    this.owner = null;
  }
}
