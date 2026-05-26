from werkzeug.security import generate_password_hash
import sqlite3

conn = sqlite3.connect('school_system.db')
cursor = conn.cursor()

# Hash the password 'admin123'
hashed = generate_password_hash('admin123')

# Update admin user
cursor.execute("UPDATE users SET password = ? WHERE username = 'admin'", (hashed,))
conn.commit()
conn.close()

print("Admin password has been hashed successfully!")