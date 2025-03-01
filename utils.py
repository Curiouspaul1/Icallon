import time
import json
import string
import random
from functools import wraps
from collections import defaultdict

from read_writer import ReadWriteLock

# import nltk
# from nltk.corpus import names
# from nltk.corpus import words

# nltk.download('names')
# nltk.download("words")

# word_list = set(words.words())
# print(len(word_list))

# def is_valid_word(word):
#     return word.lower() in word_list

# print(is_valid_word("lion"))   # True
# print(is_valid_word("zzzz"))   # False

# male_names = set(names.words('male.txt'))
# female_names = set(names.words('female.txt'))

# print(len(male_names))
# print(len(female_names))

# def is_name(word):
#     return word in male_names or word in female_names

# print(is_name("Olamide"))  # True
# print(is_name("Banana"))  # False


lock = ReadWriteLock()


def create_letter_defaultdict(default_value):
    """Creates a defaultdict with letters a-z as keys and a default value."""
    return defaultdict(
        lambda: default_value,
        {letter: default_value for letter in string.ascii_lowercase}
    )


def letter_to_idx(letter: str) -> int:
    if not isinstance(letter, str):
        raise ValueError('Invalid string provided')

    return ord(letter.lower()) - 96


def parse_event_data(fn):
    @wraps(fn)
    def decorated(*args):
        data, *other_args = args
        data = json.loads(data)
        data = eval(data) if data != "" else data
        return fn(data, *other_args)
    return decorated


def genRoomId():
    chars = "ABCDEFGHIJKLMNPQRSTUVWXYZ0123456789"

    token = "".join(random.choice(chars) for x in range(12))

    return token


def writeUpdate(obj: dict, filename: str) -> None:
    with lock.acquire_write():
        try:
            with open(filename, 'w') as _file:
                json.dump(obj, _file, indent=4)
        finally:
            lock.release_write()


def getFile(filename: str) -> dict:
    lock.acquire_read()
    try:
        with open(filename, 'r') as fp:
            data = json.load(fp)
            return data
    finally:
        lock.release_read()

print(getFile('rooms.json'))
time.sleep(3)
lock.release_write()
lock.release_read()

def addToRoom(room_id: str, player: str) -> None:
    rooms = getFile('rooms.json')
    if room_id in rooms:
        rooms[room_id]['players'].append(player)
        rooms[room_id]['player_to_pos'][player] = rooms[room_id]['pos']

        rooms[room_id]['pos'] += 1
        rooms[room_id]['last_interaction'] = time.time()

        writeUpdate(rooms, 'rooms.json')


def indexRoom(room_id):
    rooms = getFile('rooms.json')
    rooms[room_id] = {
        'ptr': 0,
        'pos': 0,
        'players': [],
        'player_to_pos': {},
        'letters': []
    }

    writeUpdate(rooms, 'rooms.json')


def removeFromRoom(room_id: str, player: str) -> None:
    rooms = getFile('rooms.json')
    if room_id in rooms:
        print('yes in rooms')
        player_positions = rooms[room_id]['player_to_pos']
        players = rooms[room_id]['players']
        print(player)
        if player in player_positions:
            player_pos = player_positions[player]
            player_positions[players[-1]] = player_pos
            players[player_pos], players[-1] = players[-1], players[player_pos]

            rooms[room_id]['pos'] -= 1
            players.pop()
            player_positions.pop(player)

        rooms[room_id]['last_interaction'] = time.time()

        writeUpdate(rooms, 'rooms.json')


def map_player_to_room(player: str, room_id: str) -> None:
    sess_to_room = getFile('player_to_rooms.json')
    if player not in sess_to_room:
        sess_to_room[player] = room_id

        writeUpdate(sess_to_room, 'player_to_rooms.json')


def get_player_room(player: str) -> [str | None]:
    sess_to_room = getFile('player_to_rooms.json')
    if player in sess_to_room:
        return sess_to_room[player]


def get_player_turn(room_id: str) -> str:
    """ fetches player to play next """
    player = None
    rooms = getFile('rooms.json')
    if room_id in rooms:
        room = rooms[room_id]
        players = room['players']
        ptr = room['ptr']
        player = players[ptr]

        if room['ptr'] < len(room['players']) - 1:
            room['ptr'] += 1
        else:
            room['ptr'] = 0  # round robin

        writeUpdate(rooms, 'rooms.json')

    return player


def store_sid(player: str, sid: str) -> None:
    """ maps player name to client sid """
    player_to_sids = getFile('player_to_sid.json')
    player_to_sids[player] = sid

    writeUpdate(player_to_sids, 'player_to_sid.json')


def get_sid(player: str) -> str:
    player_to_sids = getFile('player_to_sid.json')
    if player in player_to_sids:
        return player_to_sids[player]


def remove_sid(player: str) -> None:
    player_to_sids = getFile('player_to_sid.json')
    if player in player_to_sids:
        player_to_sids.pop(player)

        writeUpdate(player_to_sids, 'player_to_sid.json')
