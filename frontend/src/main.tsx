import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { HeatThemeProvider } from "./theme/heatThemes";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <HeatThemeProvider>
        <App />
      </HeatThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
