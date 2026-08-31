# Local Apple Studio

Private local NSFW image studio. Scene builder UI → natural-language Flux prompt → **Flux 2 Klein 9B** via **mflux** on Apple Silicon.

macOS + Docker Desktop + Metal. Linux checkouts cannot run generation.

## Layout

```
launcher.sh          # deploy/start/stop, model + LoRA import
frontend/            # FastAPI + static UI (Docker, no mflux)
  catalog/           # YAML: schemas, fragments, LoRAs, constraints
  src/               # compose, jobs, engine client, mflux wrapper
  web/               # vanilla HTML/CSS/JS
backend/             # loopback FastAPI; Metal; Seatbelt jail
lora.md              # LoRA filenames, triggers, SNOFS notes
prompts.md           # hand-tuned prompt experiments (not loaded by the app)
```

## Run

```
./launcher.sh --deploy | --start | --stop | --restart | --status | --logs
./launcher.sh --download-model [HF_TOKEN]
./launcher.sh --import-loras [ZIP]
```

- UI: `http://127.0.0.1:8080`
- Backend: `127.0.0.1:8090` (service account `ivoai`, `/opt/ivoai`)
- Frontend container is read-only; `/data` is tmpfs (outputs die with the container)
- After catalog or Python changes: rebuild/restart the frontend (`--restart`)

`ENGINE_MODE=local` runs mflux in-process (dev). Docker uses `ENGINE_MODE=remote`.

## Pipeline

1. UI loads `/api/schema?mode=` and `/api/defaults`.
2. Field changes debounce to `POST /api/compose` → sanitize → match LoRAs → `compose_prompt`.
3. `POST /api/generate` or `POST /api/recipe` queues a job.
4. Engine posts prompt, LoRAs, and ref images to the host backend.
5. `MfluxBackend` loads Flux2Klein or Edit on a dedicated MLX thread. System prefixes from `system_prompts.py` are prepended on the host.

Modes: **gen** (scratch), **edit** (restage), **undress** (clothes only), **pose** (identity photo + SNOFS). UI home is Generate vs Edit; Edit splits into Undress and Pose.

## Catalog first

The builder is YAML. Do not hard-code field lists in JS except chrome.

| File | Role |
|---|---|
| `pose_schema.yaml` | Pose-edit builder (`for:` on pose options = allowed `sex.category`) |
| `schema.yaml` | Gen builder |
| `undress_schema.yaml` | Undress builder |
| `edit_fragments.yaml` | Pose/edit prompt sentences |
| `fragments.yaml` | Gen prompt fragments |
| `constraints.yaml` | Last-write sanitizer; `on_select` snaps conflicting fields |
| `loras.yaml` | LoRA catalog (filenames, tags, triggers, `auto`, `default_loras`) |

Pose options use `for: [solo, anal, …]`. Changing `sex.category` hides illegal poses and snaps to a default (`POSE_DEFAULTS` in `web/js/app.js` must match `constraints.yaml`). Every pose Klein sees must keep **face, tits, pussy, anus, and both feet/heels** in frame. Do not add doggy/from-behind poses that hide heels or breasts.

`scenes.yaml` / pose plates are retired; keep `/api/scenes` shape stable.

## Prompt rules (Klein + SNOFS)

SNOFS is natural language, not tags. Prefer the words in `lora.md` (`anus`, `anal sex`, `vagina`/`pussy`, `penis`/`cock`, `photograph`).

- Say **photograph**, never **photorealistic**.
- Short, vulgar, concrete sentences. One visual per sentence. Do not paraphrase the same crotch three ways.
- Do not put measurements Klein cannot picture (`2cm`). Describe the picture: “strip of skin between her empty pussy and the cock in her anus.”
- Do not put “not a close-up of her crotch” in the **positive** (Flux draws mentioned tokens).
- Identity lock stays precise (face). Sex copy stays porn-caption, not clinical.
- System prefixes live in `system_prompts.py` and are applied on the host. Do not duplicate a long system lock in the user prompt.
- CFG negatives (`pose_negative_for`) must stay **short**. A kitchen-sink negative at guidance 2.0 melts anatomy.
- Pose/undress skip “deformed/grotesque” negatives (they fight gape/prolapse).

`prompts.md` is a human scratchpad. Wire a line into fragments only after it survives real gens.

## LoRAs

- Pose always pins **SNOFS** (`default_loras: [snofs]`, `max_loras: 2`).
- Anal / rectal-sleeve pose also pins **POV Anal** weights. Do **not** inject its reverse-cowgirl `prompt_trigger` (it fights frog-leg).
- `auto: false` = manual pin or default only. Specialists stay off unless tagged or pinned.
- Filenames and triggers: `lora.md` then `loras.yaml`.

## Code map

| Module | Job |
|---|---|
| `composer.py` | Scene dict → prompt |
| `constraints.py` | `sanitize_scene`, `blocked_options` |
| `lora_match.py` | Tag match vs files on disk |
| `system_prompts.py` | System prefix + CFG negatives |
| `engine.py` | Local mflux vs remote HTTP |
| `mflux_backend.py` | MLX thread, generate, negatives |
| `jobs.py` / `recipe.py` | Queue; undress→pose steps |
| `web/js/app.js` | Schema-driven UI |

## How to change behavior

- New field or pose: schema YAML + fragment YAML + `for:` / `constraints.yaml`. JS only if chrome or `POSE_DEFAULTS`.
- New LoRA: file in `/opt/ivoai/lora`, entry in `loras.yaml` / `lora.md`.
- Prompt wording: fragments + `system_prompts.py`. Check the UI prompt preview before declaring a gen “the new compose.”
- Backend jail / ports / service account: `launcher.sh` + `backend/sandbox.sb`.

No tests or CI in-tree. A compose smoke is:

```
cd frontend && PYTHONPATH=. python -c "from src.composer import compose_prompt; print(compose_prompt({...}, mode='pose'))"
```

Do not add README, tests, or refactors unless asked. Keep diffs scoped to the request.
