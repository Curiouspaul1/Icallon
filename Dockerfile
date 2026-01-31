FROM python:3.12.9-bullseye

WORKDIR /app

COPY . .

RUN apt update && apt install -y \
    libpcre2-dev \
    libssl-dev \
    build-essential \
    python3-dev

RUN pip install gunicorn
RUN pip install -r requirements.txt

# prepare dbs
RUN echo "{}" > player_to_rooms.json \
    && echo "{}" > player_to_sid.json \
    && echo "{}" > rooms.json \
    && echo "{}" > sid_to_players.json \
    && echo "{}" > player_tokens.json

# Grant write permissions to the current user
RUN chmod 666 player_to_rooms.json player_to_sid.json rooms.json

CMD [ "/bin/sh", "run.sh" ]
