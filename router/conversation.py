"""Primary router-internal conversation model and compatibility mappings."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Literal, Protocol

from router.normalization import NormalizedGeneration, NormalizedMessage, NormalizedToolCall
from router.schemas import JSONValue
from router.tools.types import ToolResult


class TurnType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL = "final"


class StepPhase(str, Enum):
    REASONING = "reasoning"
    TOOL_PLAN = "tool_plan"
    REFINEMENT = "refinement"
    FINALIZATION = "finalization"


class ExecutionStrategy(str, Enum):
    SEQUENTIAL = "sequential"


class ExecutionDependencyOrigin(str, Enum):
    DECLARED = "declared"
    EXECUTION_STRATEGY = "execution_strategy"


class ExecutionNodeStatus(str, Enum):
    PLANNED = "planned"
    COMPLETED = "completed"


class ConversationTurn(Protocol):
    type: TurnType
    metadata: dict[str, JSONValue]


@dataclass(frozen=True)
class UserTurn(ConversationTurn):
    role: Literal["system", "user"]
    content: str | None = None
    content_json: JSONValue | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    type: TurnType = field(default=TurnType.USER, init=False)


@dataclass(frozen=True)
class AssistantTurn(ConversationTurn):
    content: str | None = None
    content_json: JSONValue | None = None
    phase: StepPhase = StepPhase.REASONING
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    role: Literal["assistant"] = field(default="assistant", init=False)
    type: TurnType = field(default=TurnType.ASSISTANT, init=False)


@dataclass(frozen=True)
class ToolCallTurn(ConversationTurn):
    tool_name: str
    tool_call_id: str
    tool_arguments: dict[str, JSONValue]
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    type: TurnType = field(default=TurnType.TOOL_CALL, init=False)


@dataclass(frozen=True)
class ToolResultTurn(ConversationTurn):
    tool_name: str | None
    tool_call_id: str | None
    content: str | None = None
    content_json: JSONValue | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    role: Literal["tool"] = field(default="tool", init=False)
    type: TurnType = field(default=TurnType.TOOL_RESULT, init=False)


@dataclass(frozen=True)
class FinalTurn(ConversationTurn):
    content: str | None = None
    content_json: JSONValue | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    role: Literal["assistant"] = field(default="assistant", init=False)
    type: TurnType = field(default=TurnType.FINAL, init=False)


@dataclass(frozen=True)
class ExecutionDependency:
    call_id: str
    origin: ExecutionDependencyOrigin


@dataclass(frozen=True)
class ExecutionPlanNode:
    tool_call: ToolCallTurn
    declared_dependencies: list[ExecutionDependency] = field(default_factory=list)
    strategy_dependencies: list[ExecutionDependency] = field(default_factory=list)
    state: ExecutionNodeStatus = ExecutionNodeStatus.PLANNED
    result: ToolResultTurn | None = None

    @property
    def status(self) -> ExecutionNodeStatus:
        return self.state

    @property
    def dependencies(self) -> list[ExecutionDependency]:
        return [*self.declared_dependencies, *self.strategy_dependencies]

    @property
    def declared_dependency_call_ids(self) -> list[str]:
        return [dependency.call_id for dependency in self.declared_dependencies]

    @property
    def strategy_dependency_call_ids(self) -> list[str]:
        return [dependency.call_id for dependency in self.strategy_dependencies]

    @property
    def depends_on_call_ids(self) -> list[str]:
        call_ids: list[str] = []
        for dependency in self.dependencies:
            if dependency.call_id not in call_ids:
                call_ids.append(dependency.call_id)
        return call_ids


@dataclass(frozen=True)
class ExecutionPlan:
    strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL
    nodes: list[ExecutionPlanNode] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionStep:
    reasoning_turns: list[AssistantTurn] = field(default_factory=list)
    planning_turns: list[AssistantTurn] = field(default_factory=list)
    refinement_turns: list[AssistantTurn] = field(default_factory=list)
    finalization_turns: list[AssistantTurn] = field(default_factory=list)
    plan: ExecutionPlan = field(default_factory=ExecutionPlan)
    final: FinalTurn | None = None

    @property
    def tool_calls(self) -> list[ToolCallTurn]:
        return [node.tool_call for node in self.plan.nodes]

    @property
    def tool_results(self) -> list[ToolResultTurn]:
        return [node.result for node in self.plan.nodes if node.result is not None]

    @property
    def primary_assistant_turn(self) -> AssistantTurn | None:
        if self.finalization_turns:
            return self.finalization_turns[-1]
        if self.planning_turns:
            return self.planning_turns[-1]
        if self.refinement_turns:
            return self.refinement_turns[-1]
        if self.reasoning_turns:
            return self.reasoning_turns[-1]
        return None


def create_execution_step() -> ExecutionStep:
    return ExecutionStep()


def create_declared_execution_plan(
    *,
    strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL,
) -> ExecutionPlan:
    return ExecutionPlan(strategy=strategy)


def message_to_turns(message: NormalizedMessage) -> list[ConversationTurn]:
    if message.role in {"system", "user"}:
        return [
            UserTurn(
                role=message.role,
                content=message.content,
                content_json=message.content_json,
                metadata=dict(message.metadata),
            )
        ]

    if message.role == "assistant":
        phase = StepPhase.TOOL_PLAN if message.tool_calls else StepPhase.REASONING
        turns: list[ConversationTurn] = [
            AssistantTurn(
                content=message.content,
                content_json=message.content_json,
                phase=phase,
                metadata=dict(message.metadata),
            )
        ]
        for tool_call in message.tool_calls:
            turns.append(tool_call_to_turn(tool_call))
        return turns

    if message.role == "tool":
        return [
            ToolResultTurn(
                content=message.content,
                content_json=message.content_json,
                tool_name=message.tool_name,
                tool_call_id=message.tool_call_id,
                metadata=dict(message.metadata),
            )
        ]

    raise ValueError(f"Unsupported normalized message role: {message.role!r}")


def messages_to_turns(messages: list[NormalizedMessage]) -> list[ConversationTurn]:
    turns: list[ConversationTurn] = []
    for message in messages:
        turns.extend(message_to_turns(message))
    return turns


def tool_call_to_turn(tool_call: NormalizedToolCall) -> ToolCallTurn:
    return ToolCallTurn(
        tool_name=tool_call.name,
        tool_call_id=tool_call.call_id,
        tool_arguments=dict(tool_call.arguments),
        metadata=dict(tool_call.metadata),
    )


def turn_to_tool_call(turn: ConversationTurn) -> NormalizedToolCall:
    if not isinstance(turn, ToolCallTurn):
        raise ValueError(f"Expected a tool_call turn, got {turn.type!r}")
    return NormalizedToolCall(
        call_id=turn.tool_call_id,
        name=turn.tool_name,
        arguments=dict(turn.tool_arguments),
        metadata=dict(turn.metadata),
    )


def generation_to_turns(generation: NormalizedGeneration) -> list[ConversationTurn]:
    """Compatibility mapping from legacy normalized generation into conversation turns."""
    phase = StepPhase.FINALIZATION if generation.final and not generation.message.tool_calls else (
        StepPhase.TOOL_PLAN if generation.message.tool_calls else StepPhase.REASONING
    )
    turns = [
        AssistantTurn(
            content=generation.message.content,
            content_json=generation.message.content_json,
            phase=phase,
            metadata=dict(generation.message.metadata),
        )
    ]
    turns.extend(tool_call_to_turn(tool_call) for tool_call in generation.message.tool_calls)
    if generation.final:
        turns.append(
            FinalTurn(
                content=generation.message.content,
                content_json=generation.message.content_json,
                metadata=_generation_metadata(generation),
            )
        )
    return turns


def build_execution_plan(
    tool_calls: list[ToolCallTurn],
    *,
    strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL,
) -> ExecutionPlan:
    plan = create_declared_execution_plan(strategy=strategy)
    for tool_call in tool_calls:
        plan = append_declared_plan_node(plan, tool_call)
    plan = derive_strategy_dependencies(plan)
    validate_execution_plan(plan)
    return plan


def append_declared_plan_node(
    plan: ExecutionPlan,
    tool_call: ToolCallTurn,
    *,
    depends_on_call_ids: list[str] | None = None,
) -> ExecutionPlan:
    if any(node.tool_call.tool_call_id == tool_call.tool_call_id for node in plan.nodes):
        return plan

    declared_dependencies = [
        ExecutionDependency(call_id=call_id, origin=ExecutionDependencyOrigin.DECLARED)
        for call_id in (depends_on_call_ids or [])
    ]
    return replace(
        plan,
        nodes=[
            *plan.nodes,
            ExecutionPlanNode(
                tool_call=tool_call,
                declared_dependencies=declared_dependencies,
            ),
        ],
    )


def derive_strategy_dependencies(plan: ExecutionPlan) -> ExecutionPlan:
    if plan.strategy != ExecutionStrategy.SEQUENTIAL:
        return plan

    nodes: list[ExecutionPlanNode] = []
    previous_call_id: str | None = None
    for node in plan.nodes:
        strategy_dependencies: list[ExecutionDependency] = []
        if previous_call_id is not None:
            strategy_dependencies.append(
                ExecutionDependency(
                    call_id=previous_call_id,
                    origin=ExecutionDependencyOrigin.EXECUTION_STRATEGY,
                )
            )
        nodes.append(replace(node, strategy_dependencies=strategy_dependencies))
        previous_call_id = node.tool_call.tool_call_id
    return replace(plan, nodes=nodes)


def validate_execution_plan(plan: ExecutionPlan) -> None:
    known_call_ids: list[str] = []
    for node in plan.nodes:
        call_id = node.tool_call.tool_call_id
        if call_id in known_call_ids:
            raise ValueError(f"Execution plan contains duplicate tool call id: {call_id}")
        known_call_ids.append(call_id)

    known_call_id_set = set(known_call_ids)
    for node in plan.nodes:
        seen_dependency_keys: set[tuple[str, ExecutionDependencyOrigin]] = set()
        for dependency in node.dependencies:
            dependency_key = (dependency.call_id, dependency.origin)
            if dependency_key in seen_dependency_keys:
                raise ValueError(
                    f"Execution plan node {node.tool_call.tool_call_id} contains duplicate dependency {dependency.call_id}"
                )
            seen_dependency_keys.add(dependency_key)
            if dependency.call_id == node.tool_call.tool_call_id:
                raise ValueError(
                    f"Execution plan node {node.tool_call.tool_call_id} cannot depend on itself"
                )
            if dependency.call_id not in known_call_id_set:
                raise ValueError(
                    f"Execution plan node {node.tool_call.tool_call_id} depends on unknown call id {dependency.call_id}"
                )


def apply_tool_result_to_plan(plan: ExecutionPlan, result: ToolResultTurn) -> ExecutionPlan:
    nodes: list[ExecutionPlanNode] = []
    matched = False
    for node in plan.nodes:
        if node.tool_call.tool_call_id == result.tool_call_id and node.result is None:
            nodes.append(replace(node, result=result, state=ExecutionNodeStatus.COMPLETED))
            matched = True
            continue
        nodes.append(node)

    if matched:
        return replace(plan, nodes=nodes)
    return plan


def mark_plan_node_completed(plan: ExecutionPlan, result: ToolResultTurn) -> ExecutionPlan:
    return apply_tool_result_to_plan(plan, result)


def apply_tool_result_to_step(step: ExecutionStep, result: ToolResultTurn) -> ExecutionStep:
    return replace(step, plan=apply_tool_result_to_plan(step.plan, result))


def mark_step_node_completed(step: ExecutionStep, result: ToolResultTurn) -> ExecutionStep:
    return apply_tool_result_to_step(step, result)


def planned_plan_nodes(plan: ExecutionPlan) -> list[ExecutionPlanNode]:
    return [node for node in plan.nodes if node.state == ExecutionNodeStatus.PLANNED]


def compute_executable_plan_nodes(plan: ExecutionPlan) -> list[ExecutionPlanNode]:
    completed_call_ids = {
        node.tool_call.tool_call_id
        for node in plan.nodes
        if node.state == ExecutionNodeStatus.COMPLETED
    }
    executable: list[ExecutionPlanNode] = []
    for node in plan.nodes:
        if node.state != ExecutionNodeStatus.PLANNED:
            continue
        if not all(dependency.call_id in completed_call_ids for dependency in node.dependencies):
            continue
        executable.append(node)
        if plan.strategy == ExecutionStrategy.SEQUENTIAL:
            break
    return executable


def next_executable_plan_nodes(plan: ExecutionPlan) -> list[ExecutionPlanNode]:
    return compute_executable_plan_nodes(plan)


def execution_steps_from_turns(turns: list[ConversationTurn]) -> list[ExecutionStep]:
    """Rebuild explicit execution-step state from the router's turn transport."""
    steps: list[ExecutionStep] = []
    current_step: ExecutionStep | None = None

    for turn in turns:
        if isinstance(turn, AssistantTurn):
            if current_step is None or current_step.final is not None or current_step.tool_results:
                current_step = create_execution_step()
                steps.append(current_step)
            current_step = _append_assistant_turn(current_step, turn)
            steps[-1] = current_step
            continue
        if current_step is None:
            continue
        if isinstance(turn, ToolCallTurn):
            current_step = replace(
                current_step,
                plan=_append_tool_call_to_plan(current_step.plan, turn),
            )
            steps[-1] = current_step
            continue
        if isinstance(turn, ToolResultTurn):
            current_step = apply_tool_result_to_step(current_step, turn)
            steps[-1] = current_step
            continue
        if isinstance(turn, FinalTurn):
            current_step = replace(current_step, final=turn)
            steps[-1] = current_step
            continue
        current_step = None

    return steps


