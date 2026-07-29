import {useState} from "react";

const KEY = "ddu.cookieConsent";

export function CookieConsent({
  onDecline,
}: {
  onDecline: () => void;
}) {
  const [visible, setVisible] = useState(() => !localStorage.getItem(KEY));

  if (!visible) return null;

  return (
    <div className="cookie-consent" role="dialog" aria-label="Storage consent">
      <p>
        We use local storage to remember your data mode preference.
      </p>
      <div>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(KEY, "accept");
            setVisible(false);
          }}
        >
          Accept
        </button>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(KEY, "decline");
            localStorage.removeItem("ddu.dataMode");
            onDecline();
            setVisible(false);
          }}
        >
          Decline
        </button>
      </div>
    </div>
  );
}

export function storageAllowed() {
  return localStorage.getItem(KEY) !== "decline";
}
