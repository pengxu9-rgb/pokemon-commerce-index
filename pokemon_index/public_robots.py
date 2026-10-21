"""Robots allow/disallow matching for the bounded public research transport.

Unlike urllib.robotparser, this recognizes publisher ``*`` and terminal ``$``
patterns and chooses the longest applicable rule (Allow wins equal lengths).
It does not turn a matching Allow into permission to use a publisher's data.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit


def _normalized(value):
    # RFC 9309 compares percent-encoded unreserved octets as their URI character;
    # reserved octets retain encoding and hexadecimal digits are case-insensitive.
    def octet(match):
        number = int(match[0][1:], 16)
        char = chr(number)
        return char if char.isascii() and (char.isalnum() or char in "-._~") else "%" + format(number, "02X")
    return re.sub(r"%[0-9A-Fa-f]{2}", octet, value)


def _matches(pattern, target):
    """Only '*' is a wildcard; terminal '$' anchors the whole path/query.

    This avoids compiling publisher-controlled patterns into a backtracking
    regular expression. Literal '?' and '[' remain ordinary URI characters.
    """
    anchored = pattern.endswith("$")
    pattern = pattern[:-1] if anchored else pattern
    at, cursor, star, retry = 0, 0, -1, 0
    while cursor < len(target):
        if at == len(pattern) and not anchored:
            return True
        if at < len(pattern) and pattern[at] == "*":
            star, retry = at, cursor
            at += 1
        elif at < len(pattern) and pattern[at] == target[cursor]:
            at += 1
            cursor += 1
        elif star >= 0:
            at = star + 1
            retry += 1
            cursor = retry
        else:
            return False
    return all(char == "*" for char in pattern[at:])


class RobotsPolicy:
    def __init__(self, body):
        self.groups = []
        agents, rules, pacing = [], [], False
        touched = False
        for raw in str(body).lstrip("\ufeff").splitlines():
            raw = raw.split("#", 1)[0].strip()
            if not raw or ":" not in raw:
                continue
            field, value = (part.strip() for part in raw.split(":", 1))
            field = field.casefold()
            if field == "user-agent":
                if touched:
                    self.groups.append((agents, rules, pacing))
                    agents, rules, pacing, touched = [], [], False, False
                if value:
                    agents.append(value.casefold())
            elif agents:
                if field in {"allow", "disallow"}:
                    touched = True
                    if value:
                        rules.append((field == "allow", _normalized(value)))
                elif field in {"crawl-delay", "request-rate"}:
                    touched = True
                    # On-demand requests cannot honor nonzero publisher pacing.
                    # Unknown/invalid pacing stays closed rather than ignored.
                    pacing = pacing or value not in {"", "0", "0.0"}
        if agents:
            self.groups.append((agents, rules, pacing))

    def _selected(self, user_agent):
        token = user_agent.casefold().split("/", 1)[0]
        scored = []
        for agents, rules, pacing in self.groups:
            scores = [0 if agent == "*" else len(agent) for agent in agents
                      if agent == "*" or agent in token]
            if scores:
                scored.append((max(scores), rules, pacing))
        if not scored:
            return []
        longest = max(row[0] for row in scored)
        return [(rules, pacing) for score, rules, pacing in scored if score == longest]

    def can_fetch(self, user_agent, url):
        parsed = urlsplit(url)
        target = _normalized((parsed.path or "/") + ("?" + parsed.query if parsed.query else ""))
        applicable = []
        for rules, _ in self._selected(user_agent):
            for allow, pattern in rules:
                end = pattern.endswith("$")
                literal = pattern[:-1] if end else pattern
                if _matches(pattern, target):
                    length = len(literal.replace("*", "").encode("utf-8"))
                    applicable.append((length, allow))
        return max(applicable, default=(0, True))[1]

    def requires_pacing(self, user_agent):
        return any(pacing for _, pacing in self._selected(user_agent))
