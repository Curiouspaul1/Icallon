"""
My first application
"""

import toga
import httpx
import requests

from toga.style import Pack
from toga.style.pack import COLUMN, ROW


class HelloWorld(toga.App):
    def startup(self):
        """Construct and show the Toga application.

        Usually, you would add your application to a main content box.
        We then create a main window (with a name matching the app), and
        show the main window.
        """
        main_box = toga.Box(style=Pack(direction=COLUMN))
        name_box = toga.Box(style=Pack(direction=ROW))

        label = toga.Label(
            "Enter your name: ",
            style=Pack(padding=(0, 5))
        )
        self.name_field = toga.TextInput(
            style=Pack(flex=1)
        )

        name_box.add(label)
        name_box.add(self.name_field)

        button = toga.Button(
            "Submit",
            on_press=self.submit,
            style=Pack(padding=5)
        )

        main_box.add(name_box)
        main_box.add(button)

        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = main_box
        self.main_window.show()

        requests.get('https://google.com')

    def submit(self, widget):
        with httpx.Client() as client:
            resp = client.get("https://jsonplaceholder.typicode.com/posts/42")

        payload = resp.json()

        self.main_window.dialog(
            toga.InfoDialog(
                "Hello",
                payload['body']
            )
        )


def main():
    return HelloWorld()
