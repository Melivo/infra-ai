from __future__ import annotations

import unittest

from router.conversation import (
    ConversationTurn,
    TurnType,
    generation_to_turns,
    messages_to_turns,
    turns_to_messages,
)
from router.normalization import NormalizedGeneration, NormalizedMessage, NormalizedToolCall


class ConversationTurnsTests(unittest.TestCase):
    def test_messages_to_turns_split_assistant_tool_call_structure(self) -> None:
        messages = [
            NormalizedMessage(role="user", content="sum this"),
            NormalizedMessage(
                role="assistant",
                content="Calling a tool.",
                tool_calls=[
                    NormalizedToolCall(
                        call_id="call-1",
                        name="add_numbers",
                        arguments={"a": 2, "b": 3},
                    )
                ],
            ),
            NormalizedMessage(
                role="tool",
                content_json={"result": 5},
                tool_call_id="call-1",
                tool_name="add_numbers",
                metadata={"ok": True},
            ),
        ]

        turns = messages_to_turns(messages)

        self.assertEqual(
            [turn.type for turn in turns],
            [
                TurnType.USER,
                TurnType.ASSISTANT,
                TurnType.TOOL_CALL,
                TurnType.TOOL_RESULT,
            ],
        )
        self.assertEqual(turns[0].role, "user")
        self.assertEqual(turns[1].content, "Calling a tool.")
        self.assertEqual(turns[2].tool_name, "add_numbers")
        self.assertEqual(turns[2].tool_call_id, "call-1")
        self.assertEqual(turns[2].tool_arguments, {"a": 2, "b": 3})
        self.assertEqual(turns[3].content_json, {"result": 5})
        self.assertEqual(turns[3].tool_name, "add_numbers")

    def test_turns_to_messages_rebuild_provider_visible_messages(self) -> None:
        turns = [
            ConversationTurn(type=TurnType.USER, role="system", content="Be concise."),
            ConversationTurn(type=TurnType.USER, role="user", content="sum this"),
            ConversationTurn(type=TurnType.ASSISTANT, role="assistant", content="Calling a tool."),
            ConversationTurn(
                type=TurnType.TOOL_CALL,
                tool_name="add_numbers",
                tool_call_id="call-1",
                tool_arguments={"a": 2, "b": 3},
            ),
            ConversationTurn(
                type=TurnType.TOOL_RESULT,
                role="tool",
                content_json={"result": 5},
                tool_name="add_numbers",
                tool_call_id="call-1",
                metadata={"ok": True},
            ),
            ConversationTurn(type=TurnType.FINAL, role="assistant", content="done"),
        ]

        messages = turns_to_messages(turns)

        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].role, "user")
        self.assertEqual(messages[2].role, "assistant")
        self.assertEqual(messages[2].content, "Calling a tool.")
        self.assertEqual(len(messages[2].tool_calls), 1)
        self.assertEqual(messages[2].tool_calls[0].name, "add_numbers")
        self.assertEqual(messages[2].tool_calls[0].arguments, {"a": 2, "b": 3})
        self.assertEqual(messages[3].role, "tool")
        self.assertEqual(messages[3].content_json, {"result": 5})

        messages_with_final = turns_to_messages(turns, include_final=True)
        self.assertEqual(len(messages_with_final), 5)
        self.assertEqual(messages_with_final[-1].role, "assistant")
        self.assertEqual(messages_with_final[-1].content, "done")

    def test_generation_to_turns_adds_final_marker_without_changing_assistant_turn(self) -> None:
        generation = NormalizedGeneration(
            message=NormalizedMessage(role="assistant", content="done"),
            final=True,
            finish_reason="stop",
            response_id="resp-1",
            model="gpt-test",
            provider_name="provider-test",
            provider_slot="slot-test",
        )

        turns = generation_to_turns(generation)

        self.assertEqual([turn.type for turn in turns], [TurnType.ASSISTANT, TurnType.FINAL])
        self.assertEqual(turns[0].content, "done")
        self.assertEqual(turns[1].content, "done")
        self.assertEqual(turns[1].metadata["finish_reason"], "stop")
        self.assertEqual(turns[1].metadata["response_id"], "resp-1")
        self.assertEqual(turns[1].metadata["provider_name"], "provider-test")


if __name__ == "__main__":
    unittest.main()
