
# **SigProfiler MCP Server**

The SigProfiler MCP Server is a Model Context Protocol (MCP) server that implements the protocol to expose the core SigProfiler suite (SigProfilerMatrixGenerator, SigProfilerAssignment, SigProfilerExtractor, and SigProfilerPlotting) as executable tools for LLM clients.


[SigProfilerMatrixGenerator](https://github.com/SigProfilerSuite/SigProfilerMatrixGenerator).

[SigProfilerAssignment](https://github.com/SigProfilerSuite/SigProfilerAssignment)

[SigProfilerPlotting](https://github.com/SigProfilerSuite/SigProfilerPlotting)

[SigProfilerExtractor](https://github.com/SigProfilerSuite/SigProfilerExtractor)



## **Prerequisites**

*  **Docker** install, [download and install Docker](https://docs.docker.com/get-started/get-docker/) if you do not have it.

    Verify installation 
    ```bash
    docker --version
    ```

## **Setup**

1. find the AI application config that supports MCP.




2. add the MCP **Server config**

    *   **(CPU version)**:
        ```json
        {
          "mcpServers": {
            "sigprofilermcp": {
              "command": "docker",
              "args": [
                "run", "-i", "--rm",
                "xinxinxia/sigprofiler-mcp-server:cpu"
              ]
            }
          }
        }
        ```

    *   **(GPU version)**:
        ```json
        {
          "mcpServers": {
            "sigprofilermcp": {
              "command": "docker",
              "args": [
                "run", "-i", "--rm",
                "xinxinxia/sigprofiler-mcp-server:gpu"
              ]
            }
          }
        }
        ```

