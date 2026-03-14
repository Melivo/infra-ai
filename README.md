# infra-ai

Minimales lokales Inference-Backend fuer `Qwen/Qwen3-32B` mit `vLLM` und OpenAI-kompatibler API auf:

`http://localhost:8000/v1`

## Struktur

```text
infra-ai/
  vllm/
    docker-compose.yml
    start.sh
    .env
  scripts/
    test_inference.py
    healthcheck.sh
  README.md
```

## Runtime-Pfade

Die Laufzeitdaten liegen bewusst ausserhalb von Git:

- Modelle: `~/.ai/models`
- Cache: `~/.ai/cache`
- Logs: `~/.ai/logs`

## Starten

1. Optional Hugging Face Token in [vllm/.env](/home/visimeos/Projects/infra-ai/vllm/.env) setzen.
2. Server starten:

```bash
cd ~/Projects/infra-ai/vllm
./start.sh
```

Der Container heisst `vllm-qwen` und exponiert Port `8000`.

## API testen

Healthcheck:

```bash
cd ~/Projects/infra-ai
./scripts/healthcheck.sh
```

Inference-Test mit dem offiziellen Python-Client:

```bash
cd ~/Projects/infra-ai
python3 -m pip install openai
python3 scripts/test_inference.py
```

Der Python-Test nutzt:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="local",
)
```

## Pre-commit

Lokale Checks einrichten:

```bash
cd ~/Projects/infra-ai
python3 -m pip install pre-commit
pre-commit install
```

Alle Checks manuell laufen lassen:

```bash
cd ~/Projects/infra-ai
pre-commit run --all-files
```

Enthalten sind:

- `shellcheck` fuer Shell-Scripts
- `bash -n` fuer Shell-Syntax
- Python-Kompilierung fuer `scripts/test_inference.py`
- `docker compose config` fuer die vLLM-Compose-Datei

## Hinweise

- Das Setup ist absichtlich minimal und nur auf den lokalen Inference-Backend-Pfad fokussiert.
- Die vLLM-Parameter sind fuer eine einzelne RTX 4090 (24 GB VRAM) abgestimmt.
- `--trust-remote-code` ist fuer `Qwen/Qwen3-32B` aktiviert.
