import re

import httpx
from bs4 import BeautifulSoup

WEB_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": "Fetches a URL and returns its content as clean plain text.",
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

_MAX_LENGTH = 8000
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; boynton-bot/1.0; +https://github.com/boyntonbot)"
    )
}


def execute_web_fetch(url: str) -> str:
    try:
        response = httpx.get(url, headers=_HEADERS, timeout=10, follow_redirects=True)
    except httpx.RequestError as exc:
        return f"Error fetching URL: {exc}"

    if response.status_code != 200:
        return f"Error: received HTTP {response.status_code} for {url}"

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Collapse more than 2 consecutive newlines down to 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text) > _MAX_LENGTH:
        text = text[:_MAX_LENGTH] + "[truncated]"

    return text

