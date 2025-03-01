import toga
from toga.style import Pack
from toga.style.pack import (
    COLUMN,
    ROW
)


def created_centered_widget(widget, row=True):
    container = toga.Box()
    if row:
        container.style.update(direction=ROW)
    else:
        container.style.update(direction=COLUMN)

    # arrange
    container.add(toga.Box(style=Pack(flex=1)))
    container.add(widget)
    container.add(toga.Box(style=Pack(flex=1)))

    return container
