from jobradar.models import Job, RawJob, Review, job_id


def test_job_id_joins_company_and_source():
    assert job_id("google", "123") == "google:123"


def test_job_round_trips_through_dict():
    job = Job(
        id="google:1", company="Google", title="Software Engineer", url="https://x/1",
        apply_url="", locations=["New York, NY, USA"], location_class="nyc", country="US",
        arrangement="onsite", description_text="d", responsibilities="r",
        qualifications_min="q", qualifications_pref="p", yoe_min=2, yoe_max=None,
        level="early", flags=[], posted_at="2026-09-01",
    )
    job.review = Review(id="google:1", skills=34, yoe_match="match", experience_match="strong",
                        reason="good", gaps=[], tags=["ai"])
    d = job.to_dict()
    assert d["review"]["skills"] == 34 and d["review"]["fit"] is None
    back = Job.from_dict(d)
    assert back == job


def test_job_from_dict_tolerates_missing_optional_fields():
    minimal = {"id": "a:1", "company": "A", "title": "T", "url": "u"}
    job = Job.from_dict(minimal)
    assert job.locations == [] and job.status == "new" and job.review is None


def test_rawjob_defaults():
    raw = RawJob(company="google", source_id="1", title="T", url="u")
    assert raw.locations == [] and raw.posted_ts is None and raw.extra == {}
