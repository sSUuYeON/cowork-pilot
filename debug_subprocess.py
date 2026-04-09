"""Minimal reproduction script for codex subprocess hang."""
import subprocess
import sys
import os

project_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

# Test 1: simplest possible codex exec via subprocess
print("=== Test 1: subprocess.run with capture_output=True ===")
cmd = [
    "codex", "exec",
    "--dangerously-bypass-approvals-and-sandbox",
    "--skip-git-repo-check",
    "-C", project_dir,
    "--json",
    "say hello",
]
print(f"Command: {' '.join(cmd)}")
print("Running with timeout=30s ...")
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    print(f"returncode: {result.returncode}")
    print(f"stdout (first 500): {result.stdout[:500]}")
    print(f"stderr (first 500): {result.stderr[:500]}")
except subprocess.TimeoutExpired:
    print("TIMEOUT after 30s — codex did not finish")
except FileNotFoundError:
    print("codex not found in PATH")
    print(f"PATH: {os.environ.get('PATH', '???')}")

print()

# Test 2: same but with stdin=DEVNULL
print("=== Test 2: subprocess.run with stdin=DEVNULL ===")
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    print(f"returncode: {result.returncode}")
    print(f"stdout (first 500): {result.stdout[:500]}")
    print(f"stderr (first 500): {result.stderr[:500]}")
except subprocess.TimeoutExpired:
    print("TIMEOUT after 30s — codex did not finish")
except FileNotFoundError:
    print("codex not found in PATH")

print()

# Test 3: Popen to see if process even starts
print("=== Test 3: Popen to check PID ===")
try:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    print(f"Process started, PID={proc.pid}")
    import time
    time.sleep(3)
    poll = proc.poll()
    if poll is None:
        print(f"Process still running after 3s (PID={proc.pid})")
        proc.kill()
        print("Killed")
    else:
        print(f"Process finished with returncode={poll}")
        out = proc.stdout.read().decode() if proc.stdout else ""
        err = proc.stderr.read().decode() if proc.stderr else ""
        print(f"stdout (first 500): {out[:500]}")
        print(f"stderr (first 500): {err[:500]}")
except FileNotFoundError:
    print("codex not found in PATH")
