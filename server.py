import os
import sys
import json
import sqlite3
import csv
import socket
import platform
import subprocess
import threading
import time
import webbrowser
import urllib.request
import urllib.error
from datetime import datetime, timezone

from flask import Flask, request, jsonify, send_from_directory
import requests

HOST = '127.0.0.1'
PORT = 28634
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jp004.db')
HTML_FILE = 'jp004.html'
AUTO_OPEN_BROWSER = True
MAX_WAIT_SECONDS = 15

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0 Safari/537.36'),
    'Accept': 'application/json,text/plain,*/*',
}

@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
    return resp

@app.route('/')
def index():
    if not os.path.exists(os.path.join(BASE_DIR, HTML_FILE)):
        return (f"<h2>File {HTML_FILE} not found</h2>"
                f"<p>Place {HTML_FILE} in the same folder as server.py</p>"), 404
    return send_from_directory(BASE_DIR, HTML_FILE)

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)

@app.route('/api/health')
def api_health():
    return jsonify({'status': 'ok', 'time': datetime.now(timezone.utc).isoformat()})

SCANNER_URL = 'https://scanner.tradingview.com/{slug}/scan'
SCAN_COLUMNS = ['name', 'description', 'close', 'currency']
BATCH_SIZE = 200

SCANNER_SLUGS = {
    'UNITED STATES': 'america', 'UNITED KINGDOM': 'uk', 'SOUTH KOREA': 'korea',
    'SOUTH AFRICA': 'rsa', 'SAUDI ARABIA': 'ksa', 'TÜRKİYE': 'turkey',
    'TURKIYE': 'turkey', 'HONG KONG': 'hongkong', 'HONGKONG': 'hongkong',
    'PHILIPIPINES': 'philippines',
    'UNITED ARAB EMIRATES': 'uae',
}

def load_ref_table():
    # DB first: ref_table table in jp004.db (inserted from ref_table.csv).
    # CSV fallback keeps the server working on a fresh DB without that table.
    try:
        if os.path.exists(DB_PATH):
            con = sqlite3.connect(DB_PATH)
            try:
                db_rows = con.execute(
                    'SELECT country, country_code, exchange, mic, suffix_yahoo, '
                    'prefix_tradingview, currency, currency_symbol FROM ref_table'
                ).fetchall()
            finally:
                con.close()
            if db_rows:
                ref = {}
                for country, _cc, _exch, mic, _suffix, prefix, ccy, _sym in db_rows:
                    mic = (mic or '').strip().upper()
                    if not mic:
                        continue
                    country_u = (country or '').strip().upper()
                    ref[mic] = {
                        'prefix': (prefix or '').strip(),
                        'slug': SCANNER_SLUGS.get(country_u, country_u.lower().replace(' ', '')),
                        'currency': (ccy or '').strip(),
                    }
                if ref:
                    print(f'  ref_table loaded from DB: {len(ref)} exchanges')
                    return ref
    except Exception as e:
        print(f'  ref_table DB read failed ({e}), falling back to CSV')
    path = os.path.join(BASE_DIR, 'ref_table.csv')
    ref = {}
    if not os.path.exists(path):
        print(f'  ⚠️  ref_table.csv not found in {BASE_DIR}')
        return ref
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            mic = (row.get('mic') or '').strip().upper()
            if not mic:
                continue
            country = (row.get('country') or '').strip().upper()
            ref[mic] = {
                'prefix': (row.get('prefix_tradingview') or '').strip(),
                'slug': SCANNER_SLUGS.get(country, country.lower().replace(' ', '')),
                'currency': (row.get('currency') or '').strip(),
            }
    return ref

REF = load_ref_table()

def tv_symbol(ticker, mic):
    info = REF.get(mic)
    if not info or not info['prefix']:
        return None
    t = ticker.strip().upper()
    return t if t.startswith(info['prefix'].upper()) else info['prefix'] + t

