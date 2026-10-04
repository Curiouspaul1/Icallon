import random
import time
import uuid
import gevent
from enum import Enum
from dataclasses import dataclass, field

from flask import request
from flask_socketio import emit, join_room, leave_room, ConnectionRefusedError

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
    clear_used_letters,
    delete_room,
    unmap_player_from_room,
    remove_sid_to_username,
    get_open_public_rooms,
    letter_to_idx,
    reset_sid_maps,
)

from bots import (
    DIFFICULTY,
    DEFAULT_DIFFICULTY,
    is_bot,
    make_bot_names,
    pick_solo_letters,
    plan_answers,
    answers_ready,
)

# =========================================================
# ROUND STATE
# =========================================================

# Sockets from a previous run are gone; start with clean sid maps.
reset_sid_maps()


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
    letter: str | None = None
    validity_reports: dict = field(default_factory=dict)

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
room_destroy_timers = {}

# =========================================================
# TIMER HELPERS
# =========================================================


def get_state(room_id):
    return round_states.setdefault(room_id, RoundState())


def _connected_count(room_id):
    """How many of this room's players currently have a live socket."""
    players = get_players(room_id) or []
    return sum(1 for p in players if get_sid(p))


def _bots_in(room_id):
    return [p for p in (get_players(room_id) or []) if is_bot(p)]


def _participant_count(room_id):
    """Everyone who will hand in answers this round: connected humans plus
    bots. (_connected_count stays humans-only on purpose: it decides
    whether a room is alive, and bots must never keep a room alive.)"""
    return _connected_count(room_id) + len(_bots_in(room_id))


def _only_bots_left(room_id):
    players = get_players(room_id)
    return bool(players) and all(is_bot(p) for p in players)


HOST_STABLE_SECS = 30
connected_since = {}  # username -> time their current socket connected
room_hosts = {}  # room_id -> who is acting host right now


def _is_stable(player, now):
    since = connected_since.get(player)
    return since is not None and now - since >= HOST_STABLE_SECS


def _host_of(room_id, players=None):
    """Who is host right now.

    Roster order is the order of entitlement: the creator first, then
    whoever joined next. The role goes to the highest-ranked player who is
    online AND has been online for HOST_STABLE_SECS. Until someone
    qualifies, whoever is already acting host keeps it; if they're gone
    too, the first online player covers.

    So: creator drops -> next online player is promoted at once. Creator
    returns -> the stand-in keeps the role until the creator has stayed
    connected for 30s, then it goes back.
    """
    if players is None:
        players = get_players(room_id) or []
    if not players:
        room_hosts.pop(room_id, None)
        return None

    online = [p for p in players if get_sid(p)]
    if not online:
        # Nobody to act; nominally the top of the roster.
        return players[0]

    now = time.time()
    current = room_hosts.get(room_id)
    host = next((p for p in online if _is_stable(p, now)), None)
    if host is None:
        host = current if current in online else online[0]

    room_hosts[room_id] = host
    return host

def _broadcast_host(room_id):
    """Tell everyone in the room who the host is right now. Sent after
    every roster/connection change so clients never guess."""
    players = get_players(room_id)
    if not players:
        return
    ioclient.emit(
        "host_update",
        {
            "host": _host_of(room_id, players),
            "players": players,
            # Who actually has a live socket. The roster alone can't tell
            # the client whether START should be enabled.
            "connected": [p for p in players if get_sid(p) or is_bot(p)],
        },
        to=room_id,
    )


# A player who drops out of a *lobby* keeps their seat this long, then is
# removed from the roster. (Mid-game drops keep their seat; turns skip them.)
LOBBY_GHOST_GRACE = 120
lobby_drop_marks = {}  # username -> time they dropped


