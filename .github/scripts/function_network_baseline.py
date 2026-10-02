"""Evaluate a function app's inbound access rules for the deploy scripts.

Commands that inspect rules read ``az functionapp config show`` JSON on
stdin; ``verify`` reads ``{"config": <config show>, "site": <functionapp
show>}`` instead.

  has-subnet-rule --subnet ID  exit 0 when the main site allows subnet ID
  deny-sites                   print each site (main, scm) that denies by
                               default
  rules --prefix PREFIX        print "<site><TAB><name>" for matching rules
  verify --subnet ID           print every baseline violation, exit 1 if any
  public-ipv4 ADDRESS          exit 0 when ADDRESS is a global IPv4 address
"""

import argparse
import ipaddress
import json
import sys
from collections.abc import Iterator
from typing import Any

RULES = {"main": "ipSecurityRestrictions", "scm": "scmIpSecurityRestrictions"}
DEFAULT_ACTIONS = {
    "main": "ipSecurityRestrictionsDefaultAction",
    "scm": "scmIpSecurityRestrictionsDefaultAction",
}
# App Service lists its default action as a synthetic last rule.
SYNTHETIC_PRIORITY = 2147483647
MIN_TLS = (1, 2)


def _normalize(resource_id: Any) -> str:
    return str(resource_id or "").strip().rstrip("/").lower()


def _rules(config: dict[str, Any], site: str) -> list[dict[str, Any]]:
    return list(config.get(RULES[site]) or [])


def _allow_rules(
    config: dict[str, Any], site: str
) -> Iterator[dict[str, Any]]:
    return (
        rule for rule in _rules(config, site) if rule.get("action") == "Allow"
    )


def _allows_subnet(rule: dict[str, Any], subnet_id: str) -> bool:
    expected = _normalize(subnet_id)
    return _normalize(rule.get("vnetSubnetResourceId")) == expected


def has_subnet_rule(config: dict[str, Any], subnet_id: str) -> bool:
    return any(
        _allows_subnet(rule, subnet_id)
        for rule in _allow_rules(config, "main")
    )


def _denies_by_default(config: dict[str, Any], site: str) -> bool:
    """Whether a site refuses traffic that no rule allows.

    Without an explicit default action, App Service denies by default as soon
    as a site has any rule of its own, and allows everything otherwise.
    """
    action = config.get(DEFAULT_ACTIONS[site])
    if action:
        return action == "Deny"
    return any(
        rule.get("priority") != SYNTHETIC_PRIORITY
        for rule in _rules(config, site)
    )


def deny_sites(config: dict[str, Any]) -> list[str]:
    return [site for site in RULES if _denies_by_default(config, site)]


def named_rules(config: dict[str, Any], prefix: str) -> list[tuple[str, str]]:
    return [
        (site, str(rule["name"]))
        for site in RULES
        for rule in _rules(config, site)
        if str(rule.get("name") or "").startswith(prefix)
    ]


def _https_only(site: dict[str, Any]) -> Any:
    # Flex Consumption apps come back in the raw ARM shape; others are flat.
    properties = site.get("properties") or {}
    return properties.get("httpsOnly", site.get("httpsOnly"))


def _tls_at_least_12(version: Any) -> bool:
    try:
        parts = tuple(int(part) for part in str(version).split("."))
    except ValueError:
        return False
    return parts >= MIN_TLS


def violations(
    config: dict[str, Any], site: dict[str, Any], subnet_id: str
) -> list[str]:
    problems = [
        f"the {name} site does not deny traffic by default"
        for name in RULES
        if not _denies_by_default(config, name)
    ]
    if config.get("scmIpSecurityRestrictionsUseMain") is not False:
        problems.append("the scm site inherits the main-site rules")
    if not has_subnet_rule(config, subnet_id):
        problems.append("the main site does not allow the APIM subnet")
    for name in RULES:
        for rule in _allow_rules(config, name):
            if name == "main" and _allows_subnet(rule, subnet_id):
                continue
            problems.append(
                f"unexpected allow rule {rule.get('name')!r} on the {name} site"
            )
    if _https_only(site) is not True:
        problems.append("HTTPS-only is not enabled")
    for key in ("minTlsVersion", "scmMinTlsVersion"):
        if not _tls_at_least_12(config.get(key)):
            problems.append(f"{key} is below 1.2")
    if config.get("ftpsState") != "Disabled":
        problems.append("FTP/FTPS publishing is not disabled")
    return problems


def is_public_ipv4(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return parsed.version == 4 and parsed.is_global


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(newline="\n")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("has-subnet-rule").add_argument(
        "--subnet", required=True
    )
    commands.add_parser("deny-sites")
    commands.add_parser("rules").add_argument("--prefix", required=True)
    commands.add_parser("verify").add_argument("--subnet", required=True)
    commands.add_parser("public-ipv4").add_argument("address")
    args = parser.parse_args(argv)

    if args.command == "public-ipv4":
        return 0 if is_public_ipv4(args.address) else 1

    document = json.load(sys.stdin)
    if args.command == "has-subnet-rule":
        return 0 if has_subnet_rule(document, args.subnet) else 1
    if args.command == "deny-sites":
        print("\n".join(deny_sites(document)))
        return 0
    if args.command == "rules":
        for site, name in named_rules(document, args.prefix):
            print(f"{site}\t{name}")
        return 0
    problems = violations(document["config"], document["site"], args.subnet)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
