import time
import json
import nltk
import string
import random
from typing import (
    List,
    Optional
)
from functools import wraps
from dataclasses import dataclass
from collections import defaultdict

from geopy import Nominatim
from nltk.corpus import words
from names_dataset import NameDataset

from read_writer import ReadWriteLock


nd = NameDataset()  # this thing uses 3.2GB RAM (💀😭)
try:
    word_list = set(words.words())
except LookupError:
    nltk.download("words")
    word_list = set(words.words())

geolocator = Nominatim(user_agent="Icallon")


lock = ReadWriteLock()

# TODO: Use classes and OOP to write more cohesive workflow


@dataclass
class Resp:
    file_json: Optional[dict] = None
    routine_resp: Optional[any] = None


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


# def writeUpdate(
#     obj: dict,
#     filename: str,
#     subroutine: callable,
#     args: List[any]
# ) -> None:
#     lock.acquire_write()
#     try:
#         with open(filename, 'r+') as _file:
#             obj = json.load(fp)
#             resp = subroutine(*args)
#             json.dump(resp, _file, indent=4)
#     finally:
#         lock.release_write()


def execute_action(filename):
    def wrapper(subroutine):
        def wrap(*args, **kwargs):
            lock.acquire_write()
            try:
                with open(filename, 'r') as _file:
                    obj: dict = json.load(_file)
                    resp: Resp = subroutine(obj, *args, **kwargs)
                if resp and resp.file_json:
                    with open(filename, 'w') as _file:
                        json.dump(resp.file_json, _file, indent=4)
                if resp and resp.routine_resp:
                    return resp.routine_resp
            finally:
                lock.release_write()
        return wrap
    return wrapper


def getFile(filename: str) -> dict:
    lock.acquire_read()
    try:
        with open(filename, 'r') as fp:
            data = json.load(fp)
            return data
    finally:
        lock.release_read()


@execute_action(filename='rooms.json')
def addToRoom(rooms: dict, room_id: str, player: str) -> None:
    if room_id in rooms:
        rooms[room_id]['players'].append(player)
        rooms[room_id]['player_to_pos'][player] = rooms[room_id]['pos']

        rooms[room_id]['pos'] += 1
        rooms[room_id]['last_interaction'] = time.time()

        return Resp(file_json=rooms)


@execute_action(filename='rooms.json')
def indexRoom(rooms, room_id):
    rooms[room_id] = {
        'ptr': 0,
        'pos': 0,
        'curr_ans_count': 0,
        'players': [],
        'letters': [],
        'player_to_pos': {},
        'round_answers': {},
        'player_to_score': {},
        'game_started': False
    }

    return Resp(file_json=rooms)


def is_in_session(room_id):
    rooms = getFile('rooms.json')
    if room_id in rooms:
        return rooms[room_id]['game_started']


@execute_action(filename='rooms.json')
def set_room_mode(rooms, room_id):
    if room_id in rooms:
        rooms[room_id]['game_started'] = True

        return Resp(file_json=rooms)


@execute_action(filename='rooms.json')
def get_players(rooms, room_id):
    if room_id in rooms:
        return Resp(routine_resp=rooms[room_id]['players'])


@execute_action(filename='rooms.json')
def removeFromRoom(rooms, room_id: str, player: str) -> None:
    if room_id in rooms:
        player_positions = rooms[room_id]['player_to_pos']
        player_scores = rooms[room_id]['player_to_score']
        players = rooms[room_id]['players']
        if player in player_positions:
            player_pos = player_positions[player]
            player_positions[players[-1]] = player_pos
            players[player_pos], players[-1] = players[-1], players[player_pos]

            rooms[room_id]['pos'] -= 1
            players.pop()
            player_positions.pop(player)

            if player in player_scores:
                player_scores.pop(player)

        rooms[room_id]['last_interaction'] = time.time()

        return Resp(file_json=rooms)


@execute_action(filename='player_to_rooms.json')
def map_player_to_room(sess_to_room, player: str, room_id: str) -> None:
    if player not in sess_to_room:
        sess_to_room[player] = room_id

        return Resp(file_json=sess_to_room)


@execute_action(filename='player_to_rooms.json')
def get_player_room(sess_to_room, player: str) -> [str | None]:
    if player in sess_to_room:
        return Resp(file_json=sess_to_room)


@execute_action(filename='rooms.json')
def get_player_turn(rooms, room_id: str) -> str:
    """ fetches player to play next """
    player = None
    if room_id in rooms:
        room = rooms[room_id]
        players = room['players']
        ptr = room['ptr']
        player = players[ptr]

        if room['ptr'] == len(room['players']) - 1:
            room['ptr'] = 0
        else:
            room['ptr'] += 1  # round robin

        resp = Resp(file_json=rooms)
        setattr(resp, 'routine_resp', player)

        return resp


@execute_action(filename='player_to_sid.json')
def store_sid(player_to_sids, player: str, sid: str) -> None:
    """ maps player name to client sid """
    player_to_sids[player] = sid
    return Resp(file_json=player_to_sids)


def get_sid(player: str) -> str:
    player_to_sids = getFile('player_to_sid.json')
    if player in player_to_sids:
        return player_to_sids[player]


@execute_action(filename='player_to_sid.json')
def remove_sid(player_to_sids, player: str) -> None:
    if player in player_to_sids:
        player_to_sids.pop(player)

        return Resp(file_json=player_to_sids)


@execute_action(filename='rooms.json')
def cross_letter(rooms, room_id: str, letter: str) -> None:
    if room_id in rooms:
        room = rooms[room_id]
        idx = letter_to_idx(letter)
        room['letters'].append(idx)

        return Resp(file_json=rooms)


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
                v = v.lower()
                chosen_letter = letter.lower()
                res = func_mappings[k](v)
                if v.startswith(chosen_letter) and res:
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
    lock.acquire_write()
    try:
        _file = open('rooms.json', 'r')
        rooms = json.load(_file)
        _file.close()  # close file after reading
        if room_id in rooms:
            room = rooms[room_id]
            # get results
            if player in room['players'] and player not in room['round_answers']:
                room['round_answers'][player] = answers
                with open('rooms.json', 'w') as _file:
                    json.dump(rooms, _file, indent=4)
                if len(room['round_answers'].keys()) == len(room['players']):
                    # calculate results
                    scores = calculate_results(room['round_answers'], letter)
                    update_scores(room, scores)
                    room['round_answers'] = {}
                    with open('rooms.json', 'w') as _file:
                        json.dump(rooms, _file, indent=4)
                    return room['player_to_score']   # signal
    finally:
        lock.release_write()


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
