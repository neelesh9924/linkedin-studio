"""Stands in for claude.exe in tests. Behaviour is picked by FAKE_MODE.

echo     emit init + a result whose marker block reports argv, stdin and env
hang     start a child Python that sleeps, record both pids, then sleep (for kill tests)
garbage  a result with no marker block
nolist   init event whose skills list lacks the requested skill
"""
import json
import os
import subprocess
import sys
import time

mode = os.environ.get("FAKE_MODE", "echo")
stdin = sys.stdin.read()


def emit(ev):
    print(json.dumps(ev), flush=True)


skills = [] if mode == "nolist" else ["linkedin-humanizer", "linkedin-interviewer", "linkedin-post-writer"]
emit({"type": "system", "subtype": "init", "session_id": "sess-123", "skills": skills})

if mode == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.environ["FAKE_PIDFILE"], "w") as f:
        json.dump({"parent": os.getpid(), "child": child.pid}, f)
    time.sleep(120)

emit({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Skill", "input": {"skill": "linkedin-humanizer"}}]}})
emit({"type": "user", "message": {"content": [{"type": "tool_result", "content": "Launching skill"}]}})
emit({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Read", "input": {"file_path": "C:\\skills\\references\\<b>story-bank.md"}}]}})
emit({"type": "user", "message": {"content": [{"type": "tool_result", "content": "file text"}]}})
if mode == "garbage":
    text = "Here is a rewrite but I forgot the block."
else:
    report = {"argv": sys.argv[1:], "stdin": stdin, "config_dir": os.environ.get("CLAUDE_CONFIG_DIR"),
              "env_keys": sorted(os.environ)}
    text = "Done.\n<<<STUDIO_JSON\n" + json.dumps(report) + "\nSTUDIO_JSON>>>"
emit({"type": "result", "subtype": "success", "is_error": False, "num_turns": 2, "session_id": "sess-123",
      "result": text, "total_cost_usd": 0.01, "permission_denials": [],
      "usage": {"input_tokens": 5, "output_tokens": 7}})
