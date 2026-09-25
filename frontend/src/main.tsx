import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

try {
  const t = localStorage.getItem("tt.theme");
  document.documentElement.dataset.theme = t ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
} catch {
  /* storage unavailable */
}

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => undefined));
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
