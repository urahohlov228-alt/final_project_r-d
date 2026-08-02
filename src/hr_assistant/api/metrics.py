"""In-process metrics: enough to see what the service is doing at a glance.

Exposed as JSON at /metrics; Cloud Run's built-in dashboards cover
infrastructure-level metrics (CPU, instances, request latency histograms).
"""

import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Metrics:
    started_at: float = field(default_factory=time.time)
    requests_total: int = 0
    chat_requests_total: int = 0
    chat_blocked_total: int = 0
    chat_errors_total: int = 0
    rate_limited_total: int = 0
    routes: Counter = field(default_factory=Counter)
    tool_calls_total: int = 0
    llm_calls_total: int = 0
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    chat_latency_ms_sum: int = 0

    def record_chat(self, result) -> None:
        self.chat_requests_total += 1
        self.routes[result.route] += 1
        if result.blocked:
            self.chat_blocked_total += 1
        self.tool_calls_total += len(result.tool_calls)
        self.llm_calls_total += result.llm_calls
        self.prompt_tokens_total += result.prompt_tokens
        self.completion_tokens_total += result.completion_tokens
        self.chat_latency_ms_sum += result.elapsed_ms

    def snapshot(self) -> dict:
        chats = max(self.chat_requests_total, 1)
        return {
            "uptime_seconds": int(time.time() - self.started_at),
            "requests_total": self.requests_total,
            "chat": {
                "total": self.chat_requests_total,
                "blocked": self.chat_blocked_total,
                "errors": self.chat_errors_total,
                "rate_limited": self.rate_limited_total,
                "by_route": dict(self.routes),
                "avg_latency_ms": self.chat_latency_ms_sum // chats,
            },
            "llm": {
                "calls": self.llm_calls_total,
                "prompt_tokens": self.prompt_tokens_total,
                "completion_tokens": self.completion_tokens_total,
            },
            "tools": {"calls": self.tool_calls_total},
        }
