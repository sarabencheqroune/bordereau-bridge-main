import hmac
import logging
import os
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import io
from pypdf import PdfReader
from .printing import Printer, PrintError

log = logging.getLogger('bordereau')
MAX_BODY = 16 * 1024 * 1024
MAX_FILE = 10 * 1024 * 1024
app = FastAPI(title='Impression locale Raspberry Pi', version='1.0.0', docs_url=None, redoc_url=None, openapi_url=None)


class Gate:
    """Vérifie la clé avant le parsing et borne aussi les corps chunked."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        token = os.getenv('API_TOKEN', '')
        headers = dict(scope['headers'])
        given = headers.get(b'x-api-key', b'').decode('latin1')
        if len(token) < 32:
            return await JSONResponse({'detail': 'API_TOKEN doit contenir au moins 32 caractères.'}, status_code=503)(scope, receive, send)
        if not hmac.compare_digest(given.encode(), token.encode()):
            return await JSONResponse({'detail': 'Authentification requise.'}, status_code=401)(scope, receive, send)
        # Buffer borné avant de laisser le parseur multipart traiter les données.
        chunks, total = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            total += len(chunk)
            if total > MAX_BODY:
                return await JSONResponse({'detail': 'Requête supérieure à 16 Mio.'}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()
        await self.app(scope, bounded_receive, send)


app.add_middleware(Gate)


def printer():
    return Printer(os.getenv('DATA_DIR', '/var/lib/bordereau'), os.getenv('PRINTER_NAME', ''))


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'impression-raspberry', 'printing_configured': bool(os.getenv('PRINTER_NAME'))}


def validate_pdf(data):
    if not data.startswith(b'%PDF-'):
        raise ValueError('PDF requis.')
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
        raise ValueError('PDF chiffré, vide ou trop long.')


@app.post('/print')
async def print_pdf(request: Request, idempotency_key: str = Header(default='', alias='Idempotency-Key')):
    if request.headers.get('content-type', '').split(';')[0].lower() != 'application/pdf':
        raise HTTPException(415, 'Content-Type application/pdf requis, PDF binaire brut.')
    data = await request.body()
    if len(data) > MAX_FILE:
        raise HTTPException(413, 'PDF supérieur à 10 Mio.')
    try:
        await run_in_threadpool(validate_pdf, data)
    except Exception:
        raise HTTPException(422, 'PDF invalide ou chiffré.')
    try:
        result = await run_in_threadpool(printer().submit, idempotency_key, data)
        return JSONResponse(result, status_code=200 if result['duplicate'] else 202)
    except PrintError as exc:
        raise HTTPException(exc.status, str(exc))


@app.get('/jobs/{key}')
def job_status(key: str):
    try:
        return printer().status(key)
    except PrintError as exc:
        raise HTTPException(exc.status, str(exc))
