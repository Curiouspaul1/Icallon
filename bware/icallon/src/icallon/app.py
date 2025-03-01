"""
Mobile app for the 'icallon' word guessing game.
"""
from pathlib import Path

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

from icallon.screens.entrypoint import create_app_entrypoint


class icallon(toga.App):
    _widget_stack: list

    def _draw(self, widget):
        main_box = toga.Box(style=Pack(
            direction=COLUMN
        ))
        header = toga.Box(style=Pack(flex=1))
        header.add(toga.Button(
            icon=toga.Icon('undo.png'),
            style=Pack(width=50, height=50),
            on_press=self._nav_pop
        ))
        main_box.add(header)
        main_box.add(widget)
        main_box.add(toga.Box(style=Pack(flex=1)))
        self.main_window.content = main_box

        if self._widget_stack:
            self.top_screen = self._widget_stack.pop()
        self._widget_stack.append(main_box)

    def startup(self):
        """Construct and show the Toga application.

        Usually, you would add your application to a main content box.
        We then create a main window (with a name matching the app), and
        show the main window.
        """
        self._widget_stack = []
        self.top_screen = None
        self.main_window = toga.MainWindow(
            title=self.formal_name
        )

        entrypoint = create_app_entrypoint()
        self._draw(entrypoint)
        if self._widget_stack:
            self.top_screen = self._widget_stack.pop()
        self._widget_stack.append(entrypoint)

        self.main_window.show()

    def _nav_pop(self, widget):
        if self.top_screen:
            self._draw(self.top_screen)


app = icallon()
