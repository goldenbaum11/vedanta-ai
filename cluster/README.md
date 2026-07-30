# Vedanta AI — Multi-Machine Inference Cluster

Pools GPU memory across multiple NVIDIA DGX Spark units to run models too
large for a single machine, via `llama.cpp`'s RPC backend (tensor-split
across the network). Designed to start at 2 nodes and grow.

## Architecture

```
                 200 Gb/s x2 (ConnectX, point-to-point, RDMA/RoCEv2)
  ┌──────────────┐  10.0.0.1 <──────────────> 10.0.0.2  ┌──────────────┐
  │ spark-5d09   │  10.0.1.1 <──────────────> 10.0.1.2  │ spark-593d   │
  │ role: master │                                       │ role: worker │
  │ llama-server │────RPC (--rpc 10.0.0.2:50052)────────▶│ggml-rpc-server│
  │ (OpenAI API) │                                       │ (GPU memory) │
  └──────┬───────┘                                       └──────────────┘
         │
         │ OPENAI_COMPATIBLE_BASE_URL (127.0.0.1:8080)
         ▼
  vedanta-ai backend (FastAPI, same machine)
```

- **master** (`spark-5d09`, user `vedantaai1`): runs `llama-server`, which
  exposes an OpenAI-compatible HTTP API (`/v1/chat/completions` etc.) that
  the vedanta-ai backend talks to. It offloads model layers it can't fit
  locally to one or more `ggml-rpc-server` workers over the interconnect.
- **worker** (`spark-593d`, user `vedantaai2`): runs `ggml-rpc-server`
  (the RPC backend binary — note it's *not* called `rpc-server` in current
  llama.cpp), which just exposes its GPU memory/compute to the master. No
  model files need to live on worker nodes — the master streams weights to
  them at load time.
- Both machines are identical NVIDIA GB10 (Grace Blackwell) units. CUDA
  reports **~124.6GB VRAM each** (unified memory exposed to CUDA) —
  combined, the cluster has **~245GB** to work with, enough for models in
  the ~100B–200B+ class that don't fit on one Spark alone.
- **Transport**: confirmed via worker logs that llama.cpp's RPC backend
  auto-negotiates **RDMA over RoCEv2** on the ConnectX NICs (not plain
  TCP) — near-native low-latency transport for tensor-split traffic.

Each pair of nodes is connected over **two independent 200Gb/s links**
(`10.0.0.x` and `10.0.1.x`, one per ConnectX port) — see
[nodes.yaml](./nodes.yaml) for the inventory. RPC traffic currently uses
just the first link; the second is available for a future bonded/aggregate
link if throughput becomes the bottleneck with larger models.

## Security notes (read before running on a new node)

`ggml-rpc-server` (the RPC/worker binary) has **no authentication**. Any
host that can reach the port has raw access to that GPU. Both scripts here
default to safe behavior, but if you customize them, keep these invariants:

- **Never bind `ggml-rpc-server` to `0.0.0.0`.** Bind only to the node's
  private interconnect IP (e.g. `10.0.0.2`). `start_worker.sh` defaults to
  `127.0.0.1` (safe but non-functional standalone) — the systemd unit sets
  the real interconnect IP explicitly via `Environment=BIND_HOST=...`.
