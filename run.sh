# uwsgi --http :5000 --threads 10 --http-websockets --http-keepalive \
#     --master --wsgi-file app.py --callable app \
#     --cheaper 10 --cheaper-step 5 --cheaper-algo spare \
#     --workers 20

gunicorn -k eventlet -w 1 -b 0.0.0.0:5000 run:app