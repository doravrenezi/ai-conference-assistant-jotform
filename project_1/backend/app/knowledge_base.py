import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"
CONFERENCE_CONFIG_PATH = KNOWLEDGE_BASE_DIR / "conference_config.json"
MARKDOWN_FILES = (
    "conference_overview.md",
    "schedule.md",
    "speakers.md",
    "workshops.md",
    "venue_and_travel.md",
    "ticket_policy.md",
    "cancellation_policy.md",
    "faq.md",
)
TOPIC_TO_FILES = {
    "ticket_types": {"ticket_policy.md", "conference_overview.md", "faq.md"},
    "workshops": {"workshops.md", "schedule.md", "speakers.md", "faq.md"},
    "dates": {"conference_overview.md", "schedule.md", "faq.md"},
    "general": set(MARKDOWN_FILES),
}
TOKEN_PATTERN = re.compile(r"[a-z0-9_]{2,}")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "me",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "we",
    "what",
    "when",
    "where",
    "which",
}


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source: str
    heading: str
    text: str
    keywords: set[str]


_KNOWLEDGE_CHUNKS: list[KnowledgeChunk] = []
_CHUNK_EMBEDDINGS: dict[str, list[float]] = {}
_KNOWLEDGE_METADATA: dict[str, object] = {}
_STRUCTURED_CONFIG: dict[str, object] = {}
_OPENAI_CLIENT = None
DEFAULT_REGISTRATION_ALLOWED_VALUES = {
    "ticket_types": {"student", "professional", "vip"},
    "workshops": {"ai_agents", "rag_basics", "prompt_engineering"},
    "days": {"june_12", "june_13", "june_14"},
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", value.strip())


def _tokenize_text(value: str) -> set[str]:
    return {token for token in TOKEN_PATTERN.findall(value.lower()) if token not in STOPWORDS}


def _title_from_filename(file_name: str) -> str:
    return file_name.replace(".md", "").replace("_", " ").title()


def _parse_markdown_sections(file_name: str, text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = _title_from_filename(file_name)
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("#"):
            section_text = "\n".join(current_lines).strip()
            if section_text:
                sections.append((current_heading, section_text))
            current_heading = line.lstrip("#").strip() or current_heading
            current_lines = []
            continue
        current_lines.append(line)

    final_text = "\n".join(current_lines).strip()
    if final_text:
        sections.append((current_heading, final_text))

    return sections


def _build_section_chunks() -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []

    for file_name in MARKDOWN_FILES:
        file_path = KNOWLEDGE_BASE_DIR / file_name
        if not file_path.exists():
            continue

        text = _normalize_text(file_path.read_text(encoding="utf-8"))
        if not text:
            continue

        sections = _parse_markdown_sections(file_name, text)
        for index, (heading, section_text) in enumerate(sections, start=1):
            content = _normalize_text(section_text)
            if not content:
                continue
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"{file_name}::section_{index}",
                    source=file_name,
                    heading=heading,
                    text=content,
                    keywords=_tokenize_text(f"{file_name} {heading} {content}"),
                )
            )

    return chunks


def _load_structured_config() -> dict[str, object]:
    if not CONFERENCE_CONFIG_PATH.exists():
        return {}
    return json.loads(CONFERENCE_CONFIG_PATH.read_text(encoding="utf-8"))


def get_registration_allowed_values() -> dict[str, set[str]]:
    config = _STRUCTURED_CONFIG or _load_structured_config()
    if not config:
        return {key: set(values) for key, values in DEFAULT_REGISTRATION_ALLOWED_VALUES.items()}

    ticket_types = {
        str(ticket_type.get("id", "")).strip()
        for ticket_type in config.get("ticket_types", [])
        if str(ticket_type.get("id", "")).strip()
    }
    workshops = {
        str(workshop.get("id", "")).strip()
        for workshop in config.get("workshops", [])
        if str(workshop.get("id", "")).strip()
    }
    days = {
        str(conference_day.get("id", "")).strip()
        for conference_day in config.get("conference", {}).get("dates", [])
        if str(conference_day.get("id", "")).strip()
    }

    return {
        "ticket_types": ticket_types or set(DEFAULT_REGISTRATION_ALLOWED_VALUES["ticket_types"]),
        "workshops": workshops or set(DEFAULT_REGISTRATION_ALLOWED_VALUES["workshops"]),
        "days": days or set(DEFAULT_REGISTRATION_ALLOWED_VALUES["days"]),
    }


