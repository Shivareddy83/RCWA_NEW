# RCAA Stage 07 Security

RCAA uses JWT bearer authentication with tenant identity (`user_id`, `merchant_id`, `role`, expiry) and Scrypt password hashing.

Roles are `ADMIN`, `OPS`, `ANALYST`, and `VIEWER`. Authorization is enforced server-side.

All merchant-owned financial resources are scoped to the authenticated merchant. Client-supplied `merchant_id` is never used as tenant authority.

Authentication configuration:

```text
AUTH_SECRET=<long random secret, at least 32 characters>
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

Demo users created by `scripts/seed_demo_data.py` use obviously fake local-only credentials. Change/remove them outside local demos.

The webhook endpoint remains signature-authenticated by the provider mechanism rather than JWT.
