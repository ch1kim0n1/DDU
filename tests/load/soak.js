import http from "k6/http";
import {sleep} from "k6";

export const options = {
  scenarios: {
    soak: {
      executor: "constant-vus",
      vus: 10,
      duration: "1h",
    },
  },
};

const BASE = __ENV.BASE_URL || "http://127.0.0.1:8120";

export default function () {
  http.post(
    `${BASE}/intel/session`,
    JSON.stringify({
      emails: [`soak${__VU}@example.com`],
      handles: [`soak_${__VU}`],
      seed_mock_findings: true,
      persona: "scammer",
    }),
    {headers: {"Content-Type": "application/json"}},
  );
  sleep(3);
}
