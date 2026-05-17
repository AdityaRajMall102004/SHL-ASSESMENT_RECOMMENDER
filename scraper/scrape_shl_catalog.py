"""
Step 2 — SHL Catalog Loader (Official API Version)
===================================================
Uses the official SHL catalog JSON API instead of scraping.
Much faster and more reliable than browser scraping.

OUTPUT:
  ../data/shl_catalog.json   → cleaned catalog used by the agent
  ../data/shl_catalog.csv    → human-readable, open in Excel to verify

HOW TO RUN:
  cd shl-assessment-recommender/scraper
  pip install requests
  python scrape_shl_catalog.py
"""

import requests
import json
import csv
from pathlib import Path
from collections import Counter

# ── CONFIG ────────────────────────────────────────────────────────────────────

CATALOG_API_URL = (
    "https://tcp-us-prod-rnd.shl.com/voiceRater/shl-ai-hiring/shl_product_catalog.json"
)

OUTPUT_DIR  = Path("../data")
OUTPUT_JSON = OUTPUT_DIR / "shl_catalog.json"
OUTPUT_CSV  = OUTPUT_DIR / "shl_catalog.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SHL-Recommender/1.0)",
    "Accept": "application/json",
}

# Test type code → full name (from SHL catalog legend)
TEST_TYPE_MAP = {
    "A": "Ability & Aptitude",
    "B": "Biodata & Situational Judgement",
    "C": "Competencies",
    "D": "Development & 360",
    "E": "Assessment Exercises",
    "K": "Knowledge & Skills",
    "P": "Personality & Behavior",
    "S": "Simulations",
}


# ── FETCH ─────────────────────────────────────────────────────────────────────

def fetch_catalog(url: str) -> list:
    """Download the catalog JSON from the API."""
    print(f"Fetching catalog from:\n  {url}\n")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    # Use strict=False to handle invalid control characters in the raw JSON
    try:
        data = json.loads(resp.text, strict=False)
    except json.JSONDecodeError as e:
        # Last resort: strip control characters manually then parse
        print(f"  Warning: JSON had issues ({e}), attempting manual clean...")
        import re
        cleaned = re.sub(r'[\x00-\x1f\x7f](?<![\\nrt])', '', resp.text)
        data = json.loads(cleaned, strict=False)

    # Handle both a bare list and a wrapped object like {"products": [...]}
    if isinstance(data, list):
        return data
    for key in ("products", "assessments", "items", "catalog", "data", "results"):
        if key in data and isinstance(data[key], list):
            print(f"  Found items under key: '{key}'")
            return data[key]

    # Print keys so you can adjust if needed
    print("  Unexpected JSON structure. Top-level keys:", list(data.keys()))
    print("  Raw sample:", str(data)[:500])
    raise ValueError("Cannot find the assessments list in the JSON.")


# ── NORMALIZE ─────────────────────────────────────────────────────────────────

def normalize(raw: dict) -> dict:
    """
    Map raw API fields to the standard schema used by the agent.
    Tries all common field name variants so it works regardless of exact API shape.
    """

    def get(*keys, default=""):
        for k in keys:
            if k in raw and raw[k] is not None:
                return raw[k]
        return default

    # Name
    name = str(get("name", "title", "product_name", "assessment_name", default="")).strip()

    # URL
    url = str(get("url", "link", "product_url", "catalog_url", "href", default="")).strip()
    if url and not url.startswith("http"):
        url = "https://www.shl.com" + url

    # Description
    description = str(get(
        "description", "desc", "overview", "summary",
        "product_description", "short_description", default=""
    )).strip()

    # Test type
    test_type_raw = str(get(
        "test_type", "type", "assessment_type", "category",
        "test_category", default=""
    )).strip()

    if test_type_raw in TEST_TYPE_MAP:
        test_type_names = [TEST_TYPE_MAP[test_type_raw]]
    elif "," in test_type_raw:
        test_type_names = [
            TEST_TYPE_MAP.get(c.strip(), c.strip())
            for c in test_type_raw.split(",") if c.strip()
        ]
    else:
        test_type_names = [test_type_raw] if test_type_raw else []

    # Remote testing
    remote_raw = get("remote_testing", "remote", "is_remote", "remote_proctoring", "online", default="")
    if isinstance(remote_raw, bool):
        remote_testing = remote_raw
    else:
        remote_testing = str(remote_raw).lower() in ("yes", "true", "1", "y")

    # Adaptive / IRT
    adaptive_raw = get("adaptive_irt", "adaptive", "irt", "is_adaptive", default="")
    if isinstance(adaptive_raw, bool):
        adaptive_irt = adaptive_raw
    else:
        adaptive_irt = str(adaptive_raw).lower() in ("yes", "true", "1", "y")

    # Job levels
    job_levels_raw = get("job_levels", "job_level", "levels", "seniority", "target_levels", default=[])
    if isinstance(job_levels_raw, list):
        job_levels = [str(j).strip() for j in job_levels_raw if j]
    elif isinstance(job_levels_raw, str) and job_levels_raw:
        job_levels = [j.strip() for j in job_levels_raw.split(",") if j.strip()]
    else:
        job_levels = []

    # Languages
    langs_raw = get("languages", "language", "available_languages", default=[])
    if isinstance(langs_raw, list):
        languages = [str(l).strip() for l in langs_raw if l]
    elif isinstance(langs_raw, str) and langs_raw:
        languages = [l.strip() for l in langs_raw.split(",") if l.strip()]
    else:
        languages = []

    # Duration
    duration = str(get("duration", "time_limit", "duration_minutes", default="")).strip()

    return {
        "name": name,
        "url": url,
        "description": description,
        "test_type_codes": test_type_raw,
        "test_type_names": test_type_names,
        "remote_testing": remote_testing,
        "adaptive_irt": adaptive_irt,
        "job_levels": job_levels,
        "languages": languages,
        "duration": duration,
    }


