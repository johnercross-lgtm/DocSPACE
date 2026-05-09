import json
import os
import urllib.error
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

Задача: перетвори англомовний медичний snippet у короткий український медичний digest.

Пиши українською мовою.
Стиль: професійно, коротко, доказово, без рекламності.
Не вигадуй фактів.
Не додавай клінічних рекомендацій, яких немає в оригінальному тексті.
Якщо це protocol / протокол огляду, обов'язково вкажи, що це саме протокол, а не завершений огляд.
Не використовуй слово "рецензія" для Cochrane Review. Пиши "огляд Cochrane" або "протокол огляду Cochrane".
Не пиши так, ніби результати вже доведені, якщо в тексті йдеться лише про цілі дослідження.
Уникай незграбних формулювань типу "доповнення B12". Краще: "прийом вітаміну B12", "пероральний прийом вітаміну B12", "суплементація вітаміном B12".

Джерело: {source}
Журнал: {journal}

Original title:
{title}

Original abstract:
{abstract}

Поверни тільки валідний JSON без markdown, без пояснень, без ```.

Формат:

{{
  "title_uk": "короткий український заголовок",
  "abstract_uk": "короткий український digest 2-4 речення",
  "key_points": [
    "ключовий пункт 1",
    "ключовий пункт 2",
    "ключовий пункт 3"
  ],
  "practical_takeaway": "обережне практичне значення для медичної аудиторії без перебільшень",
  "specialty": "одна основна спеціальність",
  "tags": ["тег1", "тег2", "тег3"],
  "priority_score": 1
}}
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
            response_payload = json.loads(response.read().decode("utf-8"))

        output_text = extract_output_text(response_payload)

        if not output_text:
            print("[warn] AI response has no text output")
            print(json.dumps(response_payload, ensure_ascii=False)[:1000])
            return article

        ai = safe_parse_json(output_text)

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

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="ignore")
        print(f"[warn] OpenAI HTTP error {error.code}: {body[:1000]}")
        return article

    except Exception as error:
        print(f"[warn] AI processing failed: {error}")
        return article
