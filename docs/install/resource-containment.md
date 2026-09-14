# Container Resource Containment

This is the security containment policy for the supported Docker/Podman Compose
profiles. It is a final host boundary, not a replacement for bounded request
bodies, graph fan-out, queue admission, or subprocess budgets in the runtime.
Those correctness controls must still reject or shed work before a container
reaches its ceiling.

## Effective Compose controls

The profiles use service-level Compose keys because the documented deployment
mode is ordinary Docker Compose or Podman Compose:

| Control | Compose key | Policy |
|---|---|---|
| Resident memory | `mem_limit` | finite service-specific ceiling; never omitted or `unlimited` |
| Swap-inclusive memory | `memswap_limit` | equal to `mem_limit`, so swap cannot extend the ceiling |
| Process tree | `pids_limit` | finite service-specific ceiling |
| CPU quota | `cpus` | positive finite quota, chosen by service role |

`deploy.resources.limits` is intentionally not used. It is a Swarm deployment
configuration and is not an enforceable limit when an operator runs the
repository's documented `docker compose ... up` or `podman compose ... up`
commands. `scripts/check-compose-resources.py` validates every shipped
Compose profile, supported overlay, and the Phoenix add-on; CI fails if a
service is missing a key, outside the safety range, or uses the ineffective
Swarm-only shape.

The production reference profile (`deploy/docker-compose.prod.yml`) uses these
ceilings:

| Role | Memory | PIDs | CPU quota |
|---|---:|---:|---:|
| nginx load balancer | 256 MiB | 128 | 0.5 CPU |
| API replica | 2 GiB | 512 | 2 CPUs |
| PostgreSQL primary or replica | 2 GiB | 512 | 2 CPUs |
| Redis | 512 MiB | 256 | 0.5 CPU |

The default full stack uses the same role policy. The engine and Conductor
ceilings include room for legitimate Python worker, browser, and image/text
composition subprocesses while bounding the entire container process tree.
They are not a promise that an arbitrary workload fits; operators should size
the host and tune runtime admission below these ceilings.

## OOM and recovery semantics

A memory-limit breach is expected to kill the offending container process. The
Compose `restart: unless-stopped` policy then recreates long-running services;
it does not make the request or in-flight graph work succeed. The load balancer
removes an API replica when its readiness check fails, while `/health/live`
becomes available again only after the replacement process starts. PostgreSQL
and Redis recovery must be checked with their health checks before API traffic
is considered ready.

After pressure, operators should inspect the evidence before increasing a
limit:

```bash
docker inspect -f '{{.State.OOMKilled}} {{.RestartCount}}' <container>
docker compose -f deploy/docker-compose.prod.yml ps
docker compose -f deploy/docker-compose.prod.yml logs --tail=200 <service>
```

A PID ceiling can similarly terminate a process that cannot fork. This is a
contained service failure, not a host-wide recovery guarantee. The health and
restart behavior above is why health checks must remain attached to every
long-running profile service.

## Unsafe and tuning profiles

No supported production profile exposes an override that removes or makes
these controls effectively unbounded. A local operator may create an explicit
source-only development override for debugging, but that is outside the
installer and production support contract and must not be used to certify a
release. Performance tuning changes host size, concurrency admission, worker
counts, and service-specific values within the checked safety ranges; it does
not remove the containment ceiling.

The release soak should deliberately apply memory and process pressure to the
engine or Conductor and record `OOMKilled`/restart evidence, readiness recovery,
and that PostgreSQL and the host remain available. A green idle health check is
not pressure evidence.

## References

- `deploy/docker-compose.prod.yml` - production reference topology
- `docker-compose.yml` - default full stack
- `scripts/check-compose-resources.py` - rendered-profile policy gate
- [deployment topology](deployment-topology.md)
- [sizing guidance](sizing.md)
