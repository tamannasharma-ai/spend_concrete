"""Small, transparent BM25-style lexical RAG; no paid embedding API."""
import math
import re
from collections import Counter


def tokens(text):
    return re.findall(r"[\w]+", text.lower(), re.UNICODE)


def retrieve(query, documents, limit=5):
    terms = set(tokens(query))
    if not documents or not terms:
        return []
    counts = [Counter(tokens(d["title"] + " " + d["text"])) for d in documents]
    avg = sum(sum(c.values()) for c in counts) / len(counts) or 1
    ranked = []
    for doc, count in zip(documents, counts):
        score = 0
        for term in terms:
            freq = count[term]
            if not freq:
                continue
            df = sum(term in c for c in counts)
            idf = math.log(1 + (len(counts) - df + 0.5) / (df + 0.5))
            score += idf * freq * 2.5 / (freq + 1.5 * (0.25 + 0.75 * sum(count.values()) / avg))
        if score:
            ranked.append({**doc, "retrieval_score": round(score, 3)})
    return sorted(ranked, key=lambda d: d["retrieval_score"], reverse=True)[:limit]
