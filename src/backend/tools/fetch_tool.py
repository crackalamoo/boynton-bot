import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

WEB_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": "Fetches a URL and returns its content as markdown-formatted text. Links are preserved as [text](url) so you can follow them with further web_fetch calls.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
            },
            "required": ["url"],
        },
    },
}

_MAX_LENGTH = 32000
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; boynton-bot/1.0; +https://github.com/boyntonbot)"
    )
}


def _extract_text(soup: BeautifulSoup, base_url: str) -> str:
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Images → alt text
    for img in soup.find_all("img"):
        alt = str(img.get("alt", "") or "").strip()
        img.replace_with(alt if alt else "")

    # Links → [text](url), skipping non-navigable hrefs. Done before the
    # table pass below so links nested inside table cells (e.g. HN's
    # front-page story listing) survive as markdown instead of being
    # silently dropped by td.get_text().
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if href.startswith(("javascript:", "mailto:")):
            a.replace_with(a.get_text(strip=True))
            continue
        href = urljoin(base_url, href)
        text = a.get_text(strip=True)
        a.replace_with(f"[{text}]({href})" if text else href)

    # Tables → TSV
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append("\t".join(cells))
        table.replace_with("\n" + "\n".join(rows) + "\n")

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def execute_web_fetch(url: str) -> str:
    try:
        response = httpx.get(url, headers=_HEADERS, timeout=10, follow_redirects=True)
    except httpx.RequestError as exc:
        return f"Error fetching URL: {exc}"

    if response.status_code != 200:
        return f"Error: received HTTP {response.status_code} for {url}"

    soup = BeautifulSoup(response.text, "html.parser")
    text = _extract_text(soup, str(response.url))

    if len(text) > _MAX_LENGTH:
        text = text[:_MAX_LENGTH] + "[truncated]"

    # Mislabeled/corrupted charsets can make httpx's auto-decode of
    # response.text produce literal NUL bytes. Postgres text columns can't
    # store NUL (0x00) at all, so strip them here to guarantee this tool
    # never returns a string that would blow up the later DB insert.
    text = text.replace("\x00", "")

    return text
