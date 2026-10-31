# Rancangan Migrasi jp004 ke SQLite (.db)

**Tujuan:** jp004 bisa menangani jutaan transaksi tanpa browser crash / freeze,
dengan tetap local-first, tanpa auto-sync broker, tanpa subscription.

**Status:** Rancangan saja. Belum ada kode yang diubah, belum ada migrasi yang
dijalankan. Implementasi hanya setelah perintah eksplisit pengguna.

**Tanggal rancangan:** 2026-10-30
**Basis kode yang dirancang:** `jp004.html` versi bersih (seed dihapus, commit
squash `b0089cc`), `server.py` Flask port 28633.

---

## 1. Masalah yang diselesaikan

Sistem saat ini:

- Data trade hidup di `localStorage` browser, per origin
  (`http://127.0.0.1:28633/`). Kunci yang dipakai:
  `tj_trades_v4`, `tj_pairs_v4`, `tj_fees_v4`, `tj_names_v4`,
  `tj_nextseq_v4`, `tj_fx_v4`, `tj_base_v4`.
- Setiap simpan, seluruh array trade di-`JSON.stringify` dan ditulis ulang
  (`saveToStorage()`), dan setiap simpan dibungkus try/catch kosong —
  kalau kuota habis, gagalnya diam-diam.
- Setiap render, `renderTrades()` membuat satu `<tr>` DOM untuk **semua**
  trade, tanpa pagination / virtual scroll, lalu memasang listener per baris.
  `renderAll()` juga menghitung ulang posisi dan summary dengan berkali-kali
  loop atas semua trade.

Akibatnya ada dua batas yang berbeda:

| Batas | Perkiraan | Penyebab |
|---|---|---|
| Penyimpanan | ~25.000–30.000 trade | localStorage ~5 MB/origin, ~163 byte/trade (terukur: 301 trade demo = 49 KB) |
| Tampilan | terasa berat mulai ~5.000 trade, berisiko freeze di atas ~10.000–20.000 | DOM ribuan baris + listener, render ulang penuh tiap perubahan |

Mengganti penyimpanan saja tidak cukup. Kalau server tetap mengirim jutaan
trade dalam satu JSON dan browser tetap me-render semuanya, browser tetap
crash. Karena itu migrasi ini sepaket: **SQLite + API berpaginasi + agregat
di server**.

---

## 2. Arsitektur target

```
Browser (jp004.html)
  │  hanya meminta 1 halaman + agregat, bukan seluruh dataset
  │  GET /api/trades?page=1&per_page=50&...
  │  GET /api/positions, GET /api/summary
  ▼
Flask server.py (port 28633, tidak berubah port/URL-nya)
  │  sqlite3 standar Python (tanpa dependensi baru)
  ▼
jp004.db (SQLite, satu file, di sebelah server.py)
  │  mode WAL, index di kolom yang sering difilter/diurut
  ▼
Backup: salinan .db + export JSON berkala (lihat §8)
```

Prinsip yang dipertahankan:

- Local-first. Tidak ada server cloud, tidak ada akun, tidak ada sync broker.
- Satu file database = satu portfolio. Copy file `.db` = pindah portfolio.
- UI dan istilah yang sudah ada dipertahankan: P&L, XIRR, jurnal, split,
  import/export, manual entry, fee BUY 0,15% / SELL 0,25%, cost = running
  average + fee, urutan kronologis `(date, seq)`.
- File `.db` **tidak pernah** di-commit ke GitHub. Masuk `.gitignore`.
  Yang dipublish tetap hanya kode + `demo.json` fiktif.

### 2.1 Di mana file .db tinggal — keputusan yang harus disadari

`.db` tinggal di mesin yang menjalankan `server.py`, bukan di browser.

- Setup sekarang (server di VM, diakses HP lewat SSH forward):
  `.db` ada di VM. Kalau VM mati / link HP putus, app tidak bisa dibuka
  sama sekali — berbeda dengan sekarang, di mana trade masih bisa dilihat
  dari localStorage walau server mati.
- Setup phone-local (server dijalankan di Termux HP):
  `.db` ada di `/sdcard/jp004/jp004.db`. Ini yang paling setia pada
  semangat local-first jp004, dan membuat app tetap jalan tanpa VM.

