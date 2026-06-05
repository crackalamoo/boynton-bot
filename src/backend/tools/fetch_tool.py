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

    # Tables → TSV
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append("\t".join(cells))
        table.replace_with("\n" + "\n".join(rows) + "\n")

    # Images → alt text
    for img in soup.find_all("img"):
        alt = img.get("alt", "").strip()
        img.replace_with(alt if alt else "")

    # Links → [text](url), skipping non-navigable hrefs
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:")):
            a.replace_with(a.get_text(strip=True))
            continue
        href = urljoin(base_url, href)
        text = a.get_text(strip=True)
        a.replace_with(f"[{text}]({href})" if text else href)

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

    return text
