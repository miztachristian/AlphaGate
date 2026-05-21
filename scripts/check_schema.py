#!/usr/bin/env python3
import sqlite3
conn = sqlite3.connect('/opt/trade-app-v2/state.db')
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(alerts_log)")
for row in cursor.fetchall():
    print(row)
conn.close()
