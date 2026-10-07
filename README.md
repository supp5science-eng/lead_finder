# Lead Finder

A command-line tool that finds local businesses that need a website, so you know exactly who to pitch.

It searches the Google Places API (New) across every municipality of a city, removes duplicates, checks each business's website (none, only social media, dead link, free subdomain, no HTTPS) and writes a CSV sorted by how good a lead each business is.

**Real run (Belgrade):** 2,394 unique businesses found, 751 of them without a website. I used the list to build 12 websites for sales pitches. Case study: [markobera.com/work/dental](https://www.markobera.com/work/dental/)

**Stack:** Python, Google Places API (New), `requests`

---

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Get a Google Places API key

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Go to **APIs & Services → Library**, find **Places API (New)** and click **Enable**.
3. Go to **APIs & Services → Credentials → Create credentials → API key**.
4. Recommended: restrict the key to Places API (New) under **API restrictions**.

## 3. Set the key

```bash
# macOS / Linux
export GOOGLE_PLACES_API_KEY="your-key"
```

```powershell
# Windows PowerShell
$env:GOOGLE_PLACES_API_KEY = "your-key"
```

The key is only read from the environment and never written to disk.

## 4. Run it

```bash
# one specific category
python lead_finder.py "ordinacija zuba"

# an entire sector (all its categories, across all zones)
python lead_finder.py --sector zanati

# everything (all sectors, all zones) — biggest run, watch your quota
python lead_finder.py --all
```

When it finishes you get **`lista.csv`** in the current folder, plus a short
summary in the terminal (how many unique businesses, and a breakdown by
priority).

---

## Output columns

`lista.csv` is UTF-8 with a BOM, so Serbian letters (ćčšžđ) display correctly
in Excel. Columns:

| column          | meaning                                                        |
|-----------------|----------------------------------------------------------------|
| `kategorija`    | the business category that matched                              |
| `sektor`        | the sector the category belongs to                              |
| `naziv`         | business name                                                   |
| `adresa`        | address                                                         |
| `telefon`       | phone (blank if Places has none)                                |
| `sajt`          | website URL, or `NEMA SAJT`                                      |
| `status_sajta`  | `NEMA` / `SAMO DRUŠTVENE` / `IMA SAJT`                           |
| `prioritet`     | 1 = hottest lead … 4 = probably skip (see below)                |
| `https`         | `da`/`ne` — only for `IMA SAJT`                                  |
| `free_subdomen` | `da`/`ne` — Wix/WordPress/etc. free subdomain                   |
| `dostupan`      | HTTP status (e.g. `200`), or `404`/`mrtav` for a dead link      |
| `rating`        | Google rating                                                   |
| `recenzije`     | number of reviews                                               |
| `maps`          | Google Maps link                                                |

### What `status_sajta` means

- **`NEMA`** — no website at all.
- **`SAMO DRUŠTVENE`** — the "website" points to Facebook/Instagram/Wolt/Glovo etc.
- **`IMA SAJT`** — a real domain.

### Priority (auto-computed, just for sorting)

The CSV is sorted by `prioritet` so the best leads are at the top:

- **1** — `NEMA` (no site). Hottest.
- **2** — `SAMO DRUŠTVENE`, or `IMA SAJT` with a **dead link** (404 / mrtav).
- **3** — `IMA SAJT` but on a **free subdomain** or **without https**.
- **4** — `IMA SAJT`, https, real domain, live. Likely skip.

It's only a hint — you make the final call.

---

## Useful flags

| flag                | what it does                                                   |
|---------------------|----------------------------------------------------------------|
| `--sector NAME`     | run a whole sector (see list below)                            |
| `--all`             | run every sector                                                |
| `--city NAME`       | city name, default `Beograd`                                    |
| `--zones "A,B,C"`   | custom comma-separated zones (default: Belgrade municipalities) |
| `--output PATH`     | output file, default `lista.csv`                                |
| `--max-pages N`     | result pages per query, 1–3 (default 3). Use `1` to save quota. |
| `--no-check-live`   | skip the HTTP liveness check — faster, leaves `dostupan` blank  |
| `--page-delay SECS` | wait before fetching the next page (default 2.5s)               |

Sectors: `zdravlje`, `lepota`, `ugostiteljstvo`, `zanati`, `auto`,
`edukacija`, `trgovina`, `dogadjaji`.

To add/remove categories or zones, edit `CATEGORIES_BY_SECTOR` and
`DEFAULT_ZONES` near the top of `lead_finder.py`.

---

## A note on cost

`--all` is roughly *(number of categories) × (number of zones) × up to 3 pages*
of API calls — that can be a few thousand requests. The free monthly credit
usually covers a lot, but while you're testing use:

```bash
python lead_finder.py --sector zdravlje --max-pages 1 --no-check-live
```

to keep both the API quota and the run time small.
