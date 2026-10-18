from html.parser import HTMLParser
from xml.etree import ElementTree

import requests

NEWS_SEARCH_URL = "https://freenewsapi.ai/v1/search"
NEWS_RSS_URL = "https://news.google.com/rss/search"
REQUEST_TIMEOUT_SECONDS = 4
SEARCH_DATE_RANGE = "30d"
RESULTS_PER_QUERY = 10
MAX_ARTICLES_PER_AUTHORITY = 12
MAX_SELECTED_RSS_ARTICLES = 3
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
        "source_type": "api",
    }


def _normalize_rss_article(
    item: ElementTree.Element,
    query_topic: str,
    local_authority: str,
    search_region: str | None,
) -> dict[str, object] | None:
    def text(name: str) -> str:
        element = item.find(name)
        return _plain_text(element.text if element is not None else None, 1000)

    title = text("title")
    url = text("link")
    if not title or not url.startswith("https://"):
        return None
    source = item.find("source")
    description = text("description")
    searchable_text = f"{title} {description}".casefold()
    if query_topic.casefold() not in searchable_text:
        return None
    location_terms = [
        word.casefold()
        for word in f"{local_authority} {search_region or ''}".split()
        if len(word) > 2
    ]
    if location_terms and not any(term in searchable_text for term in location_terms):
        return None
    publisher = _plain_text(source.text if source is not None else None, 200) or "Google News"
    published_at = text("pubDate") or None
    return {
        "id": url[:200],
        "title": title[:300],
        "description": description,
        "url": url[:2000],
        "publisher": publisher,
        "host": "",
        "published_at": published_at,
        "date_source": "rss",
        "crawled_at": None,
        "language": "en",
        "country_source": "publisher",
        "query_topic": query_topic,
        "source_type": "rss",
    }


def _rss_relevance_score(article: dict[str, object]) -> int:
    text = f"{article.get('title', '')} {article.get('description', '')}".casefold()
    topic = str(article.get("query_topic") or "").casefold()
    score = 0
    if topic and topic in str(article.get("title") or "").casefold():
        score += 4
    if topic and topic in text:
        score += 2
    if topic in {"dust", "pollution", "smoke", "flooding", "industrial", "construction"}:
        score += 3
    if any(term in text for term in (
        "dust",
        "pollution",
        "smoke",
        "flood",
        "contamination",
        "construction",
        "industrial",
        "burst pipe",
        "water supply",
    )):
        score += 2
    return score


def fetch_rss_articles(
    local_authority: str,
    search_region: str | None = None,
    search_terms: list[str] | None = None,
    session=None,
) -> dict[str, object]:
    """Fetch recent local environmental articles from a public RSS search feed."""
    queries = build_borough_queries(local_authority, search_region, search_terms)[:2]
    http = session or requests.Session()
    errors = []
    articles_by_url = {}
    query_log = []

    for topic, query in queries:
        query_log.append(query)
        try:
            response = http.get(
                NEWS_RSS_URL,
                params={
                    "q": f"{query} when:30d",
                    "hl": "en-GB",
                    "gl": "GB",
                    "ceid": "GB:en",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.content
            if not isinstance(content, (bytes, str)):
                raise ValueError("RSS response did not contain XML")
            root = ElementTree.fromstring(content)
        except requests.RequestException:
            errors.append("rss_provider_unavailable")
            continue
        except (ElementTree.ParseError, TypeError, ValueError):
            errors.append("rss_invalid_response")
            continue

        for item in root.findall("./channel/item"):
            article = _normalize_rss_article(
                item,
                topic,
                local_authority,
                search_region,
            )
            if article is not None:
                articles_by_url.setdefault(article["url"].split("#", 1)[0], article)

    articles = sorted(
        articles_by_url.values(),
        key=lambda article: (
            _rss_relevance_score(article),
            article.get("published_at") or "",
        ),
        reverse=True,
    )[:MAX_ARTICLES_PER_AUTHORITY]
    return {
        "local_authority": " ".join(local_authority.split())[:100],
        "status": "ok" if articles else "unavailable" if errors else "empty",
        "articles": articles,
        "errors": sorted(set(errors)),
        "lookback": SEARCH_DATE_RANGE,
        "queries": query_log,
        "source_type": "rss",
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
    if not articles:
        rss = fetch_rss_articles(
            local_authority,
            search_region=search_region,
            search_terms=search_terms,
            session=http,
        )
        if rss["articles"]:
            return {
                **rss,
                "errors": sorted(set([*errors, *rss["errors"]])),
                "provider_status": status if "status" in locals() else "empty",
            }

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
        "source_type": "api",
    }