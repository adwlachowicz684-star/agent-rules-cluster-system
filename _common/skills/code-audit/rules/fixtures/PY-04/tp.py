import threading

shared = {'n': 0}

def work():
    shared['n'] += 1

t = threading.Thread(target=work)
t.start()
