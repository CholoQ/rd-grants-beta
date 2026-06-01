#!/usr/bin/env python3
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import ADMIN_TOKEN, HOST, PORT, STATIC_DIR, logger
from .features import build_compare, build_grant_summary, build_readiness_check
from .ranking import build_recommendation_response
from .repository import bootstrap_data, create_lead, fetch_news, get_grant_by_id, get_meta, list_grants, list_leads, prepare_item
from .jgrants import refresh_data
from .utils import utcnow
from .rd_scheme import build_rd_meta, build_rd_search
from .company_profile import infer_company_profile_from_url


class AppHandler(BaseHTTPRequestHandler):
    def _send(self, payload: bytes, content_type: str = "application/json", status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, obj, status: int = 200) -> None:
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _require_admin(self) -> bool:
        if not ADMIN_TOKEN:
            return True
        token = self.headers.get("X-Admin-Token", "")
        if token == ADMIN_TOKEN:
            return True
        self._json({"error": "unauthorized"}, status=401)
        return False

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._json({"ok": True, "time": utcnow()}); return
            if parsed.path == "/api/grants":
                params = parse_qs(parsed.query)
                query = params.get("query", [""])[0]
                status = params.get("status", [None])[0]
                limit = int(params.get("limit", ["100"])[0])
                self._json({"items": list_grants(query=query, status=status, limit=limit)})
                return
            if parsed.path == "/api/grant":
                params = parse_qs(parsed.query)
                grant_id = params.get("id", [""])[0]
                if not grant_id:
                    self._json({"error": "id is required"}, status=400); return
                item = get_grant_by_id(grant_id)
                if not item:
                    self._json({"error": "not_found"}, status=404); return
                self._json({"item": prepare_item(item)})
                return
            if parsed.path == "/api/news":
                self._json({"items": fetch_news()}); return
            if parsed.path == "/api/meta":
                self._json(get_meta()); return
            if parsed.path == "/api/leads":
                if not self._require_admin():
                    return
                params = parse_qs(parsed.query)
                limit = int(params.get("limit", ["100"])[0])
                lead_type = params.get("lead_type", [None])[0]
                self._json({"items": list_leads(limit=limit, lead_type=lead_type)}); return
            if parsed.path == "/api/legal":
                from .config import LEGAL_DISCLAIMER
                self._json(LEGAL_DISCLAIMER); return
            if parsed.path == "/api/rd-meta":
                self._json(build_rd_meta()); return
            if parsed.path == "/api/grant-summary":
                params = parse_qs(parsed.query)
                grant_id = params.get('id', [''])[0]
                if not grant_id:
                    self._json({'error': 'id is required'}, status=400); return
                self._json(build_grant_summary(grant_id)); return
            self.serve_static(parsed.path)
        except KeyError:
            self._json({"error": "not_found"}, status=404)
        except Exception as exc:
            logger.exception("GET failed: %s", exc)
            self._json({"error": "internal_server_error"}, status=500)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/recommend":
                body = self._read_body()
                user_text = body.get("input_text", "").strip()
                if not user_text:
                    self._json({"error": "input_text is required"}, status=400); return
                self._json(build_recommendation_response(user_text, include_closed=bool(body.get("include_closed", False)), fast_mode=body.get("fast_mode")))
                return
            if self.path == "/api/lead":
                body = self._read_body()
                self._json(create_lead(body)); return
            if self.path == "/api/refresh":
                if not self._require_admin():
                    return
                self._json(refresh_data()); return
            if self.path == '/api/compare':
                body = self._read_body()
                self._json(build_compare(body.get('ids') or [])); return
            if self.path == '/api/readiness-check':
                body = self._read_body()
                self._json(build_readiness_check(body.get('ids') or [])); return
            if self.path == '/api/rd-search':
                body = self._read_body()
                self._json(build_rd_search(body)); return
            if self.path == '/api/company-profile':
                body = self._read_body()
                self._json(infer_company_profile_from_url((body.get('url') or '').strip(), (body.get('need_text') or '').strip())); return
            self._json({"error": "Not found"}, status=404)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=400)
        except Exception as exc:
            logger.exception("POST failed: %s", exc)
            self._json({"error": "internal_server_error"}, status=500)

    def serve_static(self, path: str) -> None:
        if path in ["/", ""]:
            path = "/index.html"
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in file_path.parents and file_path != STATIC_DIR / "index.html":
            self._json({"error": "invalid path"}, status=400); return
        if not file_path.exists() or not file_path.is_file():
            self._json({"error": "Not found"}, status=404); return
        content_type = "text/plain; charset=utf-8"
        if file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif file_path.suffix == ".png":
            content_type = "image/png"
        elif file_path.suffix in {".jpg", ".jpeg"}:
            content_type = "image/jpeg"
        elif file_path.suffix == ".webp":
            content_type = "image/webp"
        elif file_path.suffix == ".svg":
            content_type = "image/svg+xml"
        elif file_path.suffix == ".ico":
            content_type = "image/x-icon"
        self._send(file_path.read_bytes(), content_type=content_type)


def main() -> None:
    bootstrap_data()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    logger.info("Grant MVP modular server running on http://%s:%s", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
