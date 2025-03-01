import random

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

from icallon.screens.create import new_game_screen
from icallon.resources.widgets import created_centered_widget


def create_game(widget):
    from icallon.app import app
    # chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    # gameCode = ''
    # for i in range(8):
    #     gameCode += random.choice(chars)
    # print(gameCode)
    # return gameCode
    app._draw(
        created_centered_widget(
            new_game_screen()
        )
    )


def join_game(widget):
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    gameCode = ''
    for i in range(8):
        gameCode += random.choice(chars)
    return gameCode


def create_app_entrypoint():
    # align buttons
    createBtn = toga.Button(
        "Create Game",
        style=Pack(
            background_color='#33658A',
            padding=(10,),
            width=140,
            height=40,
            font_size=12,
            color='#fff'
        ),
        on_press=create_game
    )

    joinBtn = toga.Button(
        "Join Game",
        style=Pack(
            background_color='#F6AE2D',
            padding=(10,),
            font_size=12,
            width=140,
            height=40,
            color='#fff'
        ),
        on_press=join_game
    )

    createBtnBox = created_centered_widget(createBtn)
    joinBtnBox = created_centered_widget(joinBtn)

    gameOptions = toga.Box(
        style=Pack(
            direction=COLUMN,
            # alignment='center'x
        )
    )

    gameOptions.add(createBtnBox)
    gameOptions.add(joinBtnBox)

    return gameOptions
