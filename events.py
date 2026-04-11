import time
import uuid
import gevent
from enum import Enum
from dataclasses import dataclass, field

from flask import request
from flask_socketio import emit, join_room, leave_room

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
    find_available_public_room,
)

# =========================================================
# ROUND STATE
# =========================================================


class RoundPhase(str, Enum):
    PICKING = "picking"
    ANSWERING = "answering"
    VALIDATING = "validating"
    VOTING = "voting"
    LEADERBOARD = "leaderboard"
    FINISHED = "finished"
    GAME_OVER = "game_over"


@dataclass
class RoundState:
    phase: RoundPhase = RoundPhase.PICKING
    phase_id: float = 0.0

    answers: dict = field(default_factory=dict)
    contested_items: list = field(default_factory=list)
    votes_cast_count: int = 0
    scores: dict = field(default_factory=dict)

    timer_start: float | None = None
    timer_duration: int | None = None

    def start_timer(self, duration):
        self.timer_start = time.time()
        self.timer_duration = duration
        self.phase_id = self.timer_start
    
    def time_left(self):
        if not self.timer_start or not self.timer_duration:
            return None
        elapsed = time.time() - self.timer_start
        return max(0, int(self.timer_duration - elapsed))


# =========================================================
# IN MEMORY STORAGE
# =========================================================

round_states: dict[str, RoundState] = {}

turn_timers = {}
voting_timers = {}
answering_timers = {}

# =========================================================
# TIMER HELPERS
# =========================================================


def get_state(room_id):
    return round_states.setdefault(room_id, RoundState())


# ---------------------------------------------------------
# TURN TIMER
# ---------------------------------------------------------


def start_turn_timer(room_id):
    if room_id in turn_timers:
        gevent.kill(turn_timers[room_id])

    state = get_state(room_id)
    state.phase = RoundPhase.PICKING
    state.start_timer(10)

    # Pass the unique phase_id to the background thread
    turn_timers[room_id] = gevent.spawn_later(
        10, handle_turn_timeout, room_id, state.phase_id
    )


def cancel_turn_timer(room_id):
    if room_id in turn_timers:
        gevent.kill(turn_timers[room_id])
        del turn_timers[room_id]


def handle_turn_timeout(room_id, expected_phase_id):
    try:
        state = round_states.get(room_id)
        # 🛡️ THE KILL SWITCH: If the ID changed, silently die.
        if not state or state.phase_id != expected_phase_id:
            return

        ioclient.emit(
            "info_toast",
            {"message": "⏳ Time's up! Skipping turn..."},
            to=room_id,
        )

        if room_id in turn_timers:
            del turn_timers[room_id]

        next_player_turn({"room_id": room_id})

    except Exception as e:
        print(f"Error in turn timeout: {e}")


# ---------------------------------------------------------
# ANSWERING TIMER
# ---------------------------------------------------------


def start_answering_timer(room_id):
    if room_id in answering_timers:
        gevent.kill(answering_timers[room_id])

    state = get_state(room_id)

    state.phase = RoundPhase.ANSWERING
    state.start_timer(35)

    answering_timers[room_id] = gevent.spawn_later(
        35, handle_answering_timeout, room_id, state.phase_id
    )


def cancel_answering_timer(room_id):
    if room_id in answering_timers:
        gevent.kill(answering_timers[room_id])
        del answering_timers[room_id]


def handle_answering_timeout(room_id, expected_phase_id):
    try:
        state = round_states.get(room_id)
        # 🛡️ THE KILL SWITCH: If the ID changed, silently die.
        if not state or state.phase_id != expected_phase_id:
            return

        if room_id in answering_timers:
            del answering_timers[room_id]

        print(f"⏰ Answering timeout for room {room_id}")

        ioclient.emit(
            "info_toast",
            {"message": "⏳ Time's up! Collecting answers..."},
            to=room_id,
        )

        process_validation(room_id)

    except Exception as e:
        print(f"Error in answering timeout: {e}")


# ---------------------------------------------------------
# VOTING TIMER
# ---------------------------------------------------------


def start_voting_timer(room_id):
    if room_id in voting_timers:
        gevent.kill(voting_timers[room_id])

    state = get_state(room_id)

    state.phase = RoundPhase.VOTING
    state.start_timer(30)

    voting_timers[room_id] = gevent.spawn_later(
        30, handle_voting_timeout, room_id, state.phase_id
    )


def cancel_voting_timer(room_id):
    if room_id in voting_timers:
        gevent.kill(voting_timers[room_id])
        del voting_timers[room_id]


def handle_voting_timeout(room_id, expected_phase_id):
    try:
        state = round_states.get(room_id)
        # 🛡️ THE KILL SWITCH: If the ID changed, silently die.
        if not state or state.phase_id != expected_phase_id:
            return

        if room_id in voting_timers:
            del voting_timers[room_id]

        ioclient.emit(
            "info_toast",
            {"message": "⏳ Voting Time's Up!"},
            to=room_id,
        )

        finalize_scores(room_id)

    except Exception as e:
        print(f"Error in voting timeout: {e}")


# =========================================================
# CONNECTION HANDLERS
# =========================================================


@ioclient.on("connect")
def connect(auth):

    if not auth or "username" not in auth or "token" not in auth:
        return False

    username = auth["username"]
    token = auth["token"]

    if not verify_and_register_user(username, token):
        return False

    store_sid(username, request.sid)
    store_sid_to_username(username, request.sid)

    room_id = get_player_room(username)

    # -------------------------------------------------
    # USER NOT IN ANY ROOM
    # -------------------------------------------------

    if not room_id:
        ioclient.emit("show_home_screen", to=request.sid)
        print(f"✅ Connected (home): {username}")
        return True

    players = get_players(room_id)

    if not players:
        ioclient.emit("show_home_screen", to=request.sid)
        return True

    join_room(room_id)

    config = get_room_config(room_id)
    game_started = is_in_session(room_id)
    turn_player = get_turn_player(room_id)
    used_letters = get_used_letters(room_id)

    state = round_states.get(room_id)

    # -------------------------------------------------
    # DEFAULT VALUES (LOBBY OR BETWEEN ROUNDS)
    # -------------------------------------------------

    phase = "picking"
    letter = None
    voting_data = []
    time_left = None
    total_duration = None
    scores = {}

    # -------------------------------------------------
    # IF ROUND STATE EXISTS
    # -------------------------------------------------
    if not state and game_started:
        # 🚑 SERVER RESTARTED MID-GAME: RAM is wiped but game is active.
        # We must kickstart the round again so the room doesn't freeze!
        start_turn_timer(room_id)
        state = round_states.get(room_id)
        print(f"🔄 Recovered ghost state for room {room_id}")

    if state:
        phase = state.phase.value
        letter = state.letter
        voting_data = state.contested_items
        time_left = state.time_left()
        total_duration = state.timer_duration

        if state.phase == RoundPhase.LEADERBOARD:
            scores = state.scores

    # -------------------------------------------------
    # BUILD RESTORE PAYLOAD
    # -------------------------------------------------

    payload = {
        "room_id": room_id,
        "game_started": game_started,
        "players": players,
        "is_host": players[0] == username,
        "categories": config["categories"],
        "allowed_letters": config["allowed_letters"],
        "turn_player": turn_player,
        "used_letters": used_letters,
        "current_state": phase,
        "current_letter": letter,
        "voting_data": voting_data,
        "time_left": time_left,
        "total_duration": total_duration,
        "scores": scores,
    }

    ioclient.emit("restore_session", payload, to=request.sid)

    print(f"✅ Connected (restored): {username}")
    return True


@ioclient.on("disconnect")
def disconnect(reason):

    player = get_user_from_sid(request.sid)

    if player:
        remove_sid_if_matches(player, request.sid)


# =========================================================
# ROOM HANDLERS
# =========================================================


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

    if len(players) >= 8:
        emit("error", {"message": "Room is full (Max 8 players)!"})
        return

    join_room(room)

    addToRoom(room, username)
    map_player_to_room(username, room)

    emit("player_joined", get_players(room), to=room)


