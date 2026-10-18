"""GraphPilot FalkorDB schema, seed data, and data-access functions."""

from .queries import (
    explore_entity_context,
    find_shortest_path,
    find_system_experts,
    get_blast_radius,
    get_people_for_incident,
    get_related_incidents,
    get_system,
    get_system_by_name,
    get_system_decisions,
    get_system_dependencies,
    get_system_documents,
    get_system_overview,
    get_system_owner,
    get_system_paths,
    get_system_projects,
    rank_critical_systems,
    resolve_entity,
)
from .memory import get_investigation, get_recent_investigations, save_investigation
from .memory import get_memory_context, get_playbooks
from .tasks import create_task, get_task, investigator_handoff, review_task
from .actions import execute_action, get_action, propose_action


def initialize_schema(*args, **kwargs):
    from .schema import initialize_schema as _initialize_schema

    return _initialize_schema(*args, **kwargs)


def seed_graph(*args, **kwargs):
    from .seed import seed_graph as _seed_graph

    return _seed_graph(*args, **kwargs)


__all__ = [
    "explore_entity_context",
    "find_shortest_path",
    "find_system_experts",
    "get_blast_radius",
    "get_people_for_incident",
    "get_related_incidents",
    "get_system",
    "get_system_by_name",
    "get_system_decisions",
    "get_system_dependencies",
    "get_system_documents",
    "get_system_overview",
    "get_system_owner",
    "get_system_paths",
    "get_system_projects",
    "rank_critical_systems",
    "resolve_entity",
    "get_investigation",
    "get_recent_investigations",
    "get_memory_context",
    "get_playbooks",
    "save_investigation",
    "create_task",
    "get_task",
    "investigator_handoff",
    "review_task",
    "propose_action",
    "get_action",
    "execute_action",
    "initialize_schema",
    "seed_graph",
]
