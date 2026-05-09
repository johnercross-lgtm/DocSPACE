import json
import os
import urllib.request


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-nano")


def build_prompt(article: dict) -> str:
    title = article.get("title", "")
    abstract = article.get("abstract", "")
    source = article.get("source", "")
    journal = article.get("journal", "")

    return f"""
Ти медичний редактор DocSPACE.

Задача: перетвори англомовний медичний snippet у короткий український digest.

Не вигадуй фактів.
Не додавай клінічних рекомендацій, яких немає в тексті.
Пиши українською.
Стиль: професійно, коротко, доказово.

Джерело: {source}
Журнал: {journal}

Original title:
{title}

Original abstract:
{abstract}

Поверни СТРОГО JSON без markdown:

{{
  "title_uk": "короткий український заголовок",
  "abstract_uk": "короткий український digest 2-4 речення",
  "key_points": [
    "ключовий пункт 1",
    "ключовий пункт 2",
    "ключовий пункт 3"
  ],
  "practical_takeaway": "практичне значення для медичної аудиторії",
  "specialty": "одна основна спеціальність",
  "tags": ["тег1", "тег2", "тег3"],
  "priority_score": 1
}}
"""


def process_article_with_ai(article: dict) -> dict:
    if not OPENAI_API_KEY:
        print("[warn] OPENAI_API_KEY is missing; returning original article")
        return article

    prompt = build_prompt(article)

    payload = {
        "model": OPENAI_MODEL,
        "input": prompt,
        "text": {
            "format": {
                "type": "json_object"
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
            data = json.loads(response.read().decode("utf-8"))

        output_text = data.get("output_text", "")
        ai = json.loads(output_text)

        original_title = article.get("title", "")
        original_abstract = article.get("abstract", "")

        article["originalTitle"] = original_title
        article["originalAbstract"] = original_abstract

        article["title"] = ai.get("title_uk") or original_title
        article["abstract"] = ai.get("abstract_uk") or original_abstract

        article["keyPoints"] = ai.get("key_points", [])
        article["practicalTakeaway"] = ai.get("practical_takeaway", "")
        article["specialty"] = ai.get("specialty", "")
        article["tags"] = ai.get("tags", [])
        article["priorityScore"] = ai.get("priority_score", 1)

        article["aiProcessed"] = True
        article["aiModel"] = OPENAI_MODEL

        return article

    except Exception as error:
        print(f"[warn] AI processing failed: {error}")
        return article
