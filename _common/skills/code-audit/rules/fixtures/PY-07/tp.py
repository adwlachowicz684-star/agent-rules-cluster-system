class Cache:
    def __del__(self):
        open('/tmp/dump.txt', 'w').write(str(self.data))
