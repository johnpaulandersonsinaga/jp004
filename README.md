# jp004

![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)
![No build step](https://img.shields.io/badge/build-none-lightgrey)
![Local first](https://img.shields.io/badge/data-localStorage-green)

A personal, global investment terminal for tracking stocks, cash
flows, dividends, fees, and derivatives across multiple markets and
currencies.

jp004 runs entirely in your browser. There is no account, no cloud
database, and no order execution. A small local Python server serves
the app and proxies live market prices. Your trade data stays in your
own browser unless you explicitly export it.

## Contents

- [Is jp004 for you?](#is-jp004-for-you)
- [Features](#features)
- [Try it in two minutes](#try-it-in-two-minutes)
- [Screenshots](#screenshots)
- [Getting started](#getting-started)
- [Usage](#usage)
- [Configuration](#configuration)
- [Data and privacy](#data-and-privacy)
- [Project structure](#project-structure)
- [Server endpoints](#server-endpoints)
- [Contributing](#contributing)
- [Support](#support)
- [Security](#security)
- [License](#license)
- [Acknowledgements](#acknowledgements)
- [Disclaimer](#disclaimer)

## Is jp004 for you?

jp004 is for investors who want to track their own portfolio **without
uploading their financial records to the cloud**.

It fits you if:

- You invest across several markets and currencies and want one
  journal, not one spreadsheet per broker.
- You care about realized vs. unrealized P&L, cost basis, and XIRR,
  not just a current balance.
- You are comfortable running a small local server and keeping your
  own backups.
- You want full control over your data: export it, delete it, and
  move it yourself.

It is not for you if you want automatic broker sync, order placement,
or a hosted account. jp004 deliberately does none of those.

## Features

### Portfolio overview

- Performance summary: balance, invested capital, total equity,
  unrealized P&L, realized P&L, and XIRR.
- Multi-currency positions with a selectable reporting currency and
  editable exchange rates.
- Light and dark themes.

### Trade journal

- Transaction types: BUY, SELL, DEPOSIT, WITHDRAW, DIVIDEND, FEE,
  WARRANT, and RIGHT.
- Bonus shares and grants are recorded as zero-price buys, so they do
  not distort cash or cost basis.
- Per-ticker detail view with positions, trades, disabled trades, and
  hedge pairs.
- Position cost is calculated as a running average including fees.
  Same-day transactions are ordered chronologically, not buy-first.

### Pairing and consolidation

- **Pair:** match one buy with one sell to lock in realized P&L for
  that pair.
- **Auto Pair:** pair eligible buys and sells automatically.
- **Consolidate BUYs / SELLs:** merge multiple trades of the same
  action into a single weighted-average trade. The original trades are
  kept as disabled trades with a replacement reference, so history is
  never silently rewritten.
- **Undo:** consolidated and paired trades can be undone from the
  trade table or the ticker detail view.

### Split and reverse split

- Available in the ticker detail view when exactly one active BUY or
  SELL trade remains for that ticker and its quantity is greater than
  zero. Exercise-linked trades cannot be split.
- The original trade is disabled and replaced by a single trade with
  the new quantity and a price adjusted so that gross value, invested
  capital, cash flow, and pair P&L are unchanged. Fractional shares
  are discarded and shown in the confirmation preview.
- A split date and ratio are stored on the replacement trade for
  future charting. Closed pairs are never touched by a split.

### Prices and exchange rates

- **Refresh Prices:** fetches current prices from the TradingView
  scanner for all active positions.
- **Refresh FX / Exchange Rates:** refreshes and edits the currency
  rates used to convert positions into the reporting currency.
- Broker fee defaults are Buy 0.15% and Sell 0.25%. Fee changes apply
  to new trades only; historical trades keep their original fee
  snapshot.

### Import, export, and printing

- **Save File:** exports the full journal as a JSON file.
- **Load File:** imports a JSON or Excel (.xlsx) journal. Loading
  replaces the entire current journal, including pairs, so export a
  backup first.
- **Print / Download:** print or download the positions and trades
  tables from the main view.
- **Reset All:** clears all local data. This cannot be undone except
  by loading a previously exported file.

## Try it in two minutes

A fictional sample portfolio is included as `demo.json` (301 trades,
2024–2026, for illustration only). To try the app without entering
your own trades, open the app and use **Load File** to load `demo.json`,
then explore positions, pairs, and performance. Otherwise, start with
your own first entries:

1. Start the server (see [Getting started](#getting-started)) and
   open `http://127.0.0.1:28633/`.
2. Add a DEPOSIT transaction for your starting cash.
3. Add a BUY transaction for a ticker you hold.
4. Press **Refresh Prices** to fetch its current price.
5. Press **Save File** to export your first backup.

That is the whole loop: enter trades, refresh prices, export often.

## Screenshots

All screenshots below show the fictional `demo.json` portfolio, not a
real portfolio.

### Performance summary and active positions

<img src="screenshots/app-main.jpg" alt="Performance summary and active positions" width="360">

### Exchange rates

<img src="screenshots/exchange-rates.jpg" alt="Exchange rates panel" width="360">

### Exchange and currency pickers

<img src="screenshots/exchange-selector.jpg" alt="Exchange picker" width="360">

<img src="screenshots/currency-selector.jpg" alt="Currency picker" width="360">

## Getting started

### Requirements

- Python 3 (tested with Python 3.12)
- A modern browser
- No API key, account, or login is required.

### Run the local server

```bash
git clone <your-repository-url>
cd jp004
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Then open:

```
http://127.0.0.1:28633/
```

If port 28633 is already in use, the server picks the next free port
and prints the actual URL on startup. Prefer resolving the port
conflict over accepting a new port: a different port is a different
browser origin, and your journal will appear empty (see
[Data and privacy](#data-and-privacy)).

The journal itself works without the server, but live price and
exchange-rate refresh require the server to be running, because the
browser calls its `/api/price` and `/api/prices` endpoints.

For agent-assisted setup, maintenance, and troubleshooting, see
[INSTRUCTIONS.md](INSTRUCTIONS.md).

## Usage

### Entering trades

Use **Add Transaction** on the main page. Choose the action, date,
ticker, quantity, and price. Cash actions (DEPOSIT, WITHDRAW, DIVIDEND,
FEE) affect the balance without creating a position. WARRANT and RIGHT
are derivative actions with their own handling.

### Pairing and consolidating

Open a ticker to see its trades. Select trades with the checkboxes to
enable **Pair** (exactly one buy and one sell) or **Consolidate**
(two or more trades of the same action). **Auto Pair** pairs eligible
trades without manual selection. Use consolidation before a split:
a split requires exactly one active trade per ticker.

### Splitting a position

Open the ticker, then use **Split / Reverse Split**. Enter the old
share count, the new share count, and the split date, then confirm the
preview. The original trade is disabled and replaced; pairs are
untouched. Use **Undo Split** to revert.

### Backups

Export with **Save File** after every session that changes trades.
Keep exports outside the browser. Loading a file replaces everything,
so a backup is the only way back from an unwanted import or a
**Reset All**.

## Configuration

### Exchange reference (`ref_table.csv`)

Each row maps a market to its TradingView symbol prefix and currency:

```
country,country_code,exchange,mic,suffix_yahoo,prefix_tradingview,currency,currency_symbol
```

The file covers 81 exchanges. The server loads it once at startup,
so restart the server after editing it.

### Broker fees

Fee defaults are set in the app's Broker Fees section and stored in
the browser. They apply to newly entered trades only.

## Data and privacy

- Trade data is stored only in the browser's `localStorage`, under
  keys such as `tj_trades_v4`, `tj_pairs_v4`, `tj_fx_v4`,
  `tj_fees_v4`, and `tj_nextseq_v4`.
- The server does not store trades. It serves static files and
  forwards price requests to TradingView.
- Because data lives in `localStorage`, it is tied to the origin
  (`scheme://host:port`). Opening the app at a different host or port
  will show an empty journal. Keep the URL identical
  (`http://127.0.0.1:28633/` by default) to keep your data visible.
- Personal export files (for example dated trade JSON or CSV files)
  are not part of this repository, with one exception: the fictional
  `demo.json` sample. See `.gitignore`.

## Project structure

```
jp004/
├── jp004.html        # The single-page app (HTML, CSS, JavaScript)
├── server.py         # Flask server: static files + price proxy
├── ref_table.csv     # Exchange reference: 81 exchanges (MIC, country,
│                     # TradingView prefix, currency)
├── requirements.txt  # Flask, requests
├── demo.json         # Fictional sample portfolio (301 trades) for trying the app
├── screenshots/      # App screenshots (demo data)
├── README.md         # This file
├── LICENSE           # Apache License 2.0
├── INSTRUCTIONS.md   # Agent runbook: local setup and maintenance
└── .gitignore        # Excludes personal data exports and logs
```

## Server endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Serves the app (`jp004.html`) |
| `GET /api/health` | Health check, returns `{"status": "ok"}` |
| `GET /api/price?ticker=BBCA&mic=XIDX` | Single current price |
| `POST /api/prices` | Batch current prices for a list of positions |

Prices come from the public TradingView scanner and may differ from a
broker's quoted prices.

## Contributing

Contributions are welcome. The usual open-source flow applies:

1. Open an issue first for anything larger than a typo, so the change
   can be discussed before code is written.
2. Fork the repository, create a focused branch, and open a pull
   request against `main`.
3. Keep pull requests small and focused on one change. A pull request
   that mixes a feature, a refactor, and a data change is hard to
   review.
4. Do not add a new dependency without discussing it in the issue
   first. jp004 intentionally has a minimal stack: vanilla
   JavaScript with no build step, plus Flask and requests on the
   server.
5. Verify before submitting: the server answers `/api/health`, the
   app loads with HTTP 200, and no personal data, export file, or
   credential is included in the change.
6. Never commit personal trade exports, logs, or backup files. The
   `.gitignore` already excludes them; do not force-add them.

Good first contributions: documentation fixes, exchange reference
corrections in `ref_table.csv`, accessibility improvements, and
additional troubleshooting entries in `INSTRUCTIONS.md`.

## Support

- **Questions and usage help:** GitHub Discussions.
- **Bugs and feature requests:** GitHub Issues, with steps to
  reproduce, the browser and Python versions, and the relevant log
  output (without any personal trade data).

## Security

If you find a security issue, do not open a public issue. Use
GitHub's private security advisory flow for this repository so the
issue can be fixed before it is disclosed.

## License

jp004 is licensed under the Apache License 2.0. See the
[LICENSE](LICENSE) file for the full text.

## Acknowledgements

- [Flask](https://flask.palletsprojects.com/) for the local server.
- [TradingView](https://www.tradingview.com/) scanner for live price
  data.

## Disclaimer

This software is provided for personal record-keeping. It is not
financial advice, and its calculations are not a substitute for a
broker's official statements. Verify realized and unrealized figures
against your broker before making investment decisions.
