"""LLM backends for the UgcwAi planner server.

A backend is any object with a `complete(system_prompt, user_prompt) -> str` method that
returns the raw text of the model answer. A backend that can constrain its output to a JSON
schema sets `supports_schema = True` and accepts an extra `schema=` argument. To add your own backend (Anthropic API, Ollama,
any OpenAI-compatible server...), write a class like ClaudeCodeBackend and register it in
make_backend() below. Contributions are welcome.
"""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request


class BackendError(Exception):
    """Raised when a backend cannot produce an answer."""


class ClaudeCodeBackend:
    """Calls the Claude Code CLI in non-interactive mode (`claude -p`).

    - Uses your normal Claude login, so no API key is needed. We deliberately do not use
      --bare, because bare mode ignores subscription logins.
    - Tools are disabled (--disallowedTools "*"): the model only answers with text.
    - The default Claude Code system prompt is replaced (--system-prompt-file), because
      the model is acting as a battle commander, not as a coding assistant.
    - The user prompt is sent through stdin, which avoids command-line length limits.
    - Every call is a fresh, unsaved session (--no-session-persistence).
    """

    def __init__(self, command="claude", model="sonnet", effort=None, timeout_s=75,
                 workdir="claude_workdir", extra_args=None):
        exe = shutil.which(command)
        if exe is None:
            raise BackendError(
                f"'{command}' was not found in PATH. Install Claude Code and log in first "
                "(check with: claude --version, then: claude auth status).")
        self.exe = exe
        self.model = model
        self.effort = effort
        self.timeout_s = timeout_s
        # Run from an empty folder so no project CLAUDE.md, hooks or MCP servers get loaded.
        self.workdir = os.path.abspath(workdir)
        self.extra_args = list(extra_args or [])
        self.last_info = {}
        os.makedirs(self.workdir, exist_ok=True)

    def _write_system_prompt(self, system_prompt):
        path = os.path.join(self.workdir, "system_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() == system_prompt:
                    return path
        except OSError:
            pass
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(system_prompt)
        return path

    def complete(self, system_prompt, user_prompt):
        args = [self.exe, "-p",
                "--output-format", "json",
                "--disallowedTools", "*",
                "--no-session-persistence",
                "--system-prompt-file", self._write_system_prompt(system_prompt)]
        if self.model:
            args += ["--model", self.model]
        if self.effort:
            args += ["--effort", self.effort]
        args += self.extra_args
        try:
            proc = subprocess.run(args, input=user_prompt, capture_output=True, text=True,
                                  encoding="utf-8", timeout=self.timeout_s, cwd=self.workdir)
        except subprocess.TimeoutExpired:
            raise BackendError(f"claude timed out after {self.timeout_s}s")
        except OSError as e:
            raise BackendError(f"could not start claude: {e}")
        if proc.returncode != 0:
            detail = (proc.stderr.strip() or proc.stdout.strip())[:300]
            raise BackendError(f"claude exited with code {proc.returncode}: {detail}")
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            raise BackendError("claude did not return JSON: " + proc.stdout[:200])
        if payload.get("is_error") or payload.get("subtype", "success") != "success":
            raise BackendError("claude reported an error: " + str(payload.get("result", ""))[:300])
        self.last_info = {"cost_usd": payload.get("total_cost_usd"),
                          "session_id": payload.get("session_id"),
                          "usage": payload.get("usage") or {}}   # input, cache read/creation, output tokens
        return payload.get("result", "")


class OpenAICompatibleBackend:
    """Any server that speaks the OpenAI chat-completions API.

    Works with Ollama (default settings below), LM Studio, llama.cpp's llama-server, vLLM,
    OpenRouter and similar. Standard library only: no extra package to install.
    """

    def __init__(self, base_url="http://localhost:11434/v1", model="gemma4:12b", api_key="",
                 timeout_s=75, temperature=0.3, max_tokens=4096, json_mode=False,
                 reasoning_effort=None, extra_body=None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode              # asks the server for a JSON-only answer
        self.reasoning_effort = reasoning_effort  # e.g. "low" for thinking models
        self.extra_body = dict(extra_body or {})
        self.last_info = {}
        self._context_warned = False
        host = urllib.parse.urlparse(self.url).hostname
        if host in ("localhost", "127.0.0.1", "::1"):
            # Never route a local server through a system proxy.
            self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        else:
            self._opener = urllib.request.build_opener()

    def complete(self, system_prompt, user_prompt):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        body.update(self.extra_body)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"),
                                         headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise BackendError(f"server returned HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise BackendError(f"cannot reach {self.url} ({e.reason}). Is the server running?")
        except (OSError, ValueError) as e:  # timeout or invalid JSON
            raise BackendError(f"request failed: {e}")
        try:
            choice = payload["choices"][0]
            message = choice["message"]
            text = message.get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError):
            raise BackendError("unexpected response: " + json.dumps(payload)[:200])
        usage = payload.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        self.last_info = {"prompt_tokens": prompt_tokens,
                          "completion_tokens": usage.get("completion_tokens"),
                          "finish_reason": choice.get("finish_reason")}
        if isinstance(prompt_tokens, int) and prompt_tokens >= 3900 and not self._context_warned:
            self._context_warned = True
            print("  WARNING: the prompt uses ~%d tokens. If the server context is 4096 (Ollama's "
                  "default on GPUs under 24 GB), the prompt may be truncated: raise the context "
                  "length to 8192 or more." % prompt_tokens)
        if not text.strip():
            reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
            hints = []
            if reasoning:
                hints.append(f"the model wrote {len(reasoning)} characters of reasoning and no answer: "
                             "raise max_tokens or lower reasoning_effort")
            if choice.get("finish_reason") == "length":
                hints.append("generation stopped at the max_tokens limit")
            if isinstance(prompt_tokens, int) and prompt_tokens >= 3900:
                hints.append("the prompt may fill a 4096-token context window: raise the context length")
            raise BackendError("the model returned an empty answer ("
                               + ("; ".join(hints) or "no explanation available")
                               + f") [prompt_tokens={prompt_tokens}]")
        return text


class OllamaBackend:
    """Ollama's native chat API (/api/chat). Recommended way to use Ollama.

    Compared with the OpenAI-compatible endpoint, it lets us set for every request:
    - the context size (num_ctx). Ollama defaults to 4096 tokens on GPUs under 24 GB, which is
      too small for a prompt that includes the terrain map;
    - thinking (think). Thinking models (gemma4, qwen3, ...) spend their token budget on a
      reasoning trace before answering, which can leave the answer empty. We switch it off
      (use "low" for gpt-oss, which cannot switch it off);
    - structured output (format). The answer is constrained to the orders JSON schema, so it
      is always valid JSON.
    """

    supports_schema = True

    def __init__(self, base_url="http://localhost:11434", model="gemma4:12b", timeout_s=75,
                 temperature=0.2, num_ctx=16384, num_predict=1536, think=False,
                 use_schema=True, keep_alive="30m", **legacy):
        base = base_url.rstrip("/")
        if base.endswith("/v1"):   # tolerate the OpenAI-style URL of older config files
            base = base[:-3]
        self.url = base + "/api/chat"
        self.model = model
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.think = think            # False, True, "low"/"medium"/"high" (gpt-oss) or None
        self.use_schema = use_schema
        self.keep_alive = keep_alive  # keep the model loaded between planning cycles
        self.last_info = {}
        if legacy:
            print("  Ollama backend: ignoring unused settings: " + ", ".join(sorted(legacy)))
        host = urllib.parse.urlparse(self.url).hostname
        if host in ("localhost", "127.0.0.1", "::1"):
            self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        else:
            self._opener = urllib.request.build_opener()

    def _post(self, body):
        for attempt in (1, 2):
            request = urllib.request.Request(
                self.url, data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with self._opener.open(request, timeout=self.timeout_s) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code == 400 and "think" in body and "think" in detail.lower() and attempt == 1:
                    print("  This model does not accept the 'think' setting: retrying without it.")
                    del body["think"]
                    self.think = None
                    continue
                raise BackendError(f"Ollama returned HTTP {e.code}: {detail}")
            except urllib.error.URLError as e:
                raise BackendError(f"cannot reach {self.url} ({e.reason}). Is Ollama running?")
            except (OSError, ValueError) as e:  # timeout or invalid JSON
                raise BackendError(f"request failed: {e}")

    def complete(self, system_prompt, user_prompt, schema=None):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx,
                        "num_predict": self.num_predict},
        }
        if self.think is not None:
            body["think"] = self.think
        if schema is not None and self.use_schema:
            body["format"] = schema
        payload = self._post(body)
        message = payload.get("message") or {}
        text = message.get("content") or ""
        thinking = message.get("thinking") or ""
        prompt_tokens = payload.get("prompt_eval_count")
        self.last_info = {"prompt_tokens": prompt_tokens, "completion_tokens": payload.get("eval_count"),
                          "done_reason": payload.get("done_reason")}
        near_limit = isinstance(prompt_tokens, int) and prompt_tokens >= 0.9 * self.num_ctx
        if near_limit:
            print(f"  WARNING: the prompt uses {prompt_tokens} of the {self.num_ctx} tokens of the "
                  "context window: raise num_ctx (and the Ollama context length if you changed it).")
        if not text.strip():
            hints = []
            if thinking:
                hints.append(f"the model wrote {len(thinking)} characters of reasoning and no answer: set "
                             "think to false (or 'low' for gpt-oss) or raise num_predict")
            if payload.get("done_reason") == "length":
                hints.append("generation stopped at the num_predict limit")
            if near_limit:
                hints.append("the prompt fills the context window")
            raise BackendError("the model returned an empty answer ("
                               + ("; ".join(hints) or "no explanation available")
                               + f") [prompt_tokens={prompt_tokens}, "
                               f"completion_tokens={payload.get('eval_count')}]")
        return text


def make_backend(config):
    """Build the backend selected in config.json."""
    name = config.get("backend", "claude_code")
    if name == "claude_code":
        return ClaudeCodeBackend(**config.get("claude_code", {}))
    if name == "ollama":
        return OllamaBackend(**config.get("ollama", {}))
    if name == "openai_compatible":
        return OpenAICompatibleBackend(**config.get("openai_compatible", {}))
    raise BackendError(
        f"Unknown or not yet implemented backend: {name!r}. Available: ollama, "
        "openai_compatible, claude_code, placeholder (rule-based, no LLM). "
        "Planned: anthropic_api.")
