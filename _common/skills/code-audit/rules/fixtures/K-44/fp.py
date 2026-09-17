import subprocess

def _identity():
    def get(k):
        return subprocess.run(["git", "config", "--get", k],
                              capture_output=True, text=True).stdout.strip()
    return get("user.name"), get("user.email")

def commit(msg, name, email):
    subprocess.run(["git", "-c", "user.name=" + name,
                    "-c", "user.email=" + email,
                    "commit", "-m", msg], check=True)
