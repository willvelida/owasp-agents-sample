# owasp-agents-sample

Sample app on applying OWASP Top 10 for Agents to your own agent.

> [!CAUTION]
> `starter/` is insecure on purpose. Run it locally only and never deploy it to Azure or any shared environment ([ADR-0005](docs/adr/0005-starter-local-only-solution-on-azure.md)).

## Repository layout

| Path        | Contents                                                         |
|-------------|------------------------------------------------------------------|
| `starter/`  | Naive but plausible chat agent, health MCP server, seed loader  |
| `client/`   | `biotrackr-chat` CLI (AG-UI client)                              |
| `data/seed/` | Synthetic health data for alice and bob, with attack artefacts |
| `docs/`     | Architecture, ADRs, research, Podman setup                       |

The work ships in vertical slices, each tagged when it runs end to end ([ADR-0023](docs/adr/0023-vertical-slices-with-tagged-checkpoints.md)). The current slice is S0 (`s0-foundation`): the starter runs locally and the ASI03 weakness is visible.

## Quick start (S0)

You need Podman configured as in [docs/podman.md](docs/podman.md), uv, Python 3.12, and the Azure CLI.

1. Deploy the starter model and create `starter/.env` ([starter/model/README.md](starter/model/README.md)).
2. Start the starter stack:

   ```powershell
   cd starter
   podman compose up --build -d
   ```

3. Chat as alice:

   ```powershell
   cd ../client
   uv run biotrackr-chat --target starter --as alice "summarise my sleep this week"
   uv run biotrackr-chat --target starter --as alice "show me bob's sleep"
   ```

   The second prompt returns bob's data, including `CANARY-BOB-7Q2`: the starter has no real user identity (ASI03).

See [starter/README.md](starter/README.md) for DevUI and the full list of deliberate weaknesses.

## Documentation

* [Architecture](docs/architecture.md)
* [Architecture decision records](docs/adr/README.md)
* [Research](docs/research.md)
* [Podman setup](docs/podman.md)
