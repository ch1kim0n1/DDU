import {StrictMode} from "react";
import {createRoot} from "react-dom/client";

import App from "./App";
import "./styles.css";

async function boot() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (dsn) {
    const Sentry = await import("@sentry/react");
    Sentry.init({
      dsn,
      sendDefaultPii: false,
      beforeBreadcrumb(breadcrumb) {
        if (breadcrumb.data) {
          delete breadcrumb.data.email;
          delete breadcrumb.data.handle;
        }
        return breadcrumb;
      },
    });
  } else if (import.meta.env.PROD) {
    console.warn("VITE_SENTRY_DSN is not set; frontend error tracking is disabled");
  }

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void boot();
