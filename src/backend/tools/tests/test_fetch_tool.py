from bs4 import BeautifulSoup

from backend.tools.fetch_tool import _extract_text


def test_extract_text_preserves_links_inside_table_cells():
    # Mimics Hacker News' front-page structure: story listing laid out as a
    # <table>, with each story's link nested inside a <td>.
    html = """
    <table>
      <tr>
        <td>1.</td>
        <td><a href="https://example.com/story1">Story One</a></td>
      </tr>
      <tr>
        <td>2.</td>
        <td><a href="https://example.com/story2">Story Two</a></td>
      </tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = _extract_text(soup, "https://news.ycombinator.com/")

    assert "[Story One](https://example.com/story1)" in text
    assert "[Story Two](https://example.com/story2)" in text


def test_extract_text_preserves_links_outside_table():
    html = '<p>See <a href="https://example.com/page">this page</a> for details.</p>'
    soup = BeautifulSoup(html, "html.parser")
    text = _extract_text(soup, "https://example.com/")

    assert "[this page](https://example.com/page)" in text


def test_extract_text_table_without_links_stays_plain_tsv():
    html = """
    <table>
      <tr><td>Name</td><td>Age</td></tr>
      <tr><td>Alice</td><td>30</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = _extract_text(soup, "https://example.com/")

    assert "Name\tAge" in text
    assert "Alice\t30" in text


def test_extract_text_relative_link_resolved_against_base_url():
    html = '<table><tr><td><a href="/relative">Relative</a></td></tr></table>'
    soup = BeautifulSoup(html, "html.parser")
    text = _extract_text(soup, "https://example.com/base/")

    assert "[Relative](https://example.com/relative)" in text


def test_extract_text_images_and_script_style_stripped():
    html = """
    <html>
      <head><style>body { color: red; }</style></head>
      <body>
        <script>alert('hi')</script>
        <img src="pic.png" alt="A picture" />
        <p>Hello world</p>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = _extract_text(soup, "https://example.com/")

    assert "color: red" not in text
    assert "alert('hi')" not in text
    assert "A picture" in text
    assert "Hello world" in text
