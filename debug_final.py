"""Final isolation test: use the EXACT prompt from the pipeline."""
import subprocess
import sys
import os
import time

PROMPT_FILE = os.path.expanduser("~/codex_debug_prompt.txt")
PROJECT_DIR = "/Users/yeonsu/planningtest/chat"

if not os.path.exists(PROMPT_FILE):
    print(f"ERROR: {PROMPT_FILE} not found. Run cowork-pilot once first.")
    sys.exit(1)

with open(PROMPT_FILE) as f:
    real_prompt = f.read()

print(f"Prompt length: {len(real_prompt)} chars")
print(f"Prompt has {real_prompt.count(chr(10))} newlines")
print(f"Prompt preview: {repr(real_prompt[:100])}")
print()

# Test A: the EXACT real prompt, via stdin
print("=== Test A: Real prompt via stdin (timeout=120s) ===")
cmd = [
    "codex", "exec",
    "--dangerously-bypass-approvals-and-sandbox",
    "--skip-git-repo-check",
    "-C", PROJECT_DIR,
    "--json", "-",
]
print(f"Command: {' '.join(cmd)}")
t0 = time.time()
try:
    result = subprocess.run(cmd, input=real_prompt, capture_output=True, text=True, timeout=120)
    elapsed = time.time() - t0
    print(f"DONE in {elapsed:.1f}s, rc={result.returncode}")
    print(f"stdout lines: {len(result.stdout.splitlines())}")
    print(f"stdout[:300]: {result.stdout[:300]}")
    if result.stderr:
        print(f"stderr[:300]: {result.stderr[:300]}")
except subprocess.TimeoutExpired:
    elapsed = time.time() - t0
    print(f"TIMEOUT after {elapsed:.1f}s")
    # Check if JSONL was created
    session_dir = os.path.expanduser("~/.codex/sessions/2026/04/09")
    if os.path.exists(session_dir):
        files = sorted(os.listdir(session_dir))
        print(f"Session files in {session_dir}: {len(files)} (latest: {files[-1] if files else 'none'})")
    else:
        print(f"No session dir: {session_dir}")
print()

# Test B: the EXACT real prompt, via argv (for comparison)
print("=== Test B: Real prompt via argv (timeout=120s) ===")
cmd_argv = [
    "codex", "exec",
    "--dangerously-bypass-approvals-and-sandbox",
    "--skip-git-repo-check",
    "-C", PROJECT_DIR,
    "--json",
    real_prompt,
]
t0 = time.time()
try:
    result = subprocess.run(cmd_argv, capture_output=True, text=True, timeout=120)
    elapsed = time.time() - t0
    print(f"DONE in {elapsed:.1f}s, rc={result.returncode}")
    print(f"stdout lines: {len(result.stdout.splitlines())}")
    print(f"stdout[:300]: {result.stdout[:300]}")
except subprocess.TimeoutExpired:
    elapsed = time.time() - t0
    print(f"TIMEOUT after {elapsed:.1f}s")
print()

# Test C: short prompt via stdin (sanity check)
print("=== Test C: Short prompt via stdin (timeout=60s) ===")
t0 = time.time()
try:
    result = subprocess.run(
        ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "-C", PROJECT_DIR, "--json", "-"],
        input="say hello",
        capture_output=True, text=True, timeout=60,
    )
    elapsed = time.time() - t0
    print(f"DONE in {elapsed:.1f}s, rc={result.returncode}")
    print(f"stdout[:200]: {result.stdout[:200]}")
except subprocess.TimeoutExpired:
    elapsed = time.time() - t0
    print(f"TIMEOUT after {elapsed:.1f}s")
