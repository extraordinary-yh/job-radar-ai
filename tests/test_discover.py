from jobradar.discover import entry_for, format_entries, slug_key

OUT = {"resolved": [
    {"name": "Ramp", "vendor": "ashby", "slug": "ramp", "careers_url": "https://jobs.ashbyhq.com/ramp", "jobCount": 142},
    {"name": "Vercel", "vendor": "greenhouse", "slug": "vercel", "careers_url": "https://job-boards.greenhouse.io/vercel", "jobCount": 87,
     "api": "https://boards-api.greenhouse.io/v1/boards/vercel/jobs"},
    {"name": "Acme Corp", "vendor": "smartrecruiters", "slug": "AcmeCorp", "careers_url": "https://jobs.smartrecruiters.com/AcmeCorp", "jobCount": 3},
    {"name": "Big Co", "vendor": "workday", "slug": "bigco", "careers_url": "https://bigco.wd5.myworkdayjobs.com/External", "jobCount": 900},
], "unresolved": [{"name": "Stealth Startup", "reason": "no board found"}]}


def test_slug_key():
    assert slug_key("C3 AI") == "c3_ai" and slug_key("Acme, Inc.") == "acme_inc" and slug_key("!!") == "company"


def test_native_ats_uses_our_adapter_and_others_go_through_careerops():
    text = format_entries(OUT)
    assert "  - name: Ramp\n    key: ramp\n    adapter: ashby\n    board: ramp   # 142 postings via ashby" in text
    assert "    adapter: greenhouse\n    board: vercel" in text
    assert "  - name: Acme Corp\n    key: acme_corp\n    adapter: careerops\n    provider: smartrecruiters\n    careers_url: https://jobs.smartrecruiters.com/AcmeCorp   # 3 postings via smartrecruiters" in text
    assert "    provider: workday\n    careers_url: https://bigco.wd5.myworkdayjobs.com/External" in text
    assert text.endswith("# unresolved (JS-rendered portal, custom slug, or Workday without a hint): Stealth Startup")
    assert format_entries({"resolved": [], "unresolved": []}) == "(no boards resolved)"
    assert entry_for({"name": "X", "vendor": "lever", "slug": "x"}).count("enabled: true") == 1
