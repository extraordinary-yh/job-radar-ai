"""Import every adapter module so registration side effects run."""
from . import apple, ashby, base, bloomberg, careerops, google, greenhouse, hackernews, lever, linkedin, microsoft, workday  # noqa: F401

__all__ = ["apple", "ashby", "base", "bloomberg", "careerops", "google", "greenhouse", "hackernews", "lever", "linkedin", "microsoft", "workday"]
