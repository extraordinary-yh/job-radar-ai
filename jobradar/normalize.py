"""Turn a RawJob into a Job: text cleanup, location class, arrangement, YOE, level, flags."""
from __future__ import annotations

import datetime as dt
import html as htmllib
import re

from .models import Job, RawJob, job_id

# ---------- text ----------
_BLOCK_RE = re.compile(r"</?(p|div|li|ul|ol|br|h[1-6]|tr|table|section)[^>]*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(s: str) -> str:
    if not s:
        return ""
    s = htmllib.unescape(s)          # Greenhouse ships HTML-escaped HTML
    s = _BLOCK_RE.sub("\n", s)
    s = _TAG_RE.sub(" ", s)
    s = htmllib.unescape(s)
    s = s.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ---------- location ----------
NYC = ("new york", "nyc", "manhattan", "brooklyn")
BAY = ("san francisco", "mountain view", "sunnyvale", "menlo park", "palo alto", "san jose",
       "redwood city", "cupertino", "south san francisco", "oakland", "berkeley", "santa clara",
       "foster city", "san mateo", "bay area", "fremont", "san bruno", "san carlos", "burlingame",
       "us-sf", "sf hq", "sf bay")
_US_TOKEN_RE = re.compile(r"(^|[\s,/(\-])(us|u\.s\.|usa)([\s,/)\-]|$)")
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
US_WORDS = ("usa", "united states", "u.s.", ", us", "us-remote", "remote-us", "remote in united states")
US_CITIES = ("seattle", "chicago", "austin", "boston", "los angeles", "washington", "denver", "atlanta", "dallas",
             "houston", "miami", "philadelphia", "portland", "san diego", "phoenix", "raleigh", "durham", "pittsburgh",
             "salt lake city", "minneapolis", "detroit", "nashville", "kirkland", "redmond", "cambridge, ma", "bellevue")
NON_US_HINTS = ("canada", "uk", "united kingdom", "london", "europe", "emea", "apac", "india",
                "germany", "france", "ireland", "japan", "singapore", "australia", "brazil",
                "mexico", "israel", "poland", "netherlands", "spain", "latam", "china", "korea")
PRIORITY = ("nyc", "bay", "remote_us", "other_us", "non_us")


def _is_us(loc: str) -> bool:
    low = loc.lower()
    if any(w in low for w in US_WORDS) or _US_TOKEN_RE.search(low):
        return True
    if any(c in low for c in US_CITIES) and not any(h in low for h in NON_US_HINTS):
        return True
    return any(tok in US_STATES for tok in re.findall(r"\b[A-Z]{2}\b", loc))


def classify_one(loc: str) -> str:
    low = loc.lower()
    if any(a in low for a in NYC):
        return "nyc"
    if any(a in low for a in BAY):
        return "bay"
    if "remote" in low:
        return "non_us" if any(h in low for h in NON_US_HINTS) and not _is_us(loc) else "remote_us"
    if _is_us(loc):
        return "other_us"
    return "non_us"


def classify_location(locations: list[str]) -> str:
    classes = {classify_one(l) for l in locations if l and l.strip()}
    for c in PRIORITY:
        if c in classes:
            return c
    return "unknown"


def country_of(location_class: str, locations: list[str]) -> str:
    if location_class in ("nyc", "bay", "remote_us", "other_us"):
        return "US"
    return "non-US" if locations else ""


# ---------- arrangement ----------
_HINTS = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite",
          "on site": "onsite", "in office": "onsite", "in-office": "onsite"}


def detect_arrangement(text: str, hint: str = "", locations: list[str] | None = None) -> str:
    h = (hint or "").strip().lower()
    if h in _HINTS:
        return _HINTS[h]
    loc_text = " ".join(locations or []).lower()
    if "remote" in loc_text:
        return "remote"
    if "hybrid" in loc_text:
        return "hybrid"
    t = (text or "").lower()
    if re.search(r"\bhybrid\b", t):
        return "hybrid"
    if re.search(r"\b(fully remote|remote[- ]first|100% remote|work from home|remote)\b", t):
        return "remote"
    if re.search(r"\b(on[- ]?site|in[- ]office)\b", t):
        return "onsite"
    return "unknown"


