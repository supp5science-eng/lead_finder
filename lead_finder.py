#!/usr/bin/env python3
"""lead_finder.py

CLI tool that builds a lead list of local businesses for a given category
(or whole sector) across the municipalities of a city, using the Google
Places API (New) Text Search endpoint.

For every business it records: name, address, phone, website (or "NEMA SAJT"),
website status, a few technical flags, rating, review count and a Maps link.
The result is written to a UTF-8 CSV that opens cleanly in Excel.

The point of the tool is the "find & qualify" phase only: it collects and
pre-filters leads. You make the final "good/bad website" call by hand.

Usage:
    export GOOGLE_PLACES_API_KEY="your-key"
    python lead_finder.py "ordinacija zuba"        # single category
    python lead_finder.py --sector zanati          # whole sector
    python lead_finder.py --all                    # every sector

See README.md for setup details.
"""

import argparse
import csv
import os
import sys
import time
from urllib.parse import urlparse

import requests

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

API_KEY_ENV = "GOOGLE_PLACES_API_KEY"
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Fields we ask the API to return. Keeping this tight keeps the bill low.
FIELD_MASK = ",".join([
    "places.displayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.googleMapsUri",
    "nextPageToken",
])

# Default zones: the 17 municipalities of Belgrade.
DEFAULT_ZONES = [
    "Stari grad", "Vračar", "Savski venac", "Novi Beograd", "Zvezdara",
    "Voždovac", "Palilula", "Zemun", "Čukarica", "Rakovica", "Surčin",
    "Grocka", "Lazarevac", "Mladenovac", "Obrenovac", "Sopot", "Barajevo",
]

# Categories grouped by sector. Pick one with --category, a whole sector with
# --sector, or everything with --all. Tweak these lists freely.
CATEGORIES_BY_SECTOR = {
    "zdravlje": [
        "ordinacija zuba", "privatna lekarska ordinacija", "fizikalna terapija",
        "estetska klinika", "veterinarska ambulanta", "optika", "privatna apoteka",
    ],
    "lepota": [
        "frizerski salon", "salon za nokte", "kozmetički salon", "masaža spa",
        "teretana", "joga studio", "pilates studio", "tattoo studio",
        "salon trepavica i obrva",
    ],
    "ugostiteljstvo": [
        "kafić", "restoran", "picerija", "pekara", "poslastičarnica",
        "ketering", "vinarija",
    ],
    "zanati": [
        "vodoinstalater", "električar", "moler", "klima servis",
        "stolar nameštaj po meri", "bravar", "selidbe", "čišćenje stanova",
        "tapetar", "servis bele tehnike",
    ],
    "auto": [
        "auto servis", "vulkanizer", "auto perionica", "auto škola",
    ],
    "edukacija": [
        "škola jezika", "privatni vrtić", "škola programiranja za decu",
        "muzička škola", "plesna škola",
    ],
    "trgovina": [
        "cvećara", "butik", "prodavnica venčanica", "zlatara",
        "prodavnica bicikala", "pet shop",
    ],
    "dogadjaji": [
        "fotograf venčanja", "dekoracija venčanja", "agencija za nekretnine",
        "knjigovodstvena agencija",
    ],
}

# Reverse lookup: category -> sector (for the output column).
SECTOR_OF_CATEGORY = {
    cat: sector
    for sector, cats in CATEGORIES_BY_SECTOR.items()
    for cat in cats
}

# Hosts that mean "only social media / marketplace", not a real website.
SOCIAL_DOMAINS = {
    "facebook.com", "fb.com", "fb.me", "instagram.com", "tiktok.com",
    "wolt.com", "glovoapp.com", "glovo.com", "linktr.ee", "linktree.com",
    "youtube.com", "youtu.be", "twitter.com", "x.com", "t.me", "wa.me",
    "messenger.com", "snapchat.com", "pinterest.com", "yelp.com",
    "tripadvisor.com", "booking.com", "google.com",
}

# Substrings that flag a free / builder subdomain (cheap or stale site).
FREE_SUBDOMAIN_HINTS = [
    "wixsite.com", "wix.com", "wordpress.com", "blogspot.", "weebly.com",
    "webnode.", "site123.", "jimdo", "ucoz.", "narod.ru", "mozello.",
    "godaddysites.com", "square.site", "carrd.co", "sites.google.com",
    "webflow.io", "netlify.app", "github.io", "tilda.ws",
]

