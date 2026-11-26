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
#
# Zusätzlich liefert {"read_data_dir": true} für Admins alle Dateien im
# Datenverzeichnis des Nutzungsbudgets, damit der Test die geschriebenen
# Buchungen und Begründungen direkt prüfen kann.

import json
import os


class Pipe:
    async def pipe(self, body: dict, __tools__: dict | None = None, __user__: dict | None = None) -> str:
        content = body["messages"][-1]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        request = json.loads(content)
        if request.get("read_data_dir"):
            return json.dumps(self._data_dir(__user__))
        tools = __tools__ or {}
        name = request["function"]
        if name not in tools:
            return json.dumps({"error": "tool-not-available", "available": sorted(tools)})
        result = await tools[name]["callable"](**request.get("args", {}))
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)

    @staticmethod
    def _data_dir(user: dict | None) -> dict:
        if (user or {}).get("role") != "admin":
            return {"error": "admin-only"}
        with open(os.environ["USAGE_BUDGET_CONFIG"], encoding="utf-8") as handle:
            directory = json.load(handle)["data_dir"]
        files = {}
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8") as handle:
                files[name] = {"content": handle.read(), "mode": oct(os.stat(path).st_mode & 0o777)}
        return {"files": files, "directory_mode": oct(os.stat(directory).st_mode & 0o777)}
