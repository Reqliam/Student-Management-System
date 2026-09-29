import sqlite3

db = sqlite3.connect("attendance.db")
db.executescript("""
    DELETE FROM attendance;
    DELETE FROM sessions;
    UPDATE sqlite_sequence SET seq = 0 WHERE name = 'attendance';
    UPDATE sqlite_sequence SET seq = 0 WHERE name = 'sessions';
""")
db.commit()
db.close()
print("Done. Attendance and sessions tables have been reset.")