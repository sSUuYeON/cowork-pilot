from cowork_pilot.planning.docs_inventory import (
    check_core_docs,
    resolve_core_doc_inventory,
    select_adaptive_docs,
)
from cowork_pilot.planning.models import ClassificationSnapshot, ProjectMode, SizeClass


def _snapshot(size_class: SizeClass) -> ClassificationSnapshot:
    return ClassificationSnapshot(
        project_mode=ProjectMode.GREENFIELD,
        size_class=size_class,
        product_type="greenfield-app",
        confidence="high",
        borderline=False,
    )


def test_docs_inventory_smoke():
    core_docs = check_core_docs()
    adaptive_docs = select_adaptive_docs()

    assert isinstance(core_docs, list)
    assert isinstance(adaptive_docs, list)


def test_small_core_doc_inventory_keeps_architecture_conditional():
    inventory = resolve_core_doc_inventory(_snapshot(SizeClass.SMALL))

    assert "design_guide" in inventory.required_core_docs
    assert "architecture" in inventory.conditional_core_docs


def test_medium_core_doc_inventory_promotes_architecture_and_security():
    inventory = resolve_core_doc_inventory(_snapshot(SizeClass.MEDIUM))

    assert "architecture" in inventory.required_core_docs
    assert "security" in inventory.required_core_docs


def test_select_adaptive_docs_returns_conditional_roles_for_small_projects():
    adaptive_docs = select_adaptive_docs(_snapshot(SizeClass.SMALL))

    assert "architecture" in adaptive_docs
