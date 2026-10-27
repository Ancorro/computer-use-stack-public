"""The stack as an OSWorld agent, where OSWorld's runners look for agents.

`scripts/osworld setup` copies this file into OSWorld's `mm_agents/`. The agent lives in this repo, in
`cu_stack.osworld_agent`, from the computer-use-stack repo.
"""

from cu_stack.osworld_agent import StackAgent

__all__ = ["StackAgent"]
