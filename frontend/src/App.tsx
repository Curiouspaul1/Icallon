import { BrowserRouter, Routes, Route } from "react-router";
import Home from "./pages/home";
import CreateGame from "./pages/create-game";
import JoinGame from "./pages/join-game";


function App() {

  return (
    <BrowserRouter>
      <Routes>
        <Route>
          <Route path="/" element={<Home/>} />
          <Route path="/create" element={<CreateGame />} />
          <Route path="/join" element={<JoinGame />} />
        </Route>
        
      </Routes>
      
    </BrowserRouter>
  );
}

export default App;
