import pytest

from jobradar.models import RawJob
from jobradar.normalize import (classify_location, detect_arrangement, detect_flags, extract_salary, extract_yoe,
                                html_to_text, level_from_title, normalize, split_qualifications)


def test_html_to_text_strips_tags_and_unescapes_twice():
    assert html_to_text("&lt;p&gt;Hi &amp;amp; bye&lt;/p&gt;<ul><li>a</li><li>b</li></ul>") == "Hi & bye\na\nb"


def test_html_to_text_straightens_curly_quotes():
    assert html_to_text("<p>You&rsquo;ll need to have:</p>") == "You'll need to have:"


@pytest.mark.parametrize("locs,expected", [
    (["New York, NY, USA"], "nyc"),
    (["United States, New York, New York"], "nyc"),
    (["Brooklyn, NY"], "nyc"),
    (["Mountain View, CA, USA"], "bay"),
    (["San Francisco, CA, US"], "bay"),
    (["Remote - US"], "remote_us"),
    (["Remote"], "remote_us"),
    (["Remote - Canada"], "non_us"),
    (["Seattle, WA, USA"], "other_us"),
    (["Seattle"], "other_us"),
    (["US-Remote"], "remote_us"),
    (["Remote in United States"], "remote_us"),
    (["San Francisco Bridge HQ"], "bay"),
    (["Toronto"], "non_us"),
    (["US"], "other_us"),
    (["US / Canada"], "other_us"),
    (["US-SEA, US-SF, US-NYC, US-Remote"], "nyc"),
    (["San Francisco, Seattle"], "bay"),
    (["Toronto, Canada Remote"], "non_us"),
    (["N/A"], "non_us"),
    (["Austin, TX"], "other_us"),
    (["London, UK"], "non_us"),
    (["Frankfurt, Germany"], "non_us"),
    (["London, UK", "New York, NY, USA"], "nyc"),
    (["Redmond, WA, US", "Remote"], "remote_us"),
    ([], "unknown"),
])
def test_classify_location(locs, expected):
    assert classify_location(locs) == expected


def test_detect_arrangement_prefers_hint():
    assert detect_arrangement("we are fully remote", "onsite") == "onsite"
    assert detect_arrangement("", "Hybrid") == "hybrid"


def test_detect_arrangement_from_text_and_locations():
    assert detect_arrangement("This is a hybrid role, 3 days in office") == "hybrid"
    assert detect_arrangement("This position is fully remote.") == "remote"
    assert detect_arrangement("Work on-site in our NYC office") == "onsite"
    assert detect_arrangement("nothing here", "", ["Remote - US"]) == "remote"
    assert detect_arrangement("nothing here") == "unknown"


@pytest.mark.parametrize("text,expected", [
    ("5 years of experience in low level systems programming languages.", (5, None)),
    ("5+ years of professional software engineering experience. 4+ years with an OOP language.", (5, None)),
    ("2-4 years of experience building web applications", (2, 4)),
    ("Minimum of 3 years experience", (3, None)),
    ("three years of relevant experience", (3, None)),
    ("Bachelor's degree or equivalent practical experience.", (None, None)),
    ("The company was founded 20 years ago and has 3 offices", (None, None)),
    ("Experience coding in Python. 1 year of experience with ML frameworks.", (1, None)),
    ("2-12+ years of professional hands-on software development experience (does not include internships)", (2, 12)),
    ("10+ years in the SAP domain, with a significant focus on solution architecture", (10, None)),
    ("3+ years of full-stack development with strong frontend focus using React", (3, None)),
    ("2 or more years of industry experience building scalable micro services", (2, None)),
    ("6+ years building and operating production backend or infrastructure systems.", (6, None)),
    ("Our product is 12 years old and used by 3 million people", (None, None)),
    ("plus two (2) years of experience in Building and shipping ML systems in production", (2, None)),
])
def test_extract_yoe(text, expected):
    assert extract_yoe(text) == expected


