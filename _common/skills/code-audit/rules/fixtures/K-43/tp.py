import subprocess

def shas(rels):
    out = subprocess.run(
        ["git", "hash-object", "-t", "blob", "--stdin-paths", "-z"],
        input="\n".join(rels), text=True, capture_output=True)
    return out.stdout

def changed():
    return subprocess.run(["git", "diff", "--name-only", "-z"],
                          capture_output=True, text=True).stdout
