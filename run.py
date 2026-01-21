from gevent import monkey
monkey.patch_all()

from app import ioclient, app  # noqa: E402


if __name__ == '__main__':
    ioclient.run(app, debug=True)
