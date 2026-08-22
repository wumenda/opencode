import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def resolve_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        matches = _ENV_VAR_PATTERN.findall(value)
        if not matches:
            return value
        result = value
        for env_var in matches:
            env_value = os.getenv(env_var, "")
            result = result.replace(f"${{{env_var}}}", env_value)
        return result
    elif isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_env_vars(item) for item in value]
    return value


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_file(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return {}

    return resolve_env_vars(data)


_WORKFLOW_SUBDIRS = ["four_new", "granular", "multi_turn"]


def _find_workflow_file(workflows_dir: Path, workflow_name: str) -> Optional[Path]:
    root_path = workflows_dir / f"{workflow_name}.yaml"
    if root_path.exists():
        return root_path

    for subdir in _WORKFLOW_SUBDIRS:
        subdir_path = workflows_dir / subdir / f"{workflow_name}.yaml"
        if subdir_path.exists():
            return subdir_path

    return None


def load_yaml_config(
    config_dir: Optional[Path] = None,
    workflow_name: Optional[str] = None,
) -> dict[str, Any]:
    if config_dir is None:
        config_dir = Path.cwd() / "config"

    config_dir = Path(config_dir)
    if not config_dir.exists():
        raise FileNotFoundError(f"Config directory not found: {config_dir}")

    defaults_file = os.getenv("CONFIG_DEFAULTS_FILE", "defaults.yaml")
    experts_file = os.getenv("CONFIG_EXPERTS_FILE", "experts.yaml")
    providers_file = os.getenv("CONFIG_PROVIDERS_FILE", "providers.yaml")

    defaults_path = (
        Path(defaults_file) if Path(defaults_file).is_absolute() else config_dir / defaults_file
    )
    experts_path = (
        Path(experts_file) if Path(experts_file).is_absolute() else config_dir / experts_file
    )
    providers_path = (
        Path(providers_file) if Path(providers_file).is_absolute() else config_dir / providers_file
    )

    defaults_data = load_yaml_file(defaults_path)
    experts_data = load_yaml_file(experts_path)
    providers_data = load_yaml_file(providers_path)

    merged = deep_merge(defaults_data, {"experts": experts_data})
    merged = deep_merge(merged, {"providers": providers_data})

    if workflow_name:
        workflow_file = _find_workflow_file(config_dir / "workflows", workflow_name)
        workflow_data = load_yaml_file(workflow_file) if workflow_file else {}
        if workflow_data:
            merged = _apply_workflow_overrides(merged, workflow_data, config_dir)

    return merged


def _apply_workflow_overrides(
    base_config: dict[str, Any],
    workflow_config: dict[str, Any],
    config_dir: Optional[Path] = None,
) -> dict[str, Any]:
    result = base_config.copy()

    if "extends" in workflow_config:
        parent_name = workflow_config["extends"]
        workflows_dir = config_dir / "workflows" if config_dir else Path("config") / "workflows"
        parent_file = _find_workflow_file(workflows_dir, parent_name)
        if parent_file and parent_file.exists():
            parent_data = load_yaml_file(parent_file)
            if parent_data:
                result = _apply_workflow_overrides(result, parent_data, config_dir)

    if "features" in workflow_config:
        base_features = result.get("features", {})
        result["features"] = deep_merge(base_features, workflow_config["features"])

    if "workflow_params" in workflow_config:
        base_params = result.get("workflow_params", {})
        result["workflow_params"] = deep_merge(base_params, workflow_config["workflow_params"])

    if "experts" in workflow_config:
        base_experts = result.get("experts", {})
        workflow_experts = workflow_config["experts"]

        resolved_experts = []
        for expert_entry in workflow_experts:
            expert_type = expert_entry["type"]
            base_expert_config = base_experts.get(expert_type, {})

            overrides = {k: v for k, v in expert_entry.items() if k != "type"}

            if overrides:
                merged_expert = deep_merge(base_expert_config, overrides)
            else:
                merged_expert = base_expert_config.copy()

            merged_expert["type"] = expert_type
            resolved_experts.append(merged_expert)

        result["workflow_experts"] = resolved_experts

    return result