def turns_to_generation(turns: list[ConversationTurn]) -> NormalizedGeneration:
    """Compatibility mapping from primary conversation turns to API-facing generation shape."""
    steps = execution_steps_from_turns(turns)
    if not steps:
        raise ValueError("Conversation turns do not contain an execution step.")

    step = steps[-1]
    assistant_turn = step.primary_assistant_turn
    if assistant_turn is None:
        raise ValueError("Conversation execution step does not contain an assistant turn.")

    metadata_source = step.final or assistant_turn
    usage = metadata_source.metadata.get("usage")
    return NormalizedGeneration(
        message=NormalizedMessage(
            role="assistant",
            content=assistant_turn.content,
            content_json=assistant_turn.content_json,
            tool_calls=[turn_to_tool_call(turn) for turn in step.tool_calls],
            metadata=dict(assistant_turn.metadata),
        ),
        final=step.final is not None,
        finish_reason=_metadata_str(metadata_source.metadata, "finish_reason"),
        response_id=_metadata_str(metadata_source.metadata, "response_id"),
        model=_metadata_str(metadata_source.metadata, "model"),
        provider_name=_metadata_str(metadata_source.metadata, "provider_name"),
        provider_slot=_metadata_str(metadata_source.metadata, "provider_slot"),
        usage=usage if isinstance(usage, dict) else None,
        metadata=dict(metadata_source.metadata),
    )


