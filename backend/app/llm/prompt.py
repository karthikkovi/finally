"""System prompt, portfolio context and message assembly for the chat LLM."""

from __future__ import annotations

from app import db
from app.services import get_portfolio

SYSTEM_PROMPT = """\
You are FinAlly, an AI trading assistant inside a simulated trading workstation.
The user trades a paper portfolio with virtual money; market orders fill instantly
at the current price.

Your job:
- Analyze portfolio composition, risk concentration and P&L using the context provided.
- Suggest trades with brief, data-driven reasoning.
- Execute trades when the user asks for them or agrees to your suggestion,
  by listing them in "trades".
- Manage the watchlist proactively (add tickers the user is interested in,
  remove ones they no longer want) via "watchlist_changes".
- Be concise: short paragraphs or bullet points, cite numbers.

Rules:
- Always respond with valid JSON matching the schema:
  {"message": string,
   "trades": [{"ticker": string, "side": "buy"|"sell", "quantity": number}],
   "watchlist_changes": [{"ticker": string, "action": "add"|"remove"}]}
- Only include trades the user has asked for or clearly agreed to.
  Use empty arrays when there are no actions.
- Quantities are share counts (> 0, fractional allowed).
  Check cash before buying and holdings before selling.
- Tickers are upper-case symbols such as AAPL.
- In "message", describe what you are doing; execution results are reported
  to the user separately.
"""

HISTORY_LIMIT = 20


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def build_portfolio_context(price_cache) -> str:
    """Render the user's current portfolio and watchlist as plain text for the LLM."""
    portfolio = get_portfolio(price_cache)
    lines = [
        "Current portfolio:",
        f"- Cash: {_money(portfolio.get('cash_balance'))}",
        f"- Positions value: {_money(portfolio.get('positions_value'))}",
        f"- Total value: {_money(portfolio.get('total_value'))}",
        f"- Unrealized P&L: {_money(portfolio.get('unrealized_pnl'))}",
    ]

    positions = portfolio.get("positions") or []
    if positions:
        lines.append(
            "Positions (ticker: qty @ avg cost -> current price, market value, unrealized P&L):"
        )
        for p in positions:
            lines.append(
                f"- {p['ticker']}: {p['quantity']:g} @ {_money(p.get('avg_cost'))} -> "
                f"{_money(p.get('current_price'))}, value {_money(p.get('market_value'))}, "
                f"P&L {_money(p.get('unrealized_pnl'))} "
                f"({p.get('unrealized_pnl_percent') or 0:+.2f}%)"
            )
    else:
        lines.append("Positions: none")

    lines.append("Watchlist (ticker: price, change since session open):")
    for ticker in db.get_watchlist():
        update = price_cache.get(ticker)
        if update is None:
            lines.append(f"- {ticker}: price not yet available")
            continue
        change = getattr(update, "change_percent_open", None)
        change_text = f" ({change:+.2f}%)" if change is not None else ""
        lines.append(f"- {ticker}: {_money(update.price)}{change_text}")

    return "\n".join(lines)


def _describe_actions(actions) -> str:
    """Summarize stored action outcomes so the LLM knows what actually happened."""
    if not isinstance(actions, dict):
        return ""
    parts = []
    for t in actions.get("trades") or []:
        outcome = (
            f"executed at {_money(t.get('price'))}"
            if t.get("status") == "executed"
            else f"FAILED: {t.get('error') or 'unknown error'}"
        )
        parts.append(f"{t.get('side')} {t.get('quantity'):g} {t.get('ticker')} {outcome}")
    for c in actions.get("watchlist_changes") or []:
        outcome = (
            "applied"
            if c.get("status") == "applied"
            else f"FAILED: {c.get('error') or 'unknown error'}"
        )
        parts.append(f"watchlist {c.get('action')} {c.get('ticker')} {outcome}")
    return f"\n[Action results: {'; '.join(parts)}]" if parts else ""


def build_messages(user_message: str, history: list[dict], portfolio_context: str) -> list[dict]:
    """Assemble the chat-completion messages: system prompt, context, history, new message."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": portfolio_context},
    ]
    for entry in history:
        if entry.get("role") in ("user", "assistant") and entry.get("content"):
            content = entry["content"]
            if entry["role"] == "assistant":
                content += _describe_actions(entry.get("actions"))
            messages.append({"role": entry["role"], "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages
