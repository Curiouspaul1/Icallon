uwsgi --http :5000 --gevent 10 --http-websockets --http-keepalive \
    --master --wsgi-file app.py --callable app \
    --cheaper 10 --cheaper-step 5 --cheaper-algo spare \
    --workers 20