def scan_tradingview(slug, symbols):
    out = {}
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i + BATCH_SIZE]
        r = requests.post(
            SCANNER_URL.format(slug=slug),
            json={'symbols': {'query': {'types': []}, 'tickers': batch},
                  'columns': SCAN_COLUMNS,
                  'range': [0, len(batch)]},
            headers={'User-Agent': HEADERS['User-Agent']},
            timeout=30,
        )
        if r.status_code == 404:
            raise RuntimeError(f"scanner '{slug}' not found (HTTP 404)")
        r.raise_for_status()
        for item in r.json().get('data', []):
            d = (item.get('d') or []) + [None] * 4
            _name, desc, close, ccy = d[:4]
            if close is not None:
                out[item.get('s')] = {'price': close, 'currency': ccy or '',
                                      'companyName': desc or ''}
    return out

@app.route('/api/prices', methods=['POST'])
def api_prices():
    body = request.get_json(silent=True) or {}
    items = body.get('items') or []
    now = datetime.now(timezone.utc).isoformat()
    results, errors = {}, {}

    groups = {}
    for it in items:
        key = str(it.get('key') or '')
        ticker = str(it.get('ticker') or '').strip()
        mic = str(it.get('mic') or '').strip().upper()
        sym = tv_symbol(ticker, mic) if ticker else None
        if not key or not sym:
            errors[key or ticker] = f'MIC {mic or "?"} has no TradingView prefix in ref_table.csv'
            continue
        groups.setdefault(REF[mic]['slug'], {})[sym] = key

    for slug, sym_map in groups.items():
        syms = list(sym_map)
        try:
            found = scan_tradingview(slug, syms)
        except Exception as e:
            for k in sym_map.values():
                errors[k] = f'TradingView failed: {e}'
            continue
        for sym, key in sym_map.items():
            d = found.get(sym)
            if d:
                results[key] = {**d, 'timestamp': now, 'tvSymbol': sym}
            else:
                errors[key] = f'{sym} has no data on TradingView'

    return jsonify({'results': results, 'errors': errors})

@app.route('/api/price')
def api_price():
    ticker = request.args.get('ticker', '').strip()
    mic = request.args.get('mic', '').strip().upper()
    sym = tv_symbol(ticker, mic) if ticker else None
    if not sym:
        return jsonify({'error': 'ticker & mic (with TradingView prefix in ref_table.csv) are required'}), 400
    try:
        found = scan_tradingview(REF[mic]['slug'], [sym])
    except Exception as e:
        return jsonify({'error': f'TradingView failed: {e}'}), 502
    d = found.get(sym)
    if not d:
        return jsonify({'error': f'{sym} has no data on TradingView'}), 404
    return jsonify({'symbol': sym, **d, 'timestamp': datetime.now(timezone.utc).isoformat()})

def find_free_port(preferred_port, host=HOST, max_tries=20):
    port = preferred_port
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                port += 1
    raise RuntimeError('No free port found after several attempts.')

def _try_webbrowser(url):
    try:
        opened = webbrowser.open(url, new=2)
        return bool(opened)
    except Exception:
        return False

def _try_os_native(url):
    system = platform.system().lower()
    candidates = []

    is_wsl = False
    try:
        with open('/proc/version', 'r') as f:
            is_wsl = 'microsoft' in f.read().lower()
    except Exception:
        pass

    if is_wsl:
        candidates = [
            ['wslview', url],
            ['cmd.exe', '/c', 'start', '', url],
            ['powershell.exe', '-Command', f'Start-Process "{url}"'],
        ]
    elif system == 'windows':
        candidates = [['cmd', '/c', 'start', '', url]]
    elif system == 'darwin':
        candidates = [['open', url]]
    else:
        candidates = [
            ['xdg-open', url],
            ['sensible-browser', url],
            ['x-www-browser', url],
            ['gio', 'open', url],
        ]

    for cmd in candidates:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False

def wait_for_server_and_open(open_url, health_check_url, max_wait=MAX_WAIT_SECONDS):
    start = time.time()
    ready = False
    while time.time() - start < max_wait:
        try:
            with urllib.request.urlopen(health_check_url, timeout=1) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.3)

    if not ready:
        print(f'  ⚠️  Server has not responded after {max_wait}s, still trying to open the browser...')

    if _try_webbrowser(open_url):
        print(f'  🌐 Browser opened automatically: {open_url}')
        return
    if _try_os_native(open_url):
        print(f'  🌐 Browser opened automatically (native): {open_url}')
        return

    print(f'  ⚠️  Failed to open the browser automatically.')
    print(f'  ➜  Open manually in your browser: {open_url}')


