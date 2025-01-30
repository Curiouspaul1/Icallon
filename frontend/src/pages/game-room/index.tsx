import { useParams } from "react-router";
import { useGameContext } from "../../context/gamecode";
import AppLayout from "../../layouts/app-layout";

const GameRoom = () => {
  const { gameCode } = useParams<{ gameCode: string }>();
  const { isValidGameCode } = useGameContext();

  if (!isValidGameCode(gameCode!)) {
    return (
      <AppLayout>
        <div className="flex flex-col items-center justify-center h-screen">
          <div className="text-red-500">Invalid Game Code</div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="flex flex-col items-center justify-center h-screen">
        <div className="text-2xl font-bold">Game Room</div>
        <div className="mt-4">Game Code: {gameCode}</div>
      </div>
    </AppLayout>
  );
};

export default GameRoom;
