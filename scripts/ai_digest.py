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
    "громадське здоровʼя",
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
- Не змінюй країну, географію або контекст дослідження.
- "Nationwide" перекладай як "загальнонаціональний", а не "всеукраїнський", якщо матеріал не про Україну.
- Якщо джерело PubMed, НЕ згадуй Cochrane, "огляд Cochrane" або "протокол огляду Cochrane", якщо цього немає в оригінальному тексті.
- Якщо джерело PubMed, зазвичай пиши "дослідження", "публікація" або "аналіз", а не "огляд Cochrane".
- Якщо це protocol / протокол огляду, вказуй це тільки тоді, коли слово protocol є в оригінальному тексті.
- Якщо це Cochrane Review, пиши "огляд Cochrane" або "протокол огляду Cochrane".
- Не використовуй слово "рецензія" для Cochrane Review.
- Не пиши так, ніби результати вже доведені, якщо в тексті йдеться лише про цілі дослідження.
- Уникай незграбних формулювань типу "доповнення B12".
- Краще використовуй: "прийом вітаміну B12", "пероральний прийом вітаміну B12", "суплементація вітаміном B12".
- Не використовуй формулювання "інших здоров'я". Пиши "інших показників здоровʼя" або "загальних наслідків для здоровʼя".
- key_points мають містити тільки 3 короткі пункти.
- Не вставляй поля practical_takeaway, specialty або tags всередину key_points.
- specialty має бути тільки одним значенням зі списку: {specialties_text}.
- Якщо матеріал загальний або доказовий, обирай "доказова медицина".
- Якщо матеріал стосується жіночого здоров'я, вагітності або репродуктивного віку, обирай "акушерство і гінекологія".
- Якщо матеріал стосується новонароджених, дітей або скринінгу новонароджених, обирай "педіатрія".

Джерело: {source}
Журнал: {journal}

Original title:
{title}

Original abstract:
{abstract}
""".strip()


def build_public_health_prompt(article: dict) -> str:
    title = article.get("title", "")
    abstract = article.get("abstract", "")
    source = article.get("source", "ЦГЗ України")
    specialties_text = ", ".join(f'"{item}"' for item in SPECIALTIES)

    return f"""
Ти медичний редактор DocSPACE.

Задача: перетвори українську новину громадського здоровʼя у коротку професійну картку для медичної стрічки.

Правила:
- Пиши українською мовою.
- Не перекладай текст іншою мовою, лише редагуй і стискай.
- Стиль: професійний, нейтральний, короткий, без рекламності.
- Не вигадуй фактів, цифр, причин, наслідків або клінічних рекомендацій.
- Не додавай висновків, яких немає в оригінальному тексті.
- Якщо оригінальний текст короткий, не розширюй його штучно.
- Якщо це статистика, збережи головні числа, період і тему без спотворення.
- Якщо це лише статистичне повідомлення, НЕ пиши поради про лікування, профілактику або дії лікаря.
- practical_takeaway має бути не рекомендацією, а нейтральним інформаційним висновком.
- Заборонені формулювання для practical_takeaway, якщо їх немає в оригіналі: "слід", "варто", "необхідно", "рекомендується", "важливо продовжувати", "залишається важливим".
- Для статистики використовуй нейтральні формули:
  "Дані можна використовувати для моніторингу епідситуації."
  "Матеріал допомагає орієнтуватися в актуальній статистиці."
  "Публікація фіксує оновлені показники за вказаний період."
- title_uk має бути коротким і зрозумілим, але не змінюй зміст.
- abstract_uk: 1–2 короткі речення.
- key_points мають містити рівно 3 короткі пункти.
- key_points не мають дублювати practical_takeaway.
- key_points мають містити тільки факти з оригінального тексту: числа, період, тему, групу населення, географію або джерело.
- Якщо в оригінальному тексті мало фактів, третій key_point може вказувати джерело або географію, але не має бути редакторським висновком.
- Не використовуй у key_points редакторські формули типу:
  "Матеріал допомагає..."
  "Публікація фіксує..."
  "Дані можна використовувати..."
- Такі формули дозволені тільки в practical_takeaway.
- Не вставляй practical_takeaway, specialty або tags всередину key_points.
- specialty має бути тільки одним значенням зі списку: {specialties_text}.
- Для матеріалів про ТБ, ВІЛ, гепатити, ГРВІ, спалахи, вакцинацію зазвичай обирай "інфекційні хвороби".
- Для загальних матеріалів ЦГЗ, статистики, профілактики або епіднагляду можна обирати "громадське здоровʼя".
- tags: 3–5 коротких тегів українською.
- priority_score: 1–10, де 10 — найбільш важливо для широкої медичної аудиторії.
- Якщо матеріал про ТБ, ВІЛ, ГРВІ, спалахи або вакцинацію, priority_score зазвичай 7–9.
- Якщо матеріал короткий і містить лише загальну інформацію, не завищуй priority_score.

Джерело: {source}

Original title:
{title}

Original text:
{abstract}
""".strip()



def build_safety_alert_prompt(article: dict) -> str:
    title = article.get("title", "")
    abstract = article.get("abstract", "")
    source = article.get("source", "FDA/EMA")
    specialties_text = ", ".join(f'"{item}"' for item in SPECIALTIES)

    return f"""
