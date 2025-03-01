import threading


class ReadWriteLock:
    def __init__(self):
        self.readers = 0
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.write_mode = False

    def acquire_read(self):
        print('woKRING ...')
        with self.condition:
            while self.write_mode:
                print('locked') # Wait if a writer is writing
                self.condition.wait()
            self.readers += 1
            self.lock.acquire()

    def release_read(self):
        with self.lock:
            self.readers -= 1
            if self.readers == 0:
                self.condition.notify_all()  # Notify writers that no readers are left

    def acquire_write(self):
        # print('getting called')
        with self.lock:
            while self.readers > 0 or self.lock.locked():
                self.condition.wait()  # Wait until no readers or writers
            self.lock.acquire()

    def release_write(self):
        with self.condition:
            self.lock.release()
            self.condition.notify_all()