# ============================================================
# jp004 SQLite storage (revision: live load/save via .db, not JSON file)
# ============================================================
TRADE_COLS = ['id','seq','date','ticker','mic','action','sub_action','dest_ticker',
  'qty','price','fee_pct','currency','amount','fx_to_idr','label',
  'linked_exercise_id','consolidated_into','merged_from','is_split',
  'split_from','split_ratio','split_date']
JS_TO_DB = {'id':'id','seq':'seq','date':'date','ticker':'ticker','mic':'mic',
  'action':'action','subAction':'sub_action','destTicker':'dest_ticker','qty':'qty',
  'price':'price','feePct':'fee_pct','currency':'currency','amount':'amount',
  'fxToIDR':'fx_to_idr','label':'label','linkedExerciseId':'linked_exercise_id',
  'consolidatedInto':'consolidated_into','mergedFrom':'merged_from',
  'isSplit':'is_split','splitFrom':'split_from','splitRatio':'split_ratio',
  'splitDate':'split_date'}
DB_TO_JS = {v:k for k,v in JS_TO_DB.items()}

def db_conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    con.execute('PRAGMA foreign_keys=ON')
    return con

def init_db():
    schema_path = os.path.join(BASE_DIR, 'schema.sql')
    con = db_conn()
    try:
        if os.path.exists(schema_path):
            with open(schema_path, 'r', encoding='utf-8') as f:
                con.executescript(f.read())
        con.commit()
    finally:
        con.close()

def trade_to_dict(row):
    d = {}
    for col in TRADE_COLS:
        v = row[col]
        if col == 'merged_from':
            d['mergedFrom'] = json.loads(v) if v else None
        elif col == 'is_split':
            d['isSplit'] = bool(v) if v is not None else None
        else:
            d[DB_TO_JS[col]] = v
    # drop None optional keys to match JS shape closely, keep required ones
    return {k: v for k, v in d.items() if v is not None or k in ('id','seq','date','action')}

def load_state_from_db():
    con = db_conn()
    try:
        trades = [trade_to_dict(r) for r in con.execute(
            'SELECT * FROM trades ORDER BY date, seq')]
        pairs = []
        for r in con.execute('SELECT * FROM hedge_pairs'):
            pairs.append({'id': r['id'], 'buyId': r['buy_id'], 'sellId': r['sell_id'],
                          'qty': r['qty'], 'remBuyId': r['rem_buy_id'], 'remSellId': r['rem_sell_id']})
        meta = {r['key']: r['value'] for r in con.execute('SELECT key, value FROM meta')}
        prices = {}
        for r in con.execute('SELECT symbol, entry_json, price FROM price_cache'):
            if r['entry_json']:
                try: prices[r['symbol']] = json.loads(r['entry_json']); continue
                except Exception: pass
            prices[r['symbol']] = {'price': r['price']}
        fx = {}
        try: fx = json.loads(meta.get('fx', '{}'))
        except Exception: fx = {}
        return {
            'trades': trades, 'hedgePairs': pairs,
            'buyFeePct': float(meta.get('buy_fee_pct', '0.15')),
            'sellFeePct': float(meta.get('sell_fee_pct', '0.25')),
            'nextSeq': int(meta.get('next_seq', '1')),
            'baseCurrency': meta.get('base_currency', 'IDR'),
            'fxToIDR': fx.get('rates', {}), 'fxMeta': fx.get('meta', {}),
            'prices': prices,
        }
    finally:
        con.close()

