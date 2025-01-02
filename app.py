import os

from flask import (
    Flask,
    render_template
)
from dotenv import load_dotenv

from extensions import (
    init,
    ioclient
)
from events import *

load_dotenv()

# init app
app = Flask(__name__)
app.config['secret_key'] = os.getenv(
    'APP_SECRET',
    os.urandom(24)
)

# init extensions
init(app)


@app.get('/')
def index():
    # show home screen
    return render_template('index.html')


if __name__ == '__main__':
    ioclient.run(app, debug=True)
