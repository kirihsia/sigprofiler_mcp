import asyncio
import json
import os
import ollama
import traceback

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# =====================================================
# 1. Configuration
# =====================================================

MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

OLLAMA_HOST = os.getenv(
    "OLLAMA_HOST",
    "http://localhost:11434"
)

OLLAMA_CLIENT = ollama.Client(host=OLLAMA_HOST)

MAX_TOOL_ROUNDS = 6

SERVER_ENV = os.environ.copy()
# Defaults only; values set by the Dockerfile (e.g. USE_GPU=True) win.
for _key, _value in {
    "OUTPUT_DIR": "/data",
    "HOST_DATA_DIR": "/data",
    "USE_GPU": "False",
    "SIGPROFILERMATRIXGENERATOR_VOLUME": "/references",
}.items():
    SERVER_ENV.setdefault(_key, _value)

SERVER_PARAMS = StdioServerParameters(
    command="sigprofiler-mcp",
    args=[],
    env=SERVER_ENV,
)


# =====================================================
# 2. Convert MCP tools to Ollama format
# =====================================================

def convert_mcp_tools(mcp_tools):
    ollama_tools = []

    for tool in mcp_tools:
        ollama_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema
            }
        })

    return ollama_tools


# =====================================================
# 3. Extract MCP tool result
# =====================================================

def extract_tool_result(result):
    output = []

    for item in result.content or []:
        if item.type == "text":
            output.append(item.text)

    return "\n".join(output) or "The tool returned no text output."


# =====================================================
# 4. Ollama chat
# =====================================================

async def ask_ollama(messages, tools=None):

    kwargs = {
        "model": MODEL,
        "messages": messages,
    }

    if tools is not None:
        kwargs["tools"] = tools

    return await asyncio.to_thread(
    OLLAMA_CLIENT.chat,
    **kwargs)


# =====================================================
# 5. Interactive conversation
# =====================================================

async def chat_loop(session, ollama_tools, mcp_tools):

    allowed_tools = {tool.name for tool in mcp_tools}

    messages = [
        {
            "role": "system",
            "content": (
                "You are SigMCP, an assistant for mutational signature analysis. "
                "Use only the MCP tools provided to you. "
                "Do not claim that an operation succeeded unless the tool result confirms it. "
                "If required information is missing, ask the user for clarification. "
                "Explain tool results clearly."
            )
        }
    ]

    print("\n" + "=" * 60)
    print("SigMCP Terminal Client")
    print(f"Model: {MODEL}")
    print("Type 'exit' or 'quit' to stop.")
    print("=" * 60)

    while True:

        try:
            user_input = input("\nYou: ").strip()

        except (EOFError, KeyboardInterrupt):
            print("\nExiting SigMCP Client.")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        messages.append({
            "role": "user",
            "content": user_input
        })

        # -------------------------------------------------
        # Multi-round tool calling
        # -------------------------------------------------

        for round_number in range(1, MAX_TOOL_ROUNDS + 1):

            try:
                response = await ask_ollama(
                    messages,
                    tools=ollama_tools
                )

            except Exception as e:
                print(f"\nOllama error: {e}")
                break

            assistant_message = response.message
            messages.append(assistant_message)

            tool_calls = assistant_message.tool_calls or []

            # No more tool calls: show final answer
            if not tool_calls:
                print("\nSigMCP:", assistant_message.content or "")
                break

            print(
                f"\n[Tool round {round_number}/{MAX_TOOL_ROUNDS}]"
            )

            # -------------------------------------------------
            # Execute MCP tools
            # -------------------------------------------------

            for tool_call in tool_calls:

                tool_name = tool_call.function.name
                arguments = tool_call.function.arguments or {}

                print(f"\nCalling tool: {tool_name}")
                print(
                    "Arguments:",
                    json.dumps(arguments, indent=2, ensure_ascii=False)
                )

                if tool_name not in allowed_tools:
                    tool_output = (
                        f"Error: Tool '{tool_name}' is not available "
                        "in the MCP server."
                    )

                else:
                    try:
                        result = await session.call_tool(
                            tool_name,
                            arguments=arguments
                        )

                        tool_output = extract_tool_result(result)

                        if result.isError:
                            tool_output = "MCP tool error: " + tool_output

                    except Exception as e:
                        tool_output = f"MCP execution error: {str(e)}"

                print("\nTool result:")
                print(tool_output)

                # Return tool result to Ollama
                messages.append({
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": tool_output
                })

        else:
            print(
                "\nMaximum tool rounds reached. "
                "Please review the results or refine your request."
            )


# =====================================================
# 6. Main
# =====================================================

async def main():

    print("\nConnecting to SigMCP Server...")

    try:
        async with stdio_client(SERVER_PARAMS) as (read, write):

            async with ClientSession(read, write) as session:

                await session.initialize()

                print("\nMCP connection established!")

                mcp_result = await session.list_tools()

                print(f"\nDiscovered {len(mcp_result.tools)} MCP tools:")

                for tool in mcp_result.tools:
                    print(f"  - {tool.name}")

                ollama_tools = convert_mcp_tools(mcp_result.tools)

                print("\nTools converted for Ollama.")

                await chat_loop(
                    session,
                    ollama_tools,
                    mcp_result.tools
                )

    except FileNotFoundError:
        print(
            "\nError: SigProfiler MCP Server executable was not found. "
            "Please check that the Server package is installed correctly."
        )

    except Exception as e:
        print("\nClient error:")
        traceback.print_exception(type(e), e, e.__traceback__)

        # Exception groups (e.g. from anyio TaskGroups) carry .exceptions.
        # Checked by attribute because BaseExceptionGroup is Python 3.11+
        # and the images run Python 3.10.
        sub_exceptions = getattr(e, "exceptions", None)
        if sub_exceptions:
            print("\nDetailed sub-exceptions:")
            for sub_exception in sub_exceptions:
                traceback.print_exception(
                    type(sub_exception),
                    sub_exception,
                    sub_exception.__traceback__
                )


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("\nSigMCP Client stopped.")
