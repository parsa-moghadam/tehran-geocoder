import sqlite3
conn = sqlite3.connect("data/tehran.db")
print("feedback before:", conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0])
print("learned before:", conn.execute("SELECT COUNT(*) FROM streets WHERE source='learned'").fetchone()[0])
conn.execute("DELETE FROM feedback")
conn.execute("DELETE FROM streets WHERE source='learned'")
conn.commit()
print("cleaned. total streets:", conn.execute("SELECT COUNT(*) FROM streets").fetchone()[0])
conn.close()