def _prune_lobby_ghosts(room_id):
    """Remove lobby players who dropped more than LOBBY_GHOST_GRACE ago and
    never came back. Only runs while somebody live is in the room; a fully
    empty lobby is handled by schedule_room_destroy instead."""
    if is_in_session(room_id) or _connected_count(room_id) == 0:
        return

    now = time.time()
    removed = False
    for p in list(get_players(room_id) or []):
        if get_sid(p):
            lobby_drop_marks.pop(p, None)
            continue
        dropped_at = lobby_drop_marks.get(p)
        # No mark means they dropped before a restart: treat as expired.
        if dropped_at is None or now - dropped_at >= LOBBY_GHOST_GRACE:
            removeFromRoom(room_id, p)
            if get_player_room(p) == room_id:
                unmap_player_from_room(p)
            lobby_drop_marks.pop(p, None)
            removed = True
            print(f"👻 Pruned {p} from lobby {room_id}")

    if removed:
        ioclient.emit("player_left", get_players(room_id), to=room_id)
        _broadcast_host(room_id)


def _leave_previous_room(username, new_room_id=None):
    """Detach a player from whatever room they were last mapped to, before
    they join or create a different one. Without this, creating/joining a
    new room leaves the player still subscribed to the old room's
    Socket.IO broadcast group AND still listed in its roster — so the old
    room never registers as empty, its timers never get torn down, and
    its stale events keep arriving on this client even after they've
    moved on to a different room."""
    old_room_id = get_player_room(username)
    if not old_room_id or old_room_id == new_room_id:
        return

    leave_room(old_room_id)
    removeFromRoom(old_room_id, username)

    if _only_bots_left(old_room_id):
        # Solo room and its human just moved on: nothing left to wait for.
        _teardown_room(old_room_id)
        return

    remaining = get_players(old_room_id)
    if remaining:
        emit("player_left", remaining, to=old_room_id)
        _broadcast_host(old_room_id)

    if _connected_count(old_room_id) == 0:
        schedule_room_destroy(old_room_id)


def _teardown_room(room_id):
    """Fully removes a room: gameplay timers, in-memory state, and the
    persisted rooms.json / player_to_rooms.json entries."""
    cancel_turn_timer(room_id)
    cancel_answering_timer(room_id)
    cancel_voting_timer(room_id)

    room_hosts.pop(room_id, None)
    room_bot_level.pop(room_id, None)
    bot_plans.pop(room_id, None)

    timer = room_destroy_timers.get(room_id)
    if timer:
        # Careful: this can be called FROM the destroy-timer's own
        # greenlet (destroy_empty_room -> _teardown_room). Killing the
        # greenlet that's currently executing us would abort this very
        # function before it finishes. Only kill if it's some other
        # (still-pending) greenlet, e.g. when called from
        # force_end_game/auto_destroy_room while a destroy was also queued.
        if timer is not gevent.getcurrent():
            gevent.kill(timer)
        del room_destroy_timers[room_id]

    for player in get_players(room_id) or []:
        unmap_player_from_room(player)

    if room_id in round_states:
        del round_states[room_id]

    delete_room(room_id)
    print(f"🗑️ Room {room_id} torn down")


# How long a room with nobody connected survives. A lobby gets much longer
# than a running game: the creator's socket drops the moment they switch
# apps to share the room code, and 30s isn't enough to paste it in a chat.
EMPTY_GAME_GRACE = 30
EMPTY_LOBBY_GRACE = 300


def schedule_room_destroy(room_id):
    """Room just hit 0 connected players. Give it 30s to come back to life
    before wiping it — also immediately silences any in-flight gameplay
    timers so they don't keep cycling against an empty room."""
    cancel_turn_timer(room_id)
    cancel_answering_timer(room_id)
    cancel_voting_timer(room_id)

    if room_id in room_destroy_timers:
        gevent.kill(room_destroy_timers[room_id])

    state = get_state(room_id)
    state.phase_id = time.time()  # invalidate any timers already in flight

    grace = EMPTY_GAME_GRACE if is_in_session(room_id) else EMPTY_LOBBY_GRACE
    room_destroy_timers[room_id] = gevent.spawn_later(
        grace, destroy_empty_room, room_id, state.phase_id
    )
    print(f"🕒 Room {room_id} is empty — destroying in {grace}s if nobody returns")