Ти медичний редактор DocSPACE.

Задача: перетвори англомовний safety alert (FDA/EMA) у коротку українську картку для медичної стрічки.

Правила:
- Обовʼязково переклади title та abstract українською мовою.
- Стиль: професійний, нейтральний, без паніки і без рекламності.
- Не вигадуй фактів, не додавай нічого поза оригінальним повідомленням.
- Не змінюй препарат/пристрій, виробника, регіон або рівень ризику.
- Збережи конкретику: що сталося, який ризик, що саме стосується алерту.
- abstract_uk: 1–3 короткі речення, без зайвої води.
- key_points: рівно 3 короткі фактичні пункти.
- practical_takeaway: короткий нейтральний практичний висновок для медичного користувача.
- specialty має бути одним значенням зі списку: {specialties_text}.
- Для safety alerts зазвичай обирай "фармакотерапія", "інфекційні хвороби" або "кардіологія" за контекстом.
- tags: 3–5 коротких тегів українською.
- priority_score: 1–10. Для потенційно серйозних safety alerts зазвичай 8–10.

Джерело: {source}

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


def sanitize_generated_text(value: str, fallback: str) -> str:
    candidate = str(value or "").strip()
    fallback_value = str(fallback or "").strip()
    lowered = candidate.lower()

    blocked_values = {
        "стандарт",
        "standard",
        "test",
        "тест",
        "n/a",
        "na",
        "null",
        "-",
        "—",
    }

    if not candidate:
        return fallback_value
    if lowered in blocked_values:
        return fallback_value
    if len(candidate) < 8:
        return fallback_value
    if len(set(candidate.replace(" ", ""))) <= 2:
        return fallback_value
    return candidate


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

        article["title"] = sanitize_generated_text(ai["title_uk"], original_title)
        article["abstract"] = sanitize_generated_text(ai["abstract_uk"], original_abstract)

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

def process_public_health_with_ai(article: dict) -> dict:
    if not OPENAI_API_KEY:
        print("[warn] OPENAI_API_KEY is missing; returning original public health item")
        return article

    prompt = build_public_health_prompt(article)

    payload = {
        "model": OPENAI_MODEL,
        "input": prompt,
        "temperature": 0.2,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "docspace_public_health_digest",
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
            print("[warn] Public health AI response has no text output")
            print(json.dumps(response_payload, ensure_ascii=False)[:1000])
            return article

        ai = normalize_ai_payload(safe_parse_json(output_text))

        original_title = article.get("title", "")
        original_abstract = article.get("abstract", "")

        article["originalTitle"] = article.get("originalTitle") or original_title
        article["originalAbstract"] = article.get("originalAbstract") or original_abstract

        article["title"] = sanitize_generated_text(ai["title_uk"], original_title)
        article["abstract"] = sanitize_generated_text(ai["abstract_uk"], original_abstract)

        article["keyPoints"] = ai["key_points"]
        article["practicalTakeaway"] = ai["practical_takeaway"]
        article["specialty"] = ai["specialty"]
        article["tags"] = ai["tags"]
        article["priorityScore"] = ai["priority_score"]

        article["source"] = article.get("source") or "ЦГЗ України"
        article["category"] = article.get("category") or "public_health"
        article["aiProcessed"] = True
        article["aiModel"] = OPENAI_MODEL

        return article

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="ignore")
        print(f"[warn] OpenAI HTTP error {error.code} for public health item: {body[:1000]}")
        return article

    except Exception as error:
        print(f"[warn] Public health AI processing failed: {error}")
        return article



def process_safety_alert_with_ai(article: dict) -> dict:
    if not OPENAI_API_KEY:
        print("[warn] OPENAI_API_KEY is missing; returning original safety alert item")
        return article

    prompt = build_safety_alert_prompt(article)

    payload = {
        "model": OPENAI_MODEL,
        "input": prompt,
        "temperature": 0.2,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "docspace_safety_alert_digest",
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
            print("[warn] Safety alert AI response has no text output")
            print(json.dumps(response_payload, ensure_ascii=False)[:1000])
            return article

        ai = normalize_ai_payload(safe_parse_json(output_text))

        original_title = article.get("title", "")
        original_abstract = article.get("abstract", "")

        article["originalTitle"] = article.get("originalTitle") or original_title
        article["originalAbstract"] = article.get("originalAbstract") or original_abstract

        article["title"] = sanitize_generated_text(ai["title_uk"], original_title)
        article["abstract"] = sanitize_generated_text(ai["abstract_uk"], original_abstract)

        article["keyPoints"] = ai["key_points"]
        article["practicalTakeaway"] = ai["practical_takeaway"]
        article["specialty"] = ai["specialty"]
        article["tags"] = ai["tags"]
        article["priorityScore"] = ai["priority_score"]

        article["source"] = article.get("source") or "FDA/EMA"
        article["category"] = article.get("category") or "drug_safety"
        article["aiProcessed"] = True
        article["aiModel"] = OPENAI_MODEL

        return article

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="ignore")
        print(f"[warn] OpenAI HTTP error {error.code} for safety alert item: {body[:1000]}")
        return article

    except Exception as error:
        print(f"[warn] Safety alert AI processing failed: {error}")
        return article
