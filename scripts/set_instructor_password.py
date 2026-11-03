# Module role: Implements the set instructor password subsystem used by the AutoGrader workflow.
from pathlib import Path
from getpass import getpass
from hashlib import pbkdf2_hmac
from secrets import token_bytes
import os
import tempfile

env = Path(".env")
if not env.is_file():
    raise SystemExit(".env missing; no changes made.")

username = input("Instructor username: ").strip()
if not username or len(username) > 128 or any(c in username for c in "\r\n="):
    raise SystemExit("Invalid username.")

password = getpass("Instructor password: ")
confirm = getpass("Confirm password: ")
if password != confirm:
    raise SystemExit("Passwords do not match.")
if len(password) < 12:
    raise SystemExit("Password must be at least 12 characters.")
if len(password) > 256:
    raise SystemExit("Password is too long.")

salt = token_bytes(16)
digest = pbkdf2_hmac("sha256", password.encode(), salt, 600000)
encoded = f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"

updates = {
    "AUTOGRADER_USERNAME": username,
    "AUTOGRADER_PASSWORD_HASH": encoded,
}
lines = env.read_text().splitlines()
output = []
written = set()

for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in updates:
        if key not in written:
            output.append(f"{key}={updates[key]}")
            written.add(key)
    else:
        output.append(line)

for key, value in updates.items():
    if key not in written:
        output.append(f"{key}={value}")

fd, temp = tempfile.mkstemp(dir=".", prefix=".env.")
try:
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(output) + "\n")
    os.chmod(temp, 0o600)
    os.replace(temp, env)
finally:
    if os.path.exists(temp):
        os.unlink(temp)

print("Instructor credentials saved. Password was not displayed.")
