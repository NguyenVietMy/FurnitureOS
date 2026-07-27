"""Shared kernel: configuration, database engine, session, declarative base.

Modules depend on core. Core never depends on a module — that direction is what keeps
the monolith modular rather than merely subdivided.
"""
