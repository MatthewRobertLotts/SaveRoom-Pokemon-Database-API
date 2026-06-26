"""Shared test configuration for v9.1 test suite.

Manages POKEMON_DB_REQUIRE_API_KEY isolation between test modules.
v1 contract tests expect auth OFF; inventory and gateway tests expect auth ON.
"""
import os

# Modules that require API key auth to be enabled
_AUTH_REQUIRED_MODULES = {
    'test_inventory_v9',
    'test_image_gateway_v9_1',
    'test_physical_photos',
    'test_gateway_logging',
}


def pytest_runtest_setup(item):
    """Set POKEMON_DB_REQUIRE_API_KEY based on the test module."""
    module_name = item.module.__name__ if hasattr(item, 'module') else ''
    if any(m in module_name for m in _AUTH_REQUIRED_MODULES):
        os.environ['POKEMON_DB_REQUIRE_API_KEY'] = '1'
    else:
        os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)


def pytest_runtest_teardown(item):
    """Restore POKEMON_DB_REQUIRE_API_KEY based on module (don't blanket-clear)."""
    module_name = item.module.__name__ if hasattr(item, 'module') else ''
    if not any(m in module_name for m in _AUTH_REQUIRED_MODULES):
        os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)
