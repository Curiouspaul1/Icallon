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

# In-memory storage
round_states = {}
turn_timers = {}
voting_timers = {}
answering_timers = {}  # NEW: Timer for the typing phase

# --- TIMERS ---


def start_turn_timer(room_id):
    """Starts a 10s timer to pick a letter."""
    if room_id in turn_timers:
        gevent.kill(turn_timers[room_id])
    turn_timers[room_id] = gevent.spawn_later(10, handle_turn_timeout, room_id)


def cancel_turn_timer(room_id):
    if room_id in turn_timers:
        gevent.kill(turn_timers[room_id])
        del turn_timers[room_id]


def handle_turn_timeout(room_id):
    try:
        ioclient.emit(
            "info_toast", {"message": "⏳ Time's up! Skipping turn..."}, to=room_id
        )
        if room_id in turn_timers:
            del turn_timers[room_id]
        next_player_turn({"room_id": room_id})
    except Exception as e:
        print(f"Error in turn timeout: {e}")


# --- NEW: ANSWERING TIMER ---


def start_answering_timer(room_id):
    """Starts a 35s timer for the answering phase (30s typing + 5s buffer)."""
    if room_id in answering_timers:
        gevent.kill(answering_timers[room_id])
    answering_timers[room_id] = gevent.spawn_later(
        35, handle_answering_timeout, room_id
    )


def cancel_answering_timer(room_id):
    if room_id in answering_timers:
        gevent.kill(answering_timers[room_id])
        del answering_timers[room_id]


def handle_answering_timeout(room_id):
    """If time runs out, force validation with whatever answers we have."""
    try:
        if room_id in answering_timers:
            del answering_timers[room_id]

        # Only proceed if we are currently in the 'answering' phase
        state = round_states.get(room_id)
        if state and state.get("status") == "answering":
            print(f"⏰ Answering timeout for room {room_id}. Forcing validation.")
            ioclient.emit(
                "info_toast",
                {"message": "⏳ Time's up! Collecting answers..."},
                to=room_id,
            )
            process_validation(room_id)
    except Exception as e:
        print(f"Error in answering timeout: {e}")


# --- VOTING TIMER ---


def start_voting_timer(room_id):
    if room_id in voting_timers:
        gevent.kill(voting_timers[room_id])
    voting_timers[room_id] = gevent.spawn_later(30, handle_voting_timeout, room_id)


def cancel_voting_timer(room_id):
    if room_id in voting_timers:
        gevent.kill(voting_timers[room_id])
        del voting_timers[room_id]


def handle_voting_timeout(room_id):
    """Forces the round to end if voting takes too long."""
    try:
        if room_id in voting_timers:
            del voting_timers[room_id]
        if room_id in round_states:
            ioclient.emit("info_toast", {"message": "⏳ Voting Time's Up!"}, to=room_id)
            finalize_scores(room_id)
    except Exception as e:
        print(f"Error in voting timeout: {e}")


# --- CONNECTION HANDLERS ---
@ioclient.on("connect")
def connect(auth):
    if not auth or "username" not in auth or "token" not in auth:
        return False

    username = auth["username"]
    token = auth["token"]

    is_allowed = verify_and_register_user(username, token)
    if not is_allowed:
        return False

    store_sid(username, request.sid)
    store_sid_to_username(
        username, request.sid
    )  # FIXED: Argument order was flipped in your snippet

    # --- RESILIENCE LOGIC ---
    existing_room = get_player_room(username)
    if existing_room:
        players = get_players(existing_room)
        if players:
            join_room(existing_room)
            game_started = is_in_session(existing_room)
            config = get_room_config(existing_room)

            # DETERMINE CURRENT STATE
            current_state = "idle"
            voting_data = []
            current_letter = None

            if existing_room in round_states:
                state = round_states[existing_room]
                current_state = state.get("status", "idle")
                current_letter = state.get("letter")
                if current_state == "voting":
                    voting_data = state.get("contested_items", [])

            ioclient.emit(
                "restore_session",
                {
                    "room_id": existing_room,
                    "game_started": game_started,
                    "players": players,
                    "is_host": (players[0] == username),
                    "current_state": current_state,
                    "current_letter": current_letter,  # <--- NEW
                    "turn_player": get_turn_player(existing_room),  # <--- NEW
                    "used_letters": get_used_letters(existing_room),  # <--- NEW
                    "voting_data": voting_data,
                    "categories": config["categories"],
                    "allowed_letters": config["allowed_letters"],
                },
                to=request.sid,
            )
        else:
            ioclient.emit('show_home_screen', to=request.sid)
    print(f"✅ Connected: {username}")
    return True


