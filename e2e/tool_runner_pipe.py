"""
title: E2E Tool Runner
description: Nur für den End-to-End-Test. Ruft das in der Nachricht genannte Tool ohne Sprachmodell auf.
version: 1.0.0
"""

# Wird vom Test direkt über die API angelegt und nie mit scripts/deploy.py
# eingespielt. Die letzte Nachricht enthält JSON:
#     {"function": "<Tool-Funktion>", "args": {...}}
# Open WebUI reicht die per tool_ids gewählten Tools als __tools__ an die Pipe.
# So laufen die Tools mit dem echten Benutzerkontext und der echten
# Benutzerdatenbank, aber ohne ein Modell, das Ergebnisse umformuliert.

import json


class Pipe:
    async def pipe(self, body: dict, __tools__: dict | None = None) -> str:
        content = body["messages"][-1]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        request = json.loads(content)
        tools = __tools__ or {}
        name = request["function"]
        if name not in tools:
            return json.dumps({"error": "tool-not-available", "available": sorted(tools)})
        result = await tools[name]["callable"](**request.get("args", {}))
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
