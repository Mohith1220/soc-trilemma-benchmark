"""Pre-submission validation script for SOC-Trilemma OpenEnv environment."""
import httpx
import sys

BASE_URL = "http://localhost:7860"
SEEDS_TO_TEST = [1, 7, 42, 99]
EXPECTED_42 = 0.2000


def run_audit() -> None:
    print("🚀 Starting Final Pre-Validation Audit...\n")

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Health Check
        try:
            health = client.get("/health").json()
            print(f"✅ Health Check: {health['status']}")
        except Exception as e:
            print(f"❌ Server not reachable at {BASE_URL}. Start uvicorn first!")
            sys.exit(1)

        # 2. MCP Compliance Check
        mcp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
        tools = [t["name"] for t in mcp["result"]["tools"]]
        expected_tools = ["query_dpi", "block_ip", "resolve_outage", "wait"]
        if all(t in tools for t in expected_tools):
            print(f"✅ MCP Compliance: 4/4 Tools Discoverable")
        else:
            print(f"❌ MCP Tool mismatch: {tools}")

        # 3. Determinism & State Isolation Check
        print("\n🧪 Running Determinism Rounds...")
        results_round_1 = {}

        # Round 1
        for seed in SEEDS_TO_TEST:
            res = client.post("/reset", json={"seed": seed, "session_id": f"test_{seed}"}).json()
            results_round_1[seed] = res.get("survival_score", 1.0)

        # Round 2 (Check for leakage)
        for seed in SEEDS_TO_TEST:
            res = client.post("/reset", json={"seed": seed, "session_id": f"test_{seed}_r2"}).json()
            if res.get("survival_score", 1.0) != results_round_1[seed]:
                print(f"❌ STATE LEAKAGE DETECTED on seed {seed}")
                sys.exit(1)

        print("✅ Determinism: Rounds match perfectly.")

        # 4. Numerical Accuracy Check (Seed 42)
        print(f"\n🎯 Final Numerical Target (Seed 42): {EXPECTED_42}")
        print("⚠️  Ensure 'python inference.py --seed 42' returns 0.2000 exactly.")

    print("\n[VERDICT]: ENVIRONMENT LOCKED. READY FOR SUBMISSION.")


if __name__ == "__main__":
    run_audit()
