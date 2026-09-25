"""Render fictional jobs without network access or touching your real workspace."""
from pathlib import Path
from datetime import date
import json
from jobradar.config import load_preferences
from jobradar.models import Job, Review
from jobradar.score import apply_scores
from jobradar.render import render_report, write_report
from jobradar.store import save_snapshot
root = Path(__file__).resolve().parents[1]
out = root / "build" / "demo"
today = date.today().isoformat()
prefs = load_preferences(root / "examples/profile/preferences.yaml")
jobs=[]
for i,(company,title,loc,skills) in enumerate([
    ("Northstar Labs (fictional)","Software Engineer, Product","remote_us","Python TypeScript React Postgres Docker"),
    ("Fieldnotes (fictional)","Full-stack Engineer","nyc","TypeScript React Node Python"),
    ("Atlas Studio (fictional)","AI Engineer","bay","Python LLM eval Docker"),
    ("Cedar Systems (fictional)","Backend Engineer","remote_us","Python Postgres Docker"),
]):
    jobs.append(Job(id=f"demo:{i+1}",company=company,title=title,url=f"https://example.com/jobs/{i+1}",
        locations=[{"remote_us":"Remote, United States","nyc":"New York, NY","bay":"San Francisco, CA"}[loc]],
        location_class=loc,country="US",arrangement="remote" if loc=="remote_us" else "hybrid",level="early",
        description_text=f"Fictional role for demonstration. Build reliable products with {skills}.",
        yoe_min=1,posted_at=today,first_seen=today,status="new"))
apply_scores(jobs,prefs,today)
jobs[0].review=Review(id="demo:1",skills=36,experience_match="strong",reason="Fictional review: API and UI ownership overlap; validate with your own evidence.",gaps=["Production scale unverified"])
# The review is illustrative. Keep score components internally consistent.
old=jobs[0].score_parts.get("skills",0)
jobs[0].score_parts["skills"]=36;jobs[0].score +=36-old;jobs[0].rank_score=jobs[0].score
meta={"date":today,"generated_at":today,"sources":[{"company":"fictional-demo","ok":True,"count":len(jobs)}],"warnings":["FICTIONAL DEMO — these are not real openings or career claims."]}
save_snapshot(out/"data/jobs",today,jobs,meta)
_,index=write_report(render_report(jobs,meta,prefs,today),out/"reports",today)
print(f"Fictional demo: {index}")
