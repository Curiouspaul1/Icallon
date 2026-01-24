import gevent
from flask import request
from flask_socketio import emit, join_room, leave_room, send
import uuid

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
    is_in_session,
    set_room_mode,
    get_used_letters,
    cross_letter,
    get_answer_validity,
    commit_round_scores,
    get_room_categories,
    get_room_config,
    set_turn_player,
    get_turn_player,
)

# In-memory storage for the active round state
round_states = {}
turn_timers = {}


def start_turn_timer(room_id):
    """Starts a 10s timer to auto-skip turn if no letter is picked."""
    if room_id in turn_timers:
        gevent.kill(turn_timers[room_id])

    turn_timers[room_id] = gevent.spawn_later(10, handle_turn_timeout, room_id)


def cancel_turn_timer(room_id):
    """Cancels the turn timer (e.g., when letter is picked)."""
    if room_id in turn_timers:
        gevent.kill(turn_timers[room_id])
        del turn_timers[room_id]


def handle_turn_timeout(room_id):
    """Executed when timer expires: Skips to next player."""
    try:
        # Notify room
        ioclient.emit(
            "info_toast", {"message": "⏳ Time's up! Skipping turn..."}, to=room_id
        )
        # Clean up timer reference
        if room_id in turn_timers:
            del turn_timers[room_id]
        # Trigger next turn logic
        next_player_turn({"room_id": room_id})
    except Exception as e:
        print(f"Error in turn timeout: {e}")


@ioclient.on("connect")
def connect(auth):
    user_id = session.get("user_id", "")
    if not user_id and (auth and 'username' in auth):
        user_id = auth.get("username", None)
        session["user_id"] = user_id
    if user_id:
        session["client_id"] = request.sid
        store_sid(user_id, request.sid)
    else:
        disconnect("Username not specified on connect")
        return False


@ioclient.on("set-session")
def set_session(data):
    if "session" in data:
        session["user_id"] = data["session"]


@ioclient.on("disconnect")
def disconnect(reason):
    player = session.get("user_id")
    if player:
        room_id = get_player_room(player)
        if room_id:
            removeFromRoom(room_id, player)
            remaining = get_players(room_id)
            if remaining:
                emit("player_left", remaining, to=room_id)
        remove_sid(player)


@ioclient.on("join")
def join(data):
    if "user_id" not in session:
        emit("error", {"message": "Connection lost. Please refresh the page."})
        return
    username = session["user_id"]
    room = data["roomID"]
    players = get_players(room)
    if players is None:
        emit("error", {"message": "Room not found!"})
        return
    if username in players:
        emit("error", {"message": "Name taken!"})
        return
    if is_in_session(room):
        emit("error", {"message": "Game started!"})
        return
    join_room(room)
    addToRoom(room, username)
    map_player_to_room(username, room)
    emit("player_joined", get_players(room), to=room)


@ioclient.on("create")
def new_room(data=None):
    username = session["user_id"]
    roomID = genRoomId()
    cats = None
    alphabet = None
    if data and isinstance(data, dict):
        cats = data.get("categories")
        alphabet = data.get("allowed_letters")
    indexRoom(roomID, categories=cats, allowed_letters=alphabet)
    join_room(roomID)
    addToRoom(roomID, username)
    map_player_to_room(username, roomID)
    emit("game_code", roomID)


@ioclient.on("start")
def start_game(data):
    room_id = data["room_id"]
    all_players = get_players(room_id)
    if len(all_players) < 2:
        emit("cant_start_game", MSG.LOW_PLAYER_COUNT)
        return
    set_room_mode(room_id)
    player = get_player_turn(room_id)
    config = get_room_config(room_id)
    ioclient.emit(
        "game_started",
        {
            "players": all_players,
            "categories": config["categories"],
            "allowed_letters": config["allowed_letters"],
        },
        to=room_id,
    )
    ioclient.emit(
        "private_player_turn",
        {"disabledLetters": get_used_letters(room_id)},
        to=get_sid(player),
    )
    ioclient.emit("public_player_turn", player, to=room_id)
    start_turn_timer(room_id)


