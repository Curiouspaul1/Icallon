from flask import session
from flask_session import Session
from flask_socketio import SocketIO
from flask_cors import CORS

# init extensions
ioclient = SocketIO(
    logger=True, engineio_logger=True,
    cors_allowed_origins=[
        "http://127.0.0.1:5501",
        "https://icallon.netlify.app"
    ],
    manage_session=False,
    async_mode='gevent'
)
sess = Session()
cors = CORS()


def init(app):
    ioclient.init_app(app)
    sess.init_app(app)
    cors.init_app(
        app, supports_credentials=True,
        origins=["http://127.0.0.1:5501", "https://icallon.netlify.app"],
        resources={
            r"/*": {
                "origins": [
                    "http://127.0.0.1:5501",
                    "https://icallon.netlify.app"
                ]
            }
        }
    )
    # other extensions