# Browser-ish UA so liveness checks aren't blocked by default.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CSV_COLUMNS = [
    "kategorija", "sektor", "naziv", "adresa", "telefon", "sajt",
    "status_sajta", "prioritet", "https", "free_subdomen", "dostupan",
    "rating", "recenzije", "maps",
]


# --------------------------------------------------------------------------- #
# Google Places
# --------------------------------------------------------------------------- #

def search_places(query, api_key, max_pages=3, page_delay=2.5):
    """Run a Text Search query and follow nextPageToken up to max_pages.

    Returns a list of raw place dicts. On any API/network error it prints a
    message and returns whatever it gathered so far (never raises).
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    results = []
    page_token = None

    for page in range(max_pages):
        body = {"textQuery": query, "languageCode": "sr", "regionCode": "RS"}
        if page_token:
            body["pageToken"] = page_token

        try:
            resp = requests.post(SEARCH_URL, headers=headers, json=body, timeout=30)
        except requests.RequestException as exc:
            print(f"    ! network error for '{query}': {exc}", file=sys.stderr)
            break

        if resp.status_code == 429:
            print(f"    ! quota / rate limit hit on '{query}' — stopping this query",
                  file=sys.stderr)
            break
        if resp.status_code != 200:
            snippet = resp.text[:200].replace("\n", " ")
            print(f"    ! API error {resp.status_code} for '{query}': {snippet}",
                  file=sys.stderr)
            break

        data = resp.json()
        results.extend(data.get("places", []))

        page_token = data.get("nextPageToken")
        if not page_token:
            break
        # The token only becomes valid a couple of seconds later.
        time.sleep(page_delay)

    return results


# --------------------------------------------------------------------------- #
# Website classification & technical flags
# --------------------------------------------------------------------------- #

def _host_of(url):
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]  # strip any port


def classify_website(url):
    """Return one of: 'NEMA', 'SAMO DRUŠTVENE', 'IMA SAJT'."""
    if not url:
        return "NEMA"
    host = _host_of(url)
    for social in SOCIAL_DOMAINS:
        if host == social or host.endswith("." + social):
            return "SAMO DRUŠTVENE"
    return "IMA SAJT"


def is_https(url):
    return "da" if url.lower().startswith("https://") else "ne"


def is_free_subdomain(url):
    host = _host_of(url)
    return "da" if any(hint in host for hint in FREE_SUBDOMAIN_HINTS) else "ne"


def check_availability(url, timeout=10):
    """Return the HTTP status as a string, or 'mrtav' if unreachable.

    Tries HEAD first (cheap); falls back to GET when the server rejects HEAD.
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.head(url, headers=headers, timeout=timeout,
                             allow_redirects=True)
        if resp.status_code in (403, 405, 501) or resp.status_code >= 500:
            resp = requests.get(url, headers=headers, timeout=timeout,
                                allow_redirects=True, stream=True)
        return str(resp.status_code)
    except requests.RequestException:
        return "mrtav"


def compute_priority(status, available, free, https):
    """Lower number = hotter lead (1 best, 4 likely skip)."""
    if status == "NEMA":
        return 1
    if status == "SAMO DRUŠTVENE":
        return 2
    # IMA SAJT from here on.
    dead = available not in ("", "200", "201", "202", "203", "204",
                             "301", "302", "303", "307", "308")
    if dead:
        return 2
    if free == "da" or https == "ne":
        return 3
    return 4


# --------------------------------------------------------------------------- #
# Record building
# --------------------------------------------------------------------------- #

def build_record(place, category, check_live):
    name = (place.get("displayName") or {}).get("text", "")
    address = place.get("formattedAddress", "")
    phone = place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or ""
    website = place.get("websiteUri", "")
    rating = place.get("rating", "")
    reviews = place.get("userRatingCount", "")
    maps = place.get("googleMapsUri", "")

    status = classify_website(website)

    https = free = available = ""
    if status == "IMA SAJT":
        https = is_https(website)
        free = is_free_subdomain(website)
        if check_live:
            available = check_availability(website)

    record = {
        "kategorija": category,
        "sektor": SECTOR_OF_CATEGORY.get(category, ""),
        "naziv": name,
        "adresa": address,
        "telefon": phone,
        "sajt": website if website else "NEMA SAJT",
        "status_sajta": status,
        "prioritet": compute_priority(status, available, free, https),
        "https": https,
        "free_subdomen": free,
        "dostupan": available,
        "rating": rating,
        "recenzije": reviews,
        "maps": maps,
    }
    return record


