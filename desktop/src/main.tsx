import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import DeckView from "./deck/DeckView";

// #deck renders the GPU Deck window; anything else is the main HUD
const Root = window.location.hash === "#deck" ? DeckView : App;

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
