"""Tests for planning doc inventory and read policy."""
import pytest
from pathlib import Path

from cowork_pilot.planning.planning_doc_inventory import (
    build_doc_role_inventory,
    select_context_paths,
    READ_POLICY_INDEX_ONLY,
    READ_POLICY_SPEC_DOCUMENTS,
    READ_POLICY_ALL,
    READ_POLICY_NONE,
)


@pytest.fixture
def project_dir(tmp_path):
    """Create a project with various doc files."""
    project = tmp_path / "project"
    project.mkdir()

    # Create specs structure
    (project / "docs").mkdir()
    (project / "docs" / "specs").mkdir()
    (project / "docs" / "specs" / "index.md").write_text("# Specs Index")
    (project / "docs" / "specs" / "feature-a.md").write_text("# Feature A")
    (project / "docs" / "specs" / "feature-b.md").write_text("# Feature B")

    # Create single-file docs
    (project / "AGENTS.md").write_text("# Agents")
    (project / "ARCHITECTURE.md").write_text("# Architecture")
    (project / "docs" / "DESIGN_GUIDE.md").write_text("# Design Guide")
    (project / "docs" / "SECURITY.md").write_text("# Security")

    # Create design docs
    (project / "docs" / "design-docs").mkdir()
    (project / "docs" / "design-docs" / "core-beliefs.md").write_text("# Core Beliefs")
    (project / "docs" / "design-docs" / "data-model.md").write_text("# Data Model")

    return project


class TestReadPolicyConstants:
    """Test read policy constants."""

    def test_read_policy_constants_exist(self):
        """All read policy constants should be defined."""
        assert READ_POLICY_NONE == "none"
        assert READ_POLICY_INDEX_ONLY == "index_only"
        assert READ_POLICY_SPEC_DOCUMENTS == "spec_documents"
        assert READ_POLICY_ALL == "all"

    def test_read_policy_constants_are_strings(self):
        """All constants should be strings."""
        assert isinstance(READ_POLICY_NONE, str)
        assert isinstance(READ_POLICY_INDEX_ONLY, str)
        assert isinstance(READ_POLICY_SPEC_DOCUMENTS, str)
        assert isinstance(READ_POLICY_ALL, str)


