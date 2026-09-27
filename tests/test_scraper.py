from scraper import _parse_robots, format_output_record


ROBOTS = """User-agent: *
Crawl-delay: 10
Disallow: /admin/
Disallow: /unifinder$
Disallow: /unifinder?
"""


def test_university_paths_are_allowed():
    rp = _parse_robots(ROBOTS)

    assert rp.can_fetch(
        "GermanUniversityCollegeProjectBot/1.0",
        "https://www.mygermanuniversity.com/universities/example",
    )

    assert not rp.can_fetch(
        "GermanUniversityCollegeProjectBot/1.0",
        "https://www.mygermanuniversity.com/unifinder?p=1",
    )


def test_output_schema_is_language_specific():
    record = {
        "name": "University of Cologne",
        "location": "Cologne",
        "type": "public",
        "students": 45000,
        "study_programs": 361,
        "min_fees": 0,
        "max_fees": 14833,
        "fee_period": "semester",
        "official_university_url": "https://uni-koeln.de/en/",
        "source_url": "https://www.mygermanuniversity.com/universities/example",
    }

    output = format_output_record(record, "en")

    assert output["name_en"] == "University of Cologne"
    assert output["location_en"] == "Cologne"
    assert output["students"] == 45000
    assert "name_de" not in output
