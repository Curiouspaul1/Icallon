# uwsgi --http :5000 --gevent 50 --gevent-monkey-patch --http-websockets --http-keepalive \
#     --master --wsgi-file run.py --callable game\
#     --cheaper 10 --cheaper-step 5 --cheaper-algo spare \
#     --workers 20

gunicorn -k eventlet -w 1 -b 0.0.0.0:5000 run:app