import asyncio
import time
import random
import string
import statistics
import socketio

SERVER_URL = "http://127.0.0.1:5000"

# Avoid the "Place" category during load testing: is_place() makes a real
# outbound network call to the public Nominatim geocoding service on every
# validation. Hammering a shared third-party rate-limited API isn't
# representative of the game's own capacity, and is rude to Nominatim.
LOAD_TEST_CATEGORIES = ["Name", "Animal", "Thing"]
SAMPLE_ANSWERS = {
    "Name": ["Alan", "Amanda", "Anna", "Andrew"],
    "Animal": ["ant", "alligator", "antelope"],
    "Thing": ["apple", "arrow", "anchor"],
}

results = {
    "connect_times": [],
    "room_create_times": [],
    "round_trip_times": [],
    "errors": [],
    "rounds_completed": 0,
}


def rand_username():
    return "p_" + "".join(random.choices(string.ascii_lowercase, k=8))


class Player:
    def __init__(self, username, is_host, room_holder):
        self.username = username
        self.token = "".join(random.choices(string.ascii_lowercase + string.digits, k=20))
        self.is_host = is_host
        self.room_holder = room_holder  # shared dict to pass room_id between the 2 players
        self.sio = socketio.AsyncClient(logger=False, engineio_logger=False)
        self.room_id = None
        self.my_turn = False
        self.game_over = False
        self.answer_wait_evt = asyncio.Event()
        self._register_handlers()

    def _register_handlers(self):
        sio = self.sio

        @sio.event
        async def connect_error(data):
            results["errors"].append(f"{self.username} connect_error: {data}")

        @sio.on("game_code")
        async def on_game_code(room_id):
            self.room_id = room_id
            self.room_holder["room_id"] = room_id

        @sio.on("player_joined")
        async def on_player_joined(players):
            if self.is_host and len(players) >= 2 and self.room_id:
                await self.sio.emit("start", {"room_id": self.room_id})

        @sio.on("public_player_turn")
        async def on_public_player_turn(player):
            self.my_turn = (player == self.username)
            if self.my_turn:
                letter = random.choice("ABCDEFGHIJ")
                await self.sio.emit(
                    "letter_selected", {"letter": letter, "room_id": self.room_id}
                )

        @sio.on("letter_chosen")
        async def on_letter_chosen(letter):
            self.current_letter = letter
            self.answer_wait_evt.set()

        @sio.on("start_voting")
        async def on_start_voting(items):
            # Auto-approve everything to keep the round moving.
            votes = {item["id"]: True for item in items}
            await self.sio.emit("cast_votes", {"room_id": self.room_id, "votes": votes})

        @sio.on("round_result")
        async def on_round_result(scores):
            results["rounds_completed"] += 1

        @sio.on("game_over")
        async def on_game_over(data):
            self.game_over = True

    async def connect(self):
        t0 = time.perf_counter()
        await self.sio.connect(
            SERVER_URL,
            auth={"username": self.username, "token": self.token},
            transports=["websocket"],
            wait_timeout=10,
        )
        results["connect_times"].append(time.perf_counter() - t0)

    async def create_or_join(self):
        if self.is_host:
            t0 = time.perf_counter()
            await self.sio.emit(
                "create",
                {"categories": LOAD_TEST_CATEGORIES, "allowed_letters": "ABCDEFGHIJ"},
            )
            for _ in range(50):
                if self.room_id:
                    break
                await asyncio.sleep(0.1)
            results["room_create_times"].append(time.perf_counter() - t0)
        else:
            for _ in range(50):
                if self.room_holder.get("room_id"):
                    break
                await asyncio.sleep(0.1)
            self.room_id = self.room_holder.get("room_id")
            if self.room_id:
                await self.sio.emit("join", {"roomID": self.room_id})

    async def play_rounds(self, max_rounds=3, round_timeout=20):
        for _ in range(max_rounds):
            if self.game_over or not self.room_id:
                return

            t0 = time.perf_counter()
            try:
                await asyncio.wait_for(self.answer_wait_evt.wait(), timeout=round_timeout)
            except asyncio.TimeoutError:
                results["errors"].append(f"{self.username} never saw letter_chosen")
                return
            self.answer_wait_evt.clear()

            answers = {cat: random.choice(vals) for cat, vals in SAMPLE_ANSWERS.items()}
            await self.sio.emit(
                "player_answer",
                {"answers": answers, "room_id": self.room_id, "letter": self.current_letter},
            )
            results["round_trip_times"].append(time.perf_counter() - t0)
            await asyncio.sleep(2)  # let voting/scoring settle before next round

    async def disconnect(self):
        try:
            await self.sio.disconnect()
        except Exception:
            pass


async def run_one_room(room_index, max_rounds):
    room_holder = {}
    host = Player(f"host{room_index}_{rand_username()}", True, room_holder)
    guest = Player(f"guest{room_index}_{rand_username()}", False, room_holder)

    try:
        await asyncio.gather(host.connect(), guest.connect())
        await host.create_or_join()
        await guest.create_or_join()
        await asyncio.gather(
            host.play_rounds(max_rounds=max_rounds),
            guest.play_rounds(max_rounds=max_rounds),
        )
    except Exception as e:
        results["errors"].append(f"room {room_index} failed: {e!r}")
    finally:
        await host.disconnect()
        await guest.disconnect()


async def main(num_rooms, max_rounds, ramp_delay):
    tasks = []
    for i in range(num_rooms):
        tasks.append(asyncio.create_task(run_one_room(i, max_rounds)))
        await asyncio.sleep(ramp_delay)  # stagger room creation instead of a thundering herd
    await asyncio.gather(*tasks)


def summarize(label, values):
    if not values:
        print(f"{label}: no samples")
        return
    values_sorted = sorted(values)
    n = len(values_sorted)
    p50 = values_sorted[n // 2]
    p95 = values_sorted[min(n - 1, int(n * 0.95))]
    print(
        f"{label}: n={n} avg={statistics.mean(values):.3f}s "
        f"p50={p50:.3f}s p95={p95:.3f}s max={max(values):.3f}s"
    )


if __name__ == "__main__":
    import sys

    num_rooms = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    max_rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    ramp_delay = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05

    print(f"=== Load test: {num_rooms} rooms x 2 players, {max_rounds} rounds each ===")
    t0 = time.perf_counter()
    asyncio.run(main(num_rooms, max_rounds, ramp_delay))
    total_time = time.perf_counter() - t0

    print(f"\nTotal wall time: {total_time:.2f}s")
    summarize("Connect time", results["connect_times"])
    summarize("Room create time", results["room_create_times"])
    summarize("Answer round-trip time", results["round_trip_times"])
    print(f"Rounds completed (round_result received): {results['rounds_completed']}")
    print(f"Errors: {len(results['errors'])}")
    for e in results["errors"][:20]:
        print("  -", e)