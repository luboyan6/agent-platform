"""Keep fresh RAG role reads on the Gateway database-owning event loop."""

import asyncio
from contextlib import asynccontextmanager

from app.gateway.deps import get_local_provider
from deerflow.mcp.rag_access import read_rag_policy, reset_rag_protected_aliases, set_rag_role_resolver


async def _current_role(actor: str) -> str | None:
    user = await get_local_provider().get_user(actor)
    return user.system_role if user is not None else None


@asynccontextmanager
async def rag_mcp_authority():
    loop = asyncio.get_running_loop()

    async def resolve(actor: str) -> str | None:
        if asyncio.get_running_loop() is loop:
            return await _current_role(actor)
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_current_role(actor), loop))

    previous_aliases = reset_rag_protected_aliases()
    previous_resolver = set_rag_role_resolver(resolve)
    try:
        await asyncio.to_thread(read_rag_policy)
        yield
    finally:
        set_rag_role_resolver(previous_resolver)
        reset_rag_protected_aliases(previous_aliases)
