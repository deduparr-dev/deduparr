import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";
import { setupConsoleSecurityFilter } from "./lib/security";

// Set up console security filter to sanitize sensitive data in production
setupConsoleSecurityFilter();

createRoot(document.getElementById("root")!).render(<App />);
