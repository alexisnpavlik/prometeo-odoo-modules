# -*- coding: utf-8 -*-
"""
Sentry Error Monitoring for Odoo Server (Python)
------------------------------------------------
This module initializes Sentry SDK on the Odoo server side.

Architectural Decision Note:
Low-level monkey patches on `odoo.http.Root.dispatch` (HTTP requests) and
`odoo.models.BaseModel._call_kw` (RPC/ORM requests) were explicitly evaluated
and discarded for stability reasons. Since they lie on the critical hot path
for all network/database operations, a bug or delay in those patches could
bring down Odoo entirely across all 12 branches.

Instead, we rely on the robust, low-risk combination of:
1. `before_send` event processing with traceback-level addon extraction.
2. Official Sentry `LoggingIntegration` to capture server errors and logs.
"""
import os
import re
import logging
import threading
import traceback

_logger = logging.getLogger(__name__)

# Pattern to extract addon directory name from traceback filenames
# Example match: .../local-addons/pos_sales_advisor/... -> pos_sales_advisor
ADDON_REGEX = re.compile(r'(?:addons|local-addons|prometeo-addons)/([^/]+)/')

# Cache of instance URL (web.base.url) per database, resolved lazily on first event
_INSTANCE_URL_CACHE = {}


def _get_instance_url(db_name):
    """
    Resuelve la URL de la instancia (web.base.url) para usarla como environment.
    Se resuelve lazy en el primer evento (al init no hay DB disponible) y se
    cachea por base de datos. Prioridad: SENTRY_ENVIRONMENT > web.base.url.
    """
    env_url = os.environ.get('SENTRY_ENVIRONMENT')
    if env_url:
        return env_url.strip()

    if not db_name:
        return None
    if db_name in _INSTANCE_URL_CACHE:
        return _INSTANCE_URL_CACHE[db_name]

    url = None
    try:
        import odoo
        registry = odoo.registry(db_name)
        with registry.cursor() as cr:
            cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'web.base.url'")
            row = cr.fetchone()
            if row and row[0]:
                url = row[0].strip()
    except Exception:
        url = None

    if url:
        _INSTANCE_URL_CACHE[db_name] = url
    return url


def before_send(event, hint):
    """
    Event processor to enrich Sentry alerts with Odoo-specific metadata.
    Wrapped in try/except to guarantee that error reporting issues never affect
    Odoo server stability or transaction flows.
    """
    try:
        # 1. Extract database name from thread local context
        db_name = getattr(threading.current_thread(), 'dbname', None)
        if db_name:
            event['tags'] = event.get('tags') or {}
            event['tags']['db_name'] = db_name

        # Environment = URL de la instancia, para distinguir origen entre sucursales
        instance_url = _get_instance_url(db_name)
        if instance_url:
            event['environment'] = instance_url

        # 2. Parse traceback frames to discover module of origin
        exc_info = hint.get('exc_info') if hint else None
        if exc_info:
            exc_type, exc_value, exc_tb = exc_info
            if exc_tb:
                frames = traceback.extract_tb(exc_tb)
                addon_name = None
                last_filename = ""
                for frame in reversed(frames):
                    filename = frame.filename
                    match = ADDON_REGEX.search(filename)
                    if match:
                        addon_name = match.group(1)
                        last_filename = filename
                        break

                if addon_name:
                    event['tags'] = event.get('tags') or {}
                    event['tags']['odoo_module'] = addon_name
                    
                    # Custom modules are identified by their physical storage path
                    is_custom = any(x in last_filename for x in ['local-addons', 'prometeo-addons'])
                    event['tags']['is_custom_module'] = str(is_custom).lower()

    except Exception:
        # Never let error reporting crash Odoo
        pass

    return event

def init_sentry():
    """
    Safely initializes Sentry SDK. If initialization fails, Odoo continues starting.
    """
    try:
        # 1. Retrieve DSN from environment or fallback
        dsn = os.environ.get('SENTRY_DSN')
        if not dsn:
            dsn = "https://5e7994545829f0e490b60b785ac8d645@o4511665781276672.ingest.us.sentry.io/4511665789272064"

        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        # Configure official Logging Integration
        sentry_logging = LoggingIntegration(
            level=logging.INFO,         # Capture INFO+ as breadcrumbs
            event_level=logging.ERROR   # Send ERROR+ logs as full Sentry events
        )

        sentry_sdk.init(
            dsn=dsn.strip(),
            send_default_pii=True,
            integrations=[sentry_logging],
            before_send=before_send
        )
        _logger.info("[SENTRY] Python SDK initialized successfully with DSN: %s", dsn)

    except Exception as e:
        _logger.error("[SENTRY] Error initializing Sentry Python SDK: %s", str(e))

# Run once upon module import
init_sentry()
