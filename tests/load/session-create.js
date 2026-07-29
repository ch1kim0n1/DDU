import http from "k6/http";
import {check, sleep} from "k6";

export const options = {
  vus: 20,
  duration: "60s",
};

const BASE = __ENV.BASE_URL || "http://127.0.0.1:8120";

export default function () {
  const res = http.post(
    `${BASE}/intel/session`,
    JSON.stringify({
      emails: [`load${__VU}@example.com`],
      handles: [`load_${__VU}`],
      seed_mock_findings: true,
      persona: "scammer",
    }),
    {headers: {"Content-Type": "application/json"}},
  );
  check(res, {"status 200": (r) => r.status === 200});
  sleep(0.2);
}
