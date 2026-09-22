import subprocess

def commit(msg):
    subprocess.run(["git", "-c", "user.name=yuanbao",
                    "-c", "user.email=yuanbao@users.noreply.github.com",
                    "commit", "-m", msg], check=True)
