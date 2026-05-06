"""One-off script: pull live JDs from the configured Greenhouse boards
and save them as text fixtures under tests/quality/sample_jds/.

Run: python tests/quality/_fetch_jds.py
"""

import html as html_module
from pathlib import Path

import requests
from bs4 import BeautifulSoup


SELECTIONS = [
    ("narvar", "7363442", "01-narvar-senior-ai-engineer"),
    ("wayve", "8478666002", "02-wayve-embedded-cpp"),
    ("datadog", "7194969", "03-datadog-ai-research-paris"),
    ("moloco", "7493062003", "04-moloco-data-scientist"),
    ("figma", "5426468004", "05-figma-enterprise-ae"),
    ("gleanwork", "4686368005", "06-glean-ai-outcomes-manager"),
    ("placerlabs", "7720617003", "07-placer-big-data-engineer"),
]


def html_to_text(content_html: str) -> str:
    """Strip HTML and produce a faithful plaintext representation,
    preserving paragraph + list structure that the JD parser will see.

    Greenhouse returns 'content' as HTML-escaped HTML (so '<p>' arrives
    as '&lt;p&gt;'), so we unescape entities BEFORE handing the string
    to BeautifulSoup — otherwise BS treats the escaped tags as plain
    text and never strips them."""
    unescaped = html_module.unescape(content_html or "")
    soup = BeautifulSoup(unescaped, "html.parser")
    # Convert <li> into '- ' bullets so the text mirrors a real resume
    # / job-listing pasted from a recruiter portal.
    for li in soup.find_all("li"):
        li.insert_before("- ")
        li.insert_after("\n")
        li.unwrap()
    # Convert paragraph-style elements into newline-delimited blocks.
    for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6"]):
        tag.append("\n")
    text = soup.get_text()
    # Tighten up whitespace.
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned: list[str] = []
    blank = 0
    for line in lines:
        if line.strip():
            cleaned.append(line)
            blank = 0
        else:
            blank += 1
            if blank <= 1:
                cleaned.append("")
    return "\n".join(cleaned).strip() + "\n"


def main() -> None:
    out_dir = Path(__file__).parent / "sample_jds"
    out_dir.mkdir(parents=True, exist_ok=True)
    for board, job_id, slug in SELECTIONS:
        url = "https://boards-api.greenhouse.io/v1/boards/{}/jobs/{}".format(board, job_id)
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print("SKIP {slug}: HTTP {code}".format(slug=slug, code=response.status_code))
            continue
        job = response.json()
        title = job.get("title", "?").strip()
        location = (job.get("location") or {}).get("name", "?").strip()
        body = html_to_text(job.get("content", "") or "")
        full = "{title}\n{location}\n\n{body}\n".format(
            title=title, location=location, body=body
        )
        path = out_dir / "{}.txt".format(slug)
        path.write_text(full, encoding="utf-8")
        print(
            "wrote {slug}.txt: title={title!r}, location={location!r}, body_chars={n}".format(
                slug=slug, title=title, location=location, n=len(body)
            )
        )


if __name__ == "__main__":
    main()