# ---------- years of experience ----------
_WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10}
_WORD_NUM_RE = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b(?=\s*\+?\s*(?:years?|yrs?))", re.I)
_YEARS = r"(?:years?|yrs?)"
_RANGE_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*" + _YEARS, re.I)
_PLUS_RE = re.compile(r"(\d{1,2})\s*(?:\+|plus|or more)\s*" + _YEARS, re.I)
_SINGLE_RE = re.compile(r"(\d{1,2})\s*" + _YEARS, re.I)
_CONTEXT_RE = re.compile(r"experience|background|industry|professional|working|hands-on|develop|engineer|build|program|"
                         r"coding|design|ship|track record|\bof [a-z]|\bin [a-z]", re.I)
_NOT_EXPERIENCE_RE = re.compile(r"^\s*(ago|old|of age|warranty)", re.I)


def _in_context(text: str, start: int, end: int) -> bool:
    return bool(_CONTEXT_RE.search(text[end:end + 80]) or _CONTEXT_RE.search(text[max(0, start - 40):start]))


def extract_yoe(text: str) -> tuple[int | None, int | None]:
    """Years of experience asked. 'N+ years', 'N or more years' and 'N-M years' always count;
    a bare 'N years' counts only near experience words. 'N years ago/old' never counts."""
    if not text:
        return None, None
    text = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s*\((\d{1,2})\)", r"\2", text, flags=re.I)   # "two (2) years"
    text = _WORD_NUM_RE.sub(lambda m: str(_WORD_NUMS[m.group(1).lower()]), text)
    mins: list[int] = []
    maxs: list[int] = []
    covered: list[tuple[int, int]] = []

    def taken(m: re.Match) -> bool:
        return any(s <= m.start() < e for s, e in covered)

    for m in _RANGE_RE.finditer(text):
        if _NOT_EXPERIENCE_RE.match(text[m.end():]):
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 15:
            mins.append(a)
            maxs.append(b)
            covered.append((m.start(), m.end()))
    for m in _PLUS_RE.finditer(text):
        if taken(m) or _NOT_EXPERIENCE_RE.match(text[m.end():]):
            continue
        n = int(m.group(1))
        if n <= 15:
            mins.append(n)
            covered.append((m.start(), m.end()))
    for m in _SINGLE_RE.finditer(text):
        if taken(m) or _NOT_EXPERIENCE_RE.match(text[m.end():]):
            continue
        if _in_context(text, m.start(), m.end()):
            n = int(m.group(1))
            if n <= 15:
                mins.append(n)
    if not mins:
        return None, None
    return max(mins), (max(maxs) if maxs else None)


# ---------- salary ----------
_MONEY = r"(?:\$|usd\s?|us\$)\s?(\d{1,3}(?:,\d{3})+|\d{2,3}(?:\.\d)?\s?k|\d{5,6})"
_SALARY_RANGE_RE = re.compile(_MONEY + r"\s*(?:-|–|—|to|and)\s*" + _MONEY, re.I)
_SALARY_SINGLE_RE = re.compile(_MONEY, re.I)
_HOURLY_RE = re.compile(r"(per|an|/)\s*(hour|hr)\b", re.I)


def _money(s: str) -> int:
    s = s.lower().replace(",", "").replace(" ", "")
    return int(float(s[:-1]) * 1000) if s.endswith("k") else int(s)


def extract_salary(text: str) -> tuple[int | None, int | None]:
    """Annual USD range from a posting ('$150,000 - $200,000', '$150K–$200K'). Hourly and tiny figures are ignored."""
    if not text:
        return None, None
    best: tuple[int, int] | None = None
    for m in _SALARY_RANGE_RE.finditer(text):
        lo, hi = _money(m.group(1)), _money(m.group(2))
        if lo >= 20_000 and hi >= lo and hi <= 2_000_000 and not _HOURLY_RE.search(text[m.end():m.end() + 12]):
            if best is None or hi > best[1]:
                best = (lo, hi)
    if best:
        return best
    singles = [_money(m.group(1)) for m in _SALARY_SINGLE_RE.finditer(text)
               if not _HOURLY_RE.search(text[m.end():m.end() + 12])]
    singles = [v for v in singles if 20_000 <= v <= 2_000_000]
    if singles:
        return min(singles), max(singles)
    return None, None


