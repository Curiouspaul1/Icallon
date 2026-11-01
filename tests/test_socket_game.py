"""A FlaskCon game played over Socket.IO with Flask-SocketIO's test client.

The app keeps its state in JSON files in the working directory, so these
tests run from a fresh temporary directory.
"""

import json
import os

import pytest


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    old_cwd = os.getcwd()
    os.chdir(tmp_path_factory.mktemp("icallon"))
    import app as app_module
    import events

    yield app_module.app, app_module.ioclient, events
    app_module.scheduler.shutdown(wait=False)
    os.chdir(old_cwd)


def connect(server, name):
    flask_app, ioclient, _ = server
    return ioclient.test_client(flask_app, auth={"username": name, "token": "t-" + name})


def events_named(client, name):
    return [e["args"] for e in client.get_received() if e["name"] == name]


def rooms():
    with open("rooms.json") as fp:
        return json.load(fp)


@pytest.fixture
def lobby(server):
    """Ada creates a 4-round FlaskCon room and Tunji joins it."""
    ada = connect(server, "Ada")
    tunji = connect(server, "Tunji")
    ada.get_received()
    tunji.get_received()

    ada.emit("create", {"pack": "flaskcon", "rounds": 4})
    received = ada.get_received()
    names = [e["name"] for e in received]
    assert names.index("room_pack") < names.index("game_code")
    pack = next(e["args"][0] for e in received if e["name"] == "room_pack")
    code = next(e["args"][0] for e in received if e["name"] == "game_code")
    assert pack == {"pack": "flaskcon"}

    tunji.emit("join", {"roomID": code})
    assert events_named(tunji, "room_pack") == [[{"pack": "flaskcon"}]]

    yield ada, tunji, code
    ada.disconnect()
    tunji.disconnect()


def test_flaskcon_room_uses_the_pack(lobby):
    _, _, code = lobby
    room = rooms()[code]
    assert room["pack"] == "flaskcon"
    assert room["categories"] == ["Name", "Animal", "Python & Flask", "Lagos & Africa"]
    assert len(room["allowed_letters"]) == 4
    assert set(room["allowed_letters"]) <= set("ABCDEFGIJKLMNOPRSTWY")


def test_full_round_rules(server, lobby):
    _, _, events = server
    ada, tunji, code = lobby
    allowed = rooms()[code]["allowed_letters"]

    ada.emit("start", {"room_id": code})
    started = events_named(ada, "game_started")
    assert started and started[0][0]["pack"] == "flaskcon"
    tunji.get_received()

    # A letter the room doesn't play is ignored...
    outside = next(c for c in "HQXZV" if c not in allowed)
    ada.emit("letter_selected", {"room_id": code, "letter": outside})
    assert events_named(ada, "letter_chosen") == []
    # ...and so is something that isn't a letter at all.
    ada.emit("letter_selected", {"room_id": code, "letter": "<b>"})
    assert events_named(ada, "letter_chosen") == []

    letter = allowed[0]
    ada.emit("letter_selected", {"room_id": code, "letter": letter.lower()})
    assert events_named(ada, "letter_chosen") == [[letter]]
    tunji.get_received()

    # Tunji writes a made-up Python term, then Ada (turn player) finishes.
    tunji.emit("player_answer", {"room_id": code, "answers": {"Python & Flask": letter + "ython"}})
    ada.emit("player_answer", {"room_id": code, "answers": {"Python & Flask": letter + "ambda"}})

    voting = events_named(ada, "start_voting")
    assert voting, "the made-up word should go to a vote"
    contested = voting[0][0]
    tunji_item = next(i for i in contested if i["player"] == "Tunji")

    # Tunji tries to approve his own word, twice. Neither counts.
    tunji.emit("cast_votes", {"room_id": code, "votes": {tunji_item["id"]: True}})
    tunji.emit("cast_votes", {"room_id": code, "votes": {tunji_item["id"]: True}})
    state = events.round_states[code]
    item = next(i for i in state.contested_items if i["id"] == tunji_item["id"])
    assert item["votes_yes"] == 0
    assert state.voters == {"Tunji"}

    # Ada says no; that closes voting and Tunji's word is rejected.
    ada.emit("cast_votes", {"room_id": code, "votes": {tunji_item["id"]: False}})
    breakdown = events_named(ada, "round_breakdown")[0][0]
    assert breakdown["answers"]["Tunji"]["Python & Flask"]["result"] == "rejected"

    # Restart wipes the scores from the game before.
    assert rooms()[code]["player_to_score"]
    ada.emit("restart_game", {"room_id": code})
    assert rooms()[code]["player_to_score"] == {}
    assert rooms()[code]["letters"] == []


def test_create_cleans_custom_config(server):
    eve = connect(server, "Eve")
    eve.get_received()
    eve.emit("create", {"categories": ["<img src=x>", "Movie"], "allowed_letters": "a<b>c"})
    code = events_named(eve, "game_code")[0][0]
    room = rooms()[code]
    assert room["allowed_letters"] == "ABC"
    assert room["pack"] is None
    eve.disconnect()


def test_overlong_names_are_refused(server):
    flask_app, ioclient, _ = server
    client = ioclient.test_client(flask_app, auth={"username": "x" * 40, "token": "t"})
    assert not client.is_connected()
