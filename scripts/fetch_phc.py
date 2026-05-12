#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

OUT_PATH = Path("data/phc-feed.json")
SOURCE_URL = "https://phc.org.ua/news/all"
SOURCE_NAME = "ЦГЗ України"
CATEGORY = "public_health"
TIMEOUT_SECONDS = 30
LIMIT = 10
ABSTRACT_LIMIT = 600

DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


@dataclass
class Token:
    kind: str
    text: str
    href: str = ""


class LinkAwareTextParser(HTMLParser):
    """Extract visible text tokens and anchor tokens in page order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[Token] = []
        self._skip_depth = 0
        self._current_href: str | None = None
        self._current_link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()

        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return

        if self._skip_depth:
            return

        if tag == "a":
            attrs_dict = {name.lower(): value or "" for name, value in attrs}
            self._current_href = attrs_dict.get("href", "").strip()
            self._current_link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return

        if self._skip_depth:
            return

        if tag == "a" and self._current_href is not None:
            text = normalize_text(" ".join(self._current_link_parts))
            if text:
                self.tokens.append(Token(kind="link", text=text, href=self._current_href))
            self._current_href = None
            self._current_link_parts = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return

        text = normalize_text(data)
        if not text:
            return

        if self._current_href is not None:
            self._current_link_parts.append(text)
        else:
            self.tokens.append(Token(kind="text", text=text))


def normalize_text(raw_text: str) -> str:
    text = unescape(raw_text or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_summary(raw_text: str) -> str:
    text = normalize_text(raw_text)
    if len(text) > ABSTRACT_LIMIT:
        return f"{text[:ABSTRACT_LIMIT].rstrip()}…"
    return text


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (DocSPACE bot)"},
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)

        if isinstance(reason, ssl.SSLError):
            insecure_context = ssl._create_unverified_context()
            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT_SECONDS,
                context=insecure_context,
            ) as response:
                return response.read().decode("utf-8", errors="ignore")

        raise


def is_date(value: str) -> bool:
    return bool(DATE_RE.match(value.strip()))


def is_time(value: str) -> bool:
    return bool(TIME_RE.match(value.strip()))


def is_news_url(href: str) -> bool:
    if not href:
        return False

    absolute_url = urllib.parse.urljoin(SOURCE_URL, href)
    parsed = urllib.parse.urlparse(absolute_url)

    if parsed.netloc and parsed.netloc != "phc.org.ua":
        return False

    path = parsed.path.rstrip("/")

    if path in {"/news", "/news/all"}:
        return False

    return path.startswith("/news/")


def parse_published_at(date_text: str, time_text: str) -> str:
    raw_value = f"{date_text} {time_text}".strip()

    try:
        parsed = datetime.strptime(raw_value, "%d.%m.%Y %H:%M")
        return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return raw_value


def find_previous_date_time(tokens: list[Token], link_index: int) -> tuple[str, str] | None:
    start = max(0, link_index - 12)
    previous = tokens[start:link_index]

    date_index: int | None = None
    date_text = ""

    for index in range(len(previous) - 1, -1, -1):
        if is_date(previous[index].text):
            date_index = index
            date_text = previous[index].text
            break

    if date_index is None:
        return None

    time_text = ""
    for token in previous[date_index + 1 :]:
        if is_time(token.text):
            time_text = token.text

    if not time_text:
        return None

    return date_text, time_text


def collect_summary(tokens: list[Token], link_index: int) -> str:
    parts: list[str] = []

    for token in tokens[link_index + 1 :]:
        text = token.text.strip()

        if not text:
            continue

        if is_date(text):
            break

        if token.kind == "link" and is_news_url(token.href):
            break

        if text in {"Поточна сторінка 1", "Page 2", "Page 3", "Page 4", "Page 5"}:
            break

        if is_time(text):
            continue

        parts.append(text)

        if len(" ".join(parts)) >= ABSTRACT_LIMIT:
            break

    return clean_summary(" ".join(parts))


def infer_tags(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}".lower()
    candidates: list[tuple[tuple[str, ...], str]] = [
        (("туберк", "тб", "манту"), "туберкульоз"),
        (("віл", "снід"), "ВІЛ/СНІД"),
        (("грві", "грип", "рсв", "респіраторно"), "респіраторні інфекції"),
        (("вакцин", "щеплен", "імуніза"), "імунізація"),
        (("гепатит",), "вірусні гепатити"),
        (("амр", "антибіотик", "антимікроб"), "антимікробна резистентність"),
        (("стрес", "менталь", "психіч", "суїцид"), "психічне здоровʼя"),
        (("астм",), "астма"),
        (("гігієна рук", "інфекційний контроль"), "інфекційний контроль"),
        (("статистика", "захворюваність", "зареєстровано"), "статистика"),
        (("діти", "дитини", "немовля"), "педіатрія"),
        (("профілакти", "уберегтися", "захист"), "профілактика"),
    ]

    tags: list[str] = []
    for keywords, tag in candidates:
        if any(keyword in text for keyword in keywords) and tag not in tags:
            tags.append(tag)

    if "громадське здоровʼя" not in tags:
        tags.append("громадське здоровʼя")

    return tags[:5]


def infer_specialty(tags: list[str], title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()

    if any(tag in tags for tag in ["туберкульоз", "ВІЛ/СНІД", "вірусні гепатити", "респіраторні інфекції"]):
        return "інфекційні хвороби"

    if any(keyword in text for keyword in ["астм", "рсв", "респіратор"]):
        return "пульмонологія"

    if any(keyword in text for keyword in ["психіч", "менталь", "стрес", "суїцид"]):
        return "психіатрія"

    if any(keyword in text for keyword in ["дит", "немовля", "школ"]):
        return "педіатрія"

    return "громадське здоровʼя"


def infer_priority(tags: list[str], title: str, summary: str) -> int:
    text = f"{title} {summary}".lower()

    if any(tag in tags for tag in ["туберкульоз", "ВІЛ/СНІД", "респіраторні інфекції"]):
        return 8

    if any(keyword in text for keyword in ["смерт", "госпіталіз", "спалах", "статистика", "захворюваність"]):
        return 7

    if any(tag in tags for tag in ["імунізація", "профілактика", "інфекційний контроль"]):
        return 6

    return 5


def build_item(title: str, summary: str, href: str, date_text: str, time_text: str, updated_at: str) -> dict:
    url = urllib.parse.urljoin(SOURCE_URL, href)
    tags = infer_tags(title, summary)
    specialty = infer_specialty(tags, title, summary)

    return {
        "title": title,
        "abstract": summary,
        "url": url,
        "source": SOURCE_NAME,
        "category": CATEGORY,
        "publishedAt": parse_published_at(date_text, time_text),
        "updatedAt": updated_at,
        "originalTitle": title,
        "originalAbstract": summary,
        "keyPoints": [],
        "practicalTakeaway": "",
        "specialty": specialty,
        "tags": tags,
        "priorityScore": infer_priority(tags, title, summary),
        "aiProcessed": False,
        "aiModel": "",
    }


def parse_items(html_text: str) -> list[dict]:
    parser = LinkAwareTextParser()
    parser.feed(html_text)
    tokens = parser.tokens

    updated_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    items: list[dict] = []
    seen_urls: set[str] = set()

    for index, token in enumerate(tokens):
        if token.kind != "link" or not is_news_url(token.href):
            continue

        previous_date_time = find_previous_date_time(tokens, index)
        if previous_date_time is None:
            continue

        title = clean_summary(token.text)
        summary = collect_summary(tokens, index)

        if not title or not summary:
            continue

        absolute_url = urllib.parse.urljoin(SOURCE_URL, token.href)
        if absolute_url in seen_urls:
            continue

        seen_urls.add(absolute_url)
        date_text, time_text = previous_date_time
        items.append(build_item(title, summary, token.href, date_text, time_text, updated_at))

    return items[:LIMIT]


def write_feed(items: list[dict]) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    try:
        html_text = fetch_text(SOURCE_URL)
    except Exception as error:
        print(f"[warn] failed to fetch {SOURCE_URL}: {error}; keeping existing file unchanged")
        return 0

    try:
        items = parse_items(html_text)
    except Exception as error:
        print(f"[warn] failed to parse PHC news page: {error}; keeping existing file unchanged")
        return 0

    if not items:
        print("[warn] parsed PHC page contains no valid items; keeping existing file unchanged")
        return 0

    write_feed(items)
    print(f"Saved {len(items)} PHC feed items to {OUT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
