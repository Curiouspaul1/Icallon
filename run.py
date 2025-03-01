# from gevent.monkey import patch_all
# patch_all()

from app import ioclient, app  # noqa: E402


if __name__ == '__main__':
    ioclient.run(app, debug=True)
