
import sqlite3
from pathlib import Path
db = Path(r"web-data") / "uts_platform.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
print("TABLES", [r[0] for r in con.execute("select name from sqlite_master where type='table' order by 1")])
for t in ("worker_agent", "worker_job"):
    try:
        cols = con.execute(f"pragma table_info({t})").fetchall()
        print(t, "COLS", [c[1] for c in cols])
        rows = con.execute(f"select * from {t} order by id desc limit 10").fetchall()
        print(t, "ROWS", len(rows))
        for r in rows:
            print(dict(r))
    except Exception as exc:
        print(t, "ERR", exc)
p = con.execute("select id,name,application_url,status,browser from project where id=15").fetchone()
print("PROJECT15", dict(p) if p else None)
