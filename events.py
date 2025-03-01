from flask import request
from flask_socketio import (
    emit, join_room,
    leave_room, send
)

from extensions import ioclient, session
from utils import (
    genRoomId,
    addToRoom,
    removeFromRoom,
    get_player_room,
    map_player_to_room,
    indexRoom,
    parse_event_data,
    get_player_turn,
    store_sid,
    remove_sid,
    get_sid
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

    print(session['user_id'])
    send(username + ' has entered the room.', to=room)


@ioclient.on('create')
def new_room(data):
    username = session['user_id']
    roomID = genRoomId()

    # save room details
    indexRoom(roomID)

    join_room(roomID)

    # store player details
    addToRoom(roomID, username)
    map_player_to_room(username, roomID)


@ioclient.on('start')
def start_game(room_id):
    player = get_player_turn()
    client_id = get_sid(player)
    ioclient.emit('player_turn', to=client_id)