@pytest.mark.parametrize("title,expected", [
    ("Software Engineering Intern, Summer 2027", "intern"),
    ("Software Engineer, Early Career, 2027 Start", "new_grad"),
    ("Software Engineering Team Lead", "manager"),
    ("Engineering Manager, Platform", "manager"),
    ("Principal Software Engineer", "staff"),
    ("Staff Machine Learning Engineer", "staff"),
    ("Senior Software Engineer - AI Inference", "senior"),
    ("Sr. Software Engineer", "senior"),
    ("Software Engineer III, Google Cloud", "mid"),
    ("Software Engineer II", "early"),
    ("Software Engineer I", "early"),
    ("Junior Developer", "early"),
    ("AI Product Engineer", "unknown"),
    ("Forward Deployed Engineer", "unknown"),
    ("Member of Technical Staff", "unknown"),
    ("Senior Member of Technical Staff, AI Research", "senior"),
    ("Lead Member of Technical Staff - AI Research", "senior"),
])
def test_level_from_title(title, expected):
    assert level_from_title(title) == expected


def test_detect_flags_sponsorship_variants():
    assert "no_sponsorship" in detect_flags("We are unable to sponsor visas now or in the future.", "", "SWE")
    assert "no_sponsorship" in detect_flags("Must be authorized to work in the US without sponsorship.", "", "SWE")
    assert "no_sponsorship" in detect_flags("Visa sponsorship is not available for this role.", "", "SWE")
    assert detect_flags("We will sponsor H-1B transfers.", "", "SWE") == []


def test_detect_flags_clearance_us_person_phd():
    assert "clearance" in detect_flags("Active TS/SCI security clearance required", "", "SWE")
    assert "us_person" in detect_flags("Must be a U.S. citizen due to ITAR", "", "SWE")
    assert "phd_required" in detect_flags("", "PhD degree in Computer Science or equivalent practical experience.", "SWE")
    assert "phd_required" not in detect_flags("", "Master's degree or PhD in CS", "SWE")
    assert "phd_required" in detect_flags("", "", "Software Engineer, PhD, Early Career")


def test_split_qualifications_google_style():
    text = "Minimum qualifications:\nBachelor's degree.\n5 years of experience.\nPreferred qualifications:\nMaster's degree."
    mn, pf = split_qualifications(text)
    assert "5 years" in mn and "Master" not in mn
    assert "Master" in pf and "5 years" not in pf


def test_split_qualifications_bloomberg_style():
    text = "We'll trust you to:\nBuild things.\nYou'll need to have:\n4+ years of experience.\nWe'd love to see:\nKubernetes."
    mn, pf = split_qualifications(text)
    assert "4+ years" in mn and "Build things" not in mn and "Kubernetes" in pf


def test_split_qualifications_stripe_and_figma_headings():
    stripe = "Who we are\nAbout Stripe\nWhat you'll do\nShip things.\nMinimum requirements\n2+ years of experience.\nPreferred qualifications\nGo."
    mn, pf = split_qualifications(stripe)
    assert mn.startswith("Minimum requirements") and "2+ years" in mn and "Ship things" not in mn and pf.startswith("Preferred qualifications")
    figma = "What you'll do at Figma:\nBuild.\nWe'd love to hear from you if you have:\nReact experience.\nWhile not required, it's an added plus if you also have:\nRust."
    mn, pf = split_qualifications(figma)
    assert mn.startswith("We'd love to hear") and "React" in mn and "Build." not in mn and "Rust" in pf


def test_split_qualifications_prefers_headings_on_their_own_line():
    stripe = ("Who you are\nWe're looking for someone who meets the minimum requirements. The preferred qualifications are a bonus, "
              "not a requirement.\nMinimum requirements\n2-12+ years of professional experience.\nPreferred qualifications\nGo.")
    mn, pf = split_qualifications(stripe)
    assert mn.startswith("Minimum requirements") and "2-12+" in mn and pf == "Preferred qualifications\nGo."
    assert extract_yoe(mn) == (2, 12)


