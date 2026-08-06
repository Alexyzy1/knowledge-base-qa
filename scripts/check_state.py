from backend.store.mysql_store import engine
from sqlalchemy import text

with engine.connect() as conn:
    for tbl in ["knowledge_base", "document", "chunk"]:
        n = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
        print(f"{tbl}: {n} rows")
