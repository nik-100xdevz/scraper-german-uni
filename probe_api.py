import argparse
import json
from pathlib import Path

import requests

from api_scraper import API_URL, USER_AGENT, find_records, build_record


def fetch(page):
    response = requests.get(
        API_URL,
        params={"page": page},
        timeout=30,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.mygermanuniversity.com/unifinder",
        },
    )
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pages",
        default="1,2,3,10,20,30,40,50,54",
        help="Comma-separated pages to probe",
    )
    parser.add_argument(
        "--raw-dir",
        default="data/api_probe",
    )
    args = parser.parse_args()

    pages = []
    for part in args.pages.split(","):
        part = part.strip()
        if not part:
            continue
        page = int(part)
        if page < 1:
            raise ValueError(f"Invalid page: {page}")
        pages.append(page)

    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    seen = {}
    total = 0

    for page in pages:
        print(f"\n=== PAGE {page} ===")

        try:
            payload = fetch(page)
            (raw_dir / f"page_{page:04d}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            items = find_records(payload)
            print(f"records: {len(items)}")

            page_names = []
            for item in items:
                record = build_record(item)
                name = record["name_en"] or record["name_de"] or "<unnamed>"
                source = record["source_url"] or record["official_university_url"] or name
                page_names.append(name)

                if source in seen:
                    print(f"DUPLICATE: {name} (also page {seen[source]})")
                else:
                    seen[source] = page
                    total += 1

            if page_names:
                print("first:", page_names[0])
                print("last: ", page_names[-1])
                print("sample:", page_names[:5])

            if isinstance(payload, dict):
                print("top-level keys:", list(payload.keys()))

        except Exception as exc:
            print(f"FAILED page {page}: {type(exc).__name__}: {exc}")

    print("\n=== SUMMARY ===")
    print(f"unique records across successful pages: {total}")
    print(f"probed pages: {pages}")


if __name__ == "__main__":
    main()
