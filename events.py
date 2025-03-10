import time

import gevent
gevent.monkey.patch_all()

from flask import request
from flask_socketio import (
    emit, join_room,
    leave_room, send
)

import messages as MSG
from extensions import ioclient, session
from utils import (
    genRoomId,
    addToRoom,
    removeFromRoom,
    get_player_room,
    map_player_to_room,
    indexRoom,
    get_player_turn,
    store_sid,
    remove_sid,
    get_players,
    get_sid,
    get_used_letters,
    score_player_attempt,
    cross_letter
)


@ioclient.on('connect')
def connect():
    print('this is getting clleds')
    user_id = session['user_id']
    print(user_id)
    session['client_id'] = request.sid
    print(session['client_id'])
    store_sid(user_id, request.sid)


@ioclient.on('set-session')
def set_session(data):
    if 'session' in data:
        session['user_id'] = data['session']


@ioclient.on('disconnect')
def disconnect():
    player = session['user_id']
    session.pop('client_id')

    # update data stores
    room_id = get_player_room(player)
    removeFromRoom(room_id, player)
    remove_sid(player)


@ioclient.on('join')
# @parse_event_data
def join(data):
    # get lcient id from session
    username = session['user_id']

    room = data['roomID']
    join_room(room)

    # store room details
    addToRoom(room, username)
    map_player_to_room(username, room)

    all_players = get_players(room)

    emit('player_joined', all_players, to=room)


@ioclient.on('create')
def new_room():
    username = session['user_id']
    roomID = genRoomId()

    # save room details
    indexRoom(roomID)

    join_room(roomID)

    # store player details
    addToRoom(roomID, username)
    map_player_to_room(username, roomID)
    emit('game_code', roomID)


@ioclient.on('start')
def start_game(data):
    room_id = data['room_id']
    player = get_player_turn(room_id)
    all_players = get_players(room_id)

    if len(all_players) < 2:
        emit('cant_start_game', MSG.LOW_PLAYER_COUNT)

    used_letters = get_used_letters(room_id)

    client_id = get_sid(player)
    ioclient.emit('game_started', all_players, to=room_id)

    ioclient.emit(
        'private_player_turn',
        {'disabledLetters': used_letters},
        to=client_id
    )

    ioclient.emit('public_player_turn', session['user_id'])


@ioclient.on('letter_selected')
def letter_selected(data):
    letter = data['letter']
    room_id = data['room_id']

    cross_letter(room_id, letter)

    ioclient.emit('letter_chosen', letter, to=room_id)


@ioclient.on('next_player_turn')
def next_player_turn(data):
    room_id = data['room_id']
    player = get_player_turn(room_id)
    used_letters = get_used_letters(room_id)

    client_id = get_sid(player)
    ioclient.emit(
        'private_player_turn',
        {'disabledLetters': used_letters},
        to=client_id
    )

    ioclient.emit('public_player_turn', player)


@ioclient.on('player_answer')
def get_player_score(data):
    player = session['user_id']
    print(f"marking {player}'s answers : {data['answers']}")
    resp = score_player_attempt(
        player, data['room_id'],
        data['answers'], data['letter']
    )

    if resp:
        # emit round-results
        ioclient.emit('round_result', resp, room=data['room_id'])
        gevent.sleep(10)
        next_player_turn({'room_id': data['room_id']})
