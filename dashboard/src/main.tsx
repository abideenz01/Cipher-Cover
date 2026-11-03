import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Session } from "./Session";
import "./theme.css";

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <Session />
  </StrictMode>,
);
