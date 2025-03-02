import threading


class ReadWriteLock:
    def __init__(self):
        self.readers = 0
        self.writer_active = False
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)

    def acquire_read(self):
        with self.lock:
            # Wait if a writer is active
            while self.writer_active:
                self.condition.wait()
            self.readers += 1

    def release_read(self):
        with self.lock:
            self.readers -= 1
            # Notify writers only when all readers are done
            if self.readers == 0:
                self.condition.notify_all()

    def acquire_write(self):
        with self.lock:
            # Wait if there are readers or another writer
            while self.readers > 0 or self.writer_active:
                self.condition.wait()
            self.writer_active = True

    def release_write(self):
        with self.lock:
            self.writer_active = False
            self.condition.notify_all()  # Notify everyone (readers + writers)
