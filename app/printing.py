"""Réservation durable avant lp : pas de réimpression automatique ambiguë."""
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile


class PrintError(Exception):
    def __init__(self, message, status=503):
        self.status = status
        super().__init__(message)


class Printer:
    def __init__(self, directory, printer, runner=subprocess.run):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = self.directory / 'jobs.sqlite3'
        self.printer = printer
        self.runner = runner
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, cups_id TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')

    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT key, state, cups_id, created FROM jobs WHERE key=?', (key,)).fetchone()
        if row is None:
            raise PrintError('Travail inconnu.', 404)
        return dict(row)

    def submit(self, key, data):
        if not re.fullmatch(r'[A-Za-z0-9._:-]{8,120}', key):
            raise PrintError('Idempotency-Key requis, entre 8 et 120 caractères simples.', 400)
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}', self.printer):
            raise PrintError('PRINTER_NAME absent ou invalide.', 503)
        digest = hashlib.sha256(data).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone()
            if previous:
                if previous['digest'] != digest:
                    raise PrintError('Même clé avec un PDF différent.', 409)
                if previous['state'] != 'accepted':
                    raise PrintError('Soumission précédente incertaine ou échouée. Contrôler CUPS avant toute reprise.', 409)
                return self.get(key) | {'duplicate': True, 'physical_print_confirmed': False}
            db.execute('INSERT INTO jobs(key,digest,state) VALUES (?,?,?)', (key, digest, 'submitting'))
        # Si le processus s’arrête après lp, la réservation reste bloquée : ne pas dupliquer.
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', dir=self.directory, delete=False) as f:
                f.write(data)
                path = f.name
            result = self.runner(['/usr/bin/lp', '-d', self.printer, '-n', '1', '-t', 'bordereau-'+key, path],
                                 capture_output=True, text=True, timeout=30,
                                 env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C'})
            match = re.search(r'request id is (\S+)', result.stdout)
            if result.returncode != 0 or not match:
                self.mark(key, 'submit_unknown')
                raise PrintError('Résultat CUPS incertain. Vérifier lpstat et les journaux avant de relancer.')
            self.mark(key, 'accepted', match.group(1))
        except FileNotFoundError as exc:
            self.mark(key, 'failed')
            raise PrintError('Commande lp absente : installer cups-client.') from exc
        except (subprocess.TimeoutExpired, OSError) as exc:
            self.mark(key, 'submit_unknown')
            raise PrintError('Soumission incertaine : vérifier CUPS, ne pas relancer automatiquement.') from exc
        finally:
            if path:
                Path(path).unlink(missing_ok=True)
        return self.get(key) | {'duplicate': False, 'physical_print_confirmed': False}

    def mark(self, key, state, cups_id=None):
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=?,cups_id=? WHERE key=?', (state, cups_id, key))

    def status(self, key):
        job = self.get(key)
        job['physical_print_confirmed'] = False
        job['queue_status'] = 'unknown'
        if job['cups_id']:
            try:
                result = self.runner(['/usr/bin/lpstat', '-W', 'not-completed', '-o', self.printer],
                                     capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    ids = [line.split()[0] for line in result.stdout.splitlines() if line.split()]
                    job['queue_status'] = 'in_queue' if job['cups_id'] in ids else 'no_longer_in_queue'
            except (OSError, subprocess.TimeoutExpired):
                pass
        return job