def cancel_room_destroy(room_id):
    """Returns True if a destroy was actually pending."""
    if room_id in room_destroy_timers:
        gevent.kill(room_destroy_timers[room_id])
        del room_destroy_timers[room_id]
        print(f"✅ Room {room_id} un-emptied — destroy cancelled")
        return True
    return False


def _resume_round(room_id):
    """schedule_room_destroy() cancels every gameplay timer. If someone then
    comes back, nothing was restarting them, so the game sat frozen on
    whatever phase it was in. Re-arm the timer for the current phase."""
    state = get_state(room_id)

    if state.phase == RoundPhase.ANSWERING and state.letter:
        start_answering_timer(room_id)
        _bots_start_answering(room_id)
    elif state.phase == RoundPhase.VOTING and state.contested_items:
        start_voting_timer(room_id)
    elif state.phase == RoundPhase.LEADERBOARD:
        trigger_next_round(room_id, state.phase_id)
    elif state.phase == RoundPhase.GAME_OVER:
        state.phase_id = time.time()
        gevent.spawn_later(30, auto_destroy_room, room_id, state.phase_id)
    else:
        # Picking (or a server restart wiped RAM): same player, fresh clock.
        start_turn_timer(room_id)
        _bot_take_turn(room_id)
    print(f"🔄 Resumed room {room_id} in phase {state.phase.value}")


def destroy_empty_room(room_id, expected_phase_id):
    try:
        state = round_states.get(room_id)
        if state and state.phase_id != expected_phase_id:
            return  # something happened in this room since we scheduled this
        if _connected_count(room_id) > 0:
            return  # someone came back after all

        ioclient.emit(
            "room_destroyed",
            {"message": "Room closed — everyone left."},
            to=room_id,
        )
        _teardown_room(room_id)
    except Exception as e:
        print(f"Error destroying empty room {room_id}: {e}")


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

        if _connected_count(room_id) == 0:
            schedule_room_destroy(room_id)
            return

        ioclient.emit(
            "info_toast",
            {"message": "⏳ Time's up! Skipping turn..."},
            to=room_id,
        )

        if room_id in turn_timers:
            del turn_timers[room_id]

        _advance_turn(room_id)

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

        if _connected_count(room_id) == 0:
            schedule_room_destroy(room_id)
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

        if _connected_count(room_id) == 0:
            schedule_room_destroy(room_id)
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

    if is_bot(username):
        # Reserved for computer players; nobody may impersonate one.
        raise ConnectionRefusedError("username_taken")

    auth_result = verify_and_register_user(username, token)
    if auth_result is None:
        # execute_action swallowed an exception (file I/O hiccup, etc.) —
        # don't silently treat that the same as "username taken"
        print(f"⚠️ Auth check errored for {username}; rejecting connection")
        return False
    if not auth_result:
        # Give the client a reason it can tell apart from "server is down".
        raise ConnectionRefusedError("username_taken")

    store_sid(username, request.sid)
    connected_since[username] = time.time()
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

    if not players or username not in players:
        # Room is gone, or this player left it earlier and the mapping is
        # stale. Don't drag them back into a room they aren't part of.
        unmap_player_from_room(username)
        ioclient.emit("show_home_screen", to=request.sid)
        return True

    join_room(room_id)
    destroy_was_pending = cancel_room_destroy(room_id)

    ioclient.emit(
        "player_reconnected",
        {"player": username, "players": players},
        to=room_id,
    )

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
    if game_started and (not state or destroy_was_pending):
        # Either the server restarted mid-game (RAM wiped), or everyone
        # dropped and the timers were cancelled. Kickstart the round again
        # so the room doesn't freeze.
        _resume_round(room_id)
        state = round_states.get(room_id)
        turn_player = get_turn_player(room_id)

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
        "is_host": _host_of(room_id, players) == username,
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
    _broadcast_host(room_id)
    # Once this player has been back long enough to count as stable, the
    # host role may be due back to them: re-evaluate and tell the room.
    gevent.spawn_later(HOST_STABLE_SECS + 1, _broadcast_host, room_id)

    print(f"✅ Connected (restored): {username}")
    return True


