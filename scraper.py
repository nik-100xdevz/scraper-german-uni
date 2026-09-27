import argparse
import gzip
import json
import re
import time
import urllib.robotparser
import xml.etree.ElementTree as ET

from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.mygermanuniversity.com"
ROBOTS_URL = f"{BASE_URL}/robots.txt"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

USER_AGENT = (
    "GermanUniversityCollegeProjectBot/1.0 "
    "(educational project; respectful crawling)"
)

DEFAULT_DELAY = 10


class RateLimiter:
    def __init__(self, delay):
        self.delay = delay
        self.last_request = 0

    def wait(self):
        elapsed = time.time() - self.last_request

        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

        self.last_request = time.time()


session = requests.Session()

session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
})


def normalize(text):
    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


def get_robots():
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(ROBOTS_URL)

    try:
        rp.read()
    except Exception as exc:
        raise RuntimeError(f"Could not read robots.txt: {exc}")

    delay = rp.crawl_delay(USER_AGENT)

    if delay is None:
        delay = DEFAULT_DELAY

    return rp, delay


def fetch(url, limiter, rp, check_robots=True, max_retries=4):
    if check_robots and not rp.can_fetch(USER_AGENT, url):
        raise PermissionError(
            f"robots.txt does not permit crawling: {url}"
        )

    for attempt in range(max_retries):
        limiter.wait()

        print(f"GET {url}")

        response = session.get(
            url,
            timeout=30,
        )

        if response.status_code in {429, 500, 502, 503, 504}:
            if attempt == max_retries - 1:
                response.raise_for_status()

            wait_time = 2 ** attempt
            print(
                f"HTTP {response.status_code}; "
                f"retrying in {wait_time}s..."
            )
            time.sleep(wait_time)
            continue

        response.raise_for_status()
        return response

    raise RuntimeError(f"Failed to fetch: {url}")


def parse_sitemap(url, limiter, rp, visited=None):
    """
    Recursively handles:
      sitemap.xml
      sitemap indexes
      .xml.gz sitemaps
    """

    if visited is None:
        visited = set()

    if url in visited:
        return set()

    visited.add(url)

    response = fetch(
    url,
    limiter,
    rp,
    check_robots=False
)

    content = response.content

    if url.endswith(".gz"):
        content = gzip.decompress(content)

    root = ET.fromstring(content)

    urls = set()

    root_name = root.tag.split("}")[-1]

    if root_name == "sitemapindex":

        for sitemap in root:
            loc = sitemap.find("{*}loc")

            if loc is not None and loc.text:
                child_url = loc.text.strip()

                urls.update(
                    parse_sitemap(
                        child_url,
                        limiter,
                        rp,
                        visited
                    )
                )

    elif root_name == "urlset":

        for item in root:
            loc = item.find("{*}loc")

            if loc is not None and loc.text:
                urls.add(loc.text.strip())

    return urls


def is_university_profile(url):
    """
    Accept only:

        /universities/SLUG

    and:

        /de/universities/SLUG

    Reject:

        /universities/SLUG/subject/...
    """

    path = urlparse(url).path.rstrip("/")

    pattern = r"^/(de/)?universities/[^/]+$"

    return bool(re.match(pattern, path))


def canonical_english_url(url):
    """
    Converts:

        /de/universities/XYZ

    into:

        /universities/XYZ
    """

    parsed = urlparse(url)

    path = parsed.path

    if path.startswith("/de/universities/"):
        path = path.replace(
            "/de/universities/",
            "/universities/",
            1
        )

    return f"{BASE_URL}{path}"


def german_url_from_english(url):
    parsed = urlparse(url)

    path = parsed.path

    if path.startswith("/de/"):
        return url

    return f"{BASE_URL}/de{path}"


def extract_number(text):
    if not text:
        return None

    match = re.search(r"[\d][\d.,]*", text)

    if not match:
        return None

    value = match.group(0)

    # Convert 47.024 / 47,024 -> 47024
    value = value.replace(",", "").replace(".", "")

    try:
        return int(value)
    except ValueError:
        return None


def parse_amount(value):
    """
    Understands:
        14,833
        14.833
        1,294
        1.294
        1.294,50
    """

    value = value.strip()

    if "," in value and "." in value:

        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "")
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")

    elif "," in value:

        parts = value.split(",")

        if len(parts[-1]) == 3:
            value = value.replace(",", "")
        else:
            value = value.replace(",", ".")

    elif "." in value:

        parts = value.split(".")

        if len(parts[-1]) == 3:
            value = value.replace(".", "")

    try:
        number = float(value)

        if number.is_integer():
            return int(number)

        return number

    except ValueError:
        return None


