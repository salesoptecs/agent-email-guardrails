"""Run Claude (Claude Code, headless) against your Salesforce sandbox or dev org through this MCP server and save the
transcript. This is the harness we used for the test in the video.

  python run_agent.py <name> <plain|guarded> "<prompt>" [--resume <session_id>] [--model <model>]

  plain    the server as-is
  guarded  the three guardrails on (hidden margin/commission fields, write allow list, untrusted-content labels)

Salesforce credentials come from your environment (SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN, optional SF_DOMAIN=test)
and reach the server through a temp config that is deleted afterwards; they are never printed.
Writes raw/<name>.jsonl (stream-json) and prints the tool calls, results and Claude's replies."""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "raw")
SF_ENV = ["SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN", "SF_DOMAIN"]
TOOLS = ["sf_query", "sf_query_all", "sf_describe", "sf_get_record", "sf_search", "sf_update"]


def main():
    name, mode, prompt = sys.argv[1], sys.argv[2], sys.argv[3]
    resume = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else None
    env = {k: os.environ[k] for k in SF_ENV if os.environ.get(k)}
    if mode == "guarded":
        env.update(SF_GUARDRAILS="1", SF_HIDDEN_FIELDS="Margin__c,Commission_Rate__c",
                   SF_WRITABLE_FIELDS="Opportunity:NextStep,Description,CloseDate;Task:Subject,Description,Status,ActivityDate")
    cfg = {"mcpServers": {"salesforce": {"command": "python", "args": [os.path.join(HERE, "salesforce_mcp_server.py")], "env": env}}}
    fd, cfg_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f)
    try:
        cmd = ["claude", "-p", prompt, "--mcp-config", cfg_path, "--strict-mcp-config", "--output-format", "stream-json",
               "--verbose", "--allowedTools", ",".join("mcp__salesforce__" + t for t in TOOLS), "--max-turns", "25",
               "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Task"]
        if resume:
            cmd += ["--resume", resume]
        if "--model" in sys.argv:
            cmd += ["--model", sys.argv[sys.argv.index("--model") + 1]]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=HERE, timeout=900, shell=True)
    finally:
        os.remove(cfg_path)
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, name + ".jsonl"), "w", encoding="utf-8").write(r.stdout)
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for c in ev["message"]["content"]:
                if c["type"] == "text":
                    print("CLAUDE:", c["text"].strip()[:1200])
                elif c["type"] == "tool_use":
                    print("TOOL  :", c["name"].replace("mcp__salesforce__", ""), json.dumps(c["input"])[:300])
        elif ev.get("type") == "user":
            for c in ev["message"]["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    body = c["content"] if isinstance(c["content"], str) else " ".join(x.get("text", "") for x in c["content"])
                    print("RESULT:", body.strip()[:400].replace("\n", " "))
        elif ev.get("type") == "result":
            print(f"== session {ev.get('session_id')} | turns {ev.get('num_turns')} | {ev.get('duration_ms', 0) / 1000:.0f}s"
                  f" | ${ev.get('total_cost_usd', 0):.3f}")
    if r.returncode:
        print("stderr:", r.stderr[-800:])


if __name__ == "__main__":
    main()
