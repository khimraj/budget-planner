import logging
from typing import Any, AsyncIterable
from livekit.agents import llm, utils
from livekit.agents.types import APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from .graph import run_agent

logger = logging.getLogger("graph_llm")

class GraphLLMStream(llm.LLMStream):
    def __init__(self, llm: llm.LLM, chat_ctx: llm.ChatContext, tools: list[llm.Tool] | None = None, conn_options: APIConnectOptions | None = None):
        super().__init__(llm=llm, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options or DEFAULT_API_CONNECT_OPTIONS)
        self._sent_result = False

    async def _run(self) -> None:
        # Extract messages
        logger.info("Preparing to run graph with message history")
        messages = []
        for msg in self._chat_ctx.messages():
            if msg.role == "user":
                messages.append(("user", msg.text_content or ""))
            elif msg.role == "assistant":
                messages.append(("assistant", msg.text_content or ""))
            # System messages are handled by the graph itself
        
        user_input = ""
        history = []
        
        if messages:
            if messages[-1][0] == "user":
                user_input = messages[-1][1]
                history = messages[:-1]
            else:
                # If the last message wasn't user, we might be in a weird state or just starting
                # But typically LLM is called after user input.
                # For now, assume strict turn-taking.
                history = messages
        
        if not user_input:
             # If called without input, maybe just return empty or generic greeting?
             if not history:
                 return
             
             logger.warning("No user input found in chat context")
             return

        try:
            logger.info(f"Running graph for input: {user_input}")
            response_text = await run_agent(user_input, history)
            logger.info(f"Graph returned: {response_text}")
            
            chunk = llm.ChatChunk(
                id=utils.shortuuid("chunk_"),
                delta=llm.ChoiceDelta(content=response_text, role="assistant")
            )
            await self._event_ch.send(chunk)
            
        except Exception as e:
            logger.error(f"Error running graph: {e}")
            chunk = llm.ChatChunk(
                id=utils.shortuuid("chunk_"),
                delta=llm.ChoiceDelta(content=f"I encountered an error: {str(e)}", role="assistant")
            )
            await self._event_ch.send(chunk)

class GraphLLM(llm.LLM):
    def __init__(self):
        super().__init__()
        self._label = "langgraph-budget-analyst"

    @property
    def model(self) -> str:
        return "langgraph-budget-analyst"

    def chat(
        self,
        chat_ctx: llm.ChatContext,
        fnc_ctx: Any | None = None,
        temperature: float | None = None,
        n: int | None = None,
        parallel_tool_calls: bool | None = None,
        **kwargs,
    ) -> "GraphLLMStream":
        tools = kwargs.get("tools", [])
        conn_options = kwargs.get("conn_options", DEFAULT_API_CONNECT_OPTIONS)
        return GraphLLMStream(llm=self, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
