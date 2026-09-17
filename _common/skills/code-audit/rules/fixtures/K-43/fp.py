import subprocess

def shas(rels):
    out = subprocess.run(
        ["git", "hash-object", "-t", "blob", "--stdin-paths", "-z"],
        input="\0".join(rels), text=True, capture_output=True)
    return out.stdout