def test_renormalize_reparses_stored_text():
    from jobradar.models import Job
    from jobradar.normalize import renormalize
    job = Job(id="stripe:1", company="Stripe", title="Backend Engineer", url="u", locations=["US-Remote"],
              qualifications_min="Who we are\nMinimum requirements\n2-12+ years of professional experience.\nPreferred qualifications\nGo.",
              qualifications_pref="", description_text="Who we are\nMinimum requirements\n2-12+ years of professional experience.")
    renormalize(job)
    assert job.qualifications_min.startswith("Minimum requirements") and (job.yoe_min, job.yoe_max) == (2, 12)
    assert job.location_class == "remote_us" and job.country == "US"


def test_split_qualifications_without_headings_returns_whole_text_as_min():
    assert split_qualifications("3 years of experience with React.") == ("3 years of experience with React.", "")


def test_normalize_builds_job_from_raw():
    raw = RawJob(
        company="google", source_id="42", title="Software Engineer II, AI",
        url="https://g/42", apply_url="https://g/apply/42",
        locations=["New York, NY, USA", "London, UK"],
        description_html="<p>We build agents with LLMs and TypeScript.</p>",
        responsibilities_html="<ul><li>Ship features.</li></ul>",
        qualifications_html="<h3>Minimum qualifications:</h3><ul><li>2 years of experience with React.</li></ul><h3>Preferred qualifications:</h3><ul><li>Experience with RAG.</li></ul>",
        posted_ts=1787557163, arrangement_hint="hybrid",
    )
    job = normalize(raw, "Google")
    assert job.id == "google:42" and job.company == "Google"
    assert job.location_class == "nyc" and job.country == "US"
    assert job.arrangement == "hybrid"
    assert job.responsibilities == "Ship features."
    assert job.qualifications_min.startswith("Minimum qualifications") and "2 years" in job.qualifications_min
    assert "RAG" in job.qualifications_pref
    assert (job.yoe_min, job.yoe_max) == (2, None)
    assert job.yoe_pref is None
    assert job.level == "early"
    assert job.posted_at == "2026-08-24"
    assert job.flags == []


def test_normalize_reads_preferred_years():
    raw = RawJob(company="anthropic", source_id="1", title="AI Engineer", url="u",
                 qualifications_html="<h3>Minimum qualifications</h3><p>Strong Python.</p><h3>Preferred qualifications</h3><p>8+ years in roles such as software engineer.</p>")
    job = normalize(raw, "Anthropic")
    assert job.yoe_min is None and job.yoe_pref == 8


def test_detect_flags_microsoft_citizenship_verification():
    text = "Citizenship & Citizenship Verification: This position requires verification of U.S. citizenship due to citizenship-based legal restrictions."
    assert "us_person" in detect_flags(text, "", "SWE")


def test_detect_flags_masters_required():
    assert "masters_required" in detect_flags("", "Master's degree in Computer Science or equivalent practical experience.", "SWE")
    assert "masters_required" in detect_flags("", "MS in CS required.", "SWE")
    assert "masters_required" not in detect_flags("", "Bachelor's or Master's degree in CS.", "SWE")
    assert "masters_required" not in detect_flags("", "Bachelor's degree. Master's degree preferred.", "SWE")
    assert "phd_required" in detect_flags("", "PhD in ML.", "SWE") and "masters_required" not in detect_flags("", "PhD in ML.", "SWE")


@pytest.mark.parametrize("text,expected", [
    ("The base salary range is $150,000 - $200,000 per year.", (150000, 200000)),
    ("Compensation: $150K–$210K plus equity", (150000, 210000)),
    ("USD 180,000 to USD 240,000", (180000, 240000)),
    ("Pay: $45 - $60 per hour", (None, None)),
    ("We raised $50,000,000 last year", (None, None)),
    ("Annual salary of $165,000", (165000, 165000)),
    ("No comp listed here", (None, None)),
])
def test_extract_salary(text, expected):
    assert extract_salary(text) == expected
