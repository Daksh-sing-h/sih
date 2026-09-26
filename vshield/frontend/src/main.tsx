import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { CallPage } from "./call/CallPage";
import { Home } from "./Home";
import "./styles.css";

// ?room=CODE → two-person call · ?lab → single-stream lab dashboard · otherwise home
const params = new URLSearchParams(location.search);
const room = params.get("room")?.toUpperCase().replace(/[^A-Z0-9]/g, "");
const page = room ? <CallPage roomId={room} /> : params.has("lab") ? <App /> : <Home />;

createRoot(document.getElementById("root")!).render(<StrictMode>{page}</StrictMode>);
