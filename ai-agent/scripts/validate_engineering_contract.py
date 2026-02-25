#!/usr/bin/env python3
"""Validate cross-repo engineering contract for ai-agent/infra/docs."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path


CONTRACT_PATH = Path("ai-agent/contracts/engineering_contract.json")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RuntimeError(f"Required file is missing: {path}") from None


def _load_contract(root: Path) -> dict:
    path = root / CONTRACT_PATH
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise RuntimeError(f"Contract file is missing: {path}") from None
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in contract file {path}: {exc}") from exc


def _extract_secret_names(infra_program: Path) -> list[str]:
    """Extract SECRET_NAMES from infra/__main__.py using AST."""
    tree = ast.parse(_read_text(infra_program), filename=str(infra_program))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SECRET_NAMES":
                    if not isinstance(node.value, ast.List):
                        raise RuntimeError(
                            "SECRET_NAMES must be a list literal in infra/__main__.py"
                        )
                    names: list[str] = []
                    for item in node.value.elts:
                        if not isinstance(item, ast.Constant) or not isinstance(
                            item.value, str
                        ):
                            raise RuntimeError(
                                "SECRET_NAMES must contain only string literals"
                            )
                        names.append(item.value)
                    return names
    raise RuntimeError("Could not find SECRET_NAMES in infra/__main__.py")


def _check_contains(
    text: str, phrases: list[str], label: str, errors: list[str]
) -> None:
    for phrase in phrases:
        if phrase not in text:
            errors.append(f"{label} is missing required phrase: {phrase!r}")


def _check_not_contains(
    text: str, phrases: list[str], label: str, errors: list[str]
) -> None:
    for phrase in phrases:
        if phrase in text:
            errors.append(f"{label} contains forbidden phrase: {phrase!r}")


def validate(root: Path) -> list[str]:
    contract = _load_contract(root)
    errors: list[str] = []

    files = contract["files"]
    deployment = contract["deployment"]
    docs = contract["docs"]
    workflow_commands = contract["workflow_commands"]

    readme_path = root / files["ai_agent_readme"]
    deploy_doc_path = root / files["deployment_doc"]
    infra_program_path = root / files["infra_program"]
    deploy_workflow_path = root / files["deploy_workflow"]
    infra_preview_workflow_path = root / files["infra_preview_workflow"]
    contract_workflow_path = root / files["contract_workflow"]

    readme_text = _read_text(readme_path)
    deploy_doc_text = _read_text(deploy_doc_path)
    deploy_workflow_text = _read_text(deploy_workflow_path)
    infra_preview_workflow_text = _read_text(infra_preview_workflow_path)
    contract_workflow_text = _read_text(contract_workflow_path)

    _check_contains(
        readme_text,
        docs["readme_required_phrases"],
        str(readme_path),
        errors,
    )
    _check_not_contains(
        readme_text,
        docs["readme_forbidden_phrases"],
        str(readme_path),
        errors,
    )
    _check_contains(
        deploy_doc_text,
        docs["deployment_required_phrases"],
        str(deploy_doc_path),
        errors,
    )

    actual_secret_names = sorted(_extract_secret_names(infra_program_path))
    expected_secret_names = sorted(deployment["required_secret_names"])
    if actual_secret_names != expected_secret_names:
        errors.append(
            "infra secret contract mismatch: "
            f"expected {expected_secret_names}, got {actual_secret_names}"
        )

    for path in deployment["health_paths"]:
        if path not in deploy_doc_text:
            errors.append(
                f"{deploy_doc_path} must document deployment health path {path!r}"
            )
        if path not in deploy_workflow_text:
            errors.append(
                f"{deploy_workflow_path} must check deployment health path {path!r}"
            )

    required_platform = deployment["platform"]
    if required_platform == "compute_engine":
        _check_contains(
            readme_text,
            ["Compute Engine"],
            str(readme_path),
            errors,
        )

    if workflow_commands["deploy_workflow"] not in deploy_workflow_text:
        errors.append(
            f"{deploy_workflow_path} must run validator command "
            f"{workflow_commands['deploy_workflow']!r}"
        )
    if workflow_commands["infra_preview_workflow"] not in infra_preview_workflow_text:
        errors.append(
            f"{infra_preview_workflow_path} must run validator command "
            f"{workflow_commands['infra_preview_workflow']!r}"
        )
    if workflow_commands["contract_workflow"] not in contract_workflow_text:
        errors.append(
            f"{contract_workflow_path} must run validator command "
            f"{workflow_commands['contract_workflow']!r}"
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate engineering contract for ai-agent/infra/docs"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root directory. Defaults to auto-detected root.",
    )
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    else:
        root = Path(__file__).resolve().parents[2]

    errors = validate(root)
    if errors:
        print("Engineering contract validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Engineering contract validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