def turn_to_message(turn: ConversationTurn) -> NormalizedMessage:
    if isinstance(turn, UserTurn):
        return NormalizedMessage(
            role=turn.role,
            content=turn.content,
            content_json=turn.content_json,
            metadata=dict(turn.metadata),
        )

    if isinstance(turn, AssistantTurn):
        return NormalizedMessage(
            role="assistant",
            content=turn.content,
            content_json=turn.content_json,
            metadata=dict(turn.metadata),
        )

    if isinstance(turn, FinalTurn):
        return NormalizedMessage(
            role="assistant",
            content=turn.content,
            content_json=turn.content_json,
            metadata=dict(turn.metadata),
        )

    if isinstance(turn, ToolCallTurn):
        return NormalizedMessage(
            role="assistant",
            tool_calls=[
                NormalizedToolCall(
                    call_id=turn.tool_call_id,
                    name=turn.tool_name,
                    arguments=dict(turn.tool_arguments),
                    metadata=dict(turn.metadata),
                )
            ],
        )

    if isinstance(turn, ToolResultTurn):
        return NormalizedMessage(
            role="tool",
            content=turn.content,
            content_json=turn.content_json,
            tool_call_id=turn.tool_call_id,
            tool_name=turn.tool_name,
            metadata=dict(turn.metadata),
        )

    raise ValueError(f"Unsupported conversation turn type: {turn!r}")


