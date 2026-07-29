# Privacy decisions

## localStorage / ePrivacy

`ddu.dataMode` is stored in `localStorage` only after cookie consent Accept. Decline keeps mock mode and does not write the preference.

`sessionStorage` holds ephemeral `ddu.sessionId` for refresh recovery and is cleared on wipe/tab close.

## Biometrics

Liveness runs in-browser. At most one verified frame may upload after pass. Templates are session-scoped and destroyed on wipe/close.

## Analytics

Plausible is cookieless. Evidence drawer and voice panel are marked `data-no-plausible`.
