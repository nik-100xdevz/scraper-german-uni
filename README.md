# scraper-german-uni

Scraper for MyGermanUniversity university profile pages.

## Output

Default run writes two independent files:

- `data/universities_en.json`
- `data/universities_de.json`

English records use:

```json
{
  "name_en": "University of Cologne",
  "location_en": "Cologne",
  "type": "public",
  "students": 45000,
  "study_programs": 361,
  "min_fees": 0,
  "max_fees": 14833,
  "fee_period": "semester",
  "official_university_url": "https://uni-koeln.de/en/",
  "source_url": "https://www.mygermanuniversity.com/universities/..."
}
```

German records use the same schema with `name_de` and `location_de`.

## Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Smoke-test the first two profiles:

```bash
python scraper.py --lang en --limit 2 --out data/test_en.json
python scraper.py --lang de --limit 2 --out data/test_de.json
```

Full bilingual run:

```bash
python scraper.py --lang both
```

Because MyGermanUniversity publishes a 10-second crawl delay, a full two-language scrape is intentionally slow.

## robots.txt handling

The scraper fetches and parses the site's current `/robots.txt` explicitly instead of relying on `urllib.robotparser.read()`. It also retries once with cache-busting if the received policy incorrectly appears to disallow `/universities/...`.

The scraper does not include a robots-bypass switch. If the site's published robots policy changes, the scraper stops rather than ignoring it.
