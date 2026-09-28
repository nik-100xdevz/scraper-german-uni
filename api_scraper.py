import argparse
import json
import re
from pathlib import Path

import requests

from scraper import BASE_URL, USER_AGENT, get_robots


API_URL = "https://api.mygermanuniversity.com/api/universities/all-search"
DEFAULT_TIMEOUT = 30


def normalize(text):
    if text is None:
        return None
    return re.sub(r"\s+", " ", str(text)).strip()


def to_number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value

    text = normalize(value)
    if not text:
        return None

    match = re.search(r"-?[\d][\d.,]*", text)
    if not match:
        return None

    raw = match.group(0)

    # Treat a final 3-digit group after a comma/dot as a thousands separator.
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        parts = raw.split(",")
        raw = raw.replace(",", "") if len(parts[-1]) == 3 else raw.replace(",", ".")
    elif "." in raw:
        parts = raw.split(".")
        raw = raw.replace(".", "") if len(parts[-1]) == 3 else raw

    try:
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return None


def walk(value):
    """Yield every mapping/list value recursively for flexible API shapes."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def key_variants(name):
    return {
        name,
        name.lower(),
        name.replace("_", ""),
        name.replace("_", "-"),
        re.sub(r"[^a-z0-9]", "", name.lower()),
    }


def find_value(record, aliases):
    """Find the first matching key anywhere in a nested record."""
    wanted = set()
    for alias in aliases:
        wanted.update(key_variants(alias))

    for obj in walk(record):
        if not isinstance(obj, dict):
            continue

        for key, value in obj.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized_key in wanted or str(key).lower() in wanted:
                return value

    return None


def find_records(payload):
    """Locate the university result list without assuming one API envelope."""
    candidates = []

    for obj in walk(payload):
        if not isinstance(obj, list) or not obj:
            continue

        dict_items = [item for item in obj if isinstance(item, dict)]
        if not dict_items:
            continue

        score = 0
        for item in dict_items[:10]:
            keys = {re.sub(r"[^a-z0-9]", "", str(k).lower()) for k in item.keys()}
            if keys & {
                "name",
                "nameen",
                "name_en",
                "universityname",
                "university",
                "slug",
            }:
                score += 1

        candidates.append((score, len(dict_items), obj))

    if not candidates:
        return []

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def university_url(record):
    value = find_value(
        record,
        [
            "official_university_url",
            "officialUniversityUrl",
            "official_url",
            "officialUrl",
            "university_url",
            "universityUrl",
            "website",
            "homepage",
        ],
    )

    if isinstance(value, dict):
        value = find_value(value, ["url", "href", "link"])

    return normalize(value)


def source_url(record):
    value = find_value(
        record,
        [
            "source_url",
            "sourceUrl",
            "url",
            "detail_url",
            "detailUrl",
            "slug",
        ],
    )

    if not value:
        return None

    text = normalize(value)

    if text.startswith("http"):
        return text

    if text.startswith("/"):
        return f"{BASE_URL}{text}"

    return f"{BASE_URL}/universities/{text}"


def build_record(item):
    name_en = find_value(
        item,
        [
            "name_en",
            "nameEn",
            "english_name",
            "englishName",
            "nameEnglish",
            "title_en",
            "titleEn",
        ],
    )
    name_de = find_value(
        item,
        [
            "name_de",
            "nameDe",
            "german_name",
            "germanName",
            "nameGerman",
            "title_de",
            "titleDe",
        ],
    )

    generic_name = find_value(item, ["name", "university_name", "universityName", "title"])

    if not name_en:
        name_en = generic_name
    if not name_de:
        name_de = generic_name

    location_en = find_value(
        item,
        [
            "location_en",
            "locationEn",
            "english_location",
            "city_en",
            "cityEn",
        ],
    )
    location_de = find_value(
        item,
        [
            "location_de",
            "locationDe",
            "german_location",
            "city_de",
            "cityDe",
        ],
    )

    generic_location = find_value(item, ["location", "city", "town"])

    if not location_en:
        location_en = generic_location
    if not location_de:
        location_de = generic_location

    university_type = find_value(item, ["type", "university_type", "universityType"])
    students = to_number(find_value(item, ["students", "student_count", "studentCount", "number_of_students"]))
    study_programs = to_number(
        find_value(
            item,
            [
                "study_programs",
                "studyPrograms",
                "programs",
                "program_count",
                "programCount",
                "number_of_programs",
            ],
        )
    )
    min_fees = to_number(
        find_value(item, ["min_fees", "minFees", "minimum_fee", "minimumFees", "min_fee"])
    )
    max_fees = to_number(
        find_value(item, ["max_fees", "maxFees", "maximum_fee", "maximumFees", "max_fee"])
    )
    fee_period = find_value(item, ["fee_period", "feePeriod", "tuition_fee_period", "tuitionFeePeriod"])

    record = {
        "name_en": normalize(name_en),
        "name_de": normalize(name_de),
        "location_en": normalize(location_en),
        "location_de": normalize(location_de),
        "type": normalize(university_type),
        "students": students,
        "study_programs": study_programs,
        "min_fees": min_fees,
        "max_fees": max_fees,
        "fee_period": normalize(fee_period) or "semester",
        "official_university_url": university_url(item),
        "source_url": source_url(item),
    }

    return record


def split_language(record, language):
    keys = [
        f"name_{language}",
        f"location_{language}",
        "type",
        "students",
        "study_programs",
        "min_fees",
        "max_fees",
        "fee_period",
        "official_university_url",
        "source_url",
    ]
    return {key: record.get(key) for key in keys}


def fetch_page(session, page, timeout=DEFAULT_TIMEOUT):
    response = session.get(
        API_URL,
        params={"page": page},
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{BASE_URL}/unifinder",
        },
    )
    response.raise_for_status()
    return response.json(), response


def scrape(max_pages=None, start_page=1, raw_dir="data/raw_api"):
    rp, _ = get_robots()

    probe_url = f"{API_URL}?page={start_page}"
    if not rp.can_fetch(USER_AGENT, probe_url):
        raise PermissionError(
            f"robots.txt does not permit API access: {probe_url}"
        )

    session = requests.Session()
    all_records = []
    seen_sources = set()

    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)

    page = start_page

    while True:
        if max_pages is not None and page >= start_page + max_pages:
            break

        print(f"GET API page {page}")
        payload, response = fetch_page(session, page)

        (raw_path / f"page_{page:04d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        items = find_records(payload)

        if not items:
            print(f"No university records found on page {page}; stopping.")
            break

        page_records = 0

        for item in items:
            record = build_record(item)

            if not record["name_en"] and not record["name_de"]:
                continue

            identity = (
                record.get("source_url")
                or record.get("official_university_url")
                or record.get("name_en")
                or record.get("name_de")
            )

            if identity in seen_sources:
                continue

            seen_sources.add(identity)
            all_records.append(record)
            page_records += 1

        print(f"Page {page}: {page_records} universities")

        # A paginated API normally returns a short final page.
        per_page = len(items)
        if per_page == 0:
            break

        page += 1

    return all_records


def main():
    parser = argparse.ArgumentParser(description="Scrape MyGermanUniversity via its UniFinder API")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--out-en", default="data/universities_en.json")
    parser.add_argument("--out-de", default="data/universities_de.json")
    parser.add_argument("--raw-dir", default="data/raw_api")
    args = parser.parse_args()

    records = scrape(
        max_pages=args.pages,
        start_page=args.start_page,
        raw_dir=args.raw_dir,
    )

    Path(args.out_en).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_de).parent.mkdir(parents=True, exist_ok=True)

    Path(args.out_en).write_text(
        json.dumps(
            [split_language(record, "en") for record in records],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    Path(args.out_de).write_text(
        json.dumps(
            [split_language(record, "de") for record in records],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Saved {len(records)} normalized records")
    print(f"English: {args.out_en}")
    print(f"German:  {args.out_de}")


if __name__ == "__main__":
    main()
