# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EoS Project

"""Package dependency resolver — resolves transitive package dependencies.

Reuses the DependencyGraph from ebuild.core.graph to determine the
correct build order for external packages.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ebuild.core.graph import CycleError, DependencyGraph
from ebuild.packages.recipe import PackageRecipe
from ebuild.packages.registry import PackageRegistry


class ResolveError(Exception):
    """Raised when package dependencies cannot be resolved."""


class PackageResolver:
    """Resolves package dependency graphs and determines build order.

    Uses the registry to look up recipes and the DependencyGraph
    to compute a topological ordering.
    """

    def __init__(self, registry: PackageRegistry) -> None:
        self.registry = registry

    def resolve(
        self,
        requested: List[Dict[str, str]],
    ) -> List[PackageRecipe]:
        """Resolve a list of requested packages into a full build order.

        Version selection:
            An explicitly requested version pins the package for the whole
            resolution, no matter where in the dependency graph the package is
            first reached. Packages requested without a version resolve to the
            newest one in the registry. Requesting two different versions of
            the same package is a conflict and raises rather than silently
            selecting one of them.

        Args:
            requested: List of dicts with 'name' and optional 'version' keys.

        Returns:
            List of PackageRecipe in correct build order (dependencies first).

        Raises:
            ResolveError: If a package or dependency cannot be found, if two
                incompatible versions of the same package are requested, or if
                the dependency graph contains a cycle.
        """
        resolved: Dict[str, PackageRecipe] = {}
        graph = DependencyGraph()

        # Collect explicit pins up front. Doing this before walking the graph
        # is what makes the result independent of request order: otherwise the
        # first traversal to reach a package fixes its version, and a pin
        # appearing later in the list is swallowed by the memoization in
        # _collect().
        pins = self._collect_pins(requested)

        for pkg in requested:
            self._collect(pkg.get("name", ""), pins, resolved, graph)

        try:
            order = graph.topological_sort()
        except CycleError as e:
            raise ResolveError(f"Package dependency cycle: {e}")

        return [resolved[name] for name in order if name in resolved]

    @staticmethod
    def _collect_pins(requested: List[Dict[str, str]]) -> Dict[str, str]:
        """Map package name → explicitly requested version.

        Raises:
            ResolveError: If the same package is requested at two different
                versions.
        """
        pins: Dict[str, str] = {}

        for pkg in requested:
            name = pkg.get("name", "")
            version = pkg.get("version")
            if not version:
                continue

            existing = pins.get(name)
            if existing is not None and existing != version:
                raise ResolveError(
                    f"Conflicting versions requested for package '{name}': "
                    f"'{existing}' and '{version}'. "
                    "Request a single version of each package."
                )
            pins[name] = version

        return pins

    def _collect(
        self,
        name: str,
        pins: Dict[str, str],
        resolved: Dict[str, PackageRecipe],
        graph: DependencyGraph,
    ) -> None:
        """Recursively collect a package and its transitive dependencies."""
        if name in resolved:
            return

        version = pins.get(name)
        recipe = self.registry.get(name, version)
        if recipe is None:
            raise ResolveError(
                f"Package '{name}'"
                + (f" v{version}" if version else "")
                + " not found in registry. "
                f"Available: {[r.name for r in self.registry.list_packages()]}"
            )

        resolved[name] = recipe
        graph.add_node(name)

        for dep_name in recipe.dependencies:
            self._collect(dep_name, pins, resolved, graph)
            graph.add_edge(name, dep_name)

    def resolve_single(self, name: str, version: Optional[str] = None) -> PackageRecipe:
        """Resolve a single package recipe from the registry."""
        recipe = self.registry.get(name, version)
        if recipe is None:
            raise ResolveError(f"Package '{name}' not found in registry.")
        return recipe
