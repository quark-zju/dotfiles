"""Detect agent metadata from supported coding-agent sessions."""

"""Append agent metadata (model, harness, prompt) to git commit messages"""

import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
import time
from typing import Dict, Iterable

PARENT_COMMIT_SCAN_LIMIT = 16
KIMI_SESSION_MAX_AGE_SECONDS = 3600
SAME_AS_BEFORE_EN = "(same as before)"
SAME_AS_BEFORE_ZH = "(同上)"
SAME_AS_BEFORE_VALUES = {SAME_AS_BEFORE_EN, SAME_AS_BEFORE_ZH}
EXEC_CMD_RE = re.compile(
    r'(?:\{|,)\s*(?:"cmd"|cmd)\s*:\s*"(?P<exec_cmd>(?:\\.|[^"\\])*)"'
)
GIT_COMMIT_RE = re.compile(r"(?:^|&&|\|\||;|\n|\\n)\s*git\s+commit\b")

# Derived from https://github.com/casonadams/opencode-secret-redactor/blob/main/src/patterns.ts
#
# MIT License
# Copyright (c) 2026 Cason Adams
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
SECRET_PATTERNS = [
    ("gitlab_pat", re.compile(r"glpat-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_pipeline_trigger", re.compile(r"glptt-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_deploy_token", re.compile(r"gldt-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_ci_job_token", re.compile(r"glcbt-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_runner_token", re.compile(r"glrt-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_service_account", re.compile(r"glsoat-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_feed_token", re.compile(r"glft-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_incoming_mail", re.compile(r"glimt-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_oauth_secret", re.compile(r"gloas-[A-Za-z0-9\-_]{20,}")),
    ("gitlab_agent_token", re.compile(r"glagent-[A-Za-z0-9\-_]{20,}")),
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{36,}")),
    ("github_oauth", re.compile(r"gho_[A-Za-z0-9]{36,}")),
    ("github_app_token", re.compile(r"ghu_[A-Za-z0-9]{36,}")),
    ("github_app_install", re.compile(r"ghs_[A-Za-z0-9]{36,}")),
    ("github_fine_grained", re.compile(r"github_pat_[A-Za-z0-9_]{22,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "aws_secret_key",
        re.compile(
            r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY|SecretAccessKey)"
            r"[=:\s\"']+([A-Za-z0-9/+=]{40})"
        ),
    ),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("openai_project_key", re.compile(r"sk-proj-[A-Za-z0-9\-_]{20,}")),
    (
        "openai_key",
        re.compile(r"sk-(?!ant-)(?!proj-)[A-Za-z0-9]{20,}"),
    ),
    ("cohere_key", re.compile(r"co-[A-Za-z0-9]{30,}")),
    ("huggingface_token", re.compile(r"hf_[A-Za-z0-9]{30,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("google_oauth_secret", re.compile(r"GOCSPX-[A-Za-z0-9\-_]{28}")),
    ("gcloud_access_token", re.compile(r"ya29\.[A-Za-z0-9\-_]{50,}")),
    ("google_refresh_token", re.compile(r"1//[A-Za-z0-9\-_]{40,}")),
    ("digitalocean_pat", re.compile(r"dop_v1_[a-f0-9]{64}")),
    ("digitalocean_oauth", re.compile(r"doo_v1_[a-f0-9]{64}")),
    ("hashicorp_vault", re.compile(r"hvs\.[A-Za-z0-9]{24,}")),
    (
        "heroku_api_key",
        re.compile(
            r"(?:HEROKU_API_KEY|heroku_api_key)[=:\s\"']+"
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
        ),
    ),
    ("vercel_token", re.compile(r"vercel_[A-Za-z0-9]{24,}")),
    ("slack_token", re.compile(r"xox[bpors]-[A-Za-z0-9-]{10,}")),
    (
        "slack_webhook",
        re.compile(r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"),
    ),
    ("twilio_api_key", re.compile(r"SK[a-f0-9]{32}")),
    (
        "sendgrid_key",
        re.compile(r"SG\.[A-Za-z0-9\-_]{22,}\.[A-Za-z0-9\-_]{22,}"),
    ),
    ("postman_key", re.compile(r"PMAK-[A-Za-z0-9-]{50,}")),
    ("datadog_api_key", re.compile(r"dd[a-z]{1,2}_[A-Za-z0-9]{32,40}")),
    ("stripe_secret", re.compile(r"sk_(?:test|live)_[A-Za-z0-9]{10,}")),
    ("stripe_restricted", re.compile(r"rk_(?:test|live)_[A-Za-z0-9]{10,}")),
    ("stripe_webhook", re.compile(r"whsec_[A-Za-z0-9]{32,}")),
    ("square_access_token", re.compile(r"sq0atp-[A-Za-z0-9\-_]{22,}")),
    ("square_oauth", re.compile(r"sq0csp-[A-Za-z0-9\-_]{43}")),
    ("npm_token", re.compile(r"npm_[A-Za-z0-9]{36,}")),
    ("pypi_token", re.compile(r"pypi-[A-Za-z0-9\-_]{50,}")),
    ("rubygems_key", re.compile(r"rubygems_[A-Za-z0-9]{48}")),
    (
        "jwt",
        re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\." r"[A-Za-z0-9_-]{10,}"
        ),
    ),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*")),
    ("basic_auth", re.compile(r"Basic\s+[A-Za-z0-9+/]{10,}={0,2}")),
    (
        "private_key",
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|ED25519\s+|DSA\s+)?PRIVATE\s+KEY-----"
            r"[\s\S]*?"
            r"-----END\s+(?:RSA\s+|EC\s+|ED25519\s+|DSA\s+)?PRIVATE\s+KEY-----"
        ),
    ),
    (
        "database_url",
        re.compile(
            r"(?:postgres|postgresql|mysql|mongodb|mongodb\+srv|redis)://"
            r"[^:\s]+:[^@\s]+@[^\s]+"
        ),
    ),
    (
        "sentry_dsn",
        re.compile(r"https://[a-f0-9]{32}@[^\s/]+\.ingest\.sentry\.io/[0-9]+"),
    ),
    ("grafana_api_key", re.compile(r"glc_[A-Za-z0-9\-_]{32,}")),
    ("doppler_token", re.compile(r"dp\.st\.[A-Za-z0-9_-]{40,}")),
    (
        "azure_connection_string",
        re.compile(
            r"DefaultEndpointsProtocol=https?;AccountName=[^;\s]+;"
            r"AccountKey=[A-Za-z0-9+/]{86}==[^\s\"']*"
        ),
    ),
    ("azure_storage_key", re.compile(r"AccountKey=([A-Za-z0-9+/]{86}==)")),
    ("azure_sas_token", re.compile(r"[?&]sig=([A-Za-z0-9%+/=]{40,})")),
    ("shopify_access_token", re.compile(r"shpat_[a-fA-F0-9]{20,}")),
    ("shopify_custom_app", re.compile(r"shpca_[a-fA-F0-9]{20,}")),
    ("shopify_private_app", re.compile(r"shppa_[a-fA-F0-9]{20,}")),
    ("shopify_shared_secret", re.compile(r"shpss_[a-fA-F0-9]{20,}")),
    ("mailgun_api_key", re.compile(r"key-[a-z0-9]{30,}")),
    ("mailchimp_api_key", re.compile(r"[a-f0-9]{32}-us\d{1,2}")),
    ("linear_api_key", re.compile(r"lin_api_[A-Za-z0-9]{40,}")),
    (
        "terraform_cloud_token",
        re.compile(r"[A-Za-z0-9]{14}\.atlasv1\.[A-Za-z0-9\-_]{60,}"),
    ),
    ("pulumi_token", re.compile(r"pul-[a-f0-9]{40}")),
    ("docker_pat", re.compile(r"dckr_pat_[A-Za-z0-9\-_]{24,}")),
    ("age_secret_key", re.compile(r"AGE-SECRET-KEY-1[A-Za-z0-9]{58}")),
    (
        "ssh_public_key",
        re.compile(r"ssh-(?:rsa|ed25519|dss)\s+[A-Za-z0-9+/]{60,}={0,2}"),
    ),
    (
        "ssh_ecdsa_key",
        re.compile(r"ecdsa-sha2-nistp(?:256|384|521)\s+[A-Za-z0-9+/]{60,}={0,2}"),
    ),
    (
        "hostname",
        re.compile(
            r"(?<![A-Za-z0-9._%+@:-])"
            r"(?:[A-Za-z0-9._%+-]+(?::\d{1,5})?@)?"
            r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
            r"(?:com|net|org)(?![A-Za-z0-9.-])",
            re.IGNORECASE,
        ),
    ),
    (
        "email",
        re.compile(r"(?<![:/])[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    ),
    (
        "credit_card",
        re.compile(
            r"\b(?:4[0-9]{3}|5[1-5][0-9]{2}|3[47][0-9]{2}|"
            r"6(?:011|5[0-9]{2}))[-\s]?[0-9]{4}[-\s]?[0-9]{4}"
            r"[-\s]?[0-9]{3,4}\b"
        ),
    ),
    ("us_ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "phone_us",
        re.compile(r"\+1[-.\s]?\(?[2-9]\d{2}\)?[-.\s]?[2-9]\d{2}[-.\s]?\d{4}"),
    ),
    (
        "env_secret",
        re.compile(
            r"(?:PASSWORD|PASSWD|SECRET|API_KEY|PRIVATE_KEY|ACCESS_KEY|AUTH_TOKEN|"
            r"ENCRYPTION_KEY|SIGNING_KEY|DB_PASSWORD|DATABASE_PASSWORD)\s*[=:]\s*"
            r"[\"']?([^\s\"']{8,})[\"']?",
            re.IGNORECASE,
        ),
    ),
]


def get_agent_env() -> Dict[str, str]:
    return (
        get_opencode_env()
        or get_codex_env()
        or get_zed_env()
        or get_claude_code_env()
        or get_dsh_env()
        or get_kimi_code_env()
    )


def get_opencode_env() -> Dict[str, str]:
    env = {}
    # Those env vars are written by the opencode plugin
    # .config/opencode/plugins/set-agent-model-env.ts
    prompt = os.getenv("AGENT_PROMPT", "").strip()
    model = os.getenv("AGENT_MODEL", "").strip()
    if prompt:
        env["Agent-Prompt"] = prompt
    if model:
        env["Agent-Model"] = model
    if prompt or model or os.getenv("OPENCODE_SESSION_ID"):
        env["Agent-Harness"] = "opencode"
    return env


def match_obj(obj, template, matched_out) -> bool:
    if (
        isinstance(template, str)
        and template.startswith("$")
        and matched_out is not None
    ):
        matched_out[template] = obj
        return True
    if type(obj) is not type(template):
        return False
    if isinstance(template, dict):
        for key, val in template.items():
            if key not in obj or not match_obj(obj[key], val, matched_out):
                return False
        return True
    else:
        return obj == template


def get_codex_env() -> Dict[str, str]:
    env = {}
    thread_id = os.getenv("CODEX_THREAD_ID")
    if not thread_id:
        return env
    # Read from codex sessions
    session_files = list(
        glob.glob(
            os.path.expanduser(f"~/.codex/sessions/**/*{thread_id}*.jsonl"),
            recursive=True,
        )
    )
    if not session_files:
        return env
    session_file = session_files[0]
    with open(session_file, "r") as f:
        lines = f.readlines()
    model = None
    prompt = []
    seen_git_commit = False
    for line in reversed(lines):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = {}
        if not model:
            # {"type":"turn_context","payload":{"turn_id":...,"model":"gpt-5.3-codex",...}}
            if match_obj(
                data, {"type": "turn_context", "payload": {"model": "$model"}}, out
            ):
                model = out.get("$model", "").strip()
        if not seen_git_commit:
            # {"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":...}]}}
            # {"type":"event_msg","payload":{"type":"user_message","message":...}}
            if match_obj(
                data,
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "$user_message"},
                },
                out,
            ):
                user_message = out.get("$user_message", "").strip()
                if user_message:
                    prompt.append(user_message)
            elif match_obj(
                data,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": "$content",
                        "internal_chat_message_metadata_passthrough": {
                            "content_item_kinds": "$content_item_kinds"
                        },
                    },
                },
                out,
            ):
                content = out.get("$content")
                content_item_kinds = out.get("$content_item_kinds")
                if isinstance(content, list) and isinstance(content_item_kinds, list):
                    user_text_parts = []
                    for item, kind in zip(content, content_item_kinds):
                        text_match = {}
                        if kind == "user.text" and match_obj(
                            item,
                            {"type": "input_text", "text": "$text"},
                            text_match,
                        ):
                            text = text_match.get("$text", "").strip()
                            if text:
                                user_text_parts.append(text)
                    if user_text_parts:
                        prompt.append("\n".join(user_text_parts))
            git_commit = False
            # {"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\"cmd\":\"git commit -m ...\"}"}}
            if match_obj(
                data,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": "$exec_cmd",
                    },
                },
                out,
            ):
                exec_cmd = out.get("$exec_cmd", "")
                git_commit = "git commit" in exec_cmd
            # {"type":"response_item","payload":{"type":"custom_tool_call","name":"exec","input":"const r = await tools.exec_command({\"cmd\":\"git commit -m ...\"});"}}
            elif match_obj(
                data,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "input": "$exec_input",
                    },
                },
                out,
            ):
                exec_input = out.get("$exec_input", "")
                git_commit = any(
                    GIT_COMMIT_RE.search(match.group("exec_cmd"))
                    for match in EXEC_CMD_RE.finditer(exec_input)
                )

            if git_commit:
                # Only use git commit as a boundary after we've already seen
                # at least one prompt message while scanning backwards.
                if prompt:
                    seen_git_commit = True
        if model and seen_git_commit:
            break
    if prompt:
        prompt_text = "\n----\n".join(reversed(prompt))
        env["Agent-Prompt"] = prompt_text
    if model:
        env["Agent-Model"] = model
    if prompt or model:
        env["Agent-Harness"] = "codex"
    return env


def get_claude_code_env() -> Dict[str, str]:
    env = {}
    session_id = os.getenv("CLAUDE_CODE_SESSION_ID")
    if not session_id:
        return env
    # Claude Code writes one transcript per session under a cwd-munged dir;
    # glob by session id to avoid replicating the dir-munging rule.
    session_files = list(
        glob.glob(
            os.path.expanduser(f"~/.claude/projects/**/*{session_id}*.jsonl"),
            recursive=True,
        )
    )
    if not session_files:
        return env
    with open(session_files[0], "r") as f:
        lines = f.readlines()
    model = None
    prompt = []
    seen_git_commit = False
    for line in reversed(lines):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = {}
        if not model:
            if match_obj(
                data, {"type": "assistant", "message": {"model": "$model"}}, out
            ):
                model = out.get("$model", "").strip()
        if not seen_git_commit:
            # Real typed/queued prompts carry origin {"kind":"human"} and a string
            # content; tool results have origin=None and a list content.
            if match_obj(
                data,
                {
                    "type": "user",
                    "origin": {"kind": "human"},
                    "message": {"role": "user", "content": "$content"},
                },
                out,
            ):
                content = out.get("$content")
                if isinstance(content, str) and content.strip():
                    prompt.append(content.strip())
            # Only use git commit as a boundary after we've already seen at least
            # one prompt while scanning backwards (the in-flight commit that
            # triggered this hook is not yet in the transcript).
            turn = {}
            if prompt and match_obj(
                data, {"type": "assistant", "message": {"content": "$content"}}, turn
            ):
                content = turn["$content"]
                if isinstance(content, list):
                    for item in content:
                        cmd = {}
                        if (
                            match_obj(
                                item,
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {"command": "$command"},
                                },
                                cmd,
                            )
                            and "git commit" in cmd.get("$command", "").lower()
                        ):
                            seen_git_commit = True
                            break
        if model and seen_git_commit:
            break
    if prompt:
        env["Agent-Prompt"] = "\n----\n".join(reversed(prompt))
    if model:
        env["Agent-Model"] = model
    if prompt or model:
        env["Agent-Harness"] = "claude-code"
    return env


def paths_overlap(a: str, b: str) -> bool:
    try:
        common = os.path.commonpath([a, b])
    except ValueError:
        return False
    return common == a or common == b


def kimi_wire_has_activity(wire_path: str) -> bool:
    try:
        with open(wire_path, "r") as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("type") in {"turn.prompt", "llm.request"}:
                    return True
    except OSError:
        pass
    return False


def find_kimi_code_wire_file(cwd: str):
    # Kimi Code does not set env vars for its Bash tool subprocesses, so find
    # the session by matching cwd against the session cwd (or legacy workDir).
    # Sessions live under ~/.kimi-code/sessions/<workspace>/session_*/ with the main
    # transcript at agents/main/wire.jsonl.
    cwd = normalize_path(cwd)
    now = time.time()
    pattern = os.path.expanduser(
        "~/.kimi-code/sessions/*/session_*/agents/main/wire.jsonl"
    )
    candidates = []
    for wire_path in glob.glob(pattern):
        try:
            candidates.append((os.path.getmtime(wire_path), wire_path))
        except OSError:
            continue

    for mtime, wire_path in sorted(candidates, reverse=True):
        # Since candidates are newest-first, every remaining transcript is
        # stale once this one is stale.
        if now - mtime > KIMI_SESSION_MAX_AGE_SECONDS:
            break
        session_dir = os.path.dirname(os.path.dirname(os.path.dirname(wire_path)))
        state_path = os.path.join(session_dir, "state.json")
        try:
            with open(state_path, "r") as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        work_dir = normalize_path(str(state.get("cwd") or state.get("workDir") or ""))
        if not work_dir or not paths_overlap(cwd, work_dir):
            continue
        # Failed/overloaded starts can leave a newer initialization-only
        # session behind. Do not let it hide the latest usable transcript.
        if not kimi_wire_has_activity(wire_path):
            continue
        return wire_path
    return None


def kimi_text_from_input(raw) -> str:
    # Kimi Code currently stores content parts directly. Older pi-derived
    # builds may store the same value as JSON text, so accept both forms.
    if isinstance(raw, str):
        if not raw.strip():
            return ""
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if not isinstance(raw, list):
        return ""
    texts = [
        part.get("text", "").strip()
        for part in raw
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    return "\n".join(text for text in texts if text)


def kimi_loop_event(data):
    # Current Kimi Code stores event as an object; older pi-derived builds may
    # contain a JSON-encoded object instead.
    if data.get("type") != "context.append_loop_event":
        return None
    event = data.get("event")
    if isinstance(event, dict):
        return event
    if not isinstance(event, str):
        return None
    try:
        return json.loads(event)
    except json.JSONDecodeError:
        return None


def get_kimi_code_env(cwd: str = None) -> Dict[str, str]:
    env = {}
    cwd = normalize_path(cwd or os.getcwd())
    wire_path = find_kimi_code_wire_file(cwd)
    if not wire_path:
        return env
    try:
        with open(wire_path, "r") as f:
            lines = f.readlines()
    except OSError:
        return env
    model = None
    prompt = []
    seen_git_commit = False
    for line in reversed(lines):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = {}
        if not model:
            # {"type":"llm.request","model":"kimi-k3","modelAlias":"moonshot-ai/kimi-k3",...}
            if match_obj(data, {"type": "llm.request", "modelAlias": "$model"}, out):
                model = out.get("$model", "").strip()
        if not seen_git_commit:
            # {"type":"turn.prompt","input":[{"type":"text","text":...}],
            #  "origin":{"kind":"user"}}
            if match_obj(
                data,
                {"type": "turn.prompt", "origin": "$origin", "input": "$input"},
                out,
            ):
                origin = out.get("$origin")
                if isinstance(origin, str):
                    try:
                        origin = json.loads(origin)
                    except json.JSONDecodeError:
                        origin = {}
                if isinstance(origin, dict) and origin.get("kind") == "user":
                    text = kimi_text_from_input(out.get("$input"))
                    if text:
                        prompt.append(text)
            # Only use git commit as a boundary after we've already seen at least
            # one prompt while scanning backwards (the in-flight commit that
            # triggered this hook is not yet in the transcript).
            event = kimi_loop_event(data)
            if prompt and event:
                cmd = {}
                if match_obj(
                    event,
                    {
                        "type": "tool.call",
                        "name": "Bash",
                        "args": {"command": "$command"},
                    },
                    cmd,
                ) and GIT_COMMIT_RE.search(cmd.get("$command", "").lower()):
                    seen_git_commit = True
        if model and seen_git_commit:
            break
    if prompt:
        env["Agent-Prompt"] = "\n----\n".join(reversed(prompt))
    if model:
        env["Agent-Model"] = model
    if prompt or model:
        env["Agent-Harness"] = "kimi-code"
    return env


def get_dsh_env() -> Dict[str, str]:
    # DeepSeek Harness exports the current session transcript path to every
    # shell-tool subprocess as DSH_SESSION_JSONL (dsh-shell-env's
    # session-persistence contributor); only agent-driven commits carry it.
    session_jsonl = os.getenv("DSH_SESSION_JSONL", "").strip()
    if not session_jsonl:
        return {}
    try:
        with open(session_jsonl, "rb") as f:
            decoded = zstd_decompress(f.read())
    except OSError:
        return {}
    if decoded is None:
        return {}
    return dsh_env_from_lines(decoded.decode("utf-8", errors="replace").splitlines())


def dsh_env_from_lines(lines) -> Dict[str, str]:
    env = {}
    model = None
    prompt = []
    seen_git_commit = False
    for line in reversed(lines):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = {}
        if not model:
            # {"type":"request/header","data":{"header":{"config":{"model":"deepseek-v4-flash",...}}}}
            if match_obj(
                data,
                {
                    "type": "request/header",
                    "data": {"header": {"config": {"model": "$model"}}},
                },
                out,
            ):
                model = out.get("$model", "").strip()
        if not seen_git_commit:
            # {"type":"user/message","data":{"content":[{"type":"text","text":...}],
            #  "source":{"kind":"user",...}}} -- plugin-injected snapshots carry
            #  source.kind "plugin" and are not agent prompts.
            if match_obj(
                data,
                {
                    "type": "user/message",
                    "data": {"source": {"kind": "user"}, "content": "$content"},
                },
                out,
            ):
                content = out.get("$content")
                if isinstance(content, list):
                    texts = [
                        part.get("text", "").strip()
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ]
                    text = "\n".join(part for part in texts if part)
                    if text:
                        prompt.append(text)
            # Only use git commit as a boundary after we've already seen at
            # least one prompt while scanning backwards (the in-flight commit
            # that triggered this hook is not yet in the transcript).
            if prompt:
                call = {}
                if match_obj(
                    data,
                    {
                        "type": "tool/call",
                        "data": {"name": "bash", "arguments": "$arguments"},
                    },
                    call,
                ):
                    arguments = call.get("$arguments")
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = None
                    if isinstance(arguments, dict) and GIT_COMMIT_RE.search(
                        str(arguments.get("command") or "").lower()
                    ):
                        seen_git_commit = True
        if model and seen_git_commit:
            break
    if prompt:
        env["Agent-Prompt"] = "\n----\n".join(reversed(prompt))
    if model:
        env["Agent-Model"] = model
    if prompt or model:
        env["Agent-Harness"] = "dsh"
    return env


def default_zed_threads_db() -> str:
    return os.path.expanduser("~/Library/Application Support/Zed/threads/threads.db")


def normalize_path(value: str) -> str:
    if not value:
        return ""
    return os.path.realpath(os.path.expanduser(value))


def decode_zed_thread_data(data_type: str, data: bytes):
    if data_type == "json":
        return json.loads(data.decode("utf-8"))
    if data_type != "zstd":
        return None
    decoded = zstd_decompress(data)
    if decoded is None:
        return None
    return json.loads(decoded.decode("utf-8"))


def zstd_decompress(data: bytes):
    try:
        from compression import zstd

        return zstd.decompress(data)
    except (ImportError, ModuleNotFoundError):
        pass
    except Exception:
        pass

    try:
        return subprocess.check_output(
            ["zstd", "-dc"],
            input=data,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def zstd_compress(data: bytes):
    # Python 3.14 ships zstd in the standard library as compression.zstd;
    # fall back to the zstd CLI on older versions (mirrors zstd_decompress).
    try:
        from compression import zstd

        return zstd.compress(data)
    except (ImportError, ModuleNotFoundError):
        pass
    except Exception:
        pass

    try:
        return subprocess.check_output(["zstd", "-c"], input=data)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


HAS_ZSTD = zstd_compress(b"") is not None


def zed_text_from_content(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("Text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def zed_agent_message_has_git_commit(message) -> bool:
    if not isinstance(message, dict):
        return False
    agent = message.get("Agent")
    if not isinstance(agent, dict):
        return False
    content = agent.get("content")
    if not isinstance(content, list):
        return False
    for item in content:
        if not isinstance(item, dict):
            continue
        tool_use = item.get("ToolUse")
        if not isinstance(tool_use, dict):
            continue
        name = str(tool_use.get("name") or "")
        if name not in {"terminal", "bash"}:
            continue
        raw_input = tool_use.get("raw_input")
        input_obj = tool_use.get("input")
        command = ""
        if isinstance(input_obj, dict):
            command = str(input_obj.get("command") or "")
        if not command and isinstance(raw_input, str):
            try:
                command = str(json.loads(raw_input).get("command") or "")
            except json.JSONDecodeError:
                command = raw_input
        if "git commit" in command.lower():
            return True
    return False


def zed_env_from_thread(thread) -> Dict[str, str]:
    env = {}
    model = thread.get("model")
    model_name = ""
    if isinstance(model, dict):
        model_name = str(model.get("model") or "").strip()

    prompts = []
    seen_git_commit = False
    messages = thread.get("messages")
    if not isinstance(messages, list):
        messages = []
    for message in reversed(messages):
        if not seen_git_commit:
            if "User" in message:
                text = zed_text_from_content(message.get("User", {}).get("content"))
                if text:
                    prompts.append(text)
            if zed_agent_message_has_git_commit(message) and prompts:
                seen_git_commit = True
        if model_name and seen_git_commit:
            break

    if prompts:
        env["Agent-Prompt"] = "\n----\n".join(reversed(prompts))
    if model_name:
        env["Agent-Model"] = model_name
    if env:
        env["Agent-Harness"] = "zed"
    return env


def get_zed_env() -> Dict[str, str]:
    tmpdir = os.getenv("TMPDIR") or os.getenv("TMP") or os.getenv("TEMP")
    if not tmpdir:
        return {}
    if os.getenv("TERM_PROGRAM") != "zed" and not os.getenv("ZED_ENVIRONMENT"):
        return {}

    db_path = os.getenv("ZED_THREADS_DB") or default_zed_threads_db()
    if not os.path.exists(db_path):
        return {}

    normalized_tmpdir = normalize_path(tmpdir)
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("""
                select data_type, data
                from threads
                order by updated_at desc
                limit 32
                """).fetchall()
    except sqlite3.Error:
        return {}

    for data_type, data in rows:
        try:
            thread = decode_zed_thread_data(data_type, data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(thread, dict):
            continue
        thread_tmpdir = normalize_path(
            str(thread.get("sandboxed_terminal_temp_dir") or "")
        )
        if thread_tmpdir and thread_tmpdir == normalized_tmpdir:
            return zed_env_from_thread(thread)
    return {}


def parse_commit_env(commit_msg: str, keys: Iterable[str]) -> Dict[str, str]:
    env = {}
    key_set = set(keys)
    current_key = None
    current_value_lines = []

    def flush_current_key():
        if current_key:
            env[current_key] = "\n".join(current_value_lines).strip()

    for line in commit_msg.splitlines():
        if current_key:
            if line.startswith("    "):
                current_value_lines.append(line[4:])
                continue
            if line == "":
                continue
            flush_current_key()
            current_key = None
            current_value_lines = []
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key not in key_set:
            continue
        if value.strip():
            env[key] = value.strip()
        else:
            current_key = key
    flush_current_key()
    return env


def normalize_repeated_value(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.splitlines() if line.strip())