**Rekomendasi rancangan:** dukung keduanya dengan satu variabel saja —
lokasi `.db` mengikuti lokasi `server.py` yang dijalankan. Jangan
mengasumsikan satu lokasi. Dokumentasikan di `INSTRUCTIONS.md` bahwa
migrasi dan backup harus dilakukan di mesin yang servernya jalan.

---

## 3. Skema database

Satu tabel utama, ditambah tabel pendukung. Semua kolom trade yang ada di
kode sekarang harus tertampung, supaya tidak ada fitur yang hilang diam-diam.

### 3.1 Tabel `trades`

Kolom inti (nama dan tipe disesuaikan dengan field JSON sekarang):

- `id` TEXT PRIMARY KEY, contoh `TRX-00001` (tetap dipakai sebagai ID
  tampil dan referensi split/merge)
- `seq` INTEGER NOT NULL UNIQUE — urutan global, sumber `tj_nextseq_v4`
- `date` TEXT NOT NULL, format `YYYY-MM-DD`
- `ticker` TEXT, `mic` TEXT — NULL untuk aksi kas (DEPOSIT/WITHDRAW)
- `action` TEXT NOT NULL: BUY, SELL, DEPOSIT, WITHDRAW, DIVIDEND, FEE,
  GRANT, BONUS_STOCK (dinormalisasi jadi BUY di load lama — lihat §5),
  WARRANT, RIGHT
- `sub_action` TEXT: untuk WARRANT/RIGHT — SELL, EXERCISE, EXPIRED, WRITE-OFF
- `dest_ticker` TEXT — untuk exercise WARRANT/RIGHT
- `qty` REAL, `price` REAL — NULL untuk aksi kas/dividen tertentu
- `fee_pct` REAL — NULL berarti legacy/frozen (perilaku lama dipertahankan)
- `currency` TEXT, `amount` REAL — untuk DEPOSIT, WITHDRAW, DIVIDEND, FEE
- `fx_to_idr` REAL NOT NULL DEFAULT 1
- `label` TEXT
- `linked_exercise_id` TEXT — untuk BUY hasil exercise
- `consolidated_into` TEXT — ID trade pengganti, NULL kalau aktif
- `merged_from` TEXT — JSON array ID trade asal (hanya untuk trade hasil merge)
- `is_split` INTEGER 0/1, `split_from` TEXT, `split_ratio` TEXT,
  `split_date` TEXT — metadata split yang sudah ada
- `created_at` / `updated_at` TEXT — audit internal, bukan field tampil

Index yang wajib ada (ini yang membuat jutaan baris tetap cepat):

- `idx_trades_date_seq` pada `(date, seq)` — urutan tampil utama
- `idx_trades_ticker_mic` pada `(ticker, mic, date, seq)` — posisi per ticker
- `idx_trades_action` pada `(action)`
- `idx_trades_active` pada `(consolidated_into)` — filter trade aktif
- `idx_trades_seq` pada `(seq)` — cursor pagination

### 3.2 Tabel pendukung

- `hedge_pairs` — pasangan hedge yang sekarang di `tj_pairs_v4`.
  Kolom: `id`, `leg_a_trade_id`, `leg_b_trade_id`, `created_at`.
  Foreign key ke `trades(id)` secara logis (tidak dipaksakan ON DELETE
  CASCADE, supaya hapus trade tidak menghapus pair diam-diam).
- `meta` (key-value, satu baris per kunci):
  `next_seq`, `buy_fee_pct`, `sell_fee_pct`, `base_currency`.
- `fx_rates` — `currency` PRIMARY KEY, `rate_to_idr`, `meta_json`.
- `price_cache` — `symbol` (simbol Yahoo hasil `tv_symbol`/`getYahooSymbol`)
  PRIMARY KEY, `ticker`, `mic`, `price`, `price_date`, `company_name`.
  Ini menggantikan `tj_names_v4` + cache harga, dan membuat refresh harga
  tidak perlu memuat seluruh trade.

### 3.3 Pengaturan SQLite

- `PRAGMA journal_mode=WAL` — baca tidak memblokir tulis, penting saat
  import besar sambil UI dibuka.
- `PRAGMA synchronous=NORMAL` — cukup untuk file lokal, jauh lebih cepat
  dari FULL saat import massal, risiko kehilangan hanya transaksi terakhir
  yang belum checkpoint saat mesin mati mendadak (diterima, karena ada
  backup export JSON — lihat §8).
- `PRAGMA foreign_keys=ON` untuk konsistensi pair, dengan pengecualian
  yang didokumentasikan di atas.
