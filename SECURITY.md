# Security and operation boundary

RecursiveCal is local research software. Its `serve` command runs in the foreground and binds only to loopback. It has no actuator driver, cloud credentials, account system, telemetry, external callbacks, or remote command execution endpoint. Stop it with Ctrl+C.

The workbench rejects cross-origin browser requests, unrecognized Host headers, non-JSON calculation requests, duplicate JSON fields, and non-finite JSON values. Request size and simulation steps are bounded. Static serving is limited to packaged web assets. Uploaded CSVs are parsed in a temporary directory and never interpreted as code. The browser renders imported text as text.

These controls support local use. The Python HTTP server is not presented as a hardened Internet-facing service. Do not put it behind a public proxy as an authenticated multi-user service. See the [Python HTTP server documentation](https://docs.python.org/3/library/http.server.html).

For a security issue, use the repository's private vulnerability reporting feature if it is enabled. Otherwise contact the repository owner through an existing private channel. Do not publish secrets or exploit details in a public issue. The project does not currently promise a response-time service level.

