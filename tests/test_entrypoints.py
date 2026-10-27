"""The Vercel entry points must expose the app (a linter once stripped these imports)."""
import importlib

from fastapi import FastAPI


def test_entrypoints_expose_app():
    for name in ("main", "api.index"):
        mod = importlib.import_module(name)
        assert isinstance(mod.app, FastAPI), name