@ioclient.on("join_public")
def handle_join_public():
    username = get_user_from_sid(request.sid)
    if not username:
        return

    # 1. Try to find an existing open public room
    room_id = find_available_public_room()

    # 2. If no open public room exists, create a brand new one
    if not room_id:
        room_id = genRoomId()
        # Mark it as public!
        indexRoom(room_id, is_public=True)

    # 3. Add the player to the room
    join_room(room_id)
    addToRoom(room_id, username)
    map_player_to_room(username, room_id)

    players = get_players(room_id)

    # If they are the only player in the room, they are the Host
    is_host = len(players) == 1

    # 4. Tell the joining player they successfully joined
    emit(
        "public_room_found",
        {"room_id": room_id, "is_host": is_host, "players": players},
    )

    # 5. Tell everyone else in the lobby that a new player joined
    emit("player_joined", players, to=room_id)


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


# =========================================================
# GAMEPLAY
# =========================================================


@ioclient.on("start")
def start_game(data):

    room_id = data["room_id"]

    players = get_players(room_id)

    if not players or len(players) < 2:
        emit("cant_start_game", {"message": "Need at least 2 players"})
        return

    set_room_mode(room_id)

    player = get_player_turn(room_id)
    set_turn_player(room_id, player)
    config = get_room_config(room_id)

    ioclient.emit(
        "game_started",
        {
            "players": players,
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


@ioclient.on("next_player_turn")
def next_player_turn(data):
    room_id = data["room_id"]
    player = get_player_turn(room_id)
    set_turn_player(room_id, player)

    used_letters = get_used_letters(room_id)
    player_sid = get_sid(player)

    if player_sid:
        ioclient.emit(
            "private_player_turn", {"disabledLetters": used_letters}, to=player_sid
        )

    ioclient.emit("public_player_turn", player, to=room_id)
    start_turn_timer(room_id)


@ioclient.on("leave_room")
def handle_leave_room(data):
    room_id = data.get("room_id")
    player = get_user_from_sid(request.sid)

    if player and room_id:
        # 1. Unsubscribe them from the socket broadcasts
        leave_room(room_id)

        # 2. Remove them from the room's database/JSON
        removeFromRoom(room_id, player)

        # 3. Tell everyone else in the room that they left
        remaining_players = get_players(room_id)
        if remaining_players:
            emit("player_left", remaining_players, to=room_id)

        # 4. Confirm success to the person who left
        emit("left_room_success", to=request.sid)


# =========================================================
# LETTER SELECTED
# =========================================================


@ioclient.on("letter_selected")
def letter_selected(data):

    letter = data["letter"]
    room_id = data["room_id"]

    cancel_turn_timer(room_id)
    turn_player = get_user_from_sid(request.sid)
    cross_letter(room_id, letter)
    set_turn_player(room_id, turn_player)

    state = get_state(room_id)

    state.phase = RoundPhase.ANSWERING
    state.letter = letter
    state.answers.clear()
    state.contested_items.clear()
    state.votes_cast_count = 0

    start_answering_timer(room_id)

    ioclient.emit("letter_chosen", letter, to=room_id)


# =========================================================
# PLAYER ANSWERS
# =========================================================


@ioclient.on("player_answer")
def handle_player_answer(data):

    player = get_user_from_sid(request.sid)
    room_id = data["room_id"]

    state = round_states.get(room_id)

    if not state or state.phase != RoundPhase.ANSWERING:
        return

    state.answers[player] = data["answers"]
    current_turn_player = get_turn_player(room_id)
    if player == current_turn_player:
        ioclient.emit("force_submit", {}, to=room_id)

    players = get_players(room_id)

    if len(state.answers) >= len(players):
        process_validation(room_id)


# =========================================================
# VALIDATION
# =========================================================


def process_validation(room_id):

    cancel_answering_timer(room_id)

    state = round_states.get(room_id)

    if not state or state.phase != RoundPhase.ANSWERING:
        return

    state.phase = RoundPhase.VALIDATING

    letter = state.letter
    contested = []

    for player, p_answers in state.answers.items():

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

    state.contested_items = contested

    if contested:

        start_voting_timer(room_id)

        ioclient.emit("start_voting", contested, room=room_id)

    else:

        finalize_scores(room_id)


# =========================================================
# VOTING
# =========================================================


@ioclient.on("cast_votes")
def handle_votes(data):

    room_id = data["room_id"]
    state = round_states.get(room_id)

    if not state or state.phase != RoundPhase.VOTING:
        return

    votes = data.get("votes", {})

    for item_id, vote_value in votes.items():

        item = next(
            (x for x in state.contested_items if x["id"] == item_id),
            None,
        )

        if item:

            if vote_value:
                item["votes_yes"] += 1
            else:
                item["votes_no"] += 1

    ioclient.emit("vote_update", state.contested_items, room=room_id)

    state.votes_cast_count += 1

    players = get_players(room_id)

    if state.votes_cast_count >= len(players):
        finalize_scores(room_id)


# =========================================================
# SCORING
# =========================================================


def finalize_scores(room_id):

    state = round_states.get(room_id)

    if not state:
        return

    cancel_voting_timer(room_id)

    if state.phase == RoundPhase.FINISHED:
        return

    state.phase = RoundPhase.FINISHED

    letter = state.letter.lower()
    round_scores = {}

    for player, answers in state.answers.items():

        points = 0
        validity = get_answer_validity(answers, letter)

        for cat, details in validity.items():

            is_valid = False

            if details["status"] == "valid":
                is_valid = True

            elif details["status"] == "needs_vote":

                item = next(
                    (
                        x
                        for x in state.contested_items
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

    state.phase = RoundPhase.LEADERBOARD
    state.scores = all_scores
    state.start_timer(10)

    ioclient.emit("round_result", all_scores, room=room_id)

    # REPLACED: gevent.sleep(10) with a non-blocking background task
    gevent.spawn_later(10, trigger_next_round, room_id, state.phase_id)


# NEW HELPER FUNCTION
def trigger_next_round(room_id, expected_phase_id):
    state = round_states.get(room_id)
    if not state or state.phase_id != expected_phase_id:
        return

    config = get_room_config(room_id)
    used_letters = get_used_letters(room_id)

    # --- NEW: EXHAUSTION CHECK ---
    # If the number of used letters equals or exceeds the total allowed letters...
    if len(used_letters) >= len(config["allowed_letters"]):
        state.phase = RoundPhase.GAME_OVER
        state.phase_id = time.time()  # New Epoch ID for the self-destruct timer

        ioclient.emit("game_over", {"scores": state.scores}, to=room_id)

        # Start the 30-second self-destruct sequence
        gevent.spawn_later(30, auto_destroy_room, room_id, state.phase_id)
    else:
        # Game continues!
        next_player_turn({"room_id": room_id})


def auto_destroy_room(room_id, expected_phase_id):
    state = round_states.get(room_id)
    # Check if the host already restarted the game or ended it manually
    if not state or state.phase_id != expected_phase_id:
        return

    ioclient.emit(
        "room_destroyed", {"message": "Room closed due to inactivity."}, to=room_id
    )
    # Cleanup memory
    if room_id in round_states:
        del round_states[room_id]


@ioclient.on("force_end_game")
def force_end_game(data):
    room_id = data["room_id"]
    username = get_user_from_sid(request.sid)
    players = get_players(room_id)

    # Only the host (player index 0) can end the game
    if players and players[0] == username:
        ioclient.emit(
            "room_destroyed", {"message": "Host ended the match."}, to=room_id
        )
        if room_id in round_states:
            del round_states[room_id]


@ioclient.on("restart_game")
def restart_game(data):
    room_id = data["room_id"]
    username = get_user_from_sid(request.sid)
    players = get_players(room_id)

    if players and players[0] == username:
        # 1. Kill the self-destruct timer by changing the phase_id
        state = get_state(room_id)
        state.phase_id = time.time()

        # 2. Reset the backend game data
        config = get_room_config(room_id)
        # NOTE: You will need to add a function in utils.py called `clear_used_letters(room_id)`
        # or manually reset the letters crossed off in your JSON here!

        # 3. Tell everyone to jump back to the picking phase
        ioclient.emit(
            "game_started",
            {
                "players": players,
                "categories": config["categories"],
                "allowed_letters": config["allowed_letters"],
            },
            to=room_id,
        )

        # 4. Start the game loop
        next_player_turn({"room_id": room_id})