# ---------- level ----------
def level_from_title(title: str) -> str:
    t = title.lower()
    if re.search(r"\bintern(ship)?\b|\bco-?op\b", t):
        return "intern"
    if re.search(r"new grad|university grad|early career|entry[- ]level|\bgraduate\b|\bcampus\b", t):
        return "new_grad"
    if re.search(r"\b(manager|director|head of|vp|vice president|chief)\b|team lead", t):
        return "manager"
    if re.search(r"\b(senior|sr\.?|lead)\b", t):
        return "senior"
    if "member of technical staff" in t or re.search(r"\bmts\b", t):
        return "unknown"                       # MTS is a title, not a Staff level
    if re.search(r"\b(staff|principal|distinguished|fellow)\b", t):
        return "staff"
    if re.search(r"\b(iii|3)\b", t):
        return "mid"
    if re.search(r"\b(ii|2|i|1|junior|jr\.?|associate)\b", t):
        return "early"
    return "unknown"


# ---------- flags ----------
FLAG_PATTERNS: dict[str, list[str]] = {
    "no_sponsorship": [
        r"(not|unable to|will not|won't|cannot|can't|do(es)? not)\s+(currently\s+|be able to\s+)?(offer|provide|consider|support|be sponsoring|sponsor)\w*\s*(visa\s+|immigration\s+|work\s+|employment\s+)?(sponsor\w*|visas?)?",
        r"without (the need for |requiring )?(visa |employer |current or future )?sponsorship",
        r"\bno (visa |immigration )?sponsorship",
        r"sponsorship (is )?not (available|offered|provided)",
    ],
    "clearance": [r"security clearance", r"\bts/sci\b", r"top secret", r"clearance (is )?required"],
    "us_person": [r"u\.?s\.? (citizen|person)s?\b.{0,20}(only|required)", r"must be (a )?u\.?s\.? citizen",
                  r"citizenship (is )?required", r"verification of u\.?s\.? citizenship", r"\bitar\b", r"export[- ]control"],
}
_PHD_RE = re.compile(r"\bph\.?\s?d\b", re.I)
_MASTERS_RE = re.compile(r"\bmaster'?s?\b|\bm\.?s\.?\b(?!\s*(office|word|excel|teams|sql|azure))|\bmsc\b|\bm\.eng\b|\bgraduate degree", re.I)
_BACHELORS_RE = re.compile(r"bachelor|\bbs\b|\bb\.s\.|\bba\b|\bb\.a\.|undergraduate|\bbsc\b", re.I)
_DEGREE_ALT_RE = re.compile(r"bachelor|master|\bms\b|\bbs\b|\bb\.s\.|\bm\.s\.", re.I)


def detect_flags(text: str, qualifications_min: str, title: str) -> list[str]:
    low = (text or "").lower()
    flags = [name for name, pats in FLAG_PATTERNS.items() if any(re.search(p, low) for p in pats)]
    qmin = qualifications_min or ""
    if _PHD_RE.search(title or "") or (_PHD_RE.search(qmin) and not _DEGREE_ALT_RE.search(qmin)):
        flags.append("phd_required")
    elif _MASTERS_RE.search(qmin) and not _BACHELORS_RE.search(qmin):
        flags.append("masters_required")          # a Master's is the minimum degree, no Bachelor's alternative
    return flags


# ---------- qualifications ----------
_PREF_HEAD_RE = re.compile(r"(preferred qualifications|preferred requirements|nice[- ]to[- ]have|we'd love to see|bonus points|preferred:|"
                           r"it'?s a plus|an added plus|added plus if|while not required|preferred skills|additional qualifications)", re.I)
_MIN_HEAD_RE = re.compile(r"(minimum qualifications|basic qualifications|required qualifications|minimum requirements|basic requirements|"
                          r"requirements:|you'll need to have|what you need|must have|qualifications:|"
                          r"we'd love to hear from you if you have|what you('ll)? bring|you should have|what you have)", re.I)