@ioclient.on("disconnect")
def disconnect(reason):

    player = get_user_from_sid(request.sid)
    remove_sid_to_username(request.sid)

    if player:
        was_current_connection = remove_sid_if_matches(player, request.sid)
        if was_current_connection:
            connected_since.pop(player, None)
            room_id = get_player_room(player)
            if room_id:
                if _connected_count(room_id) > 0:
                    # Someone's still here — let them know, don't tear anything down.
                    ioclient.emit(
                        "player_disconnected",
                        {"player": player, "players": get_players(room_id)},
                        to=room_id,
                    )
                    # The host may be the one who just dropped.
                    _broadcast_host(room_id)
                else:
                    schedule_room_destroy(room_id)

                if not is_in_session(room_id):
                    # Hold their lobby seat for a while, then free it.
                    lobby_drop_marks[player] = time.time()
                    gevent.spawn_later(
                        LOBBY_GHOST_GRACE + 1, _prune_lobby_ghosts, room_id
                    )


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

    _leave_previous_room(username, room)
    join_room(room)
    cancel_room_destroy(room)

    addToRoom(room, username)
    map_player_to_room(username, room)

    emit("player_joined", get_players(room), to=room)
    _broadcast_host(room)
    _prune_lobby_ghosts(room)


@ioclient.on("join_public")
def handle_join_public():
    username = get_user_from_sid(request.sid)
    if not username:
        return

    # 1. Try to find an existing open public room that somebody is
    #    actually in. A lobby whose players have all dropped is just waiting
    #    to be destroyed; matching into it strands the new player.
    room_id = next(
        (
            rid
            for rid, roster in (get_open_public_rooms() or [])
            if any(get_sid(p) for p in roster if p != username)
        ),
        None,
    )

    # 2. If no open public room exists, create a brand new one
    if not room_id:
        room_id = genRoomId()
        # Mark it as public!
        indexRoom(room_id, is_public=True)

    # 3. Add the player to the room
    _leave_previous_room(username, room_id)
    join_room(room_id)
    cancel_room_destroy(room_id)
    addToRoom(room_id, username)
    map_player_to_room(username, room_id)

    players = get_players(room_id)
    is_host = _host_of(room_id, players) == username

    # 4. Tell the joining player they successfully joined
    emit(
        "public_room_found",
        {"room_id": room_id, "is_host": is_host, "players": players},
    )

    # 5. Tell everyone else in the lobby that a new player joined
    emit("player_joined", players, to=room_id)
    _broadcast_host(room_id)
    _prune_lobby_ghosts(room_id)

@ioclient.on("create")
def new_room(data=None):

    username = get_user_from_sid(request.sid)

    if not username:
        return

    roomID = genRoomId()

    cats = data.get("categories") if data else None
    alphabet = data.get("allowed_letters") if data else None

    indexRoom(roomID, categories=cats, allowed_letters=alphabet)

    _leave_previous_room(username, roomID)
    join_room(roomID)

    addToRoom(roomID, username)
    map_player_to_room(username, roomID)

    emit("game_code", roomID)
    _broadcast_host(roomID)


