"""Stand-in for the Azure CLI that keeps one app's access rules in a file.

The deploy script under test calls it through a bash ``az`` function. Every
call is appended to $CALL_LOG; the app state lives in $FAKE_AZ_STATE as
``{"apimSubnet", "httpsOnly", "defaults": {...}, "rules": {...}}``.
"""

import json
import os
import sys

RULE_KEYS = {
    "main": "ipSecurityRestrictions",
    "scm": "scmIpSecurityRestrictions",
}
DEFAULT_KEYS = {
    "main": "ipSecurityRestrictionsDefaultAction",
    "scm": "scmIpSecurityRestrictionsDefaultAction",
}
SYNTHETIC_PRIORITY = 2147483647


def _option(args: list[str], name: str) -> str | None:
    return args[args.index(name) + 1] if name in args else None


def _site(args: list[str]) -> str:
    return "scm" if _option(args, "--scm-site") == "true" else "main"


def _config(state: dict) -> dict:
    """Render `az functionapp config show` the way App Service does."""
    config = {
        "scmIpSecurityRestrictionsUseMain": state["useMain"],
        "minTlsVersion": "1.2",
        "scmMinTlsVersion": "1.2",
        "ftpsState": "Disabled",
    }
    for site, key in RULE_KEYS.items():
        rules = list(state["rules"][site])
        action = state["defaults"][site]
        denies = action == "Deny" or (not action and bool(rules))
        rules.append(
            {
                "name": "Deny all" if denies else "Allow all",
                "action": "Deny" if denies else "Allow",
                "ipAddress": "Any",
                "priority": SYNTHETIC_PRIORITY,
            }
        )
        config[key] = rules
        config[DEFAULT_KEYS[site]] = action
    return config


def main(args: list[str]) -> int:
    sys.stdout.reconfigure(newline="\n")
    path = os.environ["FAKE_AZ_STATE"]
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    if args == ["__rules__"]:
        print(
            " ".join(
                f"{site}:{rule['name']}"
                for site, rules in state["rules"].items()
                for rule in rules
            )
        )
        return 0
    with open(os.environ["CALL_LOG"], "a", encoding="utf-8") as log:
        log.write(" ".join(args) + "\n")

    command = " ".join(arg for arg in args[:4] if not arg.startswith("-"))
    if command.startswith("apim show"):
        print(state["apimSubnet"])
    elif command.startswith("functionapp config show"):
        print(json.dumps(_config(state)))
    elif command.startswith("functionapp show"):
        print(json.dumps({"properties": {"httpsOnly": state["httpsOnly"]}}))
    elif command == "functionapp config access-restriction add":
        rule = {
            "name": _option(args, "--rule-name"),
            "action": _option(args, "--action"),
            "priority": int(_option(args, "--priority")),
        }
        if "--subnet" in args:
            rule["vnetSubnetResourceId"] = _option(args, "--subnet")
        if "--ip-address" in args:
            rule["ipAddress"] = _option(args, "--ip-address")
        state["rules"][_site(args)].append(rule)
    elif command == "functionapp config access-restriction remove":
        site, name = _site(args), _option(args, "--rule-name")
        kept = [rule for rule in state["rules"][site] if rule["name"] != name]
        if len(kept) == len(state["rules"][site]):
            print(f"No rule named {name} on the {site} site", file=sys.stderr)
            return 1
        state["rules"][site] = kept
    elif command == "functionapp config access-restriction set":
        if "--default-action" in args:
            state["defaults"]["main"] = _option(args, "--default-action")
        if "--scm-default-action" in args:
            state["defaults"]["scm"] = _option(args, "--scm-default-action")
        flag = "--use-same-restrictions-for-scm-site"
        if flag in args:
            state["useMain"] = _option(args, flag) == "true"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