def turns_to_messages(
    turns: list[ConversationTurn],
    *,
    include_final: bool = False,
) -> list[NormalizedMessage]:
    messages: list[NormalizedMessage] = []
    pending_assistant: NormalizedMessage | None = None

    def flush_pending_assistant() -> None:
        nonlocal pending_assistant
        if pending_assistant is None:
            return
        messages.append(pending_assistant)
        pending_assistant = None

    for turn in turns:
        if isinstance(turn, ToolCallTurn):
            tool_call = turn_to_tool_call(turn)
            if pending_assistant is None:
                pending_assistant = NormalizedMessage(role="assistant", tool_calls=[tool_call])
            else:
                pending_assistant = replace(
                    pending_assistant,
                    tool_calls=[*pending_assistant.tool_calls, tool_call],
                )
            continue

        flush_pending_assistant()
        if isinstance(turn, FinalTurn) and not include_final:
            continue
        if isinstance(turn, AssistantTurn):
            pending_assistant = turn_to_message(turn)
            continue
        messages.append(turn_to_message(turn))

    flush_pending_assistant()
    return messages


def tool_result_to_turn(result: ToolResult) -> ToolResultTurn:
    return ToolResultTurn(
        content=result.output_text if result.output_json is not None else _tool_result_text(result),
        content_json=result.output_json,
        tool_name=result.name,
        tool_call_id=result.call_id,
        metadata=_tool_result_metadata(result),
    )