@ioclient.on("create_solo")
def new_solo_room(data=None):
    """One human against 1-3 bots. No lobby: the match starts at once."""
    username = get_user_from_sid(request.sid)
    if not username:
        return
    data = data or {}

    def _int(key, default, low, high):
        try:
            return max(low, min(high, int(data.get(key, default))))
        except (TypeError, ValueError):
            return default

    n_bots = _int("bots", 2, 1, 3)
    rounds = _int("rounds", 5, 3, 26)
    level = data.get("difficulty")
    if level not in DIFFICULTY:
        level = DEFAULT_DIFFICULTY

    room_id = genRoomId()
    indexRoom(room_id, allowed_letters=pick_solo_letters(rounds))

    _leave_previous_room(username, room_id)
    join_room(room_id)

    # Human first, so they get the first turn.
    addToRoom(room_id, username)
    map_player_to_room(username, room_id)
    for bot in make_bot_names(n_bots):
        addToRoom(room_id, bot)
    room_bot_level[room_id] = level

    set_room_mode(room_id)
    config = get_room_config(room_id)

    emit("solo_room", {"room_id": room_id})
    ioclient.emit(
        "game_started",
        {
            "players": get_players(room_id),
            "categories": config["categories"],
            "allowed_letters": config["allowed_letters"],
        },
        to=room_id,
    )
    _broadcast_host(room_id)
    _advance_turn(room_id)


# =========================================================
# BOT PLAY
# =========================================================
# Bots act through the same functions people do (_begin_round,
# _record_answers). Every timer carries the round's phase_id, so anything
# scheduled for a round that has since moved on simply does nothing.

room_bot_level = {}  # room_id -> difficulty name
bot_plans = {}  # room_id -> {bot: {"start": time, "plan": [...]}}


def _bot_take_turn(room_id):
    """If it's a bot's turn to pick a letter, have it pick after a pause."""
    bot = get_turn_player(room_id)
    if not is_bot(bot):
        return
    state = get_state(room_id)
    gevent.spawn_later(
        random.uniform(1.5, 3.5), _bot_pick_letter, room_id, bot, state.phase_id
    )


def _bot_pick_letter(room_id, bot, expected_phase_id):
    try:
        state = round_states.get(room_id)
        if not state or state.phase_id != expected_phase_id:
            return
        if state.phase != RoundPhase.PICKING or get_turn_player(room_id) != bot:
            return

        config = get_room_config(room_id)
        used = set(get_used_letters(room_id) or [])
        free = [c for c in config["allowed_letters"] if letter_to_idx(c) not in used]
        if free:
            _begin_round(room_id, bot, random.choice(free))
    except Exception as e:
        print(f"Error in bot letter pick: {e}")


def _bots_start_answering(room_id):
    """Plan each bot's round and schedule when it hands its answers in."""
    bots = _bots_in(room_id)
    if not bots:
        return

    state = get_state(room_id)
    config = get_room_config(room_id)
    level = room_bot_level.get(room_id, DEFAULT_DIFFICULTY)
    plans = bot_plans.setdefault(room_id, {})

    for bot in bots:
        if bot in state.answers:
            continue
        plan = plan_answers(config["categories"], state.letter, level)
        plans[bot] = {"start": time.time(), "plan": plan}
        finish_at = plan[-1][2] if plan else 1.0
        gevent.spawn_later(
            finish_at + 0.2, _bot_submit, room_id, bot, state.phase_id
        )


def _bot_answers_now(room_id, bot):
    entry = bot_plans.get(room_id, {}).get(bot)
    if not entry:
        return {}
    return answers_ready(entry["plan"], time.time() - entry["start"])


def _bot_submit(room_id, bot, expected_phase_id):
    try:
        state = round_states.get(room_id)
        if not state or state.phase_id != expected_phase_id:
            return
        if state.phase != RoundPhase.ANSWERING or bot in state.answers:
            return
        _record_answers(room_id, bot, _bot_answers_now(room_id, bot))
    except Exception as e:
        print(f"Error in bot submit: {e}")


