from flask_socketio import SocketIO


# init extensions
ioclient = SocketIO(logger=True, engineio_logger=True)


def init(app):
    ioclient.init_app(app)
    # other extensions