class TestBuildDocRoleInventory:
    """Test build_doc_role_inventory function."""

    def test_inventory_returns_dict(self, project_dir):
        """Should return a dict of role -> paths."""
        inventory = build_doc_role_inventory(project_dir)
        assert isinstance(inventory, dict)

    def test_inventory_has_all_roles(self, project_dir):
        """Should have entries for all expected roles."""
        inventory = build_doc_role_inventory(project_dir)
        expected_roles = {
            "spec_documents",
            "spec_index",
            "agents",
            "architecture",
            "design_guide",
            "security",
            "core_beliefs",
            "data_model",
        }
        assert set(inventory.keys()) >= expected_roles

    def test_spec_documents_role(self, project_dir):
        """spec_documents role should contain all spec files except index."""
        inventory = build_doc_role_inventory(project_dir)
        spec_docs = inventory.get("spec_documents", ())

        assert isinstance(spec_docs, tuple)
        # Should contain feature-a.md and feature-b.md but not index.md
        spec_names = {p.name for p in spec_docs}
        assert "feature-a.md" in spec_names
        assert "feature-b.md" in spec_names
        assert "index.md" not in spec_names

    def test_spec_index_role(self, project_dir):
        """spec_index role should contain only index.md."""
        inventory = build_doc_role_inventory(project_dir)
        spec_index = inventory.get("spec_index", ())

        assert isinstance(spec_index, tuple)
        # Should contain index.md
        spec_names = {p.name for p in spec_index}
        assert "index.md" in spec_names

    def test_agents_role(self, project_dir):
        """agents role should contain AGENTS.md."""
        inventory = build_doc_role_inventory(project_dir)
        agents = inventory.get("agents", ())

        assert isinstance(agents, tuple)
        assert any(p.name == "AGENTS.md" for p in agents)

    def test_architecture_role(self, project_dir):
        """architecture role should find ARCHITECTURE.md files."""
        inventory = build_doc_role_inventory(project_dir)
        arch = inventory.get("architecture", ())

        assert isinstance(arch, tuple)
        # Should find ARCHITECTURE.md (not docs/ARCHITECTURE.md in this setup)
        assert any("ARCHITECTURE.md" in str(p) for p in arch)

    def test_design_guide_role(self, project_dir):
        """design_guide role should contain docs/DESIGN_GUIDE.md."""
        inventory = build_doc_role_inventory(project_dir)
        design = inventory.get("design_guide", ())

        assert isinstance(design, tuple)
        assert any(p.name == "DESIGN_GUIDE.md" for p in design)

    def test_security_role(self, project_dir):
        """security role should contain docs/SECURITY.md."""
        inventory = build_doc_role_inventory(project_dir)
        security = inventory.get("security", ())

        assert isinstance(security, tuple)
        assert any(p.name == "SECURITY.md" for p in security)

    def test_core_beliefs_role(self, project_dir):
        """core_beliefs role should contain design-docs/core-beliefs.md."""
        inventory = build_doc_role_inventory(project_dir)
        beliefs = inventory.get("core_beliefs", ())

        assert isinstance(beliefs, tuple)
        assert any(p.name == "core-beliefs.md" for p in beliefs)

    def test_data_model_role(self, project_dir):
        """data_model role should contain design-docs/data-model.md."""
        inventory = build_doc_role_inventory(project_dir)
        model = inventory.get("data_model", ())

        assert isinstance(model, tuple)
        assert any(p.name == "data-model.md" for p in model)

    def test_missing_files_not_in_inventory(self, tmp_path):
        """Missing files should not appear in inventory."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "docs").mkdir()

        inventory = build_doc_role_inventory(project)

        # These roles should either be empty or not contain non-existent files
        for role, paths in inventory.items():
            for path in paths:
                assert path.exists(), f"Non-existent path in {role}: {path}"

    def test_product_specs_variant(self, tmp_path):
        """Should handle docs/product-specs structure."""
        project = tmp_path / "project"
        project.mkdir()

        # Create product-specs structure instead
        (project / "docs").mkdir()
        (project / "docs" / "product-specs").mkdir()
        (project / "docs" / "product-specs" / "index.md").write_text("# Product Specs")
        (project / "docs" / "product-specs" / "feature-x.md").write_text("# Feature X")

        inventory = build_doc_role_inventory(project)

        # Should find spec files in product-specs
        spec_docs = inventory.get("spec_documents", ())
        assert any(p.name == "feature-x.md" for p in spec_docs)


class TestSelectContextPaths:
    """Test select_context_paths function."""

    def test_select_with_none_policy(self, project_dir):
        """none policy should return empty tuple."""
        inventory = build_doc_role_inventory(project_dir)

        paths = select_context_paths(
            inventory=inventory,
            required_roles=("agents", "spec_index"),
            read_policy=READ_POLICY_NONE,
        )

        assert paths == ()

    def test_select_with_index_only_policy(self, project_dir):
        """index_only policy should return only spec_index."""
        inventory = build_doc_role_inventory(project_dir)

        paths = select_context_paths(
            inventory=inventory,
            required_roles=("agents", "spec_index"),
            read_policy=READ_POLICY_INDEX_ONLY,
        )

        # Should only contain spec_index files
        spec_index = inventory.get("spec_index", ())
        for path in paths:
            assert path in spec_index, f"Path {path} not in spec_index"

    def test_select_with_spec_documents_policy(self, project_dir):
        """spec_documents policy should return spec_documents role."""
        inventory = build_doc_role_inventory(project_dir)

        paths = select_context_paths(
            inventory=inventory,
            required_roles=("spec_documents", "agents"),
            read_policy=READ_POLICY_SPEC_DOCUMENTS,
        )

        # Should contain spec_documents
        spec_docs = inventory.get("spec_documents", ())
        for path in paths:
            assert path in spec_docs, f"Path {path} not in spec_documents"

    def test_select_with_all_policy(self, project_dir):
        """all policy should return all requested roles."""
        inventory = build_doc_role_inventory(project_dir)

        roles = ("agents", "architecture", "spec_index")
        paths = select_context_paths(
            inventory=inventory,
            required_roles=roles,
            read_policy=READ_POLICY_ALL,
        )

        # Should contain all files from all requested roles
        expected = set()
        for role in roles:
            if role in inventory:
                expected.update(inventory[role])

        assert set(paths) == expected

    def test_select_with_all_policy_empty_roles(self, project_dir):
        """all policy with empty roles should return empty."""
        inventory = build_doc_role_inventory(project_dir)

        paths = select_context_paths(
            inventory=inventory,
            required_roles=(),
            read_policy=READ_POLICY_ALL,
        )

        assert paths == ()

    def test_select_returns_tuple(self, project_dir):
        """Should return a tuple of Paths."""
        inventory = build_doc_role_inventory(project_dir)

        paths = select_context_paths(
            inventory=inventory,
            required_roles=("agents",),
            read_policy=READ_POLICY_ALL,
        )

        assert isinstance(paths, tuple)
        assert all(isinstance(p, Path) for p in paths)

    def test_select_respects_role_boundaries(self, project_dir):
        """Should only select from requested roles."""
        inventory = build_doc_role_inventory(project_dir)

        # Request only agents role
        paths = select_context_paths(
            inventory=inventory,
            required_roles=("agents",),
            read_policy=READ_POLICY_ALL,
        )

        # Should not include spec_documents or other roles
        agents = inventory.get("agents", ())
        assert set(paths) == set(agents)

    def test_select_with_missing_role_in_inventory(self, project_dir):
        """Should handle roles not in inventory gracefully."""
        inventory = build_doc_role_inventory(project_dir)
        # Remove a role if it exists, or request a non-existent one
        roles = ("nonexistent_role", "agents")

        paths = select_context_paths(
            inventory=inventory,
            required_roles=roles,
            read_policy=READ_POLICY_ALL,
        )

        # Should only return paths for roles that exist
        agents = inventory.get("agents", ())
        assert set(paths) == set(agents)

    def test_select_index_only_with_spec_documents_required(self, project_dir):
        """index_only policy should ignore spec_documents requirement."""
        inventory = build_doc_role_inventory(project_dir)

        paths = select_context_paths(
            inventory=inventory,
            required_roles=("spec_documents", "agents"),
            read_policy=READ_POLICY_INDEX_ONLY,
        )

        # Should only include spec_index, not spec_documents
        spec_index = inventory.get("spec_index", ())
        spec_docs = inventory.get("spec_documents", ())

        for path in paths:
            assert path in spec_index, f"Path {path} not in spec_index"
            # Should not include spec_documents
            if spec_docs:
                for doc in spec_docs:
                    assert path != doc, f"Found spec_document {doc} in index_only results"

    def test_select_spec_documents_policy_includes_index(self, project_dir):
        """spec_documents policy should include spec_documents but not spec_index."""
        inventory = build_doc_role_inventory(project_dir)

        paths = select_context_paths(
            inventory=inventory,
            required_roles=("spec_documents", "spec_index"),
            read_policy=READ_POLICY_SPEC_DOCUMENTS,
        )

        # Should include spec_documents
        spec_docs = inventory.get("spec_documents", ())
        spec_index = inventory.get("spec_index", ())

        # All paths should be from spec_documents
        for path in paths:
            assert path in spec_docs, f"Path {path} not in spec_documents"

        # Should not include spec_index items
        for idx_path in spec_index:
            assert idx_path not in paths, f"spec_index item {idx_path} should not be in results"
