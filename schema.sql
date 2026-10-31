-- jp004 SQLite schema (from RANCANGAN-JP004-SQLITE.md, adapted)
-- Run: sqlite3 jp004.db < schema.sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS trades (
  id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL UNIQUE,
  date TEXT NOT NULL,
  ticker TEXT,
  mic TEXT,
  action TEXT NOT NULL,
  sub_action TEXT,
  dest_ticker TEXT,
  qty REAL,
  price REAL,
  fee_pct REAL,
  currency TEXT,
  amount REAL,
  fx_to_idr REAL NOT NULL DEFAULT 1,
  label TEXT,
  linked_exercise_id TEXT,
  consolidated_into TEXT,
  merged_from TEXT,
  is_split INTEGER NOT NULL DEFAULT 0,
  split_from TEXT,
  split_ratio TEXT,
  split_date TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_date_seq ON trades(date, seq);
CREATE INDEX IF NOT EXISTS idx_trades_ticker_mic ON trades(ticker, mic, date, seq);
CREATE INDEX IF NOT EXISTS idx_trades_action ON trades(action);
CREATE INDEX IF NOT EXISTS idx_trades_active ON trades(consolidated_into);
CREATE INDEX IF NOT EXISTS idx_trades_seq ON trades(seq);

CREATE TABLE IF NOT EXISTS hedge_pairs (
  id TEXT PRIMARY KEY,
  buy_id TEXT,
  sell_id TEXT,
  qty REAL,
  rem_buy_id TEXT,
  rem_sell_id TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS fx_rates (
  currency TEXT PRIMARY KEY,
  rate_to_idr REAL,
  meta_json TEXT
);
CREATE TABLE IF NOT EXISTS price_cache (
  symbol TEXT PRIMARY KEY,
  ticker TEXT,
  mic TEXT,
  price REAL,
  price_date TEXT,
  company_name TEXT,
  entry_json TEXT
);

CREATE TABLE IF NOT EXISTS ref_table (
  country TEXT,
  country_code TEXT,
  exchange TEXT,
  mic TEXT PRIMARY KEY,
  suffix_yahoo TEXT,
  prefix_tradingview TEXT,
  currency TEXT,
  currency_symbol TEXT
);
CREATE INDEX IF NOT EXISTS idx_ref_table_country ON ref_table(country);
