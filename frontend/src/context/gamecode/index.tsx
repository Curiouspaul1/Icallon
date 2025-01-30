import React, { createContext, useContext, useState, useEffect } from "react";

interface GameContextType {
  gameCodes: string[];
  addGameCode: (code: string) => void;
  isValidGameCode: (code: string) => boolean;
}

const GameContext = createContext<GameContextType | undefined>(undefined);

export const GameProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [gameCodes, setGameCodes] = useState<string[]>(() => {
    const storedGameCodes = localStorage.getItem("gameCodes");
    return storedGameCodes ? JSON.parse(storedGameCodes) : [];
  });

  useEffect(() => {
    localStorage.setItem("gameCodes", JSON.stringify(gameCodes));
  }, [gameCodes]);

  const addGameCode = (code: string) => {
    setGameCodes((prev) => [...prev, code]);
  };

  const isValidGameCode = (code: string) => {
    return gameCodes.includes(code);
  };

  return (
    <GameContext.Provider value={{ gameCodes, addGameCode, isValidGameCode }}>
      {children}
    </GameContext.Provider>
  );
};

export const useGameContext = () => {
  const context = useContext(GameContext);
  if (!context) {
    throw new Error("useGameContext must be used within a GameProvider");
  }
  return context;
};
