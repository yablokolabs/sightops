import { useState, type FormEvent } from "react";

import { ErrorNote } from "./Common";

export function Composer({
  onSend,
  pending,
  error,
  placeholder = "Ask SightOps…"
}: {
  onSend: (content: string) => Promise<boolean>;
  pending: boolean;
  error: string | null;
  placeholder?: string;
}) {
  const [value, setValue] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = value.trim();
    if (!content || pending) return;
    const ok = await onSend(content);
    if (ok) setValue("");
  }

  return (
    <form onSubmit={submit} className="border-t border-mist bg-white px-4 py-3">
      <label htmlFor="composer" className="sr-only">
        Message SightOps
      </label>
      <div className="flex items-end gap-2">
        <textarea
          id="composer"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          rows={2}
          placeholder={placeholder}
          className="min-h-[44px] flex-1 resize-y rounded-lg border border-mist px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
        />
        <button
          type="submit"
          disabled={pending || value.trim().length === 0}
          className="inline-flex min-h-[44px] items-center rounded-lg bg-brand px-5 text-sm font-semibold text-white transition hover:bg-navy focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-light disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? "Sending…" : "Send"}
        </button>
      </div>
      <p className="mt-1 text-[11px] text-slate">
        SightOps never controls real machinery, and any remediation it proposes is simulated and
        requires your approval.
      </p>
      {error ? (
        <div className="mt-2">
          <ErrorNote message={error} />
        </div>
      ) : null}
    </form>
  );
}
