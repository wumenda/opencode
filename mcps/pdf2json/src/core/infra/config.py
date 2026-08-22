import logging
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from dotenv import load_dotenv

from src.core.infra.yaml_config import load_yaml_config
from src.core.infra.settings_llm import LLMSettings, ReasoningEffort, ThinkingType
from src.core.infra.settings_validation import ValidationSettings
from src.core.infra.settings_cache import CacheSettings
from src.core.infra.settings_image import ImageSettings, DEFAULT_EXPERT_IMAGE_SIZES
from src.core.infra.settings_multipage import MultipageSettings

DEFAULT_PROVIDERS_FILE = "providers.json"


def load_project_env(env_file: Optional[Path] = None) -> None:
    """Explicitly load the project .env file so env vars are available
    regardless of the current working directory.

    If ``env_file`` is provided and exists, it is loaded directly.
    Otherwise the ``.env`` file in the project root (three levels above
    ``src/``) is loaded.  ``override=True`` is used so that values in the
    .env file take precedence over any pre-existing environment variables.
    """
    if env_file is not None:
        target = Path(env_file)
        if target.exists():
            load_dotenv(target, override=True)
        return

    project_root = Path(__file__).resolve().parent.parent.parent.parent
    target = project_root / ".env"
    if target.exists():
        load_dotenv(target, override=True)
    else:
        # Fallback to python-dotenv default behaviour (search cwd and parents).
        load_dotenv(override=True)


load_project_env()

_ENV_DEFAULT_MODEL = os.getenv("LLM_MODEL", "Doubao-Seed-2.0-pro")
_ENV_DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
_ENV_DEFAULT_API_KEY = os.getenv("LLM_API_KEY", "")


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=False)

    name: str
    key: str = ""
    base_url: str
    api_key: str = Field(repr=False)
    api_type: str = "openai"

    @classmethod
    def from_dict(cls, data: dict[str, str], key: str = "") -> "ProviderConfig":
        return cls(
            name=data.get("name", "Unknown"),
            key=key or data.get("name", "Unknown"),
            base_url=data.get("base_url", ""),
            api_key=data.get("api_key", ""),
            api_type=data.get("api_type", "openai"),
        )


class ExpertConfig(BaseModel):
    model_config = ConfigDict(frozen=False)

    provider: str
    model: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    seed: Optional[int] = None
    response_format: Optional[dict[str, str]] = None
    timeout: int = 600
    image_size: Optional[int] = None
    prompt_version: str = "v1"
    reasoning_effort: ReasoningEffort = ReasoningEffort.NONE
    thinking_type: ThinkingType = ThinkingType.AUTO
    stream: bool = False
    enable_image_annotation: bool = True
    enable_preprocessing: bool = True
    inject_image_size: Optional[bool] = None
    enable_prefix_caching: Optional[bool] = None


