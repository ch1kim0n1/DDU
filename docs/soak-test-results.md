# Soak test results

Script: `tests/load/soak.js` (k6)

Target profile: 1000 sessions over 1 hour, 10 VUs.

| Metric | Target | Result |
|---|---|---|
| Session create success | >99% | Pending first staging run |
| Memory growth | Plateau | Pending |
| Redis expired keys | Cleaned | Pending |

Run against staging only:

```bash
k6 run -e BASE_URL=https://staging.example.com tests/load/soak.js
```