# generic section intros: used only when no specific requirements heading exists
_MIN_GENERIC_RE = re.compile(r"(what we're looking for|about you|who you are)", re.I)


def _heading_line_re(head_re: re.Pattern[str]) -> re.Pattern[str]:
    # the same alternatives, but anchored to a whole line ("Minimum requirements", "Preferred qualifications:")
    return re.compile(r"^[ \t]*(?:" + head_re.pattern + r")[ \t:]*$", re.I | re.M)


_PREF_LINE_RE = _heading_line_re(_PREF_HEAD_RE)
_MIN_LINE_RE = _heading_line_re(_MIN_HEAD_RE)
_MIN_GENERIC_LINE_RE = _heading_line_re(_MIN_GENERIC_RE)


def _first(text: str, *patterns: re.Pattern[str]) -> int | None:
    """Start of the first pattern that matches, trying patterns in priority order."""
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.start()
    return None


def split_qualifications(text: str) -> tuple[str, str]:
    text = text or ""
    pref_idx = _first(text, _PREF_LINE_RE, _PREF_HEAD_RE)
    if pref_idx is None:
        pref_idx = len(text)
    before = text[:pref_idx]
    # specific requirements heading on its own line > generic intro line > phrase anywhere
    min_idx = _first(before, _MIN_LINE_RE, _MIN_GENERIC_LINE_RE, _MIN_HEAD_RE, _MIN_GENERIC_RE)
    min_text = before[min_idx:] if min_idx is not None else before
    return min_text.strip(), text[pref_idx:].strip()


# ---------- assemble ----------
def ts_to_date(ts: int | None) -> str | None:
    if not ts:
        return None
    if ts > 10_000_000_000:          # milliseconds
        ts //= 1000
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat()


def renormalize(job: Job) -> None:
    """Re-run the text-derived fields on a stored job so parser fixes apply without refetching."""
    quals = "\n".join(x for x in (job.qualifications_min, job.qualifications_pref) if x)
    full = "\n".join(x for x in (job.description_text, job.responsibilities, quals) if x)
    # Excluded snapshot rows intentionally omit their full text.  They still
    # retain the parsed years/flags needed to stay excluded, so never replace
    # those durable fields with empty parser output during a report re-render.
    if not full.strip():
        job.level = level_from_title(job.title)
        job.location_class = classify_location(job.locations)
        job.country = country_of(job.location_class, job.locations)
        return
    qmin, qpref = split_qualifications(quals or job.description_text)
    job.qualifications_min, job.qualifications_pref = qmin, qpref
    job.yoe_min, job.yoe_max = extract_yoe(qmin or full)
    job.yoe_pref = extract_yoe(qpref)[0]
    job.salary_min, job.salary_max = extract_salary(full)
    job.flags = detect_flags(full, qmin, job.title)
    job.level = level_from_title(job.title)
    job.location_class = classify_location(job.locations)
    job.country = country_of(job.location_class, job.locations)


def normalize(raw: RawJob, company_name: str) -> Job:
    desc = html_to_text(raw.description_html)
    resp = html_to_text(raw.responsibilities_html)
    quals = html_to_text(raw.qualifications_html)
    qmin, qpref = split_qualifications(quals or desc)
    full = "\n".join(x for x in (desc, resp, quals) if x)
    loc_class = classify_location(raw.locations)
    job = Job(
        id=job_id(raw.company, raw.source_id), company=company_name, title=raw.title.strip(),
        url=raw.url, apply_url=raw.apply_url, locations=list(raw.locations),
        location_class=loc_class, country=country_of(loc_class, raw.locations),
        arrangement=detect_arrangement(full, raw.arrangement_hint, raw.locations),
        description_text=desc, responsibilities=resp, qualifications_min=qmin,
        qualifications_pref=qpref, level=level_from_title(raw.title), posted_at=ts_to_date(raw.posted_ts),
    )
    job.yoe_min, job.yoe_max = extract_yoe(qmin or full)
    job.yoe_pref = extract_yoe(qpref)[0]
    job.salary_min, job.salary_max = extract_salary(full)
    job.flags = detect_flags(full, qmin, raw.title)
    return job
