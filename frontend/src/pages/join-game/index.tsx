import { useState } from "react";
import { useNavigate } from "react-router";
import { useGameContext } from "../../context/gamecode";
import AppLayout from "../../layouts/app-layout";

const JoinGame = () => {
  const [gameCode, setGameCode] = useState("");
  const navigate = useNavigate();
  const { isValidGameCode } = useGameContext();

  const handleJoinGame = () => {
    if (isValidGameCode(gameCode)) {
      navigate(`/game/${gameCode}`);
    } else {
      alert("Invalid Game Code");
    }
  };

  return (
    <AppLayout>
      <div className="flex flex-col items-center justify-center h-screen">
        <div className="text-2xl font-bold">Join Game</div>
        <input
          type="text"
          placeholder="Enter Game Code"
          value={gameCode}
          onChange={(e) => setGameCode(e.target.value)}
          className="mt-4 px-4 py-2 border rounded bg-white"
        />
        <button
          onClick={handleJoinGame}
          className="mt-4 px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600"
        >
          Join Game
        </button>
      </div>
    </AppLayout>
  );
};

export default JoinGame;
