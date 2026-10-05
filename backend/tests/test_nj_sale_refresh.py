from pipeline.nj_sale_refresh import write_summary


def test_summary_lists_counts_and_failures(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    write_summary({
        "before": {"scheduled": 10}, "after": {"scheduled": 12},
        "stages": {"zillow": {"submitted": 2}},
        "failures": [{"stage": "scrape", "item": "Ocean open", "error": "HTTPError: 503"}],
    })

    text = summary.read_text()
    assert "| scheduled | 10 | 12 |" in text
    assert "submitted" in text
    assert "scrape · Ocean open: HTTPError: 503" in text


def test_summary_is_skipped_outside_github(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    write_summary({"before": {}, "after": {}, "stages": {}, "failures": []})
