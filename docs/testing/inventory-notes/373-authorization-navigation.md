---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

The authorization snapshot tests cover the live no-store capability contract for admin and zero-permission users plus assigned/elevated/expired/revoked transitions. The backend tests remain the authorization contract because the frontend is a convenience projection and the API remains authoritative; browser E2E remains an environment-level follow-up.
