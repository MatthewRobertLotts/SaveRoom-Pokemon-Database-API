#!/usr/bin/env python3
"""Configuration boundary for the SaveRoom Pokémon DB local app layer.

The defaults intentionally preserve the existing local prototype layout while
allowing deployment/runtime paths to be supplied by CLI args or environment
variables. Non-secret settings live here rather than in a required .env file.

CHANGE (v9.1): Added image_root, signed_url_secret, skip_search_setup fields
so that tests can inject all configuration via PokemonDBSettings instead of
mutating module-level globals or patching env vars at runtime.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = PROJECT_DIR / 'full_tcgdex' / 'pokemon_tcg_set_knowledge_base.sqlite'
DEFAULT_UI_DIR = PROJECT_DIR / 'pokemon_db_v2_browser_ui'
DEFAULT_IMAGE_CACHE_DIR = PROJECT_DIR / 'image_cache' / 'webp_q72_512'
DEFAULT_REPORTS_DIR = PROJECT_DIR / 'full_tcgdex' / 'reports'
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8765
DEFAULT_CORS_ORIGINS = ('http://127.0.0.1:8765', 'http://localhost:8765')
DEFAULT_RUNTIME_ENV = 'development'

ENV_PREFIX = 'POKEMON_DB_'


@dataclass(frozen=True)
class PokemonDBSettings:
    """Runtime settings for the FastAPI/search/reporting layer.

    v9.1 additions:
    - image_root: where catalogue images are stored on disk
    - signed_url_secret: secret key for signed image URLs
    - skip_search_setup: if True, skip expensive FTS rebuild during create_app
    - require_api_key: if True, enforce API key auth on /api/v1 routes
    """

    db: Path = DEFAULT_DB
    ui_dir: Path = DEFAULT_UI_DIR
    image_cache_dir: Path | None = DEFAULT_IMAGE_CACHE_DIR
    reports_dir: Path = DEFAULT_REPORTS_DIR
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS

    # v9.1 — allow all image-gateway paths and auth to come from settings
    image_root: Path | None = None
    signed_url_secret: str | None = None
    skip_search_setup: bool = False
    require_api_key: bool = False
    runtime_env: str = DEFAULT_RUNTIME_ENV
    db_source: str = 'default'
    debug: bool = False
    public_base_url: str | None = None
    physical_photo_root: Path | None = None
    trusted_proxy: bool = False
    log_level: str = 'INFO'
    # v9.1 — quota limits
    image_hourly_delivery_limit: int = 1000
    image_daily_delivery_limit: int = 5000

    @property
    def image_cache_mounted(self) -> bool:
        return self.image_cache_dir is not None and self.image_cache_dir.exists()

    def with_reports_default(self) -> 'PokemonDBSettings':
        if self.reports_dir == DEFAULT_REPORTS_DIR and self.db != DEFAULT_DB:
            return replace(self, reports_dir=self.db.parent / 'reports')
        return self


def _env(name: str) -> str | None:
    value = os.environ.get(f'{ENV_PREFIX}{name}')
    return value if value not in (None, '') else None


def _path(value: str | Path | None) -> Path | None:
    if value in (None, ''):
        return None
    return Path(value).expanduser().resolve()


def _split_origins(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    origins = tuple(part.strip().rstrip('/') for part in value.split(',') if part.strip())
    return origins


def _bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _is_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.strip().lower()
    placeholders = {'changeme', 'change-me', 'replace-me', 'replace-with-secure-secret', 'dev-secret'}
    return lowered in placeholders or 'replace' in lowered or 'placeholder' in lowered


def settings_from_env() -> PokemonDBSettings:
    """Build settings from POKEMON_DB_* environment variables and defaults."""

    image_cache_raw = _env('IMAGE_CACHE_DIR')
    image_cache_dir = _path(image_cache_raw) if image_cache_raw is not None else DEFAULT_IMAGE_CACHE_DIR
    reports_raw = _env('REPORTS_DIR')
    cors = _split_origins(_env('CORS_ORIGINS'))
    image_root_raw = _env('IMAGE_ROOT')
    secret_raw = _env('SIGNED_URL_SECRET')
    require_key_raw = _env('REQUIRE_API_KEY')
    db_raw = _env('DB')
    runtime_env = (_env('ENV') or DEFAULT_RUNTIME_ENV).strip().lower()
    return PokemonDBSettings(
        db=_path(db_raw) or DEFAULT_DB,
        ui_dir=_path(_env('UI_DIR')) or DEFAULT_UI_DIR,
        image_cache_dir=image_cache_dir,
        reports_dir=_path(reports_raw) or DEFAULT_REPORTS_DIR,
        host=_env('HOST') or DEFAULT_HOST,
        port=int(_env('PORT') or DEFAULT_PORT),
        cors_origins=cors or DEFAULT_CORS_ORIGINS,
        image_root=_path(image_root_raw),
        signed_url_secret=secret_raw or None,
        skip_search_setup=False,
        require_api_key=_bool(require_key_raw),
        runtime_env=runtime_env,
        db_source='env' if db_raw else 'default',
        debug=_bool(_env('DEBUG')),
        public_base_url=_env('PUBLIC_BASE_URL'),
        physical_photo_root=_path(_env('PHYSICAL_PHOTO_ROOT')),
        trusted_proxy=_bool(_env('TRUSTED_PROXY')),
        log_level=(_env('LOG_LEVEL') or 'INFO').upper(),
    ).with_reports_default()


def add_common_args(parser: argparse.ArgumentParser, *, include_server: bool = False) -> None:
    """Add common runtime path/config arguments to a parser."""

    parser.add_argument('--db', default=None, help=f'SQLite database path (env: {ENV_PREFIX}DB).')
    parser.add_argument('--ui-dir', default=None, help=f'Static browser UI directory (env: {ENV_PREFIX}UI_DIR).')
    parser.add_argument('--image-cache-dir', default=None, help=f'Local image cache directory to mount at /images (env: {ENV_PREFIX}IMAGE_CACHE_DIR).')
    parser.add_argument('--reports-dir', default=None, help=f'Reports/log output directory (env: {ENV_PREFIX}REPORTS_DIR).')
    parser.add_argument('--cors-origin', action='append', dest='cors_origins', help='Allowed CORS origin. May be repeated. Defaults to local browser origins.')
    parser.add_argument('--image-root', default=None, help=f'Catalogue image storage root (env: {ENV_PREFIX}IMAGE_ROOT).')
    parser.add_argument('--env', dest='runtime_env', default=None, choices=('development', 'test', 'production'), help=f'Runtime environment name (env: {ENV_PREFIX}ENV).')
    parser.add_argument('--public-base-url', default=None, help=f'Public base URL for generated links (env: {ENV_PREFIX}PUBLIC_BASE_URL).')
    parser.add_argument('--physical-photo-root', default=None, help=f'Physical item photo storage root (env: {ENV_PREFIX}PHYSICAL_PHOTO_ROOT).')
    parser.add_argument('--require-api-key', action='store_true', help=f'Require API keys on /api/v1 routes (env: {ENV_PREFIX}REQUIRE_API_KEY).')
    if include_server:
        parser.add_argument('--host', default=None, help=f'Bind host (env: {ENV_PREFIX}HOST).')
        parser.add_argument('--port', type=int, default=None, help=f'Bind port (env: {ENV_PREFIX}PORT).')


def settings_from_args(args: argparse.Namespace) -> PokemonDBSettings:
    """Merge parsed argparse args over environment/default settings."""

    base = settings_from_env()
    image_cache_dir = base.image_cache_dir
    if getattr(args, 'image_cache_dir', None) is not None:
        image_cache_dir = _path(args.image_cache_dir)
    cors_arg = getattr(args, 'cors_origins', None)
    image_root_arg = getattr(args, 'image_root', None)
    db_arg = getattr(args, 'db', None)
    return replace(
        base,
        db=_path(db_arg) or base.db,
        db_source='arg' if db_arg else base.db_source,
        ui_dir=_path(getattr(args, 'ui_dir', None)) or base.ui_dir,
        image_cache_dir=image_cache_dir,
        reports_dir=_path(getattr(args, 'reports_dir', None)) or base.reports_dir,
        host=getattr(args, 'host', None) or base.host,
        port=getattr(args, 'port', None) or base.port,
        cors_origins=tuple(origin.rstrip('/') for origin in cors_arg) if cors_arg else base.cors_origins,
        image_root=_path(image_root_arg) or base.image_root,
        runtime_env=getattr(args, 'runtime_env', None) or base.runtime_env,
        public_base_url=getattr(args, 'public_base_url', None) or base.public_base_url,
        physical_photo_root=_path(getattr(args, 'physical_photo_root', None)) or base.physical_photo_root,
        require_api_key=True if getattr(args, 'require_api_key', False) else base.require_api_key,
    ).with_reports_default()


def validate_settings(settings: PokemonDBSettings, *, require_ui: bool = True) -> PokemonDBSettings:
    """Validate path settings before serving or writing reports."""

    errors: list[str] = []
    if not settings.db.exists() or not settings.db.is_file():
        errors.append(f'Database does not exist or is not a file: {settings.db}')
    if require_ui and (not settings.ui_dir.exists() or not settings.ui_dir.is_dir()):
        errors.append(f'UI directory does not exist or is not a directory: {settings.ui_dir}')
    if settings.image_cache_dir is not None and settings.image_cache_dir.exists() and not settings.image_cache_dir.is_dir():
        errors.append(f'Image cache path exists but is not a directory: {settings.image_cache_dir}')
    env_name = settings.runtime_env.strip().lower()
    if env_name not in {'development', 'test', 'production'}:
        errors.append(f'POKEMON_DB_ENV must be development, test or production; got {settings.runtime_env!r}')
    if settings.physical_photo_root is not None and settings.physical_photo_root.exists() and not settings.physical_photo_root.is_dir():
        errors.append(f'Physical photo root exists but is not a directory: {settings.physical_photo_root}')
    if settings.log_level.upper() not in {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}:
        errors.append(f'POKEMON_DB_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL; got {settings.log_level!r}')
    if env_name == 'production':
        if settings.db_source == 'default':
            errors.append('Production requires an explicit database path via POKEMON_DB_DB or --db; refusing to use the development default silently.')
        if not settings.require_api_key:
            errors.append('Production requires POKEMON_DB_REQUIRE_API_KEY=1 or --require-api-key.')
        if settings.debug:
            errors.append('Production must not run with POKEMON_DB_DEBUG enabled.')
        if _is_placeholder_secret(settings.signed_url_secret) or len(settings.signed_url_secret or '') < 32:
            errors.append('Production requires a non-placeholder POKEMON_DB_SIGNED_URL_SECRET with at least 32 characters.')
        if settings.host not in {'127.0.0.1', 'localhost'} and not settings.public_base_url:
            errors.append('Production public binds require POKEMON_DB_PUBLIC_BASE_URL so generated URLs are explicit.')
    if errors:
        raise ValueError('; '.join(errors))
    # Validate quota limits are positive
    if settings.image_hourly_delivery_limit <= 0:
        raise ValueError(f'image_hourly_delivery_limit must be positive, got {settings.image_hourly_delivery_limit}')
    if settings.image_daily_delivery_limit <= 0:
        raise ValueError(f'image_daily_delivery_limit must be positive, got {settings.image_daily_delivery_limit}')
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    return settings


def public_settings(settings: PokemonDBSettings) -> dict[str, object]:
    """Path-safe settings for API responses."""

    return {
        'database_name': settings.db.name,
        'ui_mounted': settings.ui_dir.exists(),
        'image_cache_mounted': settings.image_cache_mounted,
        'image_cache_url_prefix': '/images' if settings.image_cache_mounted else None,
        'cors_origins': list(settings.cors_origins),
        'runtime_env': settings.runtime_env,
        'api_key_required': settings.require_api_key,
    }


def startup_lines(settings: PokemonDBSettings, support_status: dict[str, object] | None = None) -> Iterable[str]:
    """Human-facing startup log lines. These are console-only, not public API."""

    yield f'DB path: {settings.db}'
    yield f'Runtime env: {settings.runtime_env}'
    yield f'DB source: {settings.db_source}'
    yield f'UI dir: {settings.ui_dir}'
    if settings.image_cache_dir is None:
        yield 'Image cache: disabled'
    elif settings.image_cache_dir.exists():
        yield f'Image cache: mounted /images -> {settings.image_cache_dir}'
    else:
        yield f'Image cache: not mounted; directory missing: {settings.image_cache_dir}'
    yield f'Reports dir: {settings.reports_dir}'
    if settings.physical_photo_root is not None:
        yield f'Physical photo root: {settings.physical_photo_root}'
    yield f'Bind: {settings.host}:{settings.port}'
    yield f'API key auth: {"required" if settings.require_api_key else "optional/local"}'
    yield f'Debug: {"on" if settings.debug else "off"}'
    yield f'Log level: {settings.log_level.upper()}'
    if settings.public_base_url:
        yield f'Public base URL: {settings.public_base_url}'
    yield f'CORS origins: {", ".join(settings.cors_origins) if settings.cors_origins else "none"}'
    if support_status:
        yield 'Cache rows: v2_card_search={v2_card_search_rows}, fts={fts_rows}, api_cache={api_cache_rows}, refreshed={refreshed}'.format(
            v2_card_search_rows=support_status.get('v2_card_search_rows'),
            fts_rows=support_status.get('fts_rows'),
            api_cache_rows=support_status.get('api_cache_rows'),
            refreshed=support_status.get('refreshed'),
        )