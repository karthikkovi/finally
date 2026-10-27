"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { formatCurrency, formatQuantity } from "@/lib/format";
import type { ChatActions, ChatMessage, ChatTradeAction, ChatWatchlistAction } from "@/lib/types";

interface ChatPanelProps {
  /** Called after the assistant replies, so the workstation can refresh portfolio and watchlist. */
  onReply?: (actions: ChatActions) => void;
}

const SUGGESTIONS = ["How is my portfolio doing?", "Buy 5 NVDA", "Add PYPL to my watchlist"];

function tradeText(t: ChatTradeAction) {
  const qty = formatQuantity(t.quantity);
  if (t.status === "executed") {
    const verb = t.side === "buy" ? "Bought" : "Sold";
    return `${verb} ${qty} ${t.ticker}${t.price != null ? ` at ${formatCurrency(t.price)}` : ""}`;
  }
  return `${t.side === "buy" ? "Buy" : "Sell"} ${qty} ${t.ticker} failed${t.error ? `: ${t.error}` : ""}`;
}

function watchText(w: ChatWatchlistAction) {
  if (w.status === "applied") {
    return w.action === "add" ? `Added ${w.ticker} to watchlist` : `Removed ${w.ticker} from watchlist`;
  }
  return `Could not ${w.action} ${w.ticker}${w.error ? `: ${w.error}` : ""}`;
}

function ActionList({ actions }: { actions: ChatActions }) {
  const items = [
    ...actions.trades.map((t) => ({ ok: t.status === "executed", text: tradeText(t), kind: t.side })),
    ...actions.watchlist_changes.map((w) => ({ ok: w.status === "applied", text: watchText(w), kind: "watch" })),
  ];
  if (!items.length) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1">
      {items.map((a, i) => (
        <li
          key={i}
          data-testid="chat-action"
          data-status={a.ok ? "ok" : "failed"}
          className={`flex items-start gap-1.5 rounded-sm border-l-2 bg-base/60 px-2 py-1 text-[12px] ${
            a.ok ? (a.kind === "sell" ? "border-down" : a.kind === "buy" ? "border-up" : "border-blue") : "border-accent"
          }`}
        >
          <span aria-hidden="true" className={a.ok ? "text-ink" : "text-accent"}>
            {a.ok ? "✓" : "!"}
          </span>
          <span className={a.ok ? "text-ink" : "text-accent"}>{a.text}</span>
        </li>
      ))}
    </ul>
  );
}

export function ChatPanel({ onReply }: ChatPanelProps) {
  const [open, setOpen] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getChatHistory()
      .then((history) => {
        // Keep anything sent before history arrived.
        if (!cancelled) setMessages((current) => [...history, ...current]);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading, open]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || loading) return;
    const now = new Date().toISOString();
    setMessages((m) => [...m, { id: `local-${now}`, role: "user", content, actions: null, created_at: now }]);
    setDraft("");
    setLoading(true);
    try {
      const reply = await api.sendChat(content);
      const actions = { trades: reply.trades ?? [], watchlist_changes: reply.watchlist_changes ?? [] };
      setMessages((m) => [
        ...m,
        { id: `reply-${Date.now()}`, role: "assistant", content: reply.message, actions, created_at: new Date().toISOString() },
      ]);
      onReply?.(actions);
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: `Message not delivered: ${err instanceof Error ? err.message : "network error"}. Try sending it again.`,
          actions: null,
          created_at: new Date().toISOString(),
          error: true,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  if (!open) {
    return (
      <aside data-testid="chat-panel" data-open="false" className="flex w-10 shrink-0 flex-col items-center border-l border-line bg-panel py-3">
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Open FinAlly assistant"
          className="rounded-sm px-1 py-2 text-[12px] font-semibold text-accent [writing-mode:vertical-rl] hover:bg-raised"
        >
          Ask FinAlly
        </button>
      </aside>
    );
  }

  return (
    <aside
      data-testid="chat-panel"
      data-open="true"
      aria-label="FinAlly assistant"
      className="flex w-[360px] shrink-0 flex-col border-l border-line bg-panel"
    >
      <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
        <div>
          <h2 className="text-[13px] font-semibold text-ink">FinAlly assistant</h2>
          <p className="text-[11.5px] text-muted">Analyzes your book and places trades for you.</p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Collapse assistant"
          className="rounded-sm px-2 py-1 text-muted hover:bg-raised hover:text-ink"
        >
          ⟩
        </button>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3" aria-live="polite">
        {messages.length === 0 && !loading && (
          <div className="text-muted">
            <p>Ask about concentration, P&amp;L, or tell me what to trade.</p>
            <div className="mt-3 flex flex-col items-start gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void send(s)}
                  className="rounded-sm border border-line-strong px-2 py-1 text-left text-[12px] text-ink hover:border-blue"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            data-testid="chat-message"
            data-role={m.role}
            className={m.role === "user" ? "ml-8 flex justify-end" : "mr-4"}
          >
            {m.role === "user" ? (
              <p className="whitespace-pre-wrap rounded-md bg-raised px-2.5 py-1.5 text-ink">{m.content}</p>
            ) : (
              <div className="border-l-2 border-accent/70 pl-2.5">
                <p className={`whitespace-pre-wrap ${m.error ? "text-down" : "text-ink"}`}>{m.content}</p>
                {m.actions && <ActionList actions={m.actions} />}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div data-testid="chat-loading" role="status" className="typing flex items-center gap-1 pl-3 text-accent">
            <span>●</span>
            <span>●</span>
            <span>●</span>
            <span className="sr-only">FinAlly is thinking</span>
          </div>
        )}
      </div>

      <form onSubmit={submit} className="flex gap-1.5 border-t border-line p-2.5">
        <input
          data-testid="chat-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask FinAlly…"
          aria-label="Message FinAlly"
          autoComplete="off"
          className="min-w-0 flex-1 rounded-sm border border-line-strong bg-base px-2 py-1.5 text-ink placeholder:text-faint focus:border-blue focus:outline-none"
        />
        <button
          type="submit"
          data-testid="chat-send"
          disabled={loading || !draft.trim()}
          className="rounded-sm bg-purple px-3 py-1.5 font-medium text-white hover:bg-purple-hover disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
