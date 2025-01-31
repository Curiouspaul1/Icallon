import { useNavigate } from "react-router";
import { useGameContext } from "../../context/gamecode";
import AppLayout from "../../layouts/app-layout";

const CreateGame = () => {
  const navigate = useNavigate();
  const { addGameCode } = useGameContext();

  const generateGameCode = () => {
    return Math.random().toString(36).substring(2, 8).toUpperCase();
  };

  const handleCreateGame = () => {
    const gameCode = generateGameCode();
    addGameCode(gameCode);
    navigate(`/game/${gameCode}`); 
  };

  return (
    <AppLayout>
      <div className="flex flex-col items-center justify-center h-screen">
        <div className="text-2xl font-bold">Create Game</div>
        <button
          onClick={handleCreateGame}
          className="mt-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Create New Game
        </button>
      </div>
    </AppLayout>
  );
};

export default CreateGame;
