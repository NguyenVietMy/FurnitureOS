"""Business modules.

One package per bounded slice of the product. Each owns its own storage, rules, wire
format, and routes, and exposes them through its `__init__.py` and nothing else.

Rules:
  1. A module may import `furnitureos.core` freely.
  2. A module may import another module only via its package root
     (`from furnitureos.modules.catalogue import ...`), never a submodule of it.
  3. Core and the composition root never import module internals either — the root
     mounts `router` and registers models, both re-exported.

Rule 2 is what lets a module be understood, tested, and later extracted on its own.
"""
