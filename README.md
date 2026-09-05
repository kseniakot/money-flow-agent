# Money Flow Agent

A local Telegram bot for tracking personal expenses. Expenses arrive as text, voice or photo (receipt / bank statement), a local model parses them, the bot shows what it recognised for review, and after approval writes it to SQLite. Wallets per currency, savings, subscriptions, reports with charts. Everything runs on your own machine, no data leaves it.

## Features

- **Text** — "milk 1.92, bananas 4.32 (2.01 per kg), headphones 30 usd" → recognises quantity, unit price, weight in kg, currency.
- **Voice** — transcribed via Whisper, then handled as text.
- **Photo** — the model decides on its own whether it is a receipt or a screenshot of bank charges (with a caption explaining it), and extracts the line items.
- **Review before saving** — the bot sends a readable preview with ✅/❌ buttons. Any message (text/voice) during review is treated as an edit: "milk is 2.10 not 1.92", "drop the eggs", "currency is euro".
- **Discounts** — a per item discount from the receipt is stored, the net price is what lands in the database.
- **Wallets** — one spending and one savings wallet per currency, the total is shown in USD at the National Bank of Belarus rate. An expense hits the wallet of its own currency, going negative is allowed.
- **Currency exchange** — `/exchange` moves money between wallets at a given rate and keeps the exchange history.
- **Ledger** — `/ledger` prints a wallet statement for a period: every movement plus the resulting balance.
- **Subscriptions** — a daily job charges subscriptions on the configured day of the month and notifies you with a cancel button.
- **Reports** — `/report` for a period: a three level breakdown (category → product → purchases) plus a pie chart.

## Requirements

- Python 3.12, [uv](https://docs.astral.sh/uv/)
- [LM Studio](https://lmstudio.ai/) with the **Qwen3-VL-8B-Instruct (MLX)** model and a running local server
- `openai-whisper` (CLI) — for voice messages
- `ffmpeg` — Whisper uses it to read audio
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Install

```bash
uv sync
brew install ffmpeg           # if not installed yet
pip install -U openai-whisper # if not installed yet (installed system wide, called as a CLI)
```

## Configuration

Copy `.env.example` to `.env` and fill in the token:

```bash
cp .env.example .env
```

```
TG_TOKEN=<token from BotFather>
LM_BASE_URL=http://localhost:1234/v1
LM_MODEL=qwen3-vl-8b-instruct-mlx
WHISPER_MODEL=medium
DEFAULT_CURRENCY=BYN
```

In LM Studio: load the model, open the **Developer → Start Server** tab (port 1234).

## Run

```bash
uv run main.py
```

## Commands

| Command | What it does |
|---|---|
| `/start` | registration, welcome message |
| `/report 2026-08-01 2026-08-31` | report for a period + chart |
| `/wallets` | balances of all wallets + total in USD |
| `/deposit 100 USD [comment]` | top up the spending wallet |
| `/savings 100 USD [comment]` | top up savings (no arguments — show) |
| `/correct USD 90 [savings]` | set a wallet balance to a value |
| `/exchange 100 USD BYN 3.2` | exchange between wallets (no arguments — history) |
| `/ledger USD 2026-08-01 2026-08-31 [savings]` | wallet statement for a period |
| `/subs` | subscriptions; `add <name> <amount> <currency> <day>`, `del <id>` |
| `/categories` | list of categories |
| `/currency USD` | default currency |
| `/history` | full purchase history (CSV file) |
| `/edit <id>` | fix a purchase |
| `/del <id>` | delete a purchase |
| `/undo` | delete the last expense |
| `/export` | export expenses to CSV |

## Architecture

```
Telegram ─┬─ text ─────────────────┐
          ├─ voice → Whisper ──────┤→ LangGraph agent → MCP server → SQLite
          └─ photo ────────────────┘        ↑ interrupt (approval)
                                             ↑ Qwen3-VL (LM Studio)
```

- `app/config.py` — settings from `.env`.
- `app/db.py` — schema and database access (raw SQL).
- `app/rates.py` — National Bank of Belarus rates (in-memory cache).
- `app/agent.py` — LangGraph graph with interrupt and memory.
- `app/logging_setup.py` — structlog setup with per chat contextvars.
- `app/backup.py` — periodic staleness based backups.
- `app/mcp/` — MCP boundary: `server.py` (categories resource + `save_expenses` tool), `client.py` (stdio client).
- `app/llm/` — model layer: `client.py` (LM Studio), `prompts.py`, `extract.py` (parse/revise).
- `app/bot/` — Telegram: `handlers.py` (handlers + commands), `render.py`, `reports.py`, `transcribe.py`.

## Tests

```bash
uv run pytest -q
```

## MCP Inspector

Poke the MCP server in the browser:

```bash
uv run mcp dev app/mcp/server.py
```