def _embedding_model() -> str:
    return os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def _get_openai_client():
    global _OPENAI_CLIENT

    if _OPENAI_CLIENT is not None:
        return _OPENAI_CLIENT

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    _OPENAI_CLIENT = OpenAI(api_key=api_key)
    return _OPENAI_CLIENT


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _embed_texts(texts: list[str]) -> list[list[float]] | None:
    client = _get_openai_client()
    if client is None:
        return None

    response = client.embeddings.create(
        model=_embedding_model(),
        input=texts,
    )
    return [item.embedding for item in response.data]


def _ensure_chunk_embeddings() -> bool:
    missing_chunks = [chunk for chunk in _KNOWLEDGE_CHUNKS if chunk.chunk_id not in _CHUNK_EMBEDDINGS]
    if not missing_chunks:
        return True

    embeddings = _embed_texts([f"{chunk.heading}\n\n{chunk.text}" for chunk in missing_chunks])
    if embeddings is None:
        return False

    for chunk, embedding in zip(missing_chunks, embeddings):
        _CHUNK_EMBEDDINGS[chunk.chunk_id] = embedding
    return True


def load_knowledge_base(force_reload: bool = False) -> dict[str, object]:
    global _KNOWLEDGE_CHUNKS, _KNOWLEDGE_METADATA, _STRUCTURED_CONFIG

    if _KNOWLEDGE_CHUNKS and _STRUCTURED_CONFIG and not force_reload:
        return _KNOWLEDGE_METADATA

    _STRUCTURED_CONFIG = _load_structured_config()
    _KNOWLEDGE_CHUNKS = _build_section_chunks()
    if force_reload:
        _CHUNK_EMBEDDINGS.clear()

    _KNOWLEDGE_METADATA = {
        "loaded": True,
        "document_count": sum(1 for file_name in MARKDOWN_FILES if (KNOWLEDGE_BASE_DIR / file_name).exists()),
        "chunk_count": len(_KNOWLEDGE_CHUNKS),
        "sources": sorted({chunk.source for chunk in _KNOWLEDGE_CHUNKS}),
        "embedding_model": _embedding_model(),
        "has_structured_config": bool(_STRUCTURED_CONFIG),
    }
    return _KNOWLEDGE_METADATA


def get_knowledge_base_metadata() -> dict[str, object]:
    if not _KNOWLEDGE_CHUNKS:
        return load_knowledge_base()
    return _KNOWLEDGE_METADATA


def _find_records(records: list[dict], query_keywords: set[str]) -> list[dict]:
    matches: list[dict] = []

    for record in records:
        haystack_parts = [str(record.get("id", "")), str(record.get("label", "")), str(record.get("weekday", ""))]
        haystack_parts.extend(str(value) for value in record.values() if isinstance(value, (str, int, float)))
        haystack = " ".join(haystack_parts).lower()
        if query_keywords & _tokenize_text(haystack):
            matches.append(record)

    return matches


def _structured_lookup(query: str, topic: str) -> dict[str, object]:
    if not _STRUCTURED_CONFIG:
        return {"used": False, "match_type": "none", "results": []}

    query_keywords = _tokenize_text(query)
    results: list[dict[str, object]] = []
    conference = _STRUCTURED_CONFIG.get("conference", {})
    rules = _STRUCTURED_CONFIG.get("registration_rules", {})
    ticket_types = _STRUCTURED_CONFIG.get("ticket_types", [])
    workshops = _STRUCTURED_CONFIG.get("workshops", [])
    dates = conference.get("dates", []) if isinstance(conference, dict) else []
    dietary_options = _STRUCTURED_CONFIG.get("dietary_options", [])

    if topic == "ticket_types":
        matched = _find_records(ticket_types, query_keywords) or ticket_types
        for record in matched:
            results.append({"kind": "ticket_type", "data": record})
        if rules.get("ticket_type"):
            results.append({"kind": "registration_rule", "data": {"field": "ticket_type", **rules["ticket_type"]}})

    elif topic == "workshops":
        matched = _find_records(workshops, query_keywords) or workshops
        for record in matched:
            results.append({"kind": "workshop", "data": record})
        if rules.get("workshop_preference"):
            results.append(
                {"kind": "registration_rule", "data": {"field": "workshop_preference", **rules["workshop_preference"]}}
            )

    elif topic == "dates":
        matched = _find_records(dates, query_keywords) or dates
        for record in matched:
            results.append({"kind": "conference_day", "data": record})
        if rules.get("selected_days"):
            results.append({"kind": "registration_rule", "data": {"field": "selected_days", **rules["selected_days"]}})

    else:
        if {"dietary", "meal", "meals", "food", "vegetarian", "vegan", "halal", "kosher", "gluten_free"} & query_keywords:
            results.append({"kind": "dietary_options", "data": {"options": dietary_options}})
        if {"ticket", "tickets", "price", "pricing", "vip", "student", "professional"} & query_keywords:
            matched_tickets = _find_records(ticket_types, query_keywords) or ticket_types
            for record in matched_tickets[:3]:
                results.append({"kind": "ticket_type", "data": record})
        if {"workshop", "workshops", "rag_basics", "ai_agents", "prompt_engineering"} & query_keywords:
            matched_workshops = _find_records(workshops, query_keywords) or workshops
            for record in matched_workshops[:3]:
                results.append({"kind": "workshop", "data": record})
        if {"date", "dates", "day", "days", "june", "friday", "saturday", "sunday"} & query_keywords:
            matched_dates = _find_records(dates, query_keywords) or dates
            for record in matched_dates[:3]:
                results.append({"kind": "conference_day", "data": record})
        if {"venue", "location", "timezone", "conference", "called", "name"} & query_keywords and conference:
            results.append(
                {
                    "kind": "conference",
                    "data": {
                        "name": conference.get("name"),
                        "short_name": conference.get("short_name"),
                        "timezone": conference.get("timezone"),
                        "venue": conference.get("venue"),
                    },
                }
            )

    return {
        "used": bool(results),
        "match_type": "structured_lookup" if results else "none",
        "results": results[:6],
    }