- Import massal selalu dalam satu transaksi + `executemany`, bukan
  satu commit per baris. Target: puluhan ribu baris per detik di mesin
  sekelas VM/Pavilion ini, bukan ratusan.

---

## 4. API server (perubahan `server.py`)

Endpoint lama dipertahankan: `/`, file statis, `/api/health`,
`/api/prices`, `/api/price`, dan mekanisme `SCANNER_SLUGS` untuk refresh
harga TradingView. Yang ditambah adalah endpoint data, semuanya mengembalikan
JSON dan **tidak pernah** mengembalikan seluruh trade sekaligus tanpa
paginasi.

### 4.1 Membaca (read)

- `GET /api/trades?page=1&per_page=50&action=BUY&ticker=BBCA&mic=XIDX&from=2024-01-01&to=2026-10-30&q=...`
  - Mengembalikan: `items` (halaman itu saja), `total`, `page`,
    `per_page`, `total_pages`.
  - Urutan default: `(date, seq)` menaik, sama seperti sekarang.
  - Filter `action=ALL` = tanpa filter aksi. Trade yang
    `consolidated_into IS NOT NULL` tetap dikembalikan (ditampilkan
    dicoret + label REPLACED BY, seperti sekarang), kecuali pemanggil
    meminta `active_only=1`.
- `GET /api/positions` — agregat SQL per `(ticker, mic)`:
  qty sisa, short qty, cost (running average + fee), invested, dan
  P&L yang belum terealisasi dihitung dari harga terakhir di `price_cache`.
  Browser tidak lagi menghitung posisi dari seluruh trade.
- `GET /api/summary` — kas IDR, net contribution, total dividen, total fee,
  total market value, dan cashflow XIRR (lihat §4.3). Satu panggilan,
  bukan loop berkali-kali di browser.
- `GET /api/trades/<id>` — detail satu trade, dipakai modal edit dan
  modal ticker.
- `GET /api/export` — dump JSON lengkap dengan format yang sama seperti
  export sekarang (field `version`, `trades`, `hedgePairs`, `priceCache`,
  dst.), supaya file export lama tetap bisa dibaca dan file baru tetap
  bisa di-load di versi lama (selama versi lama masih dipakai).

### 4.2 Menulis (write)

Semua operasi tulis harus lewat satu transaksi SQLite, dan mengembalikan
trade/hasil yang baru supaya UI tidak perlu me-load ulang seluruh tabel.

- `POST /api/trades` — tambah satu trade. Server yang menetapkan `seq`
  dari `meta.next_seq` (atomic, bukan dari browser) supaya tidak ada
  duplikasi seq saat dua tab terbuka.
- `PUT /api/trades/<id>` — edit satu trade.
- `DELETE /api/trades/<id>` — hapus satu trade. Perilaku terhadap pair,
  merge, dan split harus sama persis dengan `deleteTrade()` sekarang,
  dan didokumentasikan di kode (bukan diasumsikan).
- `POST /api/trades/<id>/split` — body: `new_ratio`, `old_ratio`,
  `split_date`. Logika yang sudah ada dipertahankan: qty baru =
  floor(qty × baru/lama), harga baru = gross lama / qty baru, gross,
  invested, kas, dan pair P&L tidak berubah, feePct dibekukan, trade
  lama dinonaktifkan sebagai REPLACED BY, Undo Split mengembalikan trade
  lama.
- `POST /api/trades/consolidate`, `POST /api/trades/pair`,
  `POST /api/trades/auto-pair` — memindahkan logika consolidate/pair
  yang sekarang di browser ke server, dengan aturan gating yang sama
  (tepat 1 trade aktif, qty sisa > 0, bukan exercise-linked, dst.).
- `POST /api/import` — terima file JSON/CSV/Excel seperti import sekarang,
  jalankan dalam satu transaksi, laporkan jumlah yang berhasil, yang
  ditolak beserta alasannya, dan **jangan** menimpa data sebelum pengguna
  mengonfirmasi (perilaku konfirmasi `Load N entries...?` dipertahankan).

### 4.3 XIRR — satu-satunya perhitungan yang harus ditulis ulang hati-hati

