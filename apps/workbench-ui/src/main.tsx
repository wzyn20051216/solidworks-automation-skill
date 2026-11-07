import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { LiveHud } from "./live/LiveHud";
import "./styles.css";

const windowKind = new URLSearchParams(location.search).get("window");

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {windowKind === "live" ? <LiveHud /> : <App />}
  </React.StrictMode>,
);