# ── SAVE ──────────────────────────────────────────────────────────────────────

def save_json(assessments, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(assessments, f, indent=2, ensure_ascii=False)
    print(f"  Saved JSON  ->  {path}  ({len(assessments)} items)")


def save_csv(assessments, path):
    if not assessments:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for a in assessments:
        rows.append({
            "name": a["name"],
            "url": a["url"],
            "description": a["description"][:200],
            "test_type_codes": a["test_type_codes"],
            "test_type_names": ", ".join(a["test_type_names"]),
            "remote_testing": a["remote_testing"],
            "adaptive_irt": a["adaptive_irt"],
            "job_levels": ", ".join(a["job_levels"]),
            "languages": ", ".join(a["languages"][:5]),
            "duration": a["duration"],
        })
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Saved CSV   ->  {path}")


# ── DIAGNOSTICS ───────────────────────────────────────────────────────────────

def print_diagnostics(raw_sample, normalized_sample):
    print("\n-- RAW API FIELDS (first item) --")
    for k, v in raw_sample.items():
        print(f"  {k:<30} = {str(v)[:80]}")

    print("\n-- NORMALIZED (first item) ------")
    for k, v in normalized_sample.items():
        print(f"  {k:<20} = {v}")
    print()


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Step 2 -- SHL Catalog Loader (API Version)")
    print("=" * 60)
    print()

    # 1. Fetch
    raw_items = fetch_catalog(CATALOG_API_URL)
    print(f"Fetched {len(raw_items)} raw items from API")

    if not raw_items:
        print("Empty catalog returned. Check the URL.")
        return

    # 2. Diagnostics on first item
    first_norm = normalize(raw_items[0])
    print_diagnostics(raw_items[0], first_norm)

    # 3. Normalize all
    assessments = [normalize(item) for item in raw_items]

    # 4. Filter out pre-packaged job solutions (keep individual test solutions only)
    before = len(assessments)
    assessments = [
        a for a in assessments
        if not any("solution" in t.lower() for t in a["test_type_names"])
        or not a["test_type_names"]
    ]
    print(f"After filtering pre-packaged solutions: {len(assessments)} / {before}")

    # 5. Save
    print("\nSaving...")
    save_json(assessments, OUTPUT_JSON)
    save_csv(assessments, OUTPUT_CSV)

    # 6. Summary
    print("\n-- CATALOG SUMMARY --")
    type_counts = Counter()
    for a in assessments:
        for t in a["test_type_names"]:
            type_counts[t] += 1
    for t, count in type_counts.most_common():
        print(f"  {t:<35} {count}")

    print(f"\n  Remote testing supported : {sum(1 for a in assessments if a['remote_testing'])} / {len(assessments)}")
    print(f"  Adaptive/IRT             : {sum(1 for a in assessments if a['adaptive_irt'])} / {len(assessments)}")
    print("\nStep 2 complete. Files ready for Step 3.")


if __name__ == "__main__":
    main()