def find_section(text, start_words, end_words):
    """
    Extracts text between two section headings.
    """

    lower_text = text.lower()

    start_index = -1

    for word in start_words:

        index = lower_text.find(word.lower())

        if index != -1:
            start_index = index
            break

    if start_index == -1:
        return ""

    end_index = len(text)

    for word in end_words:

        index = lower_text.find(
            word.lower(),
            start_index + 1
        )

        if index != -1 and index < end_index:
            end_index = index

    return text[start_index:end_index]


def parse_fees(text, language):
    if language == "en":

        section = find_section(
            text,
            [
                "Fees & Costs",
                "Fees and Costs",
            ],
            [
                "Application Deadlines",
                "Numerus Clausus",
                "City Information",
            ],
        )

        free_words = [
            "free",
            "no tuition fees",
        ]

    else:

        section = find_section(
            text,
            [
                "Gebühren & Kosten",
                "Gebühren und Kosten",
            ],
            [
                "Bewerbungsfristen",
                "Numerus Clausus",
                "Stadtinformationen",
            ],
        )

        free_words = [
            "keine studiengebühren",
            "keine gebühren",
        ]

    amounts = []

    # € 14,833
    for match in re.findall(
        r"€\s*([\d.,]+)",
        section
    ):
        parsed = parse_amount(match)

        if parsed is not None:
            amounts.append(parsed)

    # 14,833 euros
    for match in re.findall(
        r"([\d.,]+)\s*(?:euros?|Euro)",
        section,
        flags=re.IGNORECASE,
    ):
        parsed = parse_amount(match)

        if parsed is not None:
            amounts.append(parsed)

    lower_section = section.lower()

    for word in free_words:

        if word in lower_section:
            amounts.append(0)

    if not amounts:
        return None, None

    return min(amounts), max(amounts)


def parse_type(lines, language):
    target = "type" if language == "en" else "typ"

    for index, line in enumerate(lines):

        if line.lower() == target:

            candidates = lines[index + 1:index + 5]

            for candidate in candidates:

                text = candidate.lower()

                if (
                    "public" in text
                    or "state" in text
                    or "staatlich" in text
                ):
                    return "public"

                if "private" in text:
                    return "private"

    return None


def parse_students(text, language):

    patterns = []

    if language == "en":
        patterns = [
            r"No\.\s*of students.*?([\d,\.]+)",
            r"students.*?([\d,\.]+)",
        ]

    else:
        patterns = [
            r"Anzahl der Studierenden.*?([\d\.,]+)",
            r"Studierenden.*?([\d\.,]+)",
        ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if match:
            return extract_number(match.group(1))

    return None


def parse_programs(text, language):

    if language == "en":

        pattern = r"Programs\s*([\d,\.]+)"

    else:

        pattern = r"Studiengänge\s*([\d\.,]+)"

    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return extract_number(match.group(1))


def parse_location(soup, language):

    h1 = soup.find("h1")

    if h1:

        # The university page places the city link directly after
        # the title area.

        for anchor in h1.find_all_next("a", limit=8):

            value = normalize(
                anchor.get_text(" ", strip=True)
            )

            if not value:
                continue

            if value.lower() in [
                "add to favorites",
                "zu favoriten hinzufügen",
                "university website",
                "website der hochschule",
            ]:
                continue

            # Most commonly the first useful link is the city.
            if len(value) < 50:
                return value

    return None


def parse_official_url(soup):

    for anchor in soup.find_all("a", href=True):

        text = normalize(
            anchor.get_text(" ", strip=True)
        ).lower()

        href = anchor["href"]

        if (
            "university website" in text
            or "website der hochschule" in text
        ):
            return href

    # Fallback: find an external non-MGU URL
    for anchor in soup.find_all("a", href=True):

        href = anchor["href"]

        if not href.startswith("http"):
            continue

        if "mygermanuniversity.com" in href:
            continue

        return href

    return None


def parse_profile(html, url, language):

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    h1 = soup.find("h1")

    if not h1:
        raise ValueError(
            f"Could not find university title: {url}"
        )

    name = normalize(
        h1.get_text(" ", strip=True)
    )

    # Remove academic-year suffix.
    name = re.sub(
        r"\s*\(\d{4}/\d{2}\)\s*$",
        "",
        name,
    )

    body_text = soup.get_text(
        "\n",
        strip=True,
    )

    lines = [
        normalize(line)
        for line in body_text.splitlines()
        if normalize(line)
    ]

    min_fees, max_fees = parse_fees(
        body_text,
        language,
    )

    students = parse_students(
        body_text,
        language,
    )

    study_programs = parse_programs(
        body_text,
        language,
    )

    university_type = parse_type(
        lines,
        language,
    )

    location = parse_location(
        soup,
        language,
    )

    official_url = parse_official_url(
        soup,
    )

    return {
        "name": name,
        "location": location,
        "type": university_type,
        "students": students,
        "study_programs": study_programs,
        "min_fees": min_fees,
        "max_fees": max_fees,
        "fee_period": "semester",
        "official_university_url": official_url,
        "source_url": url,
    }


def scrape_language(language, output_file):

    print("\nReading robots.txt...")

    rp, delay = get_robots()

    print(f"Crawl delay: {delay} seconds")

    limiter = RateLimiter(delay)

    # Sitemap is explicitly published by the website.
    sitemap_urls = parse_sitemap(
        SITEMAP_URL,
        limiter,
        rp,
    )

    print(
        f"Discovered {len(sitemap_urls)} sitemap URLs"
    )

    university_urls = set()

    for url in sitemap_urls:

        if not is_university_profile(url):
            continue

        university_urls.add(
            canonical_english_url(url)
        )

    university_urls = sorted(
        university_urls
    )

    print(
        f"Found {len(university_urls)} university profiles"
    )

    # Safety check: scrape only the 529 university profiles
    # expected from the published sitemap.
    if len(university_urls) != 529:
        raise RuntimeError(
            f"Expected 529 university profiles, "
            f"but found {len(university_urls)}"
        )

    results = []

    failed = []

    for index, english_url in enumerate(
        university_urls,
        start=1,
    ):

        if language == "en":
            target_url = english_url
        else:
            target_url = german_url_from_english(
                english_url
            )

        print(
            f"\n[{index}/{len(university_urls)}]"
        )

        try:

            response = fetch(
                target_url,
                limiter,
                rp,
            )

            record = parse_profile(
                response.text,
                target_url,
                language,
            )

            results.append(record)

        except Exception as exc:

            print(
                f"FAILED: {target_url}\n{exc}"
            )

            failed.append({
                "url": target_url,
                "error": str(exc),
            })

    Path(output_file).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            results,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"\nSaved {len(results)} records to {output_file}"
    )

    if failed:

        failed_file = (
            Path(output_file).parent
            / f"failed_{language}.json"
        )

        with open(
            failed_file,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                failed,
                file,
                indent=2,
                ensure_ascii=False,
            )

        print(
            f"Failed URLs saved to {failed_file}"
        )


