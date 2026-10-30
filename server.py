import os
import sys
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
PORT = 28633
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