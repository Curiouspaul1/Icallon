import os
import time
import json
import nltk
import string
import random
from typing import List, Optional
from functools import wraps
from dataclasses import dataclass
from collections import defaultdict

from geopy import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from nltk.corpus import words
from names_dataset import NameDataset

from read_writer import ReadWriteLock

# Initialize datasets
nd = NameDataset()
try:
    word_list = set(words.words())
except LookupError:
    nltk.download("words")
    word_list = set(words.words())

geolocator = Nominatim(user_agent="Icallon")
lock = ReadWriteLock()


@dataclass
class Resp:
    file_json: Optional[dict] = None
    routine_resp: Optional[any] = None


# --- HELPER DECORATORS ---


def execute_action(filename):
    def wrapper(subroutine):
        def wrap(*args, **kwargs):
            lock.acquire_write()
            try:
                # Create file if missing
                if not os.path.exists(filename):
                    with open(filename, "w") as f:
                        json.dump({}, f)

                with open(filename, "r") as _file:
                    try:
                        obj: dict = json.load(_file)
                    except json.JSONDecodeError:
                        obj = {}

                    resp: Resp = subroutine(obj, *args, **kwargs)

                if resp and resp.file_json is not None:
                    with open(filename, "w") as _file:
                        json.dump(resp.file_json, _file, indent=4)

                if resp:
                    return resp.routine_resp
            except Exception as e:
                print(f"Error in {filename}: {e}")
            finally:
                lock.release_write()

        return wrap

    return wrapper


def getFile(filename: str) -> dict:
    lock.acquire_read()
    try:
        if not os.path.exists(filename):
            return {}
        with open(filename, "r") as fp:
            return json.load(fp)
    except:
        return {}
    finally:
        lock.release_read()


# --- TOKEN & AUTH UTILS (NEW) ---


@execute_action(filename="player_tokens.json")
def verify_and_register_user(tokens, username, incoming_token):
    """
    Returns True if user is allowed to connect (New user OR Correct Token).
    Returns False if username is taken by someone with a different token.
    """
    # Case 1: Brand new username -> Claim it
    if username not in tokens:
        tokens[username] = incoming_token
        return Resp(file_json=tokens, routine_resp=True)

    # Case 2: Username exists -> Check if it's the same person
    if tokens[username] == incoming_token:
        return Resp(routine_resp=True)

    # Case 3: Username taken by someone else
    return Resp(routine_resp=False)


# --- SOCKET & ROOM UTILS ---


def genRoomId():
    chars = "ABCDEFGHIJKLMNPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for x in range(6))


def letter_to_idx(letter: str) -> int:
    return ord(letter.lower()) - 96


@execute_action(filename="rooms.json")
def get_room_config(rooms, room_id):
    if room_id in rooms:
        return Resp(
            routine_resp={
                "categories": rooms[room_id].get("categories", []),
                "allowed_letters": rooms[room_id].get(
                    "allowed_letters", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                ),
            }
        )


@execute_action(filename="rooms.json")
def addToRoom(rooms: dict, room_id: str, player: str) -> None:
    if room_id in rooms:
        if player not in rooms[room_id]["players"]:
            rooms[room_id]["players"].append(player)
            if "player_to_pos" not in rooms[room_id]:
                rooms[room_id]["player_to_pos"] = {}
            rooms[room_id]["player_to_pos"][player] = len(rooms[room_id]["players"]) - 1
        rooms[room_id]["last_interaction"] = time.time()
        return Resp(file_json=rooms)


@execute_action(filename="rooms.json")
def indexRoom(rooms, room_id, categories=None, allowed_letters=None):
    if not categories:
        categories = ["Name", "Animal", "Place", "Thing"]
    if not allowed_letters:
        allowed_letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    rooms[room_id] = {
        "ptr": 0,
        "pos": 0,
        "curr_ans_count": 0,
        "players": [],
        "letters": [],
        "allowed_letters": allowed_letters,
        "categories": categories,
        "turn_player": None,
        "player_to_pos": {},
        "round_answers": {},
        "player_to_score": {},
        "game_started": False,
        "last_interaction": time.time(),
    }
    return Resp(file_json=rooms)


@execute_action(filename="rooms.json")
def set_turn_player(rooms, room_id, player):
    if room_id in rooms:
        rooms[room_id]["turn_player"] = player
        return Resp(file_json=rooms)


@execute_action(filename="rooms.json")
def get_turn_player(rooms, room_id):
    if room_id in rooms:
        return Resp(routine_resp=rooms[room_id].get("turn_player"))


@execute_action(filename="rooms.json")
def set_room_mode(rooms, room_id):
    if room_id in rooms:
        rooms[room_id]["game_started"] = True
        return Resp(file_json=rooms)


@execute_action(filename="rooms.json")
def get_players(rooms, room_id):
    if room_id in rooms:
        return Resp(routine_resp=rooms[room_id]["players"])


@execute_action(filename="rooms.json")
def removeFromRoom(rooms, room_id: str, player: str) -> None:
    if room_id in rooms:
        if player in rooms[room_id]["players"]:
            rooms[room_id]["players"].remove(player)
        rooms[room_id]["last_interaction"] = time.time()
        return Resp(file_json=rooms)


def is_in_session(room_id):
    rooms = getFile("rooms.json")
    if room_id in rooms:
        return rooms[room_id]["game_started"]


