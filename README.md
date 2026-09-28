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


## API-first scraper

The UniFinder frontend exposes its university search through:

```
https://api.mygermanuniversity.com/api/universities/all-search?page=1
```

Use `api_scraper.py` to collect the structured API data instead of visiting every university HTML page.

### Test one API page

```bash
python api_scraper.py --pages 1
```

This writes:

```
data/universities_en.json
data/universities_de.json
data/raw_api/page_0001.json
```

The raw file is important: if the API uses a field name different from the common aliases in `api_scraper.py`, add that key to the corresponding alias list instead of rewriting the scraper.

### Full API scrape

```bash
python api_scraper.py
```

The API scraper still checks `robots.txt` before requesting the endpoint. It does not bypass a published robots restriction.
