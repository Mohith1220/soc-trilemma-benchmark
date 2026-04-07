# Pre-Submission Validation Checklist

## ✅ Environment Variables (inference.py)
- `HF_TOKEN`: `os.getenv("HF_TOKEN")` - NO default (line 34)
- `API_BASE_URL`: `os.getenv("API_BASE_URL", "https://mohith1220-soc-trilemma-benchmark.hf.space")` (line 35)
- `MODEL_NAME`: `os.getenv("MODEL_NAME", "meta-llama/Llama-3.3-70B-Instruct")` (line 36)

## ✅ OpenAI Client Usage
- Import: `from openai import OpenAI` (line 74)
- Client initialization: `OpenAI(base_url=f"{API_BASE_URL}/v1", api_key=HF_TOKEN)` (lines 76-78)

## ✅ Structured Stdout Logs
- `[START]` format: `[START] task={task_id} env={BENCHMARK} model={MODEL_NAME}` (line 142, 221)
- `[STEP]` format: `[STEP] step={n} action={action_str} reward={reward:.4f} done={done} error={error}` (line 184)
- `[END]` format: `[END] success={success} steps={n} score={score:.4f} rewards={rewards}` (line 202)
- All prints use `flush=True`

## ✅ 3+ Tasks with Graders
- `tasks/easy.yaml`: name=easy, grader with score_range [0.0, 1.0]
- `tasks/medium.yaml`: name=medium, grader with score_range [0.0, 1.0]
- `tasks/hard.yaml`: name=hard, grader with score_range [0.0, 1.0]

## ✅ Score Range Compliance
- YAML declares: `score_range: [0.0, 1.0]` (theoretical bounds)
- Python enforces: `_clamp` returns values in `(0.005, 0.995)` (actual runtime bounds)
- No rounding in `_clamp` to prevent boundary violations

## ✅ OpenEnv Spec Compliance
- `openenv.yaml`: name, version, entry_point, tasks list
- Typed models: Pydantic models in `app/models.py`
- Endpoints: `/reset`, `/step`, `/state`, `/health`, `/mcp`

## ✅ Dockerfile
- Base: `python:3.11`
- Non-root user: `appuser` (UID 1000)
- Port: 7860
- Healthcheck: `curl -f http://localhost:7860/health`
- CMD: `uvicorn app.app:app --host 0.0.0.0 --port 7860 --workers 1`

## ✅ Inference Script
- Location: `inference.py` (root directory)
- Wait for server: `wait_for_server()` polls `/health` for 60s
- Task env var: Reads `TASK_NAME` or `TASK` env var
- Timeout handling: Prints safe `[END] score=0.0050` on timeout

## ✅ Runtime Constraints
- Timeout: `wait_for_server` has 60s timeout, episode runs complete quickly
- Resources: Designed for vcpu=2, memory=8gb (FastAPI + single worker)

## ✅ Tests
- 114 tests passing
- Property-based tests with Hypothesis
- Integration tests for HTTP and WebSocket
- Unit tests for grader logic
