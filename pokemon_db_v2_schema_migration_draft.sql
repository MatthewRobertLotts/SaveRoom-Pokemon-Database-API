-- Pokémon Card Database v2 schema migration draft
-- Generated 2026-06-13. REVIEW BEFORE APPLYING.
-- This file is intentionally additive: it does not rewrite or delete existing cards/sets.

PRAGMA foreign_keys = ON;
BEGIN;

-- Canonical reviewed alias table. Populate from set_aliases_proposed only after review.
CREATE TABLE IF NOT EXISTS set_aliases (
    alias_language_code TEXT NOT NULL,
    alias_set_id TEXT NOT NULL,
    target_language_code TEXT NOT NULL,
    target_set_id TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'import_alias',
    source_url TEXT,
    method TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    notes TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (alias_language_code, alias_set_id),
    FOREIGN KEY (target_language_code, target_set_id) REFERENCES sets(language_code, set_id)
);
CREATE INDEX IF NOT EXISTS idx_set_aliases_target ON set_aliases(target_language_code, target_set_id);

-- Source document registry for repeatable/provenance-backed enrichment.
CREATE TABLE IF NOT EXISTS source_documents (
    source_document_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_title TEXT,
    source_publisher TEXT,
    source_type TEXT NOT NULL,
    language_code TEXT,
    fetched_at TEXT NOT NULL,
    retrieved_by TEXT,
    content_hash TEXT,
    cache_path TEXT,
    license_notes TEXT,
    reliability_notes TEXT,
    FOREIGN KEY (language_code) REFERENCES languages(code)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_documents_url_hash ON source_documents(source_url, COALESCE(content_hash, ''));

-- More general provenance model for all new v2 enrichment rows.
CREATE TABLE IF NOT EXISTS provenance_records (
    provenance_id TEXT PRIMARY KEY,
    entity_table TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    language_code TEXT,
    source_document_id TEXT,
    source_url TEXT NOT NULL,
    method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_notes TEXT,
    extraction_notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (language_code) REFERENCES languages(code),
    FOREIGN KEY (source_document_id) REFERENCES source_documents(source_document_id)
);
CREATE INDEX IF NOT EXISTS idx_provenance_records_entity ON provenance_records(entity_table, entity_key);
CREATE INDEX IF NOT EXISTS idx_provenance_records_source ON provenance_records(source_url, method);

CREATE TABLE IF NOT EXISTS card_variants (
    variant_id TEXT PRIMARY KEY,
    language_code TEXT NOT NULL,
    card_id TEXT NOT NULL,
    set_id TEXT NOT NULL,
    local_id TEXT,
    variant_type TEXT NOT NULL,
    variant_label TEXT,
    print_finish TEXT,
    distribution_context TEXT,
    notes TEXT,
    source_url TEXT NOT NULL,
    method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_notes TEXT,
    FOREIGN KEY (language_code, card_id) REFERENCES cards(language_code, card_id)
);
CREATE INDEX IF NOT EXISTS idx_card_variants_card ON card_variants(language_code, card_id);

CREATE TABLE IF NOT EXISTS card_reprints (
    reprint_id TEXT PRIMARY KEY,
    language_code TEXT,
    source_card_id TEXT NOT NULL,
    source_set_id TEXT,
    reprint_card_id TEXT NOT NULL,
    reprint_set_id TEXT,
    relationship_type TEXT NOT NULL DEFAULT 'reprint',
    notes TEXT,
    source_url TEXT NOT NULL,
    method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_card_reprints_source ON card_reprints(language_code, source_card_id);
CREATE INDEX IF NOT EXISTS idx_card_reprints_reprint ON card_reprints(language_code, reprint_card_id);

CREATE TABLE IF NOT EXISTS card_trivia (
    trivia_id TEXT PRIMARY KEY,
    language_code TEXT,
    card_id TEXT NOT NULL,
    set_id TEXT,
    trivia_text TEXT NOT NULL,
    trivia_type TEXT,
    source_url TEXT NOT NULL,
    method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_card_trivia_card ON card_trivia(language_code, card_id);

CREATE TABLE IF NOT EXISTS card_errors (
    error_id TEXT PRIMARY KEY,
    language_code TEXT,
    card_id TEXT NOT NULL,
    set_id TEXT,
    error_type TEXT NOT NULL,
    error_description TEXT NOT NULL,
    affected_prints TEXT,
    correction_status TEXT,
    source_url TEXT NOT NULL,
    method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_card_errors_card ON card_errors(language_code, card_id);

CREATE TABLE IF NOT EXISTS card_errata (
    errata_id TEXT PRIMARY KEY,
    language_code TEXT,
    card_id TEXT NOT NULL,
    set_id TEXT,
    errata_date TEXT,
    original_text TEXT,
    corrected_text TEXT NOT NULL,
    ruling_context TEXT,
    source_url TEXT NOT NULL,
    method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_card_errata_card ON card_errata(language_code, card_id);

CREATE TABLE IF NOT EXISTS sealed_product_sources (
    sealed_product_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    product_type TEXT NOT NULL,
    language_code TEXT,
    set_id TEXT,
    release_date TEXT,
    region TEXT,
    contents_summary TEXT,
    source_url TEXT NOT NULL,
    method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_notes TEXT,
    FOREIGN KEY (language_code) REFERENCES languages(code)
);
CREATE INDEX IF NOT EXISTS idx_sealed_product_sources_set ON sealed_product_sources(language_code, set_id);

CREATE TABLE IF NOT EXISTS market_snapshots (
    market_snapshot_id TEXT PRIMARY KEY,
    language_code TEXT,
    card_id TEXT,
    sealed_product_id TEXT,
    marketplace TEXT NOT NULL,
    price_amount REAL,
    price_currency TEXT,
    condition_grade TEXT,
    snapshot_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_card ON market_snapshots(language_code, card_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_product ON market_snapshots(sealed_product_id, snapshot_at);

CREATE TABLE IF NOT EXISTS inventory_links (
    inventory_link_id TEXT PRIMARY KEY,
    language_code TEXT,
    card_id TEXT,
    sealed_product_id TEXT,
    external_system TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_url TEXT,
    link_status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_links_external ON inventory_links(external_system, external_id);
CREATE INDEX IF NOT EXISTS idx_inventory_links_card ON inventory_links(language_code, card_id);

COMMIT;