@ioclient.on("disconnect")
def disconnect(reason):
    player = get_user_from_sid(request.sid)
    if player:
        remove_sid_if_matches(player, request.sid)


# --- ROOM HANDLERS (Unchanged) ---
@ioclient.on("join")
def join(data):
    username = get_user_from_sid(request.sid)
    if not username:
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
    username = get_user_from_sid(request.sid)
    if not username:
        return
    roomID = genRoomId()
    cats = data.get("categories") if data else None
    alphabet = data.get("allowed_letters") if data else None
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

    player_sid = get_sid(player)
    if player_sid:
        ioclient.emit(
            "private_player_turn",
            {"disabledLetters": get_used_letters(room_id)},
            to=player_sid,
        )
    ioclient.emit("public_player_turn", player, to=room_id)
    start_turn_timer(room_id)


@ioclient.on("leave_room")
def handle_leave_room(data):
    room_id = data.get("room_id")
    player = get_user_from_sid(request.sid)
    if player and room_id:
        leave_room(room_id)
        removeFromRoom(room_id, player)
        remaining = get_players(room_id)
        if remaining:
            emit("player_left", remaining, to=room_id)
        emit("left_room_success")


# --- GAMEPLAY HANDLERS ---


@ioclient.on("letter_selected")
def letter_selected(data):
    letter = data["letter"]
    room_id = data["room_id"]
    cancel_turn_timer(room_id)

    # NEW: Start the safety timer for answering
    start_answering_timer(room_id)

    turn_player = get_user_from_sid(request.sid)
    cross_letter(room_id, letter)
    set_turn_player(room_id, turn_player)

    round_states[room_id] = {
        "status": "answering",  # NEW: State tracking
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
    player_sid = get_sid(player)
    if player_sid:
        ioclient.emit(
            "private_player_turn", {"disabledLetters": used_letters}, to=player_sid
        )
    ioclient.emit("public_player_turn", player, to=room_id)
    start_turn_timer(room_id)


@ioclient.on("player_answer")
def handle_player_answer(data):
    try:
        player = get_user_from_sid(request.sid)
        room_id = data["room_id"]
        state = round_states.get(room_id)

        # NEW: Ignore answers if we aren't in answering phase (e.g. timeout already hit)
        if not state or state.get("status") != "answering":
            return

        state["answers"][player] = data["answers"]

        current_turn_player = get_turn_player(room_id)
        if player == current_turn_player:
            emit("force_submit", {}, room=room_id)

        all_players = get_players(room_id)
        if len(state["answers"]) >= len(all_players):
            process_validation(room_id)

    except Exception as e:
        print(f"Error in answer handler: {e}")


def process_validation(room_id):
    try:
        # Stop the answering timer immediately
        cancel_answering_timer(room_id)

        state = round_states.get(room_id)
        if not state or state.get("status") != "answering":
            return

        # Lock state so we don't validate twice
        state["status"] = "validating"

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

        if state["contested_items"]:
            state["status"] = "voting"  # Update state
            start_voting_timer(room_id)
            ioclient.emit("start_voting", contested, room=room_id)
        else:
            finalize_scores(room_id)

    except Exception as e:
        print(f"Error in validation: {e}")


@ioclient.on("cast_votes")
def handle_votes(data):
    room_id = data["room_id"]
    state = round_states.get(room_id)

    # CRASH FIX: Check if state still exists and matches
    if not state or state.get("status") != "voting":
        return

    incoming_votes = data.get("votes", {})
    for item_id, vote_value in incoming_votes.items():
        item = next((x for x in state["contested_items"] if x["id"] == item_id), None)
        if item:
            if vote_value:
                item["votes_yes"] += 1
            else:
                item["votes_no"] += 1

    ioclient.emit("vote_update", state["contested_items"], room=room_id)

    state["votes_cast_count"] += 1
    all_players = get_players(room_id)

    if state["votes_cast_count"] >= len(all_players):
        finalize_scores(room_id)


def finalize_scores(room_id):
    if room_id not in round_states:
        return

    cancel_voting_timer(room_id)

    state = round_states[room_id]
    # Check if we already finished (paranoid check)
    if state.get("status") == "finished":
        return

    state["status"] = "finished"  # Lock it

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
                if item and item["votes_yes"] >= item["votes_no"]:
                    is_valid = True
            if is_valid:
                points += 10
        round_scores[player] = points

    all_scores = commit_round_scores(room_id, round_scores)
    round_states.pop(room_id, None)

    ioclient.emit("round_result", all_scores, room=room_id)
    gevent.sleep(10)
    next_player_turn({"room_id": room_id})
