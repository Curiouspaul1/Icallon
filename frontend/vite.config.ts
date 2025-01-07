import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "tailwindcss";
import macrosPlugin from "vite-plugin-babel-macros";
import svgr from "vite-plugin-svgr";

// https://vitejs.dev/config/
export default defineConfig({
  css: {
    postcss: {
      plugins: [tailwindcss()],
    },
  },
  plugins: [react(), macrosPlugin(), svgr()],
  resolve: {
    alias: {
      src: "/src",
      apis: "/src/apis",
      data: "/src/data",
      utils: "/src/utils",
      pages: "/src/pages",
      types: "/src/types",
      styles: "/src/styles",
      assets: "/src/assets",
      services: "/src/services",
      components: "/src/components",
    },
  },
});