class Settings(BaseModel):
    model_config = ConfigDict(frozen=False)

    api_key: str = Field(repr=False, default=_ENV_DEFAULT_API_KEY)
    base_url: str = _ENV_DEFAULT_BASE_URL
    model: str = _ENV_DEFAULT_MODEL

    max_tokens: int = 16092
    max_retries: int = 3
    max_image_size: int = 4096
    max_image_pixels: int = 36_000_000
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    seed: Optional[int] = None
    response_format: Optional[dict[str, str]] = None
    timeout: int = 600
    connect_timeout: int = 60

    reasoning_effort: ReasoningEffort = ReasoningEffort.NONE
    thinking_type: ThinkingType = ThinkingType.AUTO
    stream: bool = False
    save_thinking: bool = False
    thinking_output_dir: Path = Field(default_factory=lambda: Path.cwd() / "thinking_output")

    expert_image_sizes: dict[str, int] = Field(
        default_factory=lambda: DEFAULT_EXPERT_IMAGE_SIZES.copy()
    )

    base_dir: Path = Field(default_factory=lambda: Path.cwd())
    data_dir: Path = Field(default_factory=lambda: Path.cwd() / "data")
    output_dir: Path = Field(default_factory=lambda: Path.cwd() / "output")
    output_images_dir: Path = Field(default_factory=lambda: Path.cwd() / "output_images")

    log_level: str = "INFO"
    log_file: Optional[Path] = None

    enable_junction_detector: bool = True
    enable_consistency_checker: bool = True
    inject_image_size: bool = True

    enable_rule_validator: bool = True
    enable_evidence_analyzer: bool = False
    enable_targeted_critic: bool = False
    enable_output_gate: bool = True

    reliability_gate_enabled: bool = True
    reliability_threshold: float = 60.0
    reliability_weights_structure: float = 0.40
    reliability_weights_connectivity: float = 0.30
    reliability_weights_semantic: float = 0.20
    reliability_weights_sufficiency: float = 0.10

    ocr_equipment_proximity_threshold: float = 0.12
    ocr_cross_drawing_search_radius: float = 0.18
    ocr_cross_drawing_bbox_expansion: float = 0.04
    ocr_boundary_proximity_threshold: float = 0.15

    keep_temp_files: bool = False
    check_port_constraints: bool = True

    enable_prefix_caching: bool = True

    providers: dict[str, ProviderConfig] = Field(default_factory=dict, repr=False)
    default_provider: str = "siliconflow"
    expert_configs: dict[str, ExpertConfig] = Field(default_factory=dict)

    workflow_experts: list[dict[str, Any]] = Field(default_factory=list)
    workflow_params: dict[str, Any] = Field(default_factory=dict)
    workflow_name: Optional[str] = None
    config_dir: Optional[Path] = None

    base_workflow: str = "direct_parallel_topology_split_boundary"
    multi_page_dpi: int = 300
    multi_page_accept_threshold: float = 0.85
    multi_page_review_threshold: float = 0.6

    # 并行控制
    parallel_node_extraction_workers: int = 2  # 设备+边界节点提取并行数（1=串行）
    parallel_multi_page_workers: int = 1  # 多页 PDF 提取并行数（1=串行）

    def model_post_init(self, __context: object) -> None:
        if not self.api_key and not self.providers:
            raise ValueError(
                "LLM_API_KEY not found. Set it via environment variable, .env file, or providers.json"
            )

        for dir_path in [self.data_dir, self.output_dir, self.output_images_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        if self.save_thinking:
            self.thinking_output_dir.mkdir(parents=True, exist_ok=True)

    def get_expert_image_size(self, expert_type: str) -> int:
        if expert_type in self.expert_configs:
            expert_conf = self.expert_configs[expert_type]
            if expert_conf.image_size is not None:
                return expert_conf.image_size
        return self.expert_image_sizes.get(expert_type, self.max_image_size)

    def get_expert_prompt_version(self, expert_type: str) -> str:
        if expert_type in self.expert_configs:
            return self.expert_configs[expert_type].prompt_version
        return "v1"

    def get_expert_inject_image_size(self, expert_type: str) -> bool:
        if expert_type in self.expert_configs:
            expert_inject = self.expert_configs[expert_type].inject_image_size
            if expert_inject is not None:
                return expert_inject
        return self.inject_image_size

    def get_expert_enable_prefix_caching(self, expert_type: str) -> bool:
        if expert_type in self.expert_configs:
            expert_val = self.expert_configs[expert_type].enable_prefix_caching
            if expert_val is not None:
                return expert_val
        return self.enable_prefix_caching

    def get_provider_config(self, provider_name: str) -> Optional[ProviderConfig]:
        return self.providers.get(provider_name)

    def get_expert_config(self, expert_type: str) -> ExpertConfig:
        if expert_type in self.expert_configs:
            return self.expert_configs[expert_type]

        return ExpertConfig(
            provider=self.default_provider,
            model=self.model,
            temperature=self.temperature,
            top_p=self.top_p,
            seed=self.seed,
            response_format=self.response_format,
            timeout=self.timeout,
        )

    def get_expert_provider_config(self, expert_type: str) -> tuple[ProviderConfig, ExpertConfig]:
        expert_config = self.get_expert_config(expert_type)
        provider_config = self.get_provider_config(expert_config.provider)

        if not provider_config:
            raise ValueError(
                f"Provider '{expert_config.provider}' not found in providers configuration. "
                f"Available providers: {list(self.providers.keys())}"
            )

        return provider_config, expert_config

    @property
    def llm(self) -> LLMSettings:
        return LLMSettings(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            max_tokens=self.max_tokens,
            max_retries=self.max_retries,
            temperature=self.temperature,
            top_p=self.top_p,
            seed=self.seed,
            response_format=self.response_format,
            timeout=self.timeout,
            connect_timeout=self.connect_timeout,
            reasoning_effort=self.reasoning_effort,
            thinking_type=self.thinking_type,
            stream=self.stream,
            save_thinking=self.save_thinking,
        )

    @property
    def validation(self) -> ValidationSettings:
        return ValidationSettings(
            enable_rule_validator=self.enable_rule_validator,
            enable_evidence_analyzer=self.enable_evidence_analyzer,
            enable_targeted_critic=self.enable_targeted_critic,
            enable_output_gate=self.enable_output_gate,
            enable_junction_detector=self.enable_junction_detector,
            enable_consistency_checker=self.enable_consistency_checker,
            inject_image_size=self.inject_image_size,
            check_port_constraints=self.check_port_constraints,
            reliability_gate_enabled=self.reliability_gate_enabled,
            reliability_threshold=self.reliability_threshold,
            reliability_weights_structure=self.reliability_weights_structure,
            reliability_weights_connectivity=self.reliability_weights_connectivity,
            reliability_weights_semantic=self.reliability_weights_semantic,
            reliability_weights_sufficiency=self.reliability_weights_sufficiency,
        )

    @property
    def cache(self) -> CacheSettings:
        return CacheSettings(
            enable_prefix_caching=self.enable_prefix_caching,
        )

    @property
    def image(self) -> ImageSettings:
        return ImageSettings(
            max_image_size=self.max_image_size,
            max_image_pixels=self.max_image_pixels,
            expert_image_sizes=self.expert_image_sizes,
            keep_temp_files=self.keep_temp_files,
        )

    @property
    def multipage(self) -> MultipageSettings:
        return MultipageSettings(
            multi_page_dpi=self.multi_page_dpi,
            multi_page_accept_threshold=self.multi_page_accept_threshold,
            multi_page_review_threshold=self.multi_page_review_threshold,
        )

    @classmethod
    def from_yaml(
        cls,
        config_dir: Optional[Path] = None,
        workflow_name: Optional[str] = None,
        env_file: Optional[Path] = None,
    ) -> "Settings":
        load_project_env(env_file)

        env_default_model = os.getenv("LLM_MODEL", "Doubao-Seed-2.0-pro")

        if config_dir is None:
            config_dir = Path.cwd() / "config"

        config = load_yaml_config(config_dir, workflow_name)

        providers_data = config.get("providers", {})
        default_provider = providers_data.get("default", "siliconflow")
        providers_raw = providers_data.get("providers", {})

        providers = {}
        for provider_name, provider_info in providers_raw.items():
            if isinstance(provider_info, dict) and "base_url" in provider_info:
                providers[provider_name] = ProviderConfig.from_dict(
                    provider_info, key=provider_name
                )

        default_api_key = ""
        default_base_url = ""
        if default_provider in providers:
            default_api_key = providers[default_provider].api_key
            default_base_url = providers[default_provider].base_url

        if not default_api_key:
            raise ValueError(
                "API key not found. Please set the corresponding environment variable "
                f"(e.g., {default_provider.upper()}_API_KEY) or check config/providers.yaml"
            )

        defaults_data = config.get("defaults", config)
        llm_defaults = defaults_data.get("llm", {})
        default_stream = llm_defaults.get("stream", False)

        default_expert_timeout = llm_defaults.get("timeout", 600)

        experts_data = config.get("experts", {})
        expert_image_sizes = DEFAULT_EXPERT_IMAGE_SIZES.copy()

        expert_configs = Settings._build_expert_configs_from_raw(
            experts_data,
            default_provider,
            env_default_model,
            default_expert_timeout,
            default_stream,
        )

        for expert_type, expert_info in experts_data.items():
            if (
                isinstance(expert_info, dict)
                and expert_type in expert_image_sizes
                and expert_info.get("image_size")
            ):
                expert_image_sizes[expert_type] = expert_info["image_size"]

        features = defaults_data.get("features", {})
        ocr_matching = defaults_data.get("ocr_matching", {})
        logging_conf = defaults_data.get("logging", {})
        base_conf = defaults_data.get("base", {})
        multi_page_conf = defaults_data.get("multi_page", {})
        parallel_conf = defaults_data.get("parallel", {})

        workflow_experts = config.get("workflow_experts", [])
        workflow_params = config.get("workflow_params", {})

        if workflow_experts:
            for expert_entry in workflow_experts:
                expert_type = expert_entry.get("type", "")
                overrides = {k: v for k, v in expert_entry.items() if k != "type"}

                if expert_type in expert_configs:
                    base_dict = expert_configs[expert_type].model_dump()
                    base_dict.update(overrides)
                    expert_configs[expert_type] = ExpertConfig(**base_dict)
                else:
                    expert_configs[expert_type] = Settings._build_expert_config(
                        overrides,
                        default_provider,
                        env_default_model,
                        default_expert_timeout,
                        default_stream,
                    )

                if expert_type in expert_image_sizes:
                    img_size = expert_configs[expert_type].image_size
                    if img_size is not None:
                        expert_image_sizes[expert_type] = img_size

        return cls(
            api_key=default_api_key,
            base_url=default_base_url,
            model=expert_configs.get(
                default_provider, ExpertConfig(provider=default_provider, model=env_default_model)
            ).model,
            max_tokens=llm_defaults.get("max_tokens", 16092),
            max_retries=llm_defaults.get("max_retries", 3),
            max_image_size=llm_defaults.get("max_image_size", 4096),
            max_image_pixels=llm_defaults.get("max_image_pixels", 36_000_000),
            temperature=llm_defaults.get("temperature"),
            top_p=llm_defaults.get("top_p"),
            seed=llm_defaults.get("seed"),
            response_format=llm_defaults.get("response_format"),
            timeout=llm_defaults.get("timeout", 600),
            connect_timeout=llm_defaults.get("connect_timeout", 60),
            reasoning_effort=ReasoningEffort(features.get("reasoning_effort", "none")),
            thinking_type=ThinkingType(features.get("thinking_type", "auto")),
            stream=default_stream,
            save_thinking=features.get("save_thinking", False),
            thinking_output_dir=Path(
                features.get("thinking_output_dir", str(Path.cwd() / "thinking_output"))
            ),
            expert_image_sizes=expert_image_sizes,
            log_level=logging_conf.get("level", "INFO"),
            enable_junction_detector=features.get("enable_junction_detector", True),
            enable_consistency_checker=features.get("enable_consistency_checker", True),
            inject_image_size=features.get("inject_image_size", True),
            keep_temp_files=features.get("keep_temp_files", False),
            enable_prefix_caching=features.get("enable_prefix_caching", True),
            ocr_equipment_proximity_threshold=ocr_matching.get(
                "equipment_proximity_threshold", 0.12
            ),
            ocr_cross_drawing_search_radius=ocr_matching.get("cross_drawing_search_radius", 0.18),
            ocr_cross_drawing_bbox_expansion=ocr_matching.get("cross_drawing_bbox_expansion", 0.04),
            ocr_boundary_proximity_threshold=ocr_matching.get("boundary_proximity_threshold", 0.15),
            providers=providers,
            default_provider=default_provider,
            expert_configs=expert_configs,
            workflow_experts=workflow_experts,
            workflow_params=workflow_params,
            workflow_name=workflow_name,
            config_dir=config_dir,
            base_workflow=base_conf.get("workflow", "direct_parallel_topology_split_boundary"),
            multi_page_dpi=multi_page_conf.get("dpi", 300),
            multi_page_accept_threshold=multi_page_conf.get("accept_threshold", 0.85),
            multi_page_review_threshold=multi_page_conf.get("review_threshold", 0.6),
            parallel_node_extraction_workers=parallel_conf.get("node_extraction_workers", 2),
            parallel_multi_page_workers=parallel_conf.get("multi_page_workers", 1),
        )

    @classmethod
    def from_env(
        cls, env_file: Optional[Path] = None, providers_file: Optional[Path] = None
    ) -> "Settings":
        if env_file and env_file.exists():
            load_dotenv(env_file)
        else:
            load_dotenv()

        providers = cls._load_providers(providers_file)

        default_provider = os.getenv("LLM_PROVIDER", "siliconflow")

        default_api_key = ""
        default_base_url = ""

        if default_provider in providers:
            default_api_key = providers[default_provider].api_key
            default_base_url = providers[default_provider].base_url

        api_key = os.getenv("LLM_API_KEY", default_api_key)
        if not api_key:
            raise ValueError(
                "LLM_API_KEY not found in environment variables or providers.json. "
                "Please check your .env file or providers.json."
            )

        base_url = os.getenv("LLM_BASE_URL", default_base_url)
        model = os.getenv("LLM_MODEL", "Doubao-Seed-2.0-pro")

        default_max_size = int(os.getenv("LLM_MAX_IMAGE_SIZE", "4096"))
        expert_sizes = cls._parse_expert_image_sizes(os.getenv("EXPERT_IMAGE_SIZES"))
        for expert_type in expert_sizes:
            env_key = f"IMAGE_SIZE_{expert_type.upper()}"
            env_value = os.getenv(env_key)
            if env_value is not None:
                expert_sizes[expert_type] = int(env_value)

        default_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "16092"))
        default_timeout = int(os.getenv("LLM_TIMEOUT", "600"))
        default_stream = os.getenv("LLM_STREAM", "false").lower() == "true"
        default_temperature: Optional[float] = None
        env_temperature = os.getenv("LLM_TEMPERATURE")
        if env_temperature is not None:
            try:
                default_temperature = float(env_temperature)
            except ValueError:
                logging.getLogger(__name__).warning(
                    f"Invalid LLM_TEMPERATURE value: {env_temperature}"
                )

        default_top_p: Optional[float] = None
        env_top_p = os.getenv("LLM_TOP_P")
        if env_top_p is not None:
            try:
                default_top_p = float(env_top_p)
            except ValueError:
                logging.getLogger(__name__).warning(f"Invalid LLM_TOP_P value: {env_top_p}")

        default_seed: Optional[int] = None
        env_seed = os.getenv("LLM_SEED")
        if env_seed is not None:
            try:
                default_seed = int(env_seed)
            except ValueError:
                logging.getLogger(__name__).warning(f"Invalid LLM_SEED value: {env_seed}")

        default_response_format: Optional[dict[str, str]] = None
        env_response_format = os.getenv("LLM_RESPONSE_FORMAT")
        if env_response_format is not None:
            import json

            try:
                parsed = json.loads(env_response_format)
                if isinstance(parsed, dict):
                    default_response_format = parsed
            except (json.JSONDecodeError, ValueError):
                logging.getLogger(__name__).warning(
                    f"Invalid LLM_RESPONSE_FORMAT value: {env_response_format}"
                )

        expert_configs = cls._load_expert_configs(
            providers=providers,
            default_provider=default_provider,
            default_model=model,
            default_timeout=default_timeout,
            default_stream=default_stream,
            default_temperature=default_temperature,
            default_top_p=default_top_p,
            default_seed=default_seed,
            default_response_format=default_response_format,
        )

        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            max_tokens=default_max_tokens,
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
            max_image_size=default_max_size,
            max_image_pixels=int(os.getenv("LLM_MAX_IMAGE_PIXELS", "36000000")),
            temperature=default_temperature,
            top_p=default_top_p,
            seed=default_seed,
            response_format=default_response_format,
            timeout=default_timeout,
            connect_timeout=int(os.getenv("LLM_CONNECT_TIMEOUT", "60")),
            reasoning_effort=ReasoningEffort(os.getenv("REASONING_EFFORT", "none")),
            thinking_type=ThinkingType(os.getenv("THINKING_TYPE", "auto")),
            stream=default_stream,
            save_thinking=os.getenv("SAVE_THINKING", "false").lower() == "true",
            thinking_output_dir=Path(
                os.getenv("THINKING_OUTPUT_DIR", str(Path.cwd() / "thinking_output"))
            ),
            expert_image_sizes=expert_sizes,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            enable_junction_detector=os.getenv("ENABLE_JUNCTION_DETECTOR", "true").lower()
            == "true",
            enable_consistency_checker=os.getenv("ENABLE_CONSISTENCY_CHECKER", "true").lower()
            == "true",
            inject_image_size=os.getenv("INJECT_IMAGE_SIZE", "true").lower() == "true",
            keep_temp_files=os.getenv("KEEP_TEMP_FILES", "false").lower() == "true",
            enable_prefix_caching=os.getenv("ENABLE_PREFIX_CACHING", "true").lower() == "true",
            providers=providers,
            default_provider=default_provider,
            expert_configs=expert_configs,
            base_workflow=os.getenv("BASE_WORKFLOW", "direct_parallel_topology_split_boundary"),
            multi_page_dpi=int(os.getenv("MULTI_PAGE_DPI", "300")),
            multi_page_accept_threshold=float(os.getenv("MULTI_PAGE_ACCEPT_THRESHOLD", "0.85")),
            multi_page_review_threshold=float(os.getenv("MULTI_PAGE_REVIEW_THRESHOLD", "0.6")),
        )

    @staticmethod
    def _parse_expert_image_sizes(env_value: Optional[str]) -> dict[str, int]:
        import json

        if not env_value:
            return DEFAULT_EXPERT_IMAGE_SIZES.copy()

        result = DEFAULT_EXPERT_IMAGE_SIZES.copy()

        try:
            if env_value.strip().startswith("{"):
                parsed = json.loads(env_value)
                result.update({k: int(v) for k, v in parsed.items()})
            else:
                for pair in env_value.split(","):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        result[key.strip()] = int(value.strip())
        except (json.JSONDecodeError, ValueError) as e:
            logging.getLogger(__name__).warning(f"Failed to parse expert image sizes from env: {e}")

        return result

    @staticmethod
    def _build_expert_config(
        raw: dict[str, Any],
        default_provider: str,
        default_model: str,
        default_timeout: int = 600,
        default_stream: bool = False,
    ) -> ExpertConfig:
        return ExpertConfig(
            provider=raw.get("provider", default_provider),
            model=raw.get("model", default_model),
            temperature=raw.get("temperature"),
            top_p=raw.get("top_p"),
            seed=raw.get("seed"),
            response_format=raw.get("response_format"),
            timeout=raw.get("timeout", default_timeout),
            image_size=raw.get("image_size"),
            prompt_version=raw.get("prompt_version", "v1"),
            reasoning_effort=ReasoningEffort(raw.get("reasoning_effort", "none")),
            thinking_type=ThinkingType(raw.get("thinking_type", "auto")),
            stream=raw.get("stream", default_stream),
            enable_image_annotation=raw.get("enable_image_annotation", True),
            inject_image_size=raw.get("inject_image_size"),
            enable_prefix_caching=raw.get("enable_prefix_caching"),
        )

    @staticmethod
    def _build_expert_configs_from_raw(
        experts_data: dict[str, dict[str, Any]],
        default_provider: str,
        default_model: str,
        default_timeout: int = 600,
        default_stream: bool = False,
    ) -> dict[str, ExpertConfig]:
        expert_configs: dict[str, ExpertConfig] = {}
        for expert_type, expert_info in experts_data.items():
            if not isinstance(expert_info, dict):
                continue
            expert_configs[expert_type] = Settings._build_expert_config(
                expert_info, default_provider, default_model, default_timeout, default_stream
            )
        return expert_configs

    @staticmethod
    def _load_providers(providers_file: Optional[Path] = None) -> dict[str, ProviderConfig]:
        import json

        if providers_file is None:
            providers_file = Path.cwd() / DEFAULT_PROVIDERS_FILE

        if not providers_file.exists():
            return {}

        try:
            with open(providers_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            providers = {}
            for provider_name, provider_data in data.items():
                providers[provider_name] = ProviderConfig.from_dict(
                    provider_data, key=provider_name
                )

            return providers
        except (json.JSONDecodeError, KeyError) as e:
            logging.getLogger(__name__).warning(
                f"Failed to load providers from {providers_file}: {e}"
            )
            return {}

    @staticmethod
    def _load_expert_configs(
        providers: dict[str, ProviderConfig],
        default_provider: str,
        default_model: str,
        default_timeout: int,
        default_stream: bool,
        default_temperature: Optional[float] = None,
        default_top_p: Optional[float] = None,
        default_seed: Optional[int] = None,
        default_response_format: Optional[dict[str, str]] = None,
    ) -> dict[str, ExpertConfig]:
        import json
        import os

        expert_types = list(DEFAULT_EXPERT_IMAGE_SIZES.keys())
        experts_data: dict[str, dict[str, Any]] = {}

        for expert_type in expert_types:
            env_prefix = f"EXPERT_{expert_type.upper()}"

            raw: dict[str, Any] = {
                "provider": os.getenv(f"{env_prefix}_PROVIDER", default_provider),
                "model": os.getenv(f"{env_prefix}_MODEL", default_model),
                "timeout": int(os.getenv(f"{env_prefix}_TIMEOUT", str(default_timeout))),
                "stream": os.getenv(f"{env_prefix}_STREAM", str(default_stream)).lower() == "true",
                "prompt_version": os.getenv(f"PROMPT_VERSION_{expert_type.upper()}", "v1"),
                "reasoning_effort": os.getenv(f"{env_prefix}_REASONING_EFFORT", "none"),
            }

            temperature: Optional[float] = default_temperature
            env_temp = os.getenv(f"{env_prefix}_TEMPERATURE")
            if env_temp is not None:
                try:
                    temperature = float(env_temp)
                except ValueError:
                    pass
            raw["temperature"] = temperature

            top_p: Optional[float] = default_top_p
            env_top_p = os.getenv(f"{env_prefix}_TOP_P")
            if env_top_p is not None:
                try:
                    top_p = float(env_top_p)
                except ValueError:
                    pass
            raw["top_p"] = top_p

            seed: Optional[int] = default_seed
            env_seed = os.getenv(f"{env_prefix}_SEED")
            if env_seed is not None:
                try:
                    seed = int(env_seed)
                except ValueError:
                    pass
            raw["seed"] = seed

            response_format: Optional[dict[str, str]] = default_response_format
            env_rf = os.getenv(f"{env_prefix}_RESPONSE_FORMAT")
            if env_rf is not None:
                try:
                    parsed = json.loads(env_rf)
                    if isinstance(parsed, dict):
                        response_format = parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            raw["response_format"] = response_format

            experts_data[expert_type] = raw

        return Settings._build_expert_configs_from_raw(
            experts_data, default_provider, default_model, default_timeout, default_stream
        )
