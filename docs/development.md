# Development and configuration

## Install and verify

```sh
cd api
uv sync --frozen --python 3.12
make quality

cd ../frontend
npm ci
npm run quality
```

## Configuration boundary

The React build uses same-origin `/api` and `/health` paths and currently has no required
`VITE_*` variables. Any future `VITE_*` value is public by definition because Vite embeds it
in browser JavaScript. Never place credentials, database URLs, session keys, or seed passwords
in frontend source, build arguments, or `VITE_*` variables.

Backend values are server-only. Copy `.env.example` to an ignored `.env`, then generate the
database password and session HMAC key locally. The committed template deliberately contains
blank, unusable placeholders. `SESSION_HMAC_KEY` must contain at least 32 unpredictable bytes;
for example, generate a value with `openssl rand -hex 32`.

The four `DEMO_*_PASSWORD` values are consumed only by the one-shot demo seed service. They are
not application defaults and are not passed to the API or web image. Production disables demo
seeding unless an operator explicitly enables it and supplies every password.

Do not print effective settings in logs. Pydantic hides validation inputs and represents secret
fields as redacted values.
