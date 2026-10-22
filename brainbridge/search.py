"""Search: FTS5 BM25 text match x recency boost.

boost = 1 + 0.5 ** (age_days / 60): 2.0 today, about 1.7 at a month, about 1.0 after a
year. With equal text, newer wins; a much stronger match on an older record still can.
Records matching all words always rank above records matching only some.
"""
import re
from datetime import date

from .config import project_key

HALF_LIFE_DAYS = 60
CANDIDATES = 400


def recency_boost(record_date: str, today: date) -> float:
    try:
        age = max((today - date.fromisoformat(record_date)).days, 0)
    except ValueError:
        age = 3650
    return 1 + 0.5 ** (age / HALF_LIFE_DAYS)


def search(db, query: str, project: str | None = None, limit: int = 8, today: date | None = None) -> list:
    today = today or date.today()
    tokens = [t for t in re.findall(r"\w+", query.casefold()) if t]
    if not tokens:
        return []
    where, params = ["records_fts MATCH ?"], []
    if project:
        where.append("r.project_key = ?")
        params.append(project_key(project))
    # Recency is applied inside SQL, so the candidate cut-off can never drop a recent record.
    db.create_function("recency", 1, lambda d: recency_boost(d, today), deterministic=True)
    sql = f"""SELECT r.id, r.connector, r.source_path, r.project, r.title, r.date, r.date_source,
                     bm25(records_fts, 4.0, 1.0, 2.0) AS bm
              FROM records_fts JOIN records r ON r.id = records_fts.rowid
              WHERE {' AND '.join(where)}
              ORDER BY bm25(records_fts, 4.0, 1.0, 2.0) * recency(r.date) LIMIT {CANDIDATES}"""
    results, seen = [], set()
    for tier, op in ((1, " AND "), (0, " OR ")):
        if tier == 0 and (len(results) >= limit or len(tokens) == 1):
            break
        for row in db.execute(sql, [op.join(f'"{t}"' for t in tokens)] + params):
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            score = -row["bm"] * recency_boost(row["date"], today)
            results.append({**dict(row), "score": round(score, 3), "tier": tier})
    results.sort(key=lambda r: (r["tier"], r["score"]), reverse=True)
    return results[:limit]
