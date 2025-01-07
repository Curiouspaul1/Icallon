import { ReactNode } from "react";

const AppLayout = ({ children }: { children: ReactNode }) => {
  return (
    <div className="flex w-screen h-screen items-center justify-center text-gray-500">
      {children}
    </div>
  );
};

export default AppLayout;
