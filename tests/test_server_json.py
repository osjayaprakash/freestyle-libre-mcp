"""server.json must agree with the package it describes, or the MCP Registry rejects it."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = json.loads((ROOT / "server.json").read_text())
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def _package(registry_type: str) -> dict:
    return next(p for p in SERVER["packages"] if p["registryType"] == registry_type)


def test_versions_match_pyproject():
    version = PROJECT["version"]
    assert SERVER["version"] == version
    assert _package("pypi")["version"] == version
    assert _package("oci")["identifier"].endswith(f":{version}")


def test_pypi_identifier_is_the_project_name():
    assert _package("pypi")["identifier"] == PROJECT["name"]


def test_readme_carries_mcp_name():
    readme = (ROOT / "README.md").read_text()
    assert f"<!-- mcp-name: {SERVER['name']} -->" in readme


def test_dockerfile_carries_server_name_label():
    dockerfile = (ROOT / "Dockerfile").read_text()
    label = re.search(r'io\.modelcontextprotocol\.server\.name="([^"]+)"', dockerfile)
    assert label and label.group(1) == SERVER["name"]


def test_env_vars_match_between_packages():
    assert _package("pypi")["environmentVariables"] == _package("oci")["environmentVariables"]