- `llama-server` (the master's OpenAI-compatible API) also ships with no
  auth and permissive CORS by default. `start_master.sh` defaults to
  `127.0.0.1` (fine — the backend runs on the same machine) and **refuses
  to start** on any other `BIND_HOST` unless `API_KEY` is also set.
- We verified this in practice: with the worker bound to `10.0.0.2`, the
  RPC port is reachable from the master over the interconnect but times
  out / connection-refused from the peer's Wi-Fi IP.

## Prerequisites (per node)

- Ubuntu 24.04, CUDA 13.0 toolkit installed at `/usr/local/cuda` (already
  present on both Sparks as shipped by NVIDIA's DGX OS image; note it's
  not on `PATH` in non-interactive SSH sessions — `setup_node.sh` adds it)
- `cmake`, `gcc`/`g++`, `git`, `python3` (all present by default)
- Passwordless SSH from the master to every worker (see below)
- Interconnect link up with a static IP per [nodes.yaml](./nodes.yaml)

## One-time setup

### 1. SSH key auth from master → worker(s)

```bash
ssh-copy-id <worker_user>@<worker_interconnect_ip>
```

Verify: `ssh -o BatchMode=yes <worker_user>@<worker_ip> echo ok`

### 2. Build llama.cpp on every node (master AND workers)

```bash
cluster/setup_node.sh
```

**Idempotent and safe to re-run** — always pulls the latest `llama.cpp`
master branch and rebuilds with CUDA + RPC backend enabled
(`-DGGML_CUDA=ON -DGGML_RPC=ON`), and upgrades the Python venv
(`~/llama.cpp/.venv`) used for model download/conversion tooling to the
latest compatible package versions (`huggingface_hub[cli]` is pinned
`<1.0` — `transformers` requires that; an unconstrained upgrade breaks
`pip check`, learned the hard way during initial setup). Exact versions
built are recorded to `~/llama.cpp/setup_state.txt` for traceability.

Both nodes are currently built at `llama.cpp` commit `571d0d5`
(2026-07-19), `ggml` version 0.17.0, CUDA 13.0.88.

To run it on a remote node from the master:

```bash
scp cluster/setup_node.sh <user>@<worker_ip>:~/setup_node.sh
ssh <user>@<worker_ip> 'bash ~/setup_node.sh'
```

Rebuild takes several minutes (CUDA kernel compilation dominates).

## Running the cluster

Both roles run as **systemd user services** (not backgrounded shell
jobs) — a plain `nohup ... &` process was observed to die when its SSH
session closed on this DGX OS image, whereas a `systemd --user` service
survives disconnects and auto-restarts on failure.

### Worker: `llama-rpc-worker.service`

Already deployed and running on `spark-593d`:

```bash
scp cluster/llama-rpc-worker.service <user>@<worker_ip>:~/.config/systemd/user/
ssh <user>@<worker_ip> '
  mkdir -p ~/.config/systemd/user
  systemctl --user daemon-reload
  systemctl --user enable --now llama-rpc-worker.service
'
```

Check status: `ssh <user>@<worker_ip> systemctl --user status llama-rpc-worker`
Logs: `ssh <user>@<worker_ip> journalctl --user -u llama-rpc-worker -f`

**Edit the `BIND_HOST` in the `.service` file to match each new worker's
own interconnect IP before deploying it** (see nodes.yaml).

### Master: `llama-master.service` (deployed from `llama-master.service.template`)

Installed and running on `spark-5d09`. To (re)deploy after changing model
or config:

```bash
sed \
  -e "s|MODEL_PATH=/home/vedantaai1/models/CHANGE_ME.gguf|MODEL_PATH=<path>|" \
  -e "s|BIND_HOST=127.0.0.1|BIND_HOST=<127.0.0.1 or 172.17.0.1>|" \
  -e "s|SKIP_RPC=0|SKIP_RPC=<0 or 1>|" \
  cluster/llama-master.service.template > ~/.config/systemd/user/llama-master.service
systemctl --user daemon-reload
systemctl --user restart llama-master.service
```

- `BIND_HOST=127.0.0.1` if only the host (native processes) call it.
- `BIND_HOST=172.17.0.1` (docker0 bridge IP) if `docker-compose` services
  need to reach it via `host.docker.internal` — this is what we actually
  run, since the FastAPI backend runs in a container. **Never `0.0.0.0`.**
- `SKIP_RPC=1` for models that fit on one node (faster — no network hop
  per layer). `SKIP_RPC=0` to tensor-split across every worker in
  `nodes.yaml` — use this for models too large for one Spark's ~124.6GB.
- `API_KEY_FILE` points at `cluster/.llama_api_key.raw` (gitignored,
  `chmod 600`, raw key only, one line, no `KEY=` prefix). Passed via
  `--api-key-file` rather than `--api-key` deliberately — the latter
  leaks the key into `ps`/`systemctl status`/cmdline output, which we hit
  in practice during setup.

Check status: `systemctl --user status llama-master`
Logs: `journalctl --user -u llama-master -f`

### Standalone 32B tier (redundancy + concurrency): `llama-32b.service` + Traefik

Second, independent serving tier alongside the RPC-split master above —
see [`docs/adr/0002-serving-model-qwen3-235b-a22b.md`](../docs/adr/0002-serving-model-qwen3-235b-a22b.md)
for the full rationale. Where the RPC-split tier is one large model
(currently Qwen3-235B-A22B) spanning both nodes for maximum
capacity/quality, this tier runs the **same smaller model
(Qwen3-32B-Q8_0, ~34GB) independently on each node** — no RPC, no
cross-node dependency — so:

- **Redundancy**: either node can serve on its own if the other (or the
  RPC link) is down.
- **Concurrency**: two requests can be served in parallel, one per node,
  instead of one at a time.

```
        :8090 (Traefik, active health-checked)
        ┌────────────┴────────────┐
        ▼                         ▼
  master :8081               worker :8081
  llama-32b.service           llama-32b.service
  (SKIP_RPC=1, local model)   (SKIP_RPC=1, local model)
```

- `cluster/llama-32b-master.service.template` /
  `cluster/llama-32b-worker.service.template` — installed as
  `llama-32b.service` in `~/.config/systemd/user/` on master and worker
  respectively (same deploy pattern as `llama-master.service` above:
  copy, `daemon-reload`, `enable --now`). Both set `SKIP_RPC=1`, port
  `8081`, and point at a **local** copy of
  `models/qwen3-32b/Qwen3-32B-Q8_0.gguf` — the model has to actually
  exist on both nodes for this tier, unlike the RPC tier where only the
  master needs the file.
- `cluster/docker-compose.yml` + `cluster/traefik-dynamic.yml` — Traefik
  reverse-proxies `:8090` to `127.0.0.1:8081` (master) and
  `10.0.0.2:8081` (worker), with **active health checks** (polls each
  backend's `/health` every 5s and pulls a dead one out of rotation
  automatically — not passive/request-triggered like a plain nginx
  setup). Deliberately its own compose file, not part of the root
  `docker-compose.yml`: this container only proxies to host-run
  `llama-server` processes, it never runs a model itself, keeping the
  app-stack and cluster/LLM planes separate (see top-level `README.md`).
  Bring it up: `docker compose -f cluster/docker-compose.yml up -d`.
- Point the app at `http://host.docker.internal:8090/v1` (or
  `http://localhost:8090/v1` for a native backend) instead of `:8080` to
  use this tier instead of the RPC-split one.

Both `llama-32b.service` units carry `StartLimitIntervalSec=600` /
`StartLimitBurst=5` — caps runaway restarts if this tier ever wedges the
way the RPC-split master originally did (60+ restarts in one boot before
being root-caused; see ADR-002). Check with `systemctl --user status
llama-32b`; a unit stuck in `start-limit-hit` needs `systemctl --user
reset-failed llama-32b.service` once the underlying issue is fixed, not
just another restart.

### Bootstrap everything at once: `bootstrap.sh`

```bash
cluster/bootstrap.sh            # cluster + docker-compose app stack
cluster/bootstrap.sh --no-app   # cluster only
```

Nine checks, run in order, **every one always runs** (a failure in an
earlier section doesn't skip later sections — you get a full picture,
not just the first problem):

1. **Interconnect network** — pings every worker's interconnect IP
2. **RPC workers** — service active + RPC port reachable, per worker
3. **Master** — `llama-server` active + `/health` responding (waits up
   to `MODEL_LOAD_TIMEOUT_S`, default 600s, for large models to finish
   loading — this is not a fixed sleep, it polls and returns as soon as
   the server is ready)
4. **Model inference** — an actual chat completion request, not just a
   health check, so a wedged/corrupt model gets caught
5. **Standalone 32B tier** — `llama-32b.service` active on master and
   worker, each instance's `/health` responding independently
6. **LLM load balancer** — Traefik container running, `:8090` responding
7. **LLM tier test suite** — runs `cluster/test_llm_tiers.sh` (quick +
   thinking + unit categories) and folds each of its checks into this
   summary; see that script's header for what each category covers
8. **App stack** — `docker compose up`, backend `/health`, frontend
9. **Agent domain smoke tests** — one real message per domain
   (`vedic_scholar`, `sanskrit_grammar`, `communication`, `infosec`,
   `survival`, `media`) through the actual backend, asserting the
   classifier routed each to the right agent

Ends with a pass/fail summary and writes `cluster/.last_bootstrap_status`
(gitignored) with a timestamp + counts, so you can check the last run
without re-running it: `cat cluster/.last_bootstrap_status`.

This is idempotent and starts whatever isn't already running along the
way — it's the single entry point for "bring the whole thing up and
prove it actually works," whether that's after a reboot, a fresh
checkout, or just to sanity-check before telling anyone the app is
ready.

### Runs automatically on boot: `vedanta-bootstrap.service`

Deployed on the master as a oneshot systemd user service that runs
`bootstrap.sh` once at every login/boot (via `loginctl enable-linger`, so
it fires even without an interactive login):

```bash
cp cluster/vedanta-bootstrap.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable vedanta-bootstrap.service
```

It does **not** block or fail the boot sequence if a check fails
(`SuccessExitStatus=0 1`) — this is a diagnostic run, not a hard
dependency of anything else. Check the result any time:

```bash
journalctl --user -u vedanta-bootstrap -n 50   # full output of the last run
cat cluster/.last_bootstrap_status              # quick pass/fail + timestamp
```

Note: `llama-rpc-worker.service` and `llama-master.service` themselves
are separately `enable`d and come back on their own after a reboot
regardless of this service — `vedanta-bootstrap.service` exists
specifically to *verify* that happened correctly and that the model
actually responds, not to be the thing that starts them (though it will
start anything it finds not running, belt-and-suspenders).

### Wiring into the app

In `vedanta-ai/.env.docker` (used by `docker compose`, since the backend
runs in a container and reaches the host-native `llama-server` via the
Docker bridge):

```
LLM_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=http://host.docker.internal:8080/v1
OPENAI_COMPATIBLE_MODEL=            # leave empty to auto-pick loaded model
OPENAI_COMPATIBLE_API_KEY=<contents of cluster/.llama_api_key.raw>
```

(If running the backend natively instead of via Docker, use
`vedanta-ai/.env` with `OPENAI_COMPATIBLE_BASE_URL=http://localhost:8080/v1`.)

## Adding a new node later

1. Cable it into the interconnect and assign the next `/30` subnet.
2. Add an entry to [nodes.yaml](./nodes.yaml) with `role: worker`.
3. `ssh-copy-id` from the master, then run `cluster/setup_node.sh` on it.
4. Deploy `llama-rpc-worker.service` on it (edit `BIND_HOST` to its IP first).
5. Restart the master's `llama-server` — `start_master.sh` re-reads
   `nodes.yaml` via `parse_nodes.py` and rebuilds the `--rpc` list
   automatically.

## Validated so far

- [x] Interconnect links established and verified (`10.0.0.1↔10.0.0.2`,
      `10.0.1.1↔10.0.1.2`), 0% packet loss both links
- [x] Passwordless SSH from master to worker
- [x] llama.cpp built with CUDA+RPC on master (spark-5d09), commit `571d0d5`
- [x] llama.cpp built with CUDA+RPC on worker (spark-593d), commit `571d0d5`
- [x] `ggml-rpc-server` deployed as a systemd user service on the worker,
      bound only to the private interconnect IP (verified unreachable via
      Wi-Fi)
- [x] RPC connectivity smoke-tested end-to-end with a small test model
      (`Qwen2.5-0.5B-Instruct-GGUF`) — confirmed real compute dispatched to
      the worker's GPU (CUDA graph warmup in worker logs) over **RDMA/RoCEv2**,
      and a full chat completion round-trip through `llama-server`'s
      OpenAI-compatible API succeeded
- [x] Production model: **Qwen3-235B-A22B, UD-Q4_K_XL** (~134GB, 3-shard
      GGUF on the master), tensor-split across both nodes via
      `--rpc 10.0.0.2:50052`. Superseded Meta-Llama-3.1-405B-Instruct,
      which never fit the cluster's combined RAM with usable headroom —
      see [`docs/adr/0002-serving-model-qwen3-235b-a22b.md`](../docs/adr/0002-serving-model-qwen3-235b-a22b.md)
      for the full incident/decision writeup
- [x] Standalone redundant/concurrent tier added: Qwen3-32B-Q8_0 running
      independently on both nodes (`llama-32b.service`, `SKIP_RPC=1`),
      behind a Traefik load balancer (`cluster/docker-compose.yml`) on
      `:8090` with active health checks
- [x] `llama-master.service` installed and enabled on spark-5d09 for
      persistence — survives reboot/logout, confirmed via
      `systemctl --user status llama-master` (active, auto-restart)
- [x] `llama-rpc-worker.service` installed and enabled on spark-593d —
      running continuously for 1+ week uptime as of this check
- [x] App `.env` pointed at the cluster and validated against the actual
      vedanta-ai backend — `docker compose` stack (backend, frontend,
      postgres, chroma) running healthy against
      `OPENAI_COMPATIBLE_BASE_URL=http://host.docker.internal:8080/v1`
- [x] `vedanta-bootstrap.service` verified — last automated bootstrap run
      (see `cluster/.last_bootstrap_status`) passed all 15 checks

Current state: **the 2-node cluster is live in production**, not just
smoke-tested. Both systemd services are enabled (survive reboot) and the
app stack is actively serving through it.
