# owasp-agents-sample

Sample app on applying OWASP Top 10 for Agents to your own agent.

> [!CAUTION]
> `starter/` is insecure on purpose. Run it locally only and never deploy it to Azure or any shared environment ([ADR-0005](docs/adr/0005-starter-local-only-solution-on-azure.md)).

## Repository layout

| Path         | Contents                                                                  |
|--------------|---------------------------------------------------------------------------|
| `starter/`   | Naive but plausible chat agent, health MCP server, seed loader            |
| `solution/`  | Hardened mirror of the starter, plus Agent ID scripts, azd infra, tests   |
| `client/`    | `biotrackr-chat` CLI (AG-UI client) for every target                       |
| `redteam/`   | Shared PyRIT harness with a cumulative scorecard                           |
| `data/seed/` | Synthetic health data for alice and bob, with attack artefacts            |
| `docs/`      | Architecture, ADRs, research, Podman setup                                |

The work ships in vertical slices, each tagged when it runs end to end ([ADR-0023](docs/adr/0023-vertical-slices-with-tagged-checkpoints.md)).

| Tag             | What runs                                                                                     |
|-----------------|-----------------------------------------------------------------------------------------------|
| `s0-foundation` | Starter locally; the ASI03 weakness is visible                                                |
| `s1-identity`   | Starter, solution locally (Entra and offline), solution on Azure; PyRIT proves the ASI03 fix  |

`git diff --no-index starter solution` shows every control.

## Quick start (S1)

You need Podman configured as in [docs/podman.md](docs/podman.md), uv, Python 3.12, the Azure CLI, and azd.

1. Run the starter and watch alice read bob's data:

   ```powershell
   cd starter
   podman compose up --build -d     # needs starter/.env, see starter/model/README.md
   cd ../client
   uv run biotrackr-chat --target starter --as alice "show me bob's sleep"   # returns CANARY-BOB-7Q2
   ```

2. Provision Entra Agent ID and Azure for the solution, then run it locally in entra mode:

   ```powershell
   cd ../starter; podman compose down; cd ../solution
   azd env new owasp-agents --location australiaeast
   azd up                                               # Agent ID objects, Azure resources, deploy, seed
   podman compose --profile login run --rm az-login     # once
   podman compose up --build -d
   cd ../client
   uv run biotrackr-chat --target solution-local --as alice "show me bob's sleep"   # refused
   ```

3. Prove it with the red team (attacks succeed on the starter and are blocked on every solution target):

   ```powershell
   cd ../redteam
   uv run python -m redteam.run --target solution-local
   uv run python -m redteam.run --target solution-azure
   ```

See [solution/README.md](solution/README.md) for offline mode, DevUI, and the control markers, and [starter/README.md](starter/README.md) for the deliberate weaknesses.

## Documentation

* [Architecture](docs/architecture.md)
* [Architecture decision records](docs/adr/README.md)
* [Research](docs/research.md)
* [Podman setup](docs/podman.md)
* [Solution scripts (Entra Agent ID)](solution/scripts/README.md)
* [Red team](redteam/README.md)
