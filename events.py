from flask_socketio import (
    emit, send, join_room, leave_room
)

from extensions import ioclient
from utils import genRoomId


@ioclient.on('connect')
def connect():
    print('received json: ' )
    emit('Welcome', 'Welcome to server')


@ioclient.on('disconnect')
def disconnect():
    pass


@ioclient.on('join')
def join(data):
    username = data['username']
    room = data['roomID']
    join_room(room)
    send(username + ' has entered the room.', to=room)


@ioclient.on('create')
def new_room(data):
    print(data, type(data))
    username = data['username']
    roomID = genRoomId()
    join_room(roomID)
    emit('roomCode', {'roomID': roomID})
    print(username)
