import ws from "k6/ws";
import http from "k6/http";
import {check} from "k6";

export const options = {vus: 50, duration: "60s"};
const BASE = __ENV.BASE_URL || "http://127.0.0.1:8120";
const WS_BASE = BASE.replace("https://", "wss://").replace("http://", "ws://");

export default function () {
  const created = http.post(
    `${BASE}/intel/session`,
    JSON.stringify({
      emails: [`ws${__VU}@example.com`],
      handles: [`ws_${__VU}`],
      seed_mock_findings: true,
      persona: "scammer",
    }),
    {headers: {"Content-Type": "application/json"}},
  );
  const sid = created.json("session_id");
  const url = `${WS_BASE}/intel/ws/${sid}`;
  const res = ws.connect(url, {}, function (socket) {
    socket.on("open", () => socket.setTimeout(() => socket.close(), 60000));
    socket.on("message", () => {});
  });
  check(res, {"ws status 101": (r) => r && r.status === 101});
}
