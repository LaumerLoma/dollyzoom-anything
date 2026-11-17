# Agent integration

Use the CLI as a synchronous subprocess. No MCP bridge, API key, or daemon is
required. Install it once with `uv tool install .`, explicitly run `dollyzoom setup`,
and check `dollyzoom doctor --json`. `dollyzoom schema` describes defaults, limits,
choices, and the versioned result envelope without loading the model.

1. Run `inspect PHOTO --json`; open `result.preview_path` with your image tool.
2. Visually locate the requested feature and normalize its coordinates using the
   displayed, oriented image. The CLI does not resolve natural-language labels.
3. Run `assess PHOTO --anchor X,Y --json`; read the reasons and cautions.
4. Run `run PHOTO --anchor X,Y --json`; review the MP4 and peak frame.

A rating is advisory. Use `--crop-mode anchor` for off-center points. Use a fresh
`--output` folder for every call and serialize jobs that share a data directory.
Choose new coordinates for every photo. Report limitations visible in the result.

```python
import json
import subprocess

completed = subprocess.run(
    ["dollyzoom", "run", "/absolute/photo.jpg", "--anchor", "0.5,0.4",
     "--anchor-label", "subject", "--output", "/absolute/new-result", "--json"],
    capture_output=True, text=True,  # set a timeout suitable for local inference
)
reply = json.loads(completed.stdout)
if completed.returncode != 0:
    raise RuntimeError(reply.get("error", reply.get("result")))
video = reply["result"]["artifacts"]["dolly_zoom.mp4"]
print(video)
```

Finite commands accept `--json` before or after the command. Stdout contains a
single object with `schema_version: 1`, `ok`, `command`, and `result` on success.
Failures contain `error.type` and `error.message`. `doctor` returns its diagnostic
`result` even when `ok` is false. Progress and subprocess logs use stderr.
`--help` and `--version` retain their normal text output.

| Exit | Meaning |
| --- | --- |
| `0` | Completed successfully |
| `1` | Doctor found missing runtime components |
| `2` | Invalid input, missing file/runtime, or execution failure |
| `130` | Interrupted with Ctrl-C |

JSON `run` and `assess` require an explicit anchor; `--no-open` alone still allows
a picker in text mode. `view` is an interactive server and rejects `--json`.
An unsuccessful process may leave diagnostics in its run folder. A render result
is ready only when the process succeeds and `job.json` has `status: complete`.

Treat filenames and JSON values as data: use an argument list, not shell string
interpolation. Inspect returns image preflight only; assess loads the reconstruction.
Setup downloads upstream dependencies and a research-licensed model; run it as an
explicit installation step, not as a side effect of a failed conversion.