@execute_action(filename="player_to_rooms.json")
def map_player_to_room(sess_to_room, player: str, room_id: str) -> None:
    sess_to_room[player] = room_id
    return Resp(file_json=sess_to_room)


@execute_action(filename="player_to_rooms.json")
def get_player_room(sess_to_room, player: str) -> [str | None]:
    if player in sess_to_room:
        return Resp(routine_resp=sess_to_room[player])


@execute_action(filename="rooms.json")
def get_player_turn(rooms, room_id: str) -> str:
    if room_id in rooms:
        room = rooms[room_id]
        if not room["players"]:
            return Resp(routine_resp=None)

        # Safe pointer handling
        if "ptr" not in room:
            room["ptr"] = 0
        if room["ptr"] >= len(room["players"]):
            room["ptr"] = 0

        player = room["players"][room["ptr"]]
        room["ptr"] = (room["ptr"] + 1) % len(room["players"])
        return Resp(file_json=rooms, routine_resp=player)


# --- SID MAPPINGS ---


@execute_action(filename="player_to_sid.json")
def store_sid(player_to_sids, player: str, sid: str) -> None:
    player_to_sids[player] = sid
    return Resp(file_json=player_to_sids)


@execute_action(filename="sid_to_players.json")
def store_sid_to_username(sid_to_player, username: str, sid: str) -> None:
    sid_to_player[sid] = username
    return Resp(file_json=sid_to_player)


@execute_action(filename="player_to_sid.json")
def remove_sid_if_matches(player_to_sids, player, sid_to_remove):
    """Safe remove: Only delete if the SID matches the disconnecting one."""
    if player in player_to_sids:
        if player_to_sids[player] == sid_to_remove:
            del player_to_sids[player]
            return Resp(file_json=player_to_sids, routine_resp=True)
    return Resp(routine_resp=False)


def get_sid(player: str) -> str:
    player_to_sids = getFile("player_to_sid.json")
    return player_to_sids.get(player)


def get_user_from_sid(sid: str) -> str:
    sid_to_players = getFile("sid_to_players.json")
    return sid_to_players.get(sid)


# --- GAMEPLAY LOGIC ---


@execute_action(filename="rooms.json")
def cross_letter(rooms, room_id: str, letter: str) -> None:
    if room_id in rooms:
        idx = letter_to_idx(letter)
        rooms[room_id]["letters"].append(idx)
        return Resp(file_json=rooms)


def get_used_letters(room_id: str) -> [str]:
    rooms = getFile("rooms.json")
    if room_id in rooms:
        return rooms[room_id]["letters"]


def clean_rooms():
    """Removes stale rooms (> 5 mins inactivity)"""
    print("Cron job active: Cleaning the rooms")
    lock.acquire_write()
    try:
        tmp_rooms = {}
        if os.path.exists("rooms.json"):
            with open("rooms.json") as fp:
                rooms = json.load(fp)
                for room in rooms:
                    diff = time.time() - rooms[room]["last_interaction"]
                    if diff < 300:
                        tmp_rooms[room] = rooms[room]
            with open("rooms.json", "w") as fp:
                json.dump(tmp_rooms, fp)
    finally:
        lock.release_write()


# --- VALIDATION LOGIC ---


def is_name(name):
    try:
        name = name.strip().title()
        result = nd.search(name)
        return bool(result.get("first_name") or result.get("last_name"))
    except Exception:
        return False


def is_valid_word(word):
    return word.lower() in word_list


def is_animal(word):
    try:
        base_path = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(base_path, "animals_names.txt")
        with open(file_path, "r") as fp:
            return word.lower() in fp.read().lower()
    except Exception as e:
        print(f"Error checking animal: {e}")
        return False


def is_place(name):
    try:
        return geolocator.geocode(name, timeout=2) is not None
    except (GeocoderTimedOut, GeocoderUnavailable):
        return False
    except Exception:
        return False


def get_answer_validity(answers, letter):
    func_mappings = {
        "Name": is_name,
        "Animal": is_animal,
        "Thing": is_valid_word,
        "Place": is_place,
    }
    report = {}
    target_letter = letter.lower()

    for category, word in answers.items():
        clean_word = word.strip()
        if not clean_word:
            continue

        # 1. Start Letter Check
        if not clean_word.lower().startswith(target_letter):
            report[category] = {"word": clean_word, "status": "invalid"}
            continue

        # 2. Category Check
        if category in func_mappings:
            try:
                is_valid = func_mappings[category](clean_word)
                status = "valid" if is_valid else "needs_vote"
            except Exception:
                status = "needs_vote"
            report[category] = {"word": clean_word, "status": status}
        else:
            # Custom Category -> Always Vote
            report[category] = {"word": clean_word, "status": "needs_vote"}

    return report


@execute_action(filename="rooms.json")
def commit_round_scores(rooms, room_id, final_scores):
    if room_id in rooms:
        room = rooms[room_id]
        if "player_to_score" not in room:
            room["player_to_score"] = {}

        for player, points in final_scores.items():
            if player not in room["player_to_score"]:
                room["player_to_score"][player] = 0
            room["player_to_score"][player] += points

        room["round_answers"] = {}
        room["last_interaction"] = time.time()
        return Resp(file_json=rooms, routine_resp=room["player_to_score"])
