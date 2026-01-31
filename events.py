import gevent
from flask import request
from flask_socketio import emit, join_room, leave_room
import uuid

# Note: 'session' import removed as we are replacing it
from extensions import ioclient
from utils import (
    genRoomId,
    addToRoom,
    removeFromRoom,
    get_player_room,
    map_player_to_room,
    indexRoom,
    get_player_turn,
    store_sid,
    remove_sid_if_matches,
    get_players,
    get_sid,
    is_in_session,
    set_room_mode,
    get_used_letters,
    cross_letter,
    get_answer_validity,
    commit_round_scores,
    get_room_config,
    set_turn_player,
    get_turn_player,
    store_sid_to_username,
    get_user_from_sid,
    verify_and_register_user,
)

# In-memory storage for state that doesn't need to persist across server restarts
round_states = {}
turn_timers = {}

# --- TIMERS ---


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
        ioclient.emit(
            "info_toast", {"message": "⏳ Time's up! Skipping turn..."}, to=room_id
        )
        if room_id in turn_timers:
            del turn_timers[room_id]
        next_player_turn({"room_id": room_id})
    except Exception as e:
        print(f"Error in turn timeout: {e}")


# --- CONNECTION HANDLERS ---


@ioclient.on("connect")
def connect(auth):
    # 1. Validate Payload
    if not auth or "username" not in auth or "token" not in auth:
        print("❌ Rejected: Missing auth data")
        return False

    username = auth["username"]
    token = auth["token"]

    # 2. Check "Ownership" via persistent token storage
    is_allowed = verify_and_register_user(username, token)

    if not is_allowed:
        print(f"❌ Rejected {username}: Token mismatch")
        return False

    # 3. Success - Map SID to Username (Reliable Source of Truth)
    store_sid(username, request.sid)
    store_sid_to_username(username, request.sid)

    print(f"✅ Connected: {username}")
    return True


@ioclient.on("disconnect")
def disconnect(reason):
    # Lookup user based on the disconnecting SID (RELIABLE)
    player = get_user_from_sid(request.sid)

    if player:
        room_id = get_player_room(player)
        if room_id:
            removeFromRoom(room_id, player)
            remaining = get_players(room_id)
            if remaining:
                emit("player_left", remaining, to=room_id)

        # Safe remove
        remove_sid_if_matches(player, request.sid)


# --- ROOM HANDLERS ---


@ioclient.on("join")
def join(data):
    # RELIABLE FETCH: Get user from SID
    username = get_user_from_sid(request.sid)

    if not username:
        emit("error", {"message": "Connection lost. Please refresh."})
        return

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
    # RELIABLE FETCH
    username = get_user_from_sid(request.sid)
    if not username:
        return

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
    if not all_players or len(all_players) < 2:
        emit("cant_start_game", {"message": "Need at least 2 players"})
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


@ioclient.on('leave_room')
def handle_leave_room(data):
    room_id = data.get('room_id')
    # Reliable fetch using SID
    player = get_user_from_sid(request.sid)
    if player and room_id:
        # 1. Leave the Socket.IO room channel
        leave_room(room_id)
        # 2. Update the Game Data (Remove player from list)
        removeFromRoom(room_id, player)
        # 3. Notify remaining players
        remaining = get_players(room_id)
        if remaining:
            emit('player_left', remaining, to=room_id)
        # 4. Confirm to the user that they are out
        emit('left_room_success')

# --- GAMEPLAY HANDLERS --
@ioclient.on("letter_selected")
def letter_selected(data):
    letter = data["letter"]
    room_id = data["room_id"]
    cancel_turn_timer(room_id)

    # RELIABLE FETCH
    turn_player = get_user_from_sid(request.sid)

    # Persist State
    cross_letter(room_id, letter)
    set_turn_player(room_id, turn_player)

    # Memory State for active round
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

    ioclient.emit(
        "private_player_turn", {"disabledLetters": used_letters}, to=get_sid(player)
    )

    ioclient.emit("public_player_turn", player, to=room_id)
    start_turn_timer(room_id)


@ioclient.on("player_answer")
def handle_player_answer(data):
    try:
        # RELIABLE FETCH
        player = get_user_from_sid(request.sid)
        room_id = data["room_id"]
        state = round_states.get(room_id)
        if not state:
            return

        state["answers"][player] = data["answers"]

        # If turn player submitted, force everyone else
        current_turn_player = get_turn_player(room_id)
        if player == current_turn_player:
            emit("force_submit", {}, room=room_id)

        # If everyone submitted, validate
        all_players = get_players(room_id)
        if len(state["answers"]) >= len(all_players):
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

    # Tally votes
    for item in state["contested_items"]:
        if data["votes"].get(item["id"]):
            item["votes_yes"] += 1
        else:
            item["votes_no"] += 1

    # Broadcast live updates
    ioclient.emit("vote_update", state["contested_items"], room=room_id)

    state["votes_cast_count"] += 1
    all_players = get_players(room_id)

    if state["votes_cast_count"] >= len(all_players):
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
                    # Tie or Majority YES wins
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
