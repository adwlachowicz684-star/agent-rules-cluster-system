import threading

shared = {'n': 0}
lock = threading.Lock()

def work():
    with lock:
        shared['n'] += 1

t = threading.Thread(target=work)
t.start()
