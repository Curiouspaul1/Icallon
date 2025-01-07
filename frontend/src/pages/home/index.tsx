import { NavLink } from "react-router";
import AppLayout from "../../layouts/app-layout";

const Home = () => {
  return (
    <AppLayout>
      <div className="flex flex-col w-full h-full py-28 items-center">
        <h1 className="text-gray-500 font-bold text-[48px]">I Call On...</h1>
        <div className="flex flex-col items-center justify-center h-full w-full p-8">
          <div className="flex w-full lg:w-1/2 flex-col lg:flex-row items-center justify-center gap-8 text-gray-500">
            <NavLink
              className="w-[40%] text-[20px] bg-gray-100 hover:bg-gray-200 flex items-center justify-center border-2 border-gray-500 rounded-md p-6"
              to={"/create"}
            >
              Create a game
            </NavLink>

            <NavLink
              className="w-[40%] text-[20px] bg-gray-100 hover:bg-gray-200 flex items-center justify-center border-2 border-gray-500 rounded-md p-6"
              to={"/join"}
            >
              Join a game
            </NavLink>
          </div>
        </div>
      </div>
    </AppLayout>
  );
};

export default Home;
