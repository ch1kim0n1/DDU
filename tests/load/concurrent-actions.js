import http from "k6/http";
import {check, sleep} from "k6";

export const options = {vus: 10, iterations: 10};
const BASE = __ENV.BASE_URL || "http://127.0.0.1:8120";

export default function () {
  const created = http.post(
    `${BASE}/intel/session`,
    JSON.stringify({
      emails: [`c${__VU}@example.com`],
      handles: [`c_${__VU}`],
      seed_mock_findings: true,
      persona: "scammer",
    }),
    {headers: {"Content-Type": "application/json"}},
  );
  check(created, {"create 200": (r) => r.status === 200});
  const sid = created.json("session_id");
  const plan = http.post(
    `${BASE}/intel/scan/plan`,
    JSON.stringify({session_id: sid, state: "TX", county: "Travis"}),
    {headers: {"Content-Type": "application/json"}},
  );
  const proposals = plan.json("proposals") || [];
  for (let i = 0; i < Math.min(5, proposals.length); i++) {
    http.post(
      `${BASE}/intel/scan/approve`,
      JSON.stringify({session_id: sid, proposal_id: proposals[i].id}),
      {headers: {"Content-Type": "application/json"}},
    );
  }
  sleep(0.5);
}