XIRR sekarang dihitung di browser dari cashflow DEPOSIT/WITHDRAW
(`buildXirrCashflows()`, `xirr()` dengan tebakan awal 0,1).
Di arsitektur baru, XIRR dihitung di server (Python) dengan algoritma
yang sama: Newton-Raphson dengan fallback bisection, tebakan dan toleransi
yang sama, dan tanggal yang sama.

**Syarat penerimaan (wajib, bukan opsional):** untuk dataset 2022 (1.172
trade), 2025 (588 trade), dan demo (301 trade), XIRR hasil server harus
sama dengan XIRR hasil browser lama sampai 4 desimal, atau selisihnya
dijelaskan sebagai bug yang diperbaiki — bukan dibiarkan lewat begitu saja.

### 4.4 Perubahan frontend (`jp004.html`)

- Hapus `loadFromStorage()` / `saveToStorage()` untuk trade, pair, fee,
  dan price cache. Ganti dengan `fetch` ke API di atas.
- `renderTrades()` hanya me-render halaman yang sedang dibuka
  (misalnya 50 baris), plus kontrol halaman, filter, dan pencarian yang
  dikirim ke server (bukan difilter di browser dari seluruh dataset).
- `renderPositions()` dan `renderSummary()` memakai hasil `/api/positions`
  dan `/api/summary`, bukan menghitung dari array trade.
- Modal ticker, modal issuer, dan aksi Split/Consolidate/Pair memanggil
  endpoint tulis di §4.2, lalu me-refresh halaman yang sedang tampil saja.
- State yang boleh tetap di localStorage: tema, filter terakhir, halaman
  terakhir, dan preferensi tampilan saja — **bukan** data trade.
- Pesan error yang jelas kalau server tidak jalan: "Server jp004 tidak
  terjangkau di 127.0.0.1:28633 — jalankan server.py dulu", bukan tabel
  kosong yang menyesatkan.

---

## 5. Migrasi dari localStorage ke .db

Ini satu-satunya momen data bisa hilang, jadi prosedurnya dibuat eksplisit
dan bisa diulang (idempotent).

### Langkah migrasi

1. **Backup dulu, migrasi belakangan.** Export JSON lengkap dari browser
   yang datanya benar (origin yang benar!), simpan salinannya di luar
   folder app, dan verifikasi jumlah trade di file itu sama dengan jumlah
   yang tampil di app. Jangan mulai migrasi dari file yang belum diverifikasi
   — pelajaran dari kasus 2022 vs 2025: file yang salah akan menghasilkan
   angka yang salah secara diam-diam.
2. **Buat `.db` baru di samping `server.py`.** Jangan menimpa file `.db`
   yang sudah ada tanpa backup. Kalau `.db` sudah ada, migrasi menolak
   kecuali diberi flag `--force` dan backup lama sudah dibuat.
3. **Import dalam satu transaksi**, dengan urutan: `meta` → `trades`
   (urut `seq`) → `hedge_pairs` → `fx_rates` → `price_cache`.
   Normalisasi yang diterapkan dan dicatat di log migrasi:
   - `BONUS_STOCK` → `BUY` harga 0, feePct 0, label "Bonus share"
     (sama seperti normalisasi di `loadFromStorage()` sekarang).
   - Aksi WARRANT/RIGHT dengan `subAction` SELL → `SELL`.
   - DEPOSIT/WITHDRAW dengan `category` DIVIDEND/INTEREST/FEE/dll. →
     aksi yang sesuai, seperti normalisasi lama.
   - Trade tanpa `seq` diberi `seq` baru yang berurutan setelah `seq`
     terbesar, dan `meta.next_seq` diperbarui.
4. **Verifikasi otomatis setelah import**, dan migrasi dinyatakan gagal
   kalau ada yang tidak cocok:
   - jumlah trade di `.db` = jumlah trade di JSON sumber
   - jumlah per aksi sama
   - kas IDR akhir sama (sampai 2 desimal)
   - posisi per ticker (qty sisa) sama
   - XIRR sama sampai 4 desimal (lihat §4.3)
   - tidak ada `id` duplikat, tidak ada `seq` duplikat
5. **Baru setelah verifikasi lolos**, tandai migrasi selesai dan arahkan
   frontend ke API. localStorage lama **tidak langsung dihapus** — dibiarkan
   sebagai cadangan sampai pengguna mengonfirmasi sendiri bahwa angka di
   versi `.db` sudah benar, lalu dihapus manual lewat tombol Clear yang
   sudah ada.

### Yang tidak dimigrasikan otomatis

