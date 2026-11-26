"""
title: E2E Simuliertes Modell
description: Nur für den End-to-End-Test. Antwortet wie ein Provider nach Drehbuch, mit Usage und auf Wunsch mit Tool-Aufruf.
version: 1.0.0
"""

# Wird vom Test direkt über die API angelegt und nie mit scripts/deploy.py
# eingespielt. Die letzte Benutzernachricht ist ein Drehbuch als JSON:
#
#     {"reply": "Text",                       Antworttext
#      "usage": [eingabe, ausgabe, gecacht],   gemeldete Tokens der Antwort
#      "tool": {"name": "...", "arguments": {}},   optional: erst ein Tool aufrufen
#      "tool_usage": [eingabe, ausgabe, gecacht]}  Tokens der Runde mit dem Tool-Aufruf
#
# Wie ein echter Provider meldet die Pipe beim Streaming Tokens nur, wenn
# stream_options.include_usage gesetzt ist; das setzt der Budget-Filter. Die
# Antwort trägt dann den Vermerk [usage angefordert]. Steht ein Tool im
# Drehbuch, antwortet die Pipe zuerst mit einem Tool-Aufruf; Open WebUI führt
# das Tool aus und ruft die Pipe mit dem Ergebnis erneut auf. Die zweite
# Antwort enthält das Tool-Ergebnis.

import json
import time
import uuid

USAGE_MARK = "[usage angefordert]"


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content or "")


class Pipe:
    async def pipe(self, body: dict):
        messages = body.get("messages") or []
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        try:
            script = json.loads(_text(messages[last_user]["content"])) if last_user >= 0 else {}
        except ValueError:
            script = {}
        if not isinstance(script, dict):
            script = {}
        script.setdefault("reply", _text(messages[last_user]["content"]) if last_user >= 0 else "")
        results = [_text(m.get("content")) for m in messages[last_user + 1:] if m.get("role") == "tool"]
        streaming = bool(body.get("stream"))
        wants_usage = bool((body.get("stream_options") or {}).get("include_usage")) or not streaming

        tool = script.get("tool")
        offered = {t.get("function", {}).get("name") for t in body.get("tools") or []}
        if tool and not results:
            if tool.get("name") not in offered:
                return self._answer(body, f"Tool nicht angeboten: {tool.get('name')} (angeboten: {sorted(offered)})",
                                    script.get("usage"), wants_usage, streaming)
            call = {"index": 0, "id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                    "function": {"name": tool["name"], "arguments": json.dumps(tool.get("arguments") or {})}}
            return self._answer(body, None, script.get("tool_usage"), wants_usage, streaming, tool_call=call)

        reply = str(script["reply"])
        if results:
            reply = f"{reply} {results[-1]}".strip()
        if wants_usage:
            reply = f"{reply} {USAGE_MARK}"
        return self._answer(body, reply, script.get("usage"), wants_usage, streaming)

    @staticmethod
    def _usage(tokens) -> dict | None:
        if not tokens:
            return None
        prompt, completion, cached = (list(tokens) + [0, 0, 0])[:3]
        return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
                "prompt_tokens_details": {"cached_tokens": cached}}

    def _answer(self, body, text, tokens, wants_usage, streaming, tool_call=None):
        model = body.get("model", "e2e_fake_llm")
        usage = self._usage(tokens) if wants_usage else None
        finish = "tool_calls" if tool_call else "stop"
        if not streaming:
            message = {"role": "assistant", "content": text}
            if tool_call:
                message["tool_calls"] = [{k: v for k, v in tool_call.items() if k != "index"}]
            result = {"id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion", "created": int(time.time()),
                      "model": model, "choices": [{"index": 0, "message": message, "finish_reason": finish}]}
            if usage:
                result["usage"] = usage
            return result

        async def chunks():
            base = {"id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion.chunk",
                    "created": int(time.time()), "model": model}
            delta = {"role": "assistant", "tool_calls": [tool_call]} if tool_call else {"role": "assistant", "content": text}
            yield {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
            yield {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}
            if usage:
                yield {**base, "choices": [], "usage": usage}

        return chunks()
