import subprocess

def run(name):
    subprocess.run('ls ' + name, shell=True)
