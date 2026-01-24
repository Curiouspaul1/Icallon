import os, time

from flask import (
    Flask,
    request,
    render_template
)
# from redis import Redis TODO: switch to
# redis IF this doesn't scale💀

from pytz import timezone
from dotenv import load_dotenv
from flask_socketio import emit
from cachelib.file import FileSystemCache
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler

from extensions import (
    init,
    session,
    ioclient
)
from utils import user_id_taken, clean_rooms

load_dotenv()

# init app
app = Flask(__name__)
app.config['secret_key'] = os.getenv(
    'APP_SECRET',
    os.urandom(24)
)
app.config['SESSION_TYPE'] = 'cachelib'
app.config['SESSION_PERMANENT'] = True
# app.config['SESSION_REDIS'] = Redis(
#     host='localhost', port=6379,
#     password='2020Paul'
# )
app.config['SESSION_SERIALIZATION_FORMAT'] = 'json'
app.config['SESSION_CACHELIB'] = FileSystemCache(
    threshold=500,
    cache_dir="sess"
)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True

# init extensions
init(app)

# init scheduler and set cron job
scheduler = BackgroundScheduler()
# cron = CronTrigger()
scheduler.add_job(
    clean_rooms,
    id='clean_rooms_db',
    trigger=CronTrigger(
        hour=0,
        minute=0,
        timezone=timezone('Africa/Lagos')
    )
)
scheduler.start()


@app.before_request
def before_request():
    print("Session accessed:", session.modified)

# @app.post('/')
# def index():
#     data = request.get_json(force=True)
#     if 'user_id' not in data:
#         return {
#             'status': 'error',
#             'message': 'missing required field user_id'
#         }, 400

#     session['user_id'] = data['user_id']
#     time.sleep(5)
#     print(session.get('client_id'))
#     return {}, 200


@app.get('/')
def index():
    return render_template('client.html')


@app.get('/session')
def show_session():
    print(session.sid)
    print(session.get('user_id', ''))
    return {
        'session': session.get('user_id', ''),
        'user': session.get('user_id', '')
    }, 200


@app.post('/session')
def add_session():
    data = request.get_json()
    requested_name = data.get('session')

    if not requested_name:
        return {'status': 'error', 'message': 'No name provided'}, 400
    current_session_name = session.get('user_id')
    if current_session_name == requested_name:
        return {'status': 'success', 'message': 'Welcome back'}, 200

    if user_id_taken(requested_name):
        return {
            'status': 'error',
            'message': 'Username already taken, pick a different one'
        }, 400
    session['user_id'] = requested_name
    print(f"New session registered: {session['user_id']}")

    return {
        'status': 'success',
        'message': ''
    }, 200


@ioclient.on('get-session')
def get_session():
    print(session.sid)
    emit('refresh-session', {
        'session': session.get('user_id', '')
    })


from events import *  # noqa: F403 F401 E402
