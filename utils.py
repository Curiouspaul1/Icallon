import time
import json
import nltk
import string
import random
from functools import wraps
from collections import defaultdict

from geopy import Nominatim
from nltk.corpus import words
from names_dataset import NameDataset

from read_writer import ReadWriteLock


nd = NameDataset()
try:
    word_list = set(words.words())
except LookupError:
    nltk.download("words")
    word_list = set(words.words())

geolocator = Nominatim(user_agent="Icallon")


lock = ReadWriteLock()

# TODO: Use classes and OOP to write more cohesive workflow


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
    lock.acquire_write()
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
        'curr_ans_count': 0,
        'players': [],
        'letters': [],
        'player_to_pos': {},
        'round_answers': {},
        'player_to_score': {}
    }

    writeUpdate(rooms, 'rooms.json')


def get_players(room_id):
    rooms = getFile('rooms.json')
    if room_id in rooms:
        return rooms[room_id]['players']


def removeFromRoom(room_id: str, player: str) -> None:
    rooms = getFile('rooms.json')
    if room_id in rooms:
        print('yes in rooms')
        player_positions = rooms[room_id]['player_to_pos']
        player_scores = rooms[room_id]['player_to_score']
        players = rooms[room_id]['players']
        print(player)
        if player in player_positions:
            player_pos = player_positions[player]
            player_positions[players[-1]] = player_pos
            players[player_pos], players[-1] = players[-1], players[player_pos]

            rooms[room_id]['pos'] -= 1
            players.pop()
            player_positions.pop(player)
            player_scores.pop(player)

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

        if room['ptr'] == len(room['players']) - 1:
            room['ptr'] = 0
        else:
            room['ptr'] += 1  # round robin

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


def cross_letter(room_id: str, letter: str) -> None:
    rooms = getFile('rooms.json')
    if room_id in rooms:
        room = rooms[room_id]
        idx = letter_to_idx(letter)
        room['letters'].append(idx)

        writeUpdate(rooms, 'rooms.json')


def get_used_letters(room_id: str) -> [str]:
    rooms = getFile('rooms.json')
    if room_id in rooms:
        return rooms[room_id]['letters']


def user_id_taken(username: str):
    player_to_sids = getFile('player_to_sid.json')
    return username in player_to_sids


def is_name(name):
    name = name.strip().title()
    result = nd.search(name)

    # Check if it's listed as a first or last name
    return bool(result.get("first_name") or result.get("last_name"))


def is_valid_word(word):
    return word.lower() in word_list


def is_animal(word):
    with open('animals_names.txt') as fp:
        animals = fp.readlines()[0]  # only one line in file
        return word in animals


def is_place(name):
    return geolocator.geocode(name) is not None


def calculate_results(batch_answers, letter):
    def calc(answer):
        func_mappings = {
            'name': is_name,
            'animal': is_animal,
            'thing': is_valid_word,
            'place': is_place
        }
        score = 0
        for k, v in answer.items():
            try:
                if v.startswith(letter) and func_mappings[k](v):
                    score += 5
            except Exception as e:
                print(f"Error while marking {k} with value {v}")
                print(str(e))
        return score

    resp = {}
    for player, ans in batch_answers.items():
        score = calc(ans)
        resp[player] = score
    return resp


def score_player_attempt(player, room_id, answers, letter):
    rooms = getFile('rooms.json')
    # print('GOt file')
    if room_id in rooms:
        room = rooms[room_id]

        # get results
        if player in room['players'] and player not in room['round_answers']:
            # scores[player] += score
            room['round_answers'][player] = answers
            writeUpdate(rooms, 'rooms.json')

            if len(room['round_answers'].keys()) == len(room['players']):
                # calculate results
                scores = calculate_results(room['round_answers'], letter)
                print(f"The scores are: {scores}")
                update_scores(room, scores)
                room['round_answers'] = {}
                writeUpdate(rooms, 'rooms.json')

                return room['player_to_score']   # signal


def update_scores(room, new_scores):
    # rooms = getFile('rooms.json')
    # if room_id in rooms:
    #     room = rooms[room_id]
    scores = room['player_to_score']
    for player, score in new_scores.items():
        if player not in scores:
            scores[player] = 0
        scores[player] += score


def clean_rooms():
    """ Removes stale rooms 🧹"""
    print('Cron job active: Cleaning the rooms')
    lock.acquire_write()
    try:
        tmp_rooms = {}
        with open('rooms.json') as fp:
            rooms = json.load(fp)
            for room in rooms:
                diff = time.time() - rooms[room]['last_interaction']
                if diff < 300:
                    tmp_rooms[room] = rooms[room]
        with open('rooms.json', 'w') as fp:
            json.dump(tmp_rooms, fp)
    finally:
        lock.release_write()