def _flush_bots(room_id):
    """The round is being cut short (turn player finished, or the clock
    ran out). Bots hand in whatever they had written by now."""
    state = round_states.get(room_id)
    if not state:
        return
    for bot in _bots_in(room_id):
        if bot not in state.answers:
            state.answers[bot] = _bot_answers_now(room_id, bot)


def _bots_vote(room_id, contested):
    """Bots approve every contested word that isn't their own. They have
    no way to judge it, and rejecting a person's answer at random would
    just feel unfair."""
    for bot in _bots_in(room_id):
        for item in contested:
            if item["player"] != bot:
                item["votes_yes"] += 1


def _humans_can_vote(room_id, contested):
    """Is there at least one connected person with someone else's word to
    judge?"""
    humans = [p for p in (get_players(room_id) or []) if not is_bot(p) and get_sid(p)]
    return any(item["player"] != h for h in humans for item in contested)


# =========================================================
# GAMEPLAY
# =========================================================


@ioclient.on("start")
def start_game(data):

    room_id = data["room_id"]

    if is_in_session(room_id):
        # Already started — ignore a duplicate/late "start" (double-click,
        # network retry, stale reconnect, etc). Without this, a second
        # start_game call would advance the turn pointer a second time
        # and silently skip whoever should have gone first.
        return

    players = get_players(room_id)
    username = get_user_from_sid(request.sid)

    if not players or _host_of(room_id, players) != username:
        emit("cant_start_game", {"message": "Only the host can start the match"})
        return

    if _connected_count(room_id) < 2:
        emit("cant_start_game", {"message": "Need at least 2 players online"})
        return

    set_room_mode(room_id)
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

    _advance_turn(room_id)


def _advance_turn(room_id):
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
    _bot_take_turn(room_id)


@ioclient.on("leave_room")
def handle_leave_room(data):
    room_id = data.get("room_id")
    player = get_user_from_sid(request.sid)

    if player and room_id:
        # 1. Unsubscribe them from the socket broadcasts
        leave_room(room_id)

        # 2. Remove them from the room's database/JSON
        removeFromRoom(room_id, player)
        if get_player_room(player) == room_id:
            # Forget the mapping too, otherwise their next reconnect pulls
            # them straight back into the room they just left.
            unmap_player_from_room(player)

        if _only_bots_left(room_id):
            # Solo room: the human is gone, so the room goes with them.
            _teardown_room(room_id)
            emit("left_room_success", to=request.sid)
            return

        # 3. Tell everyone else in the room that they left
        remaining_players = get_players(room_id)
        if remaining_players:
            emit("player_left", remaining_players, to=room_id)
            _broadcast_host(room_id)

        # 3b. If that was the last connected player, start the teardown clock.
        if _connected_count(room_id) == 0:
            schedule_room_destroy(room_id)

        # 4. Confirm success to the person who left
        emit("left_room_success", to=request.sid)


# =========================================================
# LETTER SELECTED
# =========================================================


@ioclient.on("letter_selected")
def letter_selected(data):

    room_id = data["room_id"]
    state = round_states.get(room_id)

    # Only the player whose turn it currently is can pick a letter, and
    # only while we're actually in the picking phase. Without this, any
    # stray or duplicate client event could reset an in-progress
    # answering round for everyone — wiping every player's typed answers
    # — regardless of who sent it or when.
    if not state or state.phase != RoundPhase.PICKING:
        return

    turn_player = get_user_from_sid(request.sid)
    if turn_player != get_turn_player(room_id):
        return

    _begin_round(room_id, turn_player, data["letter"])


def _begin_round(room_id, turn_player, letter):
    """A letter has been picked (by a person or a bot): start answering."""
    state = get_state(room_id)

    cancel_turn_timer(room_id)
    cross_letter(room_id, letter)
    set_turn_player(room_id, turn_player)

    state.phase = RoundPhase.ANSWERING
    state.letter = letter
    state.answers.clear()
    state.contested_items.clear()
    state.votes_cast_count = 0

    start_answering_timer(room_id)

    ioclient.emit("letter_chosen", letter, to=room_id)
    _bots_start_answering(room_id)


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

    _record_answers(room_id, player, data["answers"])


