from datetime import date

from pipeline.download_new_york_salesweb import jobs


def test_jobs_use_current_date_for_current_year():
    result = jobs(["Albany"], 2025, 2026, today=date(2026, 9, 15))
    assert [job.key for job in result] == ["albany_2025", "albany_2026"]
    assert result[0].end_date == "12/31/2025"
    assert result[1].end_date == "09/15/2026"


def test_jobs_cover_every_county_year():
    assert len(jobs(["Albany", "Erie"], 2020, 2022, today=date(2026, 1, 1))) == 6
