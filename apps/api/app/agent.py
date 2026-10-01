from typing import TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.config import settings
from app.engine import validate_graph


class GeneratedNode(BaseModel):
    id: str
    type: str = Field(description="One of the registered node types")
    config: dict = Field(default_factory=dict)
    x: float = 0
    y: float = 0


class GeneratedEdge(BaseModel):
    source: str
    target: str
    sourceHandle: str | None = None


class GeneratedWorkflow(BaseModel):
    name: str
    nodes: list[GeneratedNode]
    edges: list[GeneratedEdge]
    missing_information: list[str] = Field(default_factory=list)


class AgentState(TypedDict):
    prompt: str
    result: dict


NODE_CATALOG = "manual-trigger, http-request, json-transform, condition, filter, delay, llm-prompt, summarizer, email, webhook, database-query"


def generate_workflow(prompt: str) -> GeneratedWorkflow:
    if not settings.llm_api_key:
        raise RuntimeError("AI agent is not configured: set LLM_API_KEY")

    def generate(state: AgentState):
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model=settings.llm_model, api_key=settings.llm_api_key, temperature=0).with_structured_output(GeneratedWorkflow)
        instruction = f"Create a workflow graph from the user request. Use only these node types: {NODE_CATALOG}. Never invent credentials, recipients, URLs, database names, or executable code; list missing values in missing_information. Every workflow starts at manual-trigger. Node IDs must be unique. Return a directed acyclic graph.\nRequest: {state['prompt']}"
        generated = model.invoke(instruction)
        definition = {"nodes": [{"id": n.id, "data": {"type": n.type, "config": n.config}, "position": {"x": n.x, "y": n.y}} for n in generated.nodes], "edges": [e.model_dump(exclude_none=True) for e in generated.edges]}
        validate_graph(definition)
        return {"result": generated.model_dump()}

    graph = StateGraph(AgentState)
    graph.add_node("generate", generate)
    graph.set_entry_point("generate")
    graph.add_edge("generate", END)
    result = graph.compile().invoke({"prompt": prompt, "result": {}})
    return GeneratedWorkflow.model_validate(result["result"])