@ioclient.on("letter_selected")
def letter_selected(data):
    letter = data["letter"]
    room_id = data["room_id"]
    cancel_turn_timer(room_id)
    turn_player = session["user_id"]

    # Save State
    cross_letter(room_id, letter)
    set_turn_player(room_id, turn_player)  # Save to DB

    # Reset Round State (Memory)
    round_states[room_id] = {
        "answers": {},
        "letter": letter,
        "contested_items": [],
        "votes_cast_count": 0,
    }
    ioclient.emit("letter_chosen", letter, to=room_id)


@ioclient.on("next_player_turn")
def next_player_turn(data):
    room_id = data["room_id"]
    player = get_player_turn(room_id)
    used_letters = get_used_letters(room_id)
    client_id = get_sid(player)

    ioclient.emit(
        "private_player_turn", {"disabledLetters": used_letters}, to=client_id
    )
    ioclient.emit("public_player_turn", player, to=room_id)
    start_turn_timer(room_id)


@ioclient.on("player_answer")
def handle_player_answer(data):
    try:
        player = session["user_id"]
        room_id = data["room_id"]
        state = round_states.get(room_id)
        if not state:
            return

        state["answers"][player] = data["answers"]

        # Check turn player from DB for robustness
        current_turn_player = get_turn_player(room_id)
        if player == current_turn_player:
            print(f"Force submit triggered by {player}")
            emit("force_submit", {}, room=room_id)

        if len(state["answers"]) == len(get_players(room_id)):
            process_validation(room_id)
    except Exception as e:
        print(f"Error in answer handler: {e}")


def process_validation(room_id):
    try:
        state = round_states[room_id]
        letter = state["letter"]
        contested = []
        for player, p_answers in state["answers"].items():
            report = get_answer_validity(p_answers, letter)
            for category, details in report.items():
                if details["status"] == "needs_vote":
                    contested.append(
                        {
                            "id": str(uuid.uuid4()),
                            "player": player,
                            "word": details["word"],
                            "category": category,
                            "votes_yes": 0,
                            "votes_no": 0,
                        }
                    )
        state["contested_items"] = contested
        if contested:
            ioclient.emit("start_voting", contested, room=room_id)
        else:
            finalize_scores(room_id)
    except Exception as e:
        print(f"Error in validation: {e}")


@ioclient.on("cast_votes")
def handle_votes(data):
    room_id = data["room_id"]
    state = round_states.get(room_id)
    if not state:
        return

    # Update counts
    for item in state["contested_items"]:
        if data["votes"].get(item["id"]):
            item["votes_yes"] += 1
        else:
            item["votes_no"] += 1

    # --- NEW: BROADCAST LIVE VOTES ---
    # Send the updated list so clients can see the numbers go up
    ioclient.emit("vote_update", state["contested_items"], room=room_id)
    # ---------------------------------

    state["votes_cast_count"] += 1
    if state["votes_cast_count"] >= len(get_players(room_id)):
        finalize_scores(room_id)


def finalize_scores(room_id):
    state = round_states[room_id]
    letter = state["letter"].lower()
    round_scores = {}

    for player, p_answers in state["answers"].items():
        points = 0
        validity = get_answer_validity(p_answers, letter)

        for cat, details in validity.items():
            is_valid = False

            if details["status"] == "valid":
                is_valid = True
            elif details["status"] == "needs_vote":
                item = next(
                    (
                        x
                        for x in state["contested_items"]
                        if x["player"] == player and x["word"] == details["word"]
                    ),
                    None,
                )
                if item:
                    # Tie-breaker: Yes wins ties (benefit of doubt)
                    if item["votes_yes"] >= item["votes_no"]:
                        is_valid = True

            if is_valid:
                points += 10

        round_scores[player] = points

    all_scores = commit_round_scores(room_id, round_scores)
    del round_states[room_id]

    ioclient.emit("round_result", all_scores, room=room_id)
    gevent.sleep(10)
    next_player_turn({"room_id": room_id})
