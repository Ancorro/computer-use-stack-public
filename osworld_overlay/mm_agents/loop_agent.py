"""The one-loop agent, where OSWorld's runners look for agents. It lives in computer-use-stack,
`cu_stack.loop_agent`; the fork's `scripts/osworld setup` copies this file in when CU_STACK is set."""

from cu_stack.loop_agent import LoopAgent

__all__ = ["LoopAgent"]
