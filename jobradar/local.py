"""Loopback job board backed by the existing append-only feedback ledger."""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .config import load_preferences
from .feedback import (applied_archive, apply_feedback, company_ignores, latest_verdicts,
                       parse_feedback_text, referral_companies, referral_marks)
from .followup import annotate_archive
from .render import render_report
from .publish import load_publish_config
from .store import SeenStore, list_snapshots, load_snapshot


class Board:
    def __init__(self, root: Path, date: str | None = None):
        self.root = Path(root).resolve()
        self.date = date
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.feedback = self.root / 'data/feedback.jsonl'
        self.snapshot()  # Fail before listening if no saved jobs exist.

    def snapshot(self):
        if self.date:
            dt.date.fromisoformat(self.date)
            path = self.root / 'data/jobs' / f'{self.date}.json'
        else:
            paths = list_snapshots(self.root / 'data/jobs')
            if not paths:
                raise ValueError('No saved jobs yet. Run the job scan first.')
            path = paths[-1]
        meta, jobs = load_snapshot(path)
        return path.stem, meta, jobs

    def html(self):
        with self.lock:
            date, meta, jobs = self.snapshot()
            seen = SeenStore(self.root / 'data/seen.json').data['jobs']
            seen = {**{j.id: {'title': j.title, 'company': j.company, 'url': j.url} for j in jobs}, **seen}
            apply_feedback(jobs, latest_verdicts(self.feedback), company_ignores(self.feedback))
            archive = annotate_archive(applied_archive(self.feedback, seen,
                                       self.root / 'data/applications'), dt.date.today().isoformat())
            return render_report(jobs, meta, load_preferences(self.root / 'profile/preferences.yaml'), date,
                                 archive=archive, referral_marks=referral_marks(self.feedback),
                                 referral_companies=referral_companies(self.feedback, seen),
                                 local={'token': self.token},
                                 pinned_jobs=load_publish_config(self.root / 'config/publish.yaml').get('pinned_jobs'))

    def save(self, text: str, request_id: str):
        if not isinstance(text, str) or not isinstance(request_id, str):
            raise ValueError('Expected feedback text and a request ID.')
        uuid.UUID(request_id)
        entries = parse_feedback_text(text)
        if not entries or len(entries) > 500:
            raise ValueError('Save between 1 and 500 selections at a time.')
        with self.lock:
            _, _, jobs = self.snapshot()
            known = set(SeenStore(self.root / 'data/seen.json').data['jobs'])
            known.update(j.id for j in jobs)
            known.update(latest_verdicts(self.feedback))
            companies = {jid.split(':', 1)[0].lower() for jid in known}
            # Validate the entire batch before opening the ledger for writes.
            for e in entries:
                if e.get('kind') == 'company_ignore':
                    if e.get('company_key') not in companies:
                        raise ValueError('Unknown company.')
                elif e.get('job_id') not in known:
                    raise ValueError('Unknown job; no selections were saved.')
            self.feedback.parent.mkdir(parents=True, exist_ok=True)
            with self.feedback.open('a+', encoding='utf-8') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.seek(0)
                prior = f.read()
                records = [json.loads(line) for line in prior.splitlines() if line.strip()]
                matches = [r for r in records if r.get('request_id') == request_id]
                if matches:
                    clean = [{k: v for k, v in r.items() if k not in ('ts', 'request_id')} for r in matches]
                    if clean != entries:
                        raise ValueError('Request ID already used for different feedback.')
                    return len(matches)
                stamp = dt.datetime.now().replace(microsecond=0).isoformat()
                body = ''.join(json.dumps({**e, 'ts': stamp, 'request_id': request_id}, ensure_ascii=False) + '\n'
                               for e in entries)
                f.seek(0, os.SEEK_END)
                f.write(('\n' if prior and not prior.endswith('\n') else '') + body)
                f.flush()
                os.fsync(f.fileno())
            return len(entries)


def make_server(root: Path, port: int = 8766, date: str | None = None):
    board = Board(root, date)

    class Handler(BaseHTTPRequestHandler):
        def allowed_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',
                                                f'localhost:{self.server.server_port}')

        def respond(self, status, body, kind='application/json'):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed_host():
                return self.respond(403, {'error': 'Local access only.'})
            path = unquote(urlsplit(self.path).path)
            if path == '/health':
                return self.respond(200, {'ok': True, 'mode': 'local', 'date': board.snapshot()[0]})
            if path in ('/', '/reports/index.html'):
                try:
                    return self.respond(200, board.html(), 'text/html')
                except (ValueError, OSError) as e:
                    return self.respond(500, {'error': str(e)})
            # Only resume PDFs, not arbitrary repository files or credentials.
            if path.startswith('/Applied Job Resumes/') and path.endswith('.pdf'):
                base = board.root / 'Applied Job Resumes'
                target = (board.root / path.lstrip('/')).resolve()
                if target.is_relative_to(base.resolve()) and target.is_file():
                    data = target.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/pdf')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
            self.respond(404, {'error': 'Not found.'})

        def do_POST(self):
            origin = self.headers.get('Origin')
            expected = f'http://{self.headers.get("Host")}'
            if (not self.allowed_host() or origin != expected or
                    self.headers.get('X-JobRadar-Token') != board.token):
                return self.respond(403, {'error': 'Open the local board and retry.'})
            if self.path != '/api/feedback':
                return self.respond(404, {'error': 'Not found.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('Invalid request size.')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Expected JSON.')
                obj = json.loads(self.rfile.read(length))
                count = board.save(obj['text'], obj['request_id'])
                return self.respond(200, {'saved': count})
            except (ValueError, KeyError, TypeError) as e:
                return self.respond(400, {'error': str(e)})
            except OSError:
                return self.respond(500, {'error': 'Could not write the local ledger. Your draft is retained; retry.'})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.board = board
    return server


def serve(root: Path, port: int = 8766, date: str | None = None):
    with make_server(root, port, date) as server:
        print(f'Job Hub: http://127.0.0.1:{server.server_port}/ (selections save locally)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
