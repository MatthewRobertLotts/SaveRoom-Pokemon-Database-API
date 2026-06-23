"""Shared test configuration for v9.1 test suite.

Manages POKEMON_DB_REQUIRE_API_KEY isolation between test modules.
v1 contract tests expect auth OFF; inventory and gateway tests expect auth ON.
"""
import os


def pytest_runtest_setup(item):
    """Set POKEMON_DB_REQUIRE_API_KEY based on the test module."""
    module_name = item.module.__name__ if hasattr(item, 'module') else ''
    if 'test_inventory_v9' in module_name or 'test_image_gateway_v9_1' in module_name:
        os.environ['POKEMON_DB_REQUIRE_API_KEY'] = '1'
    else:
        os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)


def pytest_runtest_teardown(item):
    """Restore POKEMON_DB_REQUIRE_API_KEY to default (off) after each test."""
    os.environ.pop('POKEMON_DB_REQUIRE_API_KEY', None)