- Data dari origin lain (browser lain / perangkat lain) tidak ikut.
  Setiap origin harus di-export dan di-import sendiri, dan pengguna harus
  memutuskan sendiri mana yang menjadi sumber kebenaran — jangan digabung
  otomatis, karena penggabungan 2022 + 2025 saja belum pernah dikonfirmasi
  pengguna.
- Seed lama yang pernah ada di `jp004.html` tidak boleh ikut. Versi `.db`
  ini dibangun dari `jp004.html` bersih (tanpa seed).

---

## 6. Target kinerja (supaya "jutaan" bisa diuji, bukan cuma diklaim)

| Skenario | Target |
|---|---|
| Ukuran `.db` untuk 1 juta trade | ~200–400 MB (tergantung label dan field opsional), plus index |
| Import 1 juta trade (bulk, satu transaksi) | selesai dalam hitungan menit, bukan jam; laporkan baris/detik di log |
| Buka halaman trade (50 baris) | < 200 ms dari server lokal, berapapun total trade-nya |
| Buka posisi + summary | < 500 ms, karena agregat SQL, bukan loop browser |
| Render tabel di browser | konstan (50 baris), tidak membesar seiring total trade |
| Pencarian ticker / filter tanggal | memakai index, bukan scan seluruh tabel di browser |

**Uji beban yang harus dijalankan sebelum klaim "mendukung jutaan":**

1. Buat dataset sintetis 1 juta trade (acak ticker dari `ref_table.csv`,
   tanggal 2022–2026, aksi BUY/SELL/DEPOSIT/DIVIDEND/FEE dengan proporsi
   realistis), import ke `.db` kosong, catat waktu dan ukuran file.
2. Uji halaman 1, halaman tengah, dan halaman terakhir — ketiganya harus
   sama cepatnya (peringatan: `OFFSET` besar di SQLite melambat; kalau
   halaman terakhir lambat, ganti ke pagination berbasis cursor
   `(date, seq)`).
3. Uji posisi dan summary di 1 juta baris — kalau agregat SQL lambat,
   tambahkan tabel agregat yang diperbarui per transaksi (trade-off yang
   didokumentasikan, bukan perbaikan diam-diam).
4. Uji di HP (bukan cuma di VM): buka halaman trade, ganti halaman,
   tambah satu trade, dan ukur waktu render-nya.

---

## 7. Keamanan, privasi, dan hal yang tidak berubah

- `.db` adalah file lokal biasa. Siapa pun yang memegang file itu memegang
  seluruh portfolio — sama seperti memegang file export JSON sekarang.
  Jangan pernah mengunggah `.db` ke GitHub, ke file hosting publik, atau
  mengirimnya lewat chat. `.gitignore` harus memuat `*.db`, `*.db-wal`,
  `*.db-shm` sebelum baris kode migrasi pertama di-commit.
- Tidak ada autentikasi baru yang ditambahkan di rancangan ini, karena
  server jp004 memang dirancang untuk `127.0.0.1` lokal. Kalau server
  dibuka ke jaringan (bukan localhost), itu keputusan terpisah yang
  membutuhkan autentikasi — di luar rancangan ini, dan harus diputuskan
  pengguna dulu.
- Aturan promo dan kejujuran fitur tidak berubah: jp004 tetap tanpa
  auto-sync broker, hanya manual + import/export. Migrasi ke `.db` tidak
  boleh dipakai untuk mengklaim fitur yang tidak ada.
- Aturan file yang sudah ada tetap berlaku: jangan menghapus SVG/PNG
  tanpa perintah eksplisit, dan jangan menimpa file app di HP dengan
  master workspace tanpa perintah.

---

## 8. Backup dan pemulihan

- **Backup utama:** salinan file `jp004.db` (saat server berhenti, atau
  lewat perintah backup SQLite yang aman saat server jalan — jangan copy
  file WAL mentah-mentah sambil transaksi berjalan tanpa checkpoint).
- **Backup kedua:** export JSON berkala dari `/api/export`, disimpan di
  luar folder app. Ini yang membuat pemulihan tetap mungkin walau file
  `.db` rusak.
- **Pemulihan:** letakkan file `.db` cadangan di samping `server.py`,
  jalankan server, buka `/api/health` + satu halaman trade, dan cocokkan
  jumlah trade dengan export JSON terakhir sebelum dipakai lagi.
