import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { installMutationSignal } from "./data/mutationSignal";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/shell.css";

// Releitura da situação das etapas depois de gravações (#291).
installMutationSignal();

const root = document.getElementById("root");

if (!root) {
  throw new Error("Pericial frontend root is missing");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
