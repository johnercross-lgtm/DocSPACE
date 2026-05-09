import json
import os
import urllib.error
import urllib.request


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-nano")


SPECIALTIES = [
    "кардіологія",
    "пульмонологія",
    "гастроентерологія",
    "ендокринологія",
    "неврологія",
    "педіатрія",
    "акушерство і гінекологія",
    "інфекційні хвороби",
    "фармакотерапія",
    "доказова медицина",
    "хірургія",
    "онкологія",
    "психіатрія",
    "дерматологія",
    "ревматологія",
    "нефрологія",
    "урологія",
    "гематологія",
    "імунологія",
    "сімейна медицина",
]


DIGEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title_uk": {
            "type": "string"
        },
        "abstract_uk": {
            "type": "string"
        },
        "key_points": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "string"
            }
        },
        "practical_takeaway": {
            "type": "string"
        },
        "specialty": {
            "type": "string",
            "enum": SPECIALTIES
        },
        "tags": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "string"
            }
        },
        "priority_score": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10
        }
    },
    "required": [
        "title_uk",
        "abstract_uk",
        "key_points",
        "practical_takeaway",
        "specialty",
        "tags",
        "priority_score"
    ]
}


def build_prompt(article: dict) -> str:
    title = article.get("title", "")
    abstract = article.get("abstract", "")
    source = article.get("source", "")
    journal = article.get("journal", "")
    specialties_text = ", ".join(f'"{item}"' for item in SPECIALTIES)

    return f"""
Ти медичний редактор DocSPACE.

Задача: перетвори англомовний медичний snippet у короткий український медичний digest.

Правила:
- Пиши українською мовою.
- Стиль: професійно, коротко, доказово, без рекламності.
- Не вигадуй фактів.
- Не додавай клінічних рекомендацій, яких немає в оригінальному тексті.
- Якщо це protocol / протокол огляду, обов'язково вкажи, що це саме протокол, а не завершений огляд.
- Не використовуй слово "рецензія" для Cochrane Review. Пиши "огляд Cochrane" або "протокол огляду Cochrane".
- Не пиши так, ніби результати вже доведені, якщо в тексті йдеться лише про цілі дослідження.
- Уникай незграбних формулювань типу "доповнення B12".
- Краще використовуй: "прийом вітаміну B12", "пероральний прийом вітаміну B12", "суплементація вітаміном B12".
- key_points мають містити тільки 3 короткі пункти.
- Не вставляй поля practical_takeaway, specialty або tags всередину key_points.
- specialty має бути тільки одним значенням зі списку: {specialties_text}.
- Якщо матеріал загальний або доказовий, обирай "доказова медицина".
- Якщо матеріал стосується жіночого здоров'я, вагітності або репродуктивного віку, обирай "акушерство і гінекологія".

Джерело: {source}
Журнал: {journal}

Original title:
{title}

Original abstract:
{abstract}
""".strip()


def extract_output_text(response_payload: dict) -> str:
    if isinstance(response_payload.get("output_text"), str):
        return response_payload["output_text"].strip()

    parts = []

    for output_item in response_payload.get("output", []):
        for content_item in output_item.get("content", []):
            text = content_item.get("text")
            if isinstance(text, str):
                parts.append(text)

    return "\n".join(parts).strip()


def safe_parse_json(text: str) -> dict:
    text = text.strip()

    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    return json.loads(text)


def normalize_ai_payload(ai: dict) -> dict:
    key_points = ai.get("key_points", [])
    if not isinstance(key_points, list):
        key_points = []

    key_points = [
        str(point).strip()
        for point in key_points
        if isinstance(point, str)
        and point.strip()
        and "practical_takeaway" not in point
        and "specialty" not in point
    ][:3]

    while len(key_points) < 3:
        key_points.append("Ключовий пункт потребує уточнення за оригінальним джерелом.")

    tags = ai.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    tags = [
        str(tag).strip()
        for tag in tags
        if isinstance(tag, str) and tag.strip()
    ][:5]

    while len(tags) < 3:
        tags.append("доказова медицина")

    priority_score = ai.get("priority_score", 1)
    try:
        priority_score = int(priority_score)
    except Exception:
        priority_score = 1

    priority_score = max(1, min(priority_score, 10))

    specialty = str(ai.get("specialty", "")).strip()
    if specialty not in SPECIALTIES:
        specialty = "доказова медицина"

    return {
        "title_uk": str(ai.get("title_uk", "")).strip(),
        "abstract_uk": str(ai.get("abstract_uk", "")).strip(),
        "key_points": key_points,
        "practical_takeaway": str(ai.get("practical_takeaway", "")).strip(),
        "specialty": specialty,
        "tags": tags,
        "priority_score": priority_score,
    }


def process_article_with_ai(article: dict) -> dict:
    if not OPENAI_API_KEY:
        print("[warn] OPENAI_API_KEY is missing; returning original article")
        return article

    prompt = build_prompt(article)

    payload = {
        "model": OPENAI_MODEL,
        "input": prompt,
        "temperature": 0.2,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "docspace_medical_digest",
                "schema": DIGEST_SCHEMA,
                "strict": True
            }
        }
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_payload = json.loads(response.read().decode("utf-8"))

        output_text = extract_output_text(response_payload)

        if not output_text:
            print("[warn] AI response has no text output")
            print(json.dumps(response_payload, ensure_ascii=False)[:1000])
            return article

        ai = normalize_ai_payload(safe_parse_json(output_text))

        original_title = article.get("title", "")
        original_abstract = article.get("abstract", "")

        article["originalTitle"] = original_title
        article["originalAbstract"] = original_abstract

        article["title"] = ai["title_uk"] or original_title
        article["abstract"] = ai["abstract_uk"] or original_abstract

        article["keyPoints"] = ai["key_points"]
        article["practicalTakeaway"] = ai["practical_takeaway"]
        article["specialty"] = ai["specialty"]
        article["tags"] = ai["tags"]
        article["priorityScore"] = ai["priority_score"]

        article["aiProcessed"] = True
        article["aiModel"] = OPENAI_MODEL

        return article

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="ignore")
        print(f"[warn] OpenAI HTTP error {error.code}: {body[:1000]}")
        return article

    except Exception as error:
        print(f"[warn] AI processing failed: {error}")
        return article