def _tool_result_text(result: ToolResult) -> str | None:
    if result.output_text is not None:
        return result.output_text
    if result.error_message is not None:
        return result.error_message
    return ""


def _tool_result_metadata(result: ToolResult) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {
        "ok": result.ok,
        "tool_name": result.name,
    }
    if result.error_code is not None:
        metadata["error_code"] = result.error_code
    return metadata


def _append_assistant_turn(step: ExecutionStep, turn: AssistantTurn) -> ExecutionStep:
    if turn.phase == StepPhase.TOOL_PLAN:
        return replace(step, planning_turns=[*step.planning_turns, turn])
    if turn.phase == StepPhase.REFINEMENT:
        return replace(step, refinement_turns=[*step.refinement_turns, turn])
    if turn.phase == StepPhase.FINALIZATION:
        return replace(step, finalization_turns=[*step.finalization_turns, turn])
    return replace(step, reasoning_turns=[*step.reasoning_turns, turn])


def _append_tool_call_to_plan(plan: ExecutionPlan, tool_call: ToolCallTurn) -> ExecutionPlan:
    updated_plan = append_declared_plan_node(plan, tool_call)
    updated_plan = derive_strategy_dependencies(updated_plan)
    validate_execution_plan(updated_plan)
    return updated_plan


def _generation_metadata(generation: NormalizedGeneration) -> dict[str, JSONValue]:
    metadata = dict(generation.metadata)
    if generation.finish_reason is not None:
        metadata["finish_reason"] = generation.finish_reason
    if generation.response_id is not None:
        metadata["response_id"] = generation.response_id
    if generation.model is not None:
        metadata["model"] = generation.model
    if generation.provider_name is not None:
        metadata["provider_name"] = generation.provider_name
    if generation.provider_slot is not None:
        metadata["provider_slot"] = generation.provider_slot
    if generation.usage is not None:
        metadata["usage"] = generation.usage
    return metadata


def _metadata_str(metadata: dict[str, JSONValue], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None
