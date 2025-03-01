import toga
from toga.style import Pack


def new_game_screen():
    new_game_btn = toga.Button(
        "New Game",
        style=Pack(
            padding=(10,),
            font_size=12,
            color='#3b82f6',
            width=140,
            height=40
        ),
        on_press=lambda: print('hello')
    )

    return new_game_btn
