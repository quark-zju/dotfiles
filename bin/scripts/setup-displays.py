#!/usr/bin/env python3
"""Configure Sway outputs based on the connected displays."""

import json
import subprocess


def swaymsg(command: str) -> None:
    subprocess.run(["swaymsg", command], check=True)


def main() -> None:
    result = subprocess.run(
        ["swaymsg", "-t", "get_outputs", "--raw"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    outputs = json.loads(result.stdout)
    names = {output["name"] for output in outputs}
    dp1 = next((output for output in outputs if output["name"] == "DP-1"), None)
    use_dp1_only = (
        "eDP-1" in names
        and dp1 is not None
        and any(
            mode["width"] >= 3840 and mode["height"] >= 2160
            for mode in dp1["modes"]
        )
    )

    if not use_dp1_only:
        swaymsg("output * enable")
        return

    swaymsg("output DP-1 enable")
    for name in sorted(names - {"DP-1"}):
        swaymsg(f"output {json.dumps(name)} disable")


if __name__ == "__main__":
    main()