def _record_answers(room_id, player, answers):
    """Take one player's answers (person or bot) and end the round if
    that was the last set we were waiting for."""
    state = round_states.get(room_id)
    if not state or state.phase != RoundPhase.ANSWERING:
        return

    state.answers[player] = answers
    if player == get_turn_player(room_id):
        # The turn player finishing ends the round for everyone.
        ioclient.emit("force_submit", {}, to=room_id)
        _flush_bots(room_id)

    if len(state.answers) >= _participant_count(room_id):
        process_validation(room_id)


# =========================================================
# VALIDATION
# =========================================================


def process_validation(room_id):

    cancel_answering_timer(room_id)

    state = round_states.get(room_id)

    if not state or state.phase != RoundPhase.ANSWERING:
        return

    # Time's up for bots too: take whatever they've written so far.
    _flush_bots(room_id)

    state.phase = RoundPhase.VALIDATING

    letter = state.letter
    contested = []

    # Validate every player's answers concurrently instead of one at a
    # time. A "Place" answer triggers a real network geocode call
    # (up to ~2s), and doing that sequentially per player is what made
    # this screen slow with more than 1-2 players.
    jobs = {
        player: gevent.spawn(get_answer_validity, p_answers, letter)
        for player, p_answers in state.answers.items()
    }
    gevent.joinall(list(jobs.values()), timeout=5)

    reports = {}
    for player, job in jobs.items():
        # If a job didn't finish in time (e.g. geocoder hung), fall back
        # to treating that player's answers as needing a vote rather than
        # blocking everyone else or crashing.
        if job.successful():
            reports[player] = job.value
        else:
            reports[player] = {
                cat: {"word": word.strip(), "status": "needs_vote"}
                for cat, word in state.answers[player].items()
                if word.strip()
            }

    state.validity_reports = reports

    for player, report in reports.items():
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

    if contested and _bots_in(room_id):
        _bots_vote(room_id, contested)
        if not _humans_can_vote(room_id, contested):
            # Solo: every contested word is the human's own, so there is
            # nobody to wait for. Skip the 30s voting screen.
            finalize_scores(room_id)
            return
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

    if state.votes_cast_count >= _connected_count(room_id):
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
        # Reuse what process_validation already computed instead of
        # re-running (and re-geocoding) everything from scratch. Only
        # falls back to a fresh computation if something's missing.
        validity = state.validity_reports.get(player) or get_answer_validity(
            answers, letter
        )

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
        _advance_turn(room_id)


def auto_destroy_room(room_id, expected_phase_id):
    state = round_states.get(room_id)
    # Check if the host already restarted the game or ended it manually
    if not state or state.phase_id != expected_phase_id:
        return

    ioclient.emit(
        "room_destroyed", {"message": "Room closed due to inactivity."}, to=room_id
    )
    _teardown_room(room_id)


@ioclient.on("force_end_game")
def force_end_game(data):
    room_id = data["room_id"]
    username = get_user_from_sid(request.sid)
    players = get_players(room_id)

    # Only the host (player index 0) can end the game
    if players and _host_of(room_id, players) == username:
        ioclient.emit(
            "room_destroyed", {"message": "Host ended the match."}, to=room_id
        )
        _teardown_room(room_id)


@ioclient.on("restart_game")
def restart_game(data):
    room_id = data["room_id"]
    username = get_user_from_sid(request.sid)
    players = get_players(room_id)

    if players and _host_of(room_id, players) == username:
        # 1. Kill the self-destruct timer by changing the phase_id
        state = get_state(room_id)
        state.phase_id = time.time()

        # 2. Reset the backend game data
        config = get_room_config(room_id)
        clear_used_letters(room_id)

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
        _advance_turn(room_id)
