"""Per-session conversation memory.

Plain in-memory store: enough for one server instance and for the course demo.
Trimmed to the last N turns so long chats can't blow up the context window,
and capped in session count so an open endpoint can't exhaust RAM.
"""

from collections import OrderedDict


class ConversationMemory:
    def __init__(self, max_turns: int = 10, max_sessions: int = 500):
        self._sessions: OrderedDict[str, list[dict]] = OrderedDict()
        self._max_messages = max_turns * 2  # a turn = user + assistant message
        self._max_sessions = max_sessions

    def history(self, session_id: str) -> list[dict]:
        messages = self._sessions.get(session_id, [])
        return list(messages)

    def append_turn(self, session_id: str, user_message: str, assistant_message: str) -> None:
        if session_id in self._sessions:
            self._sessions.move_to_end(session_id)
        messages = self._sessions.setdefault(session_id, [])
        messages.append({"role": "user", "content": user_message})
        messages.append({"role": "assistant", "content": assistant_message})
        if len(messages) > self._max_messages:
            del messages[: len(messages) - self._max_messages]
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)  # drop least recently used session

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