def save_state_to_db(data):
    con = db_conn()
    try:
        con.execute('BEGIN')
        con.execute('DELETE FROM trades')
        con.execute('DELETE FROM hedge_pairs')
        con.execute('DELETE FROM price_cache')
        for tr in data.get('trades', []):
            vals = []
            for col in TRADE_COLS:
                js = DB_TO_JS[col]
                v = tr.get(js)
                if col == 'merged_from':
                    v = json.dumps(v) if v is not None else None
                elif col == 'is_split':
                    v = 1 if v else 0
                vals.append(v)
            con.execute('INSERT INTO trades (%s) VALUES (%s)' % (
                ','.join(TRADE_COLS), ','.join('?'*len(TRADE_COLS))), vals)
        for pr in data.get('hedgePairs', []):
            con.execute('INSERT INTO hedge_pairs (id, buy_id, sell_id, qty, rem_buy_id, rem_sell_id) VALUES (?,?,?,?,?,?)',
                        (pr.get('id'), pr.get('buyId'), pr.get('sellId'), pr.get('qty'), pr.get('remBuyId'), pr.get('remSellId')))
        for sym, entry in (data.get('prices') or {}).items():
            price = entry.get('price') if isinstance(entry, dict) else None
            con.execute('INSERT INTO price_cache (symbol, price, entry_json) VALUES (?,?,?)',
                        (sym, price, json.dumps(entry) if isinstance(entry, dict) else None))
        meta = {
            'buy_fee_pct': str(data.get('buyFeePct', 0.15)),
            'sell_fee_pct': str(data.get('sellFeePct', 0.25)),
            'next_seq': str(data.get('nextSeq', 1)),
            'base_currency': str(data.get('baseCurrency', 'IDR')),
            'fx': json.dumps({'rates': data.get('fxToIDR', {}), 'meta': data.get('fxMeta', {})}),
        }
        for k, v in meta.items():
            con.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)', (k, v))
        con.commit()
        return len(data.get('trades', []))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

init_db()

@app.route('/api/db/health')
def api_db_health():
    st = load_state_from_db()
    return jsonify({'status': 'ok', 'db': os.path.basename(DB_PATH),
                    'exists': os.path.exists(DB_PATH),
                    'trade_count': len(st['trades'])})

@app.route('/api/db/state')
def api_db_state():
    return jsonify(load_state_from_db())

@app.route('/api/db/trades')
def api_db_trades():
    try:
        page = max(1, int(request.args.get('page', '1')))
        per_page = max(1, min(500, int(request.args.get('per_page', '50'))))
    except ValueError:
        page, per_page = 1, 50
    st = load_state_from_db()
    trades = st['trades']
    action = request.args.get('action')
    ticker = request.args.get('ticker')
    if action and action != 'ALL':
        trades = [t for t in trades if t.get('action') == action]
    if ticker:
        trades = [t for t in trades if (t.get('ticker') or '').upper() == ticker.upper()]
    total = len(trades)
    start = (page - 1) * per_page
    return jsonify({'items': trades[start:start+per_page], 'total': total,
                    'page': page, 'per_page': per_page,
                    'total_pages': (total + per_page - 1)//per_page if total else 0})

@app.route('/api/db/save', methods=['POST'])
def api_db_save():
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data.get('trades'), list):
        return jsonify({'error': 'trades must be a list'}), 400
    n = save_state_to_db(data)
    return jsonify({'status': 'ok', 'saved_trades': n})


if __name__ == '__main__':
    if not os.path.exists(os.path.join(BASE_DIR, HTML_FILE)):
        print(f'\n  ❌ File {HTML_FILE} not found in this folder!')
        print(f'  ➜ Place {HTML_FILE} in the same folder as server.py\n')
        sys.exit(1)

    try:
        actual_port = find_free_port(PORT)
    except RuntimeError as e:
        print(f'\n  ❌ {e}\n')
        sys.exit(1)

    if actual_port != PORT:
        print(f'  ℹ️  Port {PORT} is in use, using port {actual_port} instead.')

    url = f'http://{HOST}:{actual_port}/'
    health_url = f'http://{HOST}:{actual_port}/api/health'

    print('\n' + '='*55)
    print('  jp004 — Local Server')
    print('='*55)
    print(f'  HTML   : {HTML_FILE}')
    print(f'  Server : {url}')
    print(f'  API    : {url}api/price?ticker=BBCA&mic=XIDX  (TradingView)')
    print('='*55 + '\n')

    if AUTO_OPEN_BROWSER:
        threading.Thread(
            target=wait_for_server_and_open, args=(url, health_url), daemon=True
        ).start()

    app.run(host=HOST, port=actual_port, debug=False, use_reloader=False)