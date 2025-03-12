from eventlet import monkey_patch
monkey_patch()

from app import ioclient, app  # noqa: E402


if __name__ == '__main__':
    ioclient.run(app, debug=True)
