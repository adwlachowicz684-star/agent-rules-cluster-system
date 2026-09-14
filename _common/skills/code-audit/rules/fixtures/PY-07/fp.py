class Cache:
    def close(self):
        open('/tmp/dump.txt', 'w').write(str(self.data))
