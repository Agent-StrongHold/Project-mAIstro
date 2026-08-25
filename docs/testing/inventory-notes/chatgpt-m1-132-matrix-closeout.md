# M1 #132 matrix closeout

The PostgreSQL Run/NodeRun/Attempt store is already implemented and wired on develop. The remaining documentation acceptance gap is the convergence matrix ownership row, which still names only `runs.sqlite_store` and `runs.store` as persistence owners. This branch exists solely to make that row name `runs.pg_store` as the canonical PostgreSQL durable backend while retaining SQLite for homelab/local use.