def scrape_bilingual(output_file):

    print("\nReading robots.txt...")

    rp, delay = get_robots()

    print(f"Crawl delay: {delay} seconds")

    limiter = RateLimiter(delay)

    sitemap_urls = parse_sitemap(
        SITEMAP_URL,
        limiter,
        rp,
    )

    english_urls = sorted({
        canonical_english_url(url)
        for url in sitemap_urls
        if is_university_profile(url)
    })

    print(
        f"Found {len(english_urls)} university profiles"
    )

    # Safety check: scrape only the 529 university profiles
    # expected from the published sitemap.
    if len(english_urls) != 529:
        raise RuntimeError(
            f"Expected 529 university profiles, "
            f"but found {len(english_urls)}"
        )

    results = []
    failed = []

    for index, english_url in enumerate(
        english_urls,
        start=1,
    ):

        german_url = german_url_from_english(
            english_url
        )

        print(
            f"\n[{index}/{len(english_urls)}]"
        )

        try:

            # English
            english_response = fetch(
                english_url,
                limiter,
                rp,
            )

            english = parse_profile(
                english_response.text,
                english_url,
                "en",
            )

            # German
            german_response = fetch(
                german_url,
                limiter,
                rp,
            )

            german = parse_profile(
                german_response.text,
                german_url,
                "de",
            )

            result = {
                "name_en": english["name"],
                "name_de": german["name"],

                "location_de": german["location"],
                "location_en": english["location"],

                "type": english["type"],

                "students": english["students"],

                "study_programs": english["study_programs"],

                "min_fees": english["min_fees"],
                "max_fees": english["max_fees"],

                "fee_period": "semester",

                "official_university_url":
                    english["official_university_url"],

                "source_url": english_url,
            }

            results.append(result)

        except Exception as exc:

            print(
                f"FAILED: {english_url}"
            )
            print(exc)

            failed.append({
                "url_en": english_url,
                "url_de": german_url,
                "error": str(exc),
            })

    Path(output_file).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            results,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"\nSaved {len(results)} records"
    )

    print(
        f"Output: {output_file}"
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--lang",
        choices=["en", "de", "both"],
        default="both",
    )

    parser.add_argument(
        "--out",
        default="data/universities.json",
    )

    args = parser.parse_args()

    if args.lang == "both":

        scrape_bilingual(
            args.out
        )

    elif args.lang == "en":

        scrape_language(
            "en",
            args.out,
        )

    else:

        scrape_language(
            "de",
            args.out,
        )


if __name__ == "__main__":
    main()