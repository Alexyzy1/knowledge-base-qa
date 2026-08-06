from backend.store.mysql_store import engine
from sqlalchemy import text

with engine.connect() as conn:
    rows = conn.execute(text("SELECT id, name FROM knowledge_base ORDER BY id")).all()
    for r in rows:
        print(r.id, r.name)
