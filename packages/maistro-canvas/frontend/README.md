# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.

## Running the book-maker POC

The Python backend under `server/` needs a database, and it has no default: an
unconfigured start is an error rather than a guess at `localhost` (#432).

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD to any value you choose
docker compose up -d postgres # starts PostgreSQL with that password on host port 5441
alembic upgrade head          # migrations read the same setting the app does
npm ci && npm run dev         # Express + Vite on 5173
```

`POSTGRES_PASSWORD` is the only thing to set. `server/config.py` composes the
connection URL from it together with the user, database and port that
`docker-compose.yml` fixes, so there is one source for "which database" rather
than one per file. Before this there were two, and they had drifted: the
application and `alembic.ini` each carried a copy authenticating as `mcp:mcp`,
which no longer matched what Compose started.

To reach a database somewhere else, set `DATABASE_URL` to a full
`postgresql+asyncpg://` URL instead; it takes precedence and
`POSTGRES_PASSWORD` is then not consulted.
