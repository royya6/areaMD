from html.parser import HTMLParser

import requests

NEWS_SEARCH_URL = "https://freenewsapi.ai/v1/search"
REQUEST_TIMEOUT_SECONDS = 8
SEARCH_DATE_RANGE = "30d"
RESULTS_PER_QUERY = 10
MAX_ARTICLES_PER_AUTHORITY = 12
MAX_QUERIES_PER_AUTHORITY = 4
ALLOWED_SEARCH_TOPICS = frozenset(
    {
        "construction",
        "debris",
        "dust",
        "fire",
        "flooding",
        "industrial",
        "pollution",
        "smoke",
        "water",
    }
)


class _PlainTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if not self._ignored_depth:
            self.parts.append(data)


def _plain_text(value: str | None, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    parser = _PlainTextExtractor()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())[:limit]


def build_borough_queries(
    local_authority: str,
    search_region: str | None = None,
    search_terms: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Build separate AND-compatible queries from authority and topic terms."""
    if not isinstance(local_authority, str) or not local_authority.strip():
        raise ValueError("local_authority must be a non-empty string")

    area_words = " ".join(local_authority.split()).split()
    if isinstance(search_region, str) and search_region.strip():
        region_words = " ".join(search_region.split()).split()
        existing_words = {word.casefold() for word in area_words}
        area_words.extend(
            word for word in region_words if word.casefold() not in existing_words
        )
    area_query = " ".join(area_words)

    topics = search_terms or ["fire", "smoke", "pollution", "water"]
    queries = []
    seen_topics = set()
    for topic in topics:
        if not isinstance(topic, str):
            continue
        normalized_topic = topic.strip().casefold()
        if normalized_topic not in ALLOWED_SEARCH_TOPICS or normalized_topic in seen_topics:
            continue
        seen_topics.add(normalized_topic)
        queries.append((normalized_topic, f"{area_query} {normalized_topic}"))
    return queries[:MAX_QUERIES_PER_AUTHORITY]


def _normalize_article(article: object, query_topic: str) -> dict[str, object] | None:
    if not isinstance(article, dict):
        return None
    title = _plain_text(article.get("title"), 300)
    url = article.get("url")
    if not title:
        return None
    if not isinstance(url, str) or not url.startswith("https://"):
        return None

    return {
        "id": str(article.get("id") or url)[:200],
        "title": title,
        "description": _plain_text(article.get("description"), 1000),
        "url": url[:2000],
        "publisher": str(article.get("sitename") or article.get("host") or "Unknown")[:200],
        "host": str(article.get("host") or "")[:200],
        "published_at": article.get("published_at")
        if isinstance(article.get("published_at"), str)
        else None,
        "date_source": article.get("date_source")
        if isinstance(article.get("date_source"), str)
        else "unknown",
        "crawled_at": article.get("crawled_at")
        if isinstance(article.get("crawled_at"), str)
        else None,
        "language": article.get("lang") if isinstance(article.get("lang"), str) else None,
        "country_source": article.get("country_source")
        if isinstance(article.get("country_source"), str)
        else "unknown",
        "query_topic": query_topic,
    }


def fetch_local_articles(
    local_authority: str,
    search_region: str | None = None,
    search_terms: list[str] | None = None,
    session=None,
) -> dict[str, object]:
    """Fetch a bounded set of recent articles using authority-level queries."""
    queries = build_borough_queries(local_authority, search_region, search_terms)
    if not queries:
        return {
            "local_authority": " ".join(local_authority.split())[:100],
            "status": "empty",
            "articles": [],
            "errors": [],
            "lookback": SEARCH_DATE_RANGE,
        }

    http = session or requests.Session()
    errors = []
    articles_by_url = {}
    query_log = []

    for topic, query in queries:
        query_log.append(query)
        try:
            response = http.get(
                NEWS_SEARCH_URL,
                params={"q": query, "date": SEARCH_DATE_RANGE, "size": RESULTS_PER_QUERY},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            errors.append("rate_limited" if status_code == 429 else "provider_unavailable")
            continue
        except (TypeError, ValueError):
            errors.append("invalid_response")
            continue

        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            errors.append("invalid_response")
            continue

        for raw_article in payload["results"]:
            article = _normalize_article(raw_article, topic)
            if article is not None:
                canonical_url = article["url"].split("#", 1)[0]
                articles_by_url.setdefault(canonical_url, article)

    articles = sorted(
        articles_by_url.values(),
        key=lambda article: article.get("published_at") or "",
        reverse=True,
    )[:MAX_ARTICLES_PER_AUTHORITY]
    if articles and errors:
        status = "partial"
    elif articles:
        status = "ok"
    elif errors:
        status = "unavailable"
    else:
        status = "empty"

    return {
        "local_authority": " ".join(local_authority.split())[:100],
        "status": status,
        "articles": articles,
        "errors": sorted(set(errors)),
        "lookback": SEARCH_DATE_RANGE,
        "queries": query_log,
    }