def _lexical_retrieval(query: str, topic: str, limit: int) -> list[dict[str, object]]:
    query_keywords = _tokenize_text(query)
    prioritized_sources = TOPIC_TO_FILES.get(topic, TOPIC_TO_FILES["general"])
    scored_chunks: list[tuple[int, KnowledgeChunk]] = []

    for chunk in _KNOWLEDGE_CHUNKS:
        overlap_score = len(query_keywords & chunk.keywords)
        if overlap_score == 0:
            continue
        source_score = 3 if chunk.source in prioritized_sources else 0
        score = overlap_score * 4 + source_score
        scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda item: (-item[0], item[1].source, item[1].heading))
    return [
        {
            "chunk_id": chunk.chunk_id,
            "source": chunk.source,
            "heading": chunk.heading,
            "content": chunk.text,
            "score": score,
        }
        for score, chunk in scored_chunks[:limit]
    ]


def _embedding_retrieval(query: str, topic: str, limit: int) -> list[dict[str, object]] | None:
    if not _ensure_chunk_embeddings():
        return None

    query_embedding_list = _embed_texts([query])
    if not query_embedding_list:
        return None

    query_embedding = query_embedding_list[0]
    prioritized_sources = TOPIC_TO_FILES.get(topic, TOPIC_TO_FILES["general"])
    scored_chunks: list[tuple[float, KnowledgeChunk]] = []

    for chunk in _KNOWLEDGE_CHUNKS:
        embedding = _CHUNK_EMBEDDINGS.get(chunk.chunk_id)
        if embedding is None:
            continue
        score = _cosine_similarity(query_embedding, embedding)
        if chunk.source in prioritized_sources:
            score += 0.025
        if score < 0.2:
            continue
        scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda item: (-item[0], item[1].source, item[1].heading))
    return [
        {
            "chunk_id": chunk.chunk_id,
            "source": chunk.source,
            "heading": chunk.heading,
            "content": chunk.text,
            "score": round(score, 4),
        }
        for score, chunk in scored_chunks[:limit]
    ]


def search_conference_knowledge_base(query: str, topic: str = "general", limit: int = 4) -> dict[str, object]:
    if not _KNOWLEDGE_CHUNKS:
        load_knowledge_base()

    structured = _structured_lookup(query, topic)
    embedding_matches = None
    retrieval_mode = "embeddings"

    try:
        embedding_matches = _embedding_retrieval(query, topic, limit)
    except Exception:
        embedding_matches = None

    if embedding_matches is None:
        retrieval_mode = "lexical_fallback"
        retrieval_matches = _lexical_retrieval(query, topic, limit)
    else:
        retrieval_matches = embedding_matches

    supported = bool(structured.get("results")) or bool(retrieval_matches)

    return {
        "query": query,
        "topic": topic,
        "knowledge_base": get_knowledge_base_metadata(),
        "supported": supported,
        "structured_data": structured,
        "retrieval": {
            "mode": retrieval_mode,
            "matches": retrieval_matches,
        },
    }
