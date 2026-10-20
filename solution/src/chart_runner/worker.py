"""One chart job, in a fresh process started by runner.py with an empty environment.

Reads {"code", "data"} as JSON on stdin, runs the code with `data` and `plt` in scope, and writes
{"title", "caption"} to result.json in the job directory. The runner reads chart.png itself.
"""

import json
import sys


def main() -> None:
    job = json.load(sys.stdin)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scope = {"data": job["data"], "plt": plt}
    exec(job["code"], scope)  # noqa: S102 - this process is the sandbox: no network, no secrets, read-only image
    result = {"title": plt.gca().get_title(), "caption": str(scope.get("caption", ""))}
    with open("result.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle)


if __name__ == "__main__":
    main()