- **Rollback ke localStorage:** selama localStorage lama belum dihapus
  (lihat §5 langkah 5), versi html lama masih bisa dibuka dan datanya
  masih ada. Setelah localStorage dihapus dan `.db` dipakai penuh,
  rollback berarti import ulang dari export JSON — bukan "undo" satu klik.

---

## 9. Tahapan implementasi (diusulkan, belum dimulai)

1. **Fase 0 — Fondasi dan backup.**
   Skema `.db`, `.gitignore` untuk `*.db*`, script migrasi + verifikasi
   (§5), dan uji paritas di dataset 2022 / 2025 / demo. Tidak ada
   perubahan UI di fase ini.
2. **Fase 1 — Baca saja.**
   Endpoint `/api/trades` berpaginasi, `/api/positions`, `/api/summary`,
   dan frontend yang membaca dari API tapi belum menulis ke `.db`.
   Uji beban 1 juta baris sintetis di endpoint baca.
3. **Fase 2 — Tulis.**
   Endpoint tulis (§4.2), termasuk split / consolidate / pair, dengan
   `seq` yang ditetapkan server. Uji paritas operasi tulis terhadap
   perilaku lama.
4. **Fase 3 — XIRR dan perhitungan server.**
   Pindahkan XIRR dan agregat summary ke server, dengan syarat paritas
   §4.3. Frontend hanya menampilkan hasil.
5. **Fase 4 — Lepas localStorage.**
   Hapus `loadFromStorage` / `saveToStorage` untuk data, sisakan hanya
   preferensi tampilan. Pesan error server-tidak-jalan yang jelas (§4.4).
6. **Fase 5 — Uji beban dan dokumentasi.**
   Uji §6 di VM dan di HP, perbarui `README.md` dan `INSTRUCTIONS.md`,
   dan publikasikan hanya kode (tanpa `.db`, tanpa data asli) ke GitHub
   setelah verifikasi demo fiktif seperti proses publish sebelumnya.

**Perkiraan usaha (bukan janji):** Fase 0–1 adalah bagian terbesar dari
pekerjaan yang berisiko (skema + paritas). Fase 2–4 sebagian besar
memindahkan logika yang sudah ada, bukan menemukan logika baru — kecuali
XIRR, yang harus diuji paritasnya secara eksplisit.

---

## 10. Keputusan yang masih perlu pengguna

Rancangan ini sengaja tidak memutuskan sendiri hal-hal berikut — semuanya
perlu jawaban pengguna sebelum implementasi:

1. **Lokasi `.db` utama:** VM (setup sekarang) atau HP Termux
   (phone-local)? Lihat §2.1 — ini mengubah alur backup dan ketergantungan
   pada link HP.
2. **Apakah localStorage lama boleh dihapus otomatis setelah migrasi
   terverifikasi, atau harus tetap sebagai cadangan sampai pengguna
   menghapus manual?** Rancangan merekomendasikan cadangan manual.
3. **Apakah versi html lama (localStorage) tetap dipertahankan sebagai
   fallback, atau langsung diganti penuh oleh versi `.db`?**
4. **Apakah uji beban 1 juta baris sintetis boleh dijalankan di VM ini,**
   mengingat ukurannya ratusan MB dan waktunya hitungan menit?

---

## Lampiran: peta dari kode lama ke komponen baru

| Komponen lama | Komponen baru |
|---|---|
| `tj_trades_v4` (localStorage) | Tabel `trades` di `jp004.db` |
| `tj_pairs_v4` | Tabel `hedge_pairs` |
| `tj_fees_v4`, `tj_nextseq_v4`, `tj_base_v4` | Tabel `meta` |
| `tj_fx_v4` | Tabel `fx_rates` |
| `tj_names_v4` + cache harga | Tabel `price_cache` |
| `saveToStorage()` | Transaksi SQLite di endpoint tulis |
| `loadFromStorage()` | `GET /api/trades`, `/api/positions`, `/api/summary` |
| `renderTrades()` seluruh tabel | Render 1 halaman (50 baris) + kontrol halaman |
| `calculatePositions()`, `renderSummary()` di browser | Agregat SQL di server |
| `xirr()` di browser | `xirr()` di server, paritas §4.3 |
| Export/import JSON | `GET /api/export`, `POST /api/import`, format dipertahankan |
| `server.py` (harga + statis) | `server.py` + endpoint data, port dan URL tidak berubah |