def dedup_key(place):
    name = (place.get("displayName") or {}).get("text", "").strip().lower()
    address = place.get("formattedAddress", "").strip().lower()
    return (name, address)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def resolve_categories(args):
    if args.all:
        return [c for cats in CATEGORIES_BY_SECTOR.values() for c in cats]
    if args.sector:
        sector = args.sector.strip().lower()
        if sector not in CATEGORIES_BY_SECTOR:
            available = ", ".join(CATEGORIES_BY_SECTOR)
            sys.exit(f"Unknown sector '{sector}'. Available: {available}")
        return list(CATEGORIES_BY_SECTOR[sector])
    if args.category:
        return [args.category]
    sys.exit("Provide a category (positional), or --sector NAME, or --all. "
             "Try -h for help.")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Build a CSV lead list of businesses from Google Places.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python lead_finder.py \"ordinacija zuba\"\n"
            "  python lead_finder.py --sector zanati\n"
            "  python lead_finder.py --all --no-check-live\n\n"
            "Sectors: " + ", ".join(CATEGORIES_BY_SECTOR)
        ),
    )
    parser.add_argument("category", nargs="?", help="single business category, e.g. 'kafić'")
    parser.add_argument("--sector", help="run every category in a sector")
    parser.add_argument("--all", action="store_true", help="run every sector")
    parser.add_argument("--city", default="Beograd", help="city name (default: Beograd)")
    parser.add_argument("--zones", help="comma-separated zones (default: Belgrade municipalities)")
    parser.add_argument("--output", default="lista.csv", help="output CSV path (default: lista.csv)")
    parser.add_argument("--max-pages", type=int, default=3,
                        help="max result pages per query, 1-3 (default: 3). Use 1 to save quota.")
    parser.add_argument("--no-check-live", action="store_true",
                        help="skip the HTTP liveness check (faster, no 'dostupan' column)")
    parser.add_argument("--page-delay", type=float, default=2.5,
                        help="seconds to wait before fetching the next page (default: 2.5)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        sys.exit(f"Missing API key. Set it with: export {API_KEY_ENV}=\"your-key\"")

    categories = resolve_categories(args)
    zones = ([z.strip() for z in args.zones.split(",") if z.strip()]
             if args.zones else DEFAULT_ZONES)
    check_live = not args.no_check_live
    max_pages = max(1, min(3, args.max_pages))

    print(f"Categories: {len(categories)} | Zones: {len(zones)} | "
          f"City: {args.city} | Queries: {len(categories) * len(zones)}")

    seen = set()
    records = []

    for category in categories:
        for zone in zones:
            query = f"{category} {zone} {args.city}".strip()
            print(f"  -> {query}")
            for place in search_places(query, api_key, max_pages, args.page_delay):
                key = dedup_key(place)
                if key in seen or key == ("", ""):
                    continue
                seen.add(key)
                records.append(build_record(place, category, check_live))

    # utf-8-sig adds a BOM so Excel reads ćčšžđ correctly.
    try:
        with open(args.output, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for record in sorted(records, key=lambda r: (r["prioritet"], r["sektor"], r["kategorija"])):
                writer.writerow(record)
    except OSError as exc:
        sys.exit(f"Could not write {args.output}: {exc}")

    print(f"\nDone. {len(records)} unique businesses -> {args.output}")
    if records:
        by_prio = {}
        for r in records:
            by_prio[r["prioritet"]] = by_prio.get(r["prioritet"], 0) + 1
        labels = {1: "NEMA sajt", 2: "samo društvene / mrtav link",
                  3: "slab sajt (free/no https)", 4: "ima uredan sajt"}
        for prio in sorted(by_prio):
            print(f"  prioritet {prio} ({labels.get(prio, '')}): {by_prio[prio]}")


if __name__ == "__main__":
    main()
