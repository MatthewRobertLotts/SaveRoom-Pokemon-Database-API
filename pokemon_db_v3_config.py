#!/usr/bin/env python3
"""Configuration boundary for the SaveRoom Pokémon DB local app layer.

The defaults intentionally preserve the existing local prototype layout while
allowing deployment/runtime paths to be supplied by CLI args or environment
variables. Non-secret settings live here rather than in a required .env file.
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

ENV_PREFIX = 'POKEMON_DB_'


@dataclass(frozen=True)
class PokemonDBSettings:
    """Runtime settings for the FastAPI/search/reporting layer."""

    db: Path = DEFAULT_DB
    ui_dir: Path = DEFAULT_UI_DIR
    image_cache_dir: Path | None = DEFAULT_IMAGE_CACHE_DIR
    reports_dir: Path = DEFAULT_REPORTS_DIR
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS

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


def settings_from_env() -> PokemonDBSettings:
    """Build settings from POKEMON_DB_* environment variables and defaults."""

    image_cache_raw = _env('IMAGE_CACHE_DIR')
    image_cache_dir = _path(image_cache_raw) if image_cache_raw is not None else DEFAULT_IMAGE_CACHE_DIR
    reports_raw = _env('REPORTS_DIR')
    cors = _split_origins(_env('CORS_ORIGINS'))
    return PokemonDBSettings(
        db=_path(_env('DB')) or DEFAULT_DB,
        ui_dir=_path(_env('UI_DIR')) or DEFAULT_UI_DIR,
        image_cache_dir=image_cache_dir,
        reports_dir=_path(reports_raw) or DEFAULT_REPORTS_DIR,
        host=_env('HOST') or DEFAULT_HOST,
        port=int(_env('PORT') or DEFAULT_PORT),
        cors_origins=cors or DEFAULT_CORS_ORIGINS,
    ).with_reports_default()


def add_common_args(parser: argparse.ArgumentParser, *, include_server: bool = False) -> None:
    """Add common runtime path/config arguments to a parser."""

    parser.add_argument('--db', default=None, help=f'SQLite database path (env: {ENV_PREFIX}DB).')
    parser.add_argument('--ui-dir', default=None, help=f'Static browser UI directory (env: {ENV_PREFIX}UI_DIR).')
    parser.add_argument('--image-cache-dir', default=None, help=f'Local image cache directory to mount at /images (env: {ENV_PREFIX}IMAGE_CACHE_DIR).')
    parser.add_argument('--reports-dir', default=None, help=f'Reports/log output directory (env: {ENV_PREFIX}REPORTS_DIR).')
    parser.add_argument('--cors-origin', action='append', dest='cors_origins', help='Allowed CORS origin. May be repeated. Defaults to local browser origins.')
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
    return replace(
        base,
        db=_path(getattr(args, 'db', None)) or base.db,
        ui_dir=_path(getattr(args, 'ui_dir', None)) or base.ui_dir,
        image_cache_dir=image_cache_dir,
        reports_dir=_path(getattr(args, 'reports_dir', None)) or base.reports_dir,
        host=getattr(args, 'host', None) or base.host,
        port=getattr(args, 'port', None) or base.port,
        cors_origins=tuple(origin.rstrip('/') for origin in cors_arg) if cors_arg else base.cors_origins,
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
    if errors:
        raise ValueError('; '.join(errors))
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
    }


def startup_lines(settings: PokemonDBSettings, support_status: dict[str, object] | None = None) -> Iterable[str]:
    """Human-facing startup log lines. These are console-only, not public API."""

    yield f'DB path: {settings.db}'
    yield f'UI dir: {settings.ui_dir}'
    if settings.image_cache_dir is None:
        yield 'Image cache: disabled'
    elif settings.image_cache_dir.exists():
        yield f'Image cache: mounted /images -> {settings.image_cache_dir}'
    else:
        yield f'Image cache: not mounted; directory missing: {settings.image_cache_dir}'
    yield f'Reports dir: {settings.reports_dir}'
    yield f'Bind: {settings.host}:{settings.port}'
    yield f'CORS origins: {", ".join(settings.cors_origins) if settings.cors_origins else "none"}'
    if support_status:
        yield 'Cache rows: v2_card_search={v2_card_search_rows}, fts={fts_rows}, api_cache={api_cache_rows}, refreshed={refreshed}'.format(
            v2_card_search_rows=support_status.get('v2_card_search_rows'),
            fts_rows=support_status.get('fts_rows'),
            api_cache_rows=support_status.get('api_cache_rows'),
            refreshed=support_status.get('refreshed'),
        )
