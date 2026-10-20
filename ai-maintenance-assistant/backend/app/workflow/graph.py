from pathlib import Path
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.workflow.nodes import (
    check_completeness_node,
    compose_recommendation_node,
    create_ticket_node,
    evaluate_policy_node,
    extract_issue_node,
    lookup_asset_node,
    request_asset_selection_node,
    request_clarification_node,
    retrieve_sop_node,
)
from app.workflow.state import MaintenanceState


def route_after_completeness(state: MaintenanceState) -> str:
    """Route to clarification if info is missing, otherwise to asset lookup."""
    if state.get("status") == "needs_information":
        return "request_clarification"
    return "lookup_asset"


def route_after_asset_lookup(state: MaintenanceState) -> str:
    """Resolve missing location, asset selection, no match, or a verified asset."""
    if state.get("status") == "needs_information":
        return "request_clarification"
    if state.get("status") == "needs_asset_selection":
        return "request_asset_selection"
    if state.get("status") == "asset_not_found":
        return "end"
    return "retrieve_sop"


def get_sqlite_checkpointer() -> SqliteSaver:
    """Create a persistent SQLite checkpointer so interrupted threads survive restarts."""
    db_file = Path(settings.checkpoints_db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    return SqliteSaver(conn)


def build_workflow_graph(checkpointer=None):
    """Construct and compile the LangGraph state graph with SQLite persistence."""
    graph = StateGraph(MaintenanceState)

    # 1. Register Nodes
    graph.add_node("extract_issue", extract_issue_node)
    graph.add_node("check_completeness", check_completeness_node)
    graph.add_node("request_clarification", request_clarification_node)
    graph.add_node("lookup_asset", lookup_asset_node)
    graph.add_node("request_asset_selection", request_asset_selection_node)
    graph.add_node("retrieve_sop", retrieve_sop_node)
    graph.add_node("evaluate_policy", evaluate_policy_node)
    graph.add_node("compose_recommendation", compose_recommendation_node)
    graph.add_node("create_ticket", create_ticket_node)

    # 2. Connect Edges
    graph.add_edge(START, "extract_issue")
    graph.add_edge("extract_issue", "evaluate_policy")
    graph.add_edge("evaluate_policy", "check_completeness")

    graph.add_conditional_edges(
        "check_completeness",
        route_after_completeness,
        {
            "request_clarification": "request_clarification",
            "lookup_asset": "lookup_asset",
        }
    )
    graph.add_edge("request_clarification", "extract_issue")

    graph.add_conditional_edges(
        "lookup_asset",
        route_after_asset_lookup,
        {
            "request_asset_selection": "request_asset_selection",
            "retrieve_sop": "retrieve_sop",
            "end": END,
            "request_clarification": "request_clarification",
        }
    )
    graph.add_conditional_edges("request_asset_selection", route_after_asset_lookup, {"retrieve_sop": "retrieve_sop", "end": END, "request_asset_selection": "request_asset_selection", "request_clarification": "request_clarification"})

    graph.add_edge("retrieve_sop", "compose_recommendation")
    graph.add_edge("compose_recommendation", "create_ticket")
    graph.add_edge("create_ticket", END)

    saver = checkpointer if checkpointer is not None else get_sqlite_checkpointer()
    return graph.compile(checkpointer=saver)


# Singleton compiled graph
workflow_graph = None


def get_workflow_graph():
    global workflow_graph
    if workflow_graph is None:
        workflow_graph = build_workflow_graph()
    return workflow_graph
