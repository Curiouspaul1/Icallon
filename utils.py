import random


def genRoomId():
    chars = "ABCDEFGHIJKLMNPQRSTUVWXYZ0123456789"

    token = "".join(random.choice(chars) for x in range(12))

    return token
