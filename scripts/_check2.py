import sqlite3
c = sqlite3.connect("data/tehran.db")
print("total:", c.execute("SELECT COUNT(*) FROM streets").fetchone()[0])
for row in c.execute("SELECT name, neighborhood, district, lat, lng, source FROM streets WHERE norm LIKE '%اکبری%'"):
    print(row)