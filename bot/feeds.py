import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

USER_AGENT = "discord-blog-bot/0.1 (+https://github.com/developowl/discord-blog-bot)"
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = httpx.Timeout(10.0)

FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")
COMMON_PATHS = ("/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml")


class FeedError(Exception):
    """사용자에게 그대로 보여줄 수 있는 메시지를 가진 오류."""


@dataclass
class Entry:
    key: str
    title: str
    link: str
    published: datetime | None
    image: str | None


@dataclass
class FetchResult:
    not_modified: bool = False
    title: str | None = None
    entries: list[Entry] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None


def normalize_url(raw: str) -> str:
    url = raw.strip()
    if not url:
        raise FeedError("블로그 URL을 입력해주세요.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FeedError("올바른 URL 형식이 아닙니다. 예: https://example.github.io")
    return url


async def _ensure_public_host(request: httpx.Request) -> None:
    host = request.url.host
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FeedError(f"도메인을 찾을 수 없습니다: {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise FeedError("내부 네트워크 주소는 등록할 수 없습니다.")


def make_client(allow_private: bool = False) -> httpx.AsyncClient:
    hooks = {} if allow_private else {"request": [_ensure_public_host]}
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": USER_AGENT},
        event_hooks=hooks,
    )


async def _get(client: httpx.AsyncClient, url: str, headers: dict | None = None) -> tuple[httpx.Response, bytes]:
    async with client.stream("GET", url, headers=headers) as resp:
        body = bytearray()
        async for chunk in resp.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise FeedError("응답이 너무 큽니다.")
        return resp, bytes(body)


def _parse(body: bytes):
    parsed = feedparser.parse(body)
    if not parsed.get("version") and not parsed.entries:
        return None
    return parsed


def _platform_candidates(url: str) -> list[str]:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    first = p.path.strip("/").split("/")[0] if p.path.strip("/") else ""
    if host.endswith("velog.io") and first.startswith("@"):
        name = first[1:]
        return [f"https://v2.velog.io/rss/{name}", f"https://v2.velog.io/rss/@{name}"]
    if host == "medium.com" and first.startswith("@"):
        return [f"https://medium.com/feed/{first}"]
    return []


def _html_candidates(base_url: str, body: bytes) -> list[str]:
    soup = BeautifulSoup(body, "html.parser")
    found = []
    for link in soup.find_all("link", href=True):
        rel = [r.lower() for r in (link.get("rel") or [])]
        if "alternate" in rel and (link.get("type") or "").lower() in FEED_TYPES:
            found.append(urljoin(base_url, link["href"]))
    return found


async def discover_feed(client: httpx.AsyncClient, raw_url: str) -> tuple[str, str, FetchResult]:
    """블로그 URL에서 피드를 찾아 (site_url, feed_url, 현재 피드 내용)을 돌려준다."""
    site_url = normalize_url(raw_url)
    candidates: list[str] = _platform_candidates(site_url)

    try:
        resp, body = await _get(client, site_url)
    except httpx.HTTPError as e:
        if not candidates:
            raise FeedError(f"블로그에 접속할 수 없습니다: {type(e).__name__}") from e
    else:
        if resp.is_success:
            if _parse(body):
                return site_url, str(resp.url), _to_result(resp, body)
            candidates += _html_candidates(str(resp.url), body)
        root = f"{resp.url.scheme}://{resp.url.host}"
        prefix = str(resp.url).rstrip("/")
        for path in COMMON_PATHS:
            candidates.append(prefix + path)
            if prefix != root:
                candidates.append(root + path)

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            resp, body = await _get(client, candidate)
        except (httpx.HTTPError, FeedError):
            continue
        if resp.is_success and _parse(body):
            return site_url, str(resp.url), _to_result(resp, body)

    raise FeedError("RSS/Atom 피드를 찾지 못했습니다. 피드 주소를 직접 입력해보세요.")


async def fetch_feed(
    client: httpx.AsyncClient, feed_url: str, etag: str | None, last_modified: str | None
) -> FetchResult:
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    resp, body = await _get(client, feed_url, headers)
    if resp.status_code == 304:
        return FetchResult(not_modified=True, etag=etag, last_modified=last_modified)
    resp.raise_for_status()
    if not _parse(body):
        raise FeedError("피드 형식을 해석할 수 없습니다.")
    return _to_result(resp, body)


OG_IMAGE_KEYS = (
    ("property", "og:image"),
    ("property", "og:image:url"),
    ("name", "og:image"),
    ("name", "twitter:image"),
)


async def fetch_og_image(client: httpx.AsyncClient, page_url: str) -> str | None:
    """글 페이지의 og:image(없으면 twitter:image) 주소를 찾는다. 실패하면 None."""
    try:
        resp, body = await _get(client, page_url)
    except (httpx.HTTPError, FeedError):
        return None
    if not resp.is_success:
        return None
    soup = BeautifulSoup(body, "html.parser")
    for attr, key in OG_IMAGE_KEYS:
        tag = soup.find("meta", attrs={attr: key})
        content = (tag.get("content") or "").strip() if tag else ""
        if content:
            url = urljoin(str(resp.url), content)
            if urlparse(url).scheme in ("http", "https"):
                return url
    return None


def _to_result(resp: httpx.Response, body: bytes) -> FetchResult:
    parsed = feedparser.parse(body)
    return FetchResult(
        title=parsed.feed.get("title"),
        entries=[e for e in (_to_entry(x) for x in parsed.entries) if e],
        etag=resp.headers.get("ETag"),
        last_modified=resp.headers.get("Last-Modified"),
    )


def _to_entry(item) -> Entry | None:
    link = item.get("link")
    key = item.get("id") or link or item.get("title")
    if not key or not link:
        return None
    published = None
    for attr in ("published_parsed", "updated_parsed"):
        if item.get(attr):
            published = datetime(*item[attr][:6], tzinfo=timezone.utc)
            break
    return Entry(
        key=key,
        title=(item.get("title") or "(제목 없음)").strip(),
        link=link,
        published=published,
        image=_image(item),
    )


def _image(item) -> str | None:
    for media in item.get("media_thumbnail", []) + item.get("media_content", []):
        if media.get("url"):
            return media["url"]
    for enc in item.get("enclosures", []):
        if (enc.get("type") or "").startswith("image/") and enc.get("href"):
            return enc["href"]
    return None
