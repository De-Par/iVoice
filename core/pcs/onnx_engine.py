from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from time import perf_counter

from core.pcs.base import BasePCSEngine
from core.text_cleanup import clean_command_text
from schemas.command import PCSNormalizationResult
from schemas.runtime import ModelPreparationResult

logger = logging.getLogger(__name__)


class ONNXPCSEngine(BasePCSEngine):
    family_name = "punctuation"
    provider_name = "onnx"

    def __init__(
        self,
        model_name: str,
        *,
        model_path: Path | None = None,
        download_root: Path | None = None,
        local_files_only: bool = True,
        device: str = "auto",
        cpu_threads: int = 0,
        max_length: int = 256,
    ) -> None:
        self.model_name = model_name
        self.model_path = model_path
        self.download_root = download_root
        self.local_files_only = local_files_only
        self.device = device
        self.cpu_threads = cpu_threads
        self.max_length = max_length
        self._pipeline = None

    @property
    def model_source(self) -> str:
        if self.model_path is not None:
            return str(self.model_path)
        return self.model_name

    def prepare(self) -> ModelPreparationResult:
        self._get_pipeline()
        return ModelPreparationResult(
            task="pcs",
            family=self.family_name,
            provider=self.provider_name,
            model_name=self.model_name,
            model_source=self.model_source,
            download_root=str(self.download_root) if self.download_root is not None else None,
            local_files_only=self.local_files_only,
            ready=True,
            mode="verified",
        )

    def normalize_text(self, text: str) -> PCSNormalizationResult:
        cleaned = clean_command_text(text)
        if not cleaned:
            return PCSNormalizationResult(
                text="",
                status="skipped",
                message="Nothing to normalize.",
                pcs_family=self.family_name,
                pcs_provider=self.provider_name,
                pcs_model_name=self.model_name,
                inference_seconds=0.0,
            )

        pipeline = self._get_pipeline()
        started_at = perf_counter()
        outputs = pipeline(cleaned)
        inference_seconds = perf_counter() - started_at
        generated_text = _extract_generated_text(outputs)
        final_text = clean_command_text(generated_text) or cleaned
        return PCSNormalizationResult(
            text=final_text,
            status="refined" if final_text != cleaned else "kept",
            message=(
                "Applied PCS post-processing."
                if final_text != cleaned
                else "PCS kept the cleaned text unchanged."
            ),
            pcs_family=self.family_name,
            pcs_provider=self.provider_name,
            pcs_model_name=self.model_name,
            inference_seconds=inference_seconds,
        )

    def _get_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline

        source_path = self._resolve_runtime_source()
        logger.info(
            "Initializing PCS family=%s provider=%s model_source=%s device=%s "
            "cpu_threads=%s local_files_only=%s download_root=%s",
            self.family_name,
            self.provider_name,
            source_path,
            self.device,
            self.cpu_threads,
            self.local_files_only,
            self.download_root,
        )

        try:
            pipeline_module = _load_pipeline_module(source_path)
            pipeline_cls = getattr(pipeline_module, "PreTrainedPipeline", None)
            if pipeline_cls is None:
                raise RuntimeError("PCS bundle does not expose PreTrainedPipeline.")
            self._pipeline = pipeline_cls(str(source_path))
        except ImportError as error:
            raise RuntimeError(
                "ONNX PCS runtime requires `punctuators`, `onnxruntime`, and `sentencepiece`."
            ) from error
        except Exception as error:
            if self.local_files_only:
                raise RuntimeError(
                    "Local ONNX PCS model is not available or is incompatible. "
                    "Run `ivoice-install-model pcs --provider onnx` once with internet access "
                    "or set `pcs.model_path`."
                ) from error
            raise

        return self._pipeline

    def _resolve_runtime_source(self) -> Path:
        if self.model_path is not None:
            return self.model_path
        if self.download_root is None:
            raise RuntimeError("PCS download_root is not configured.")

        repo_dir = self.download_root / f"models--{self.model_name.replace('/', '--')}"
        snapshots_dir = repo_dir / "snapshots"
        if not snapshots_dir.exists():
            raise RuntimeError(f"PCS snapshot directory not found: {snapshots_dir}")

        refs_main = repo_dir / "refs" / "main"
        if refs_main.exists():
            revision = refs_main.read_text(encoding="utf-8").strip()
            if revision:
                snapshot_path = snapshots_dir / revision
                if snapshot_path.exists():
                    return snapshot_path

        snapshot_candidates = sorted(
            (path for path in snapshots_dir.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
        if snapshot_candidates:
            return snapshot_candidates[-1]

        raise RuntimeError(f"No PCS snapshots found under {snapshots_dir}")


def _load_pipeline_module(source_path: Path):
    pipeline_path = source_path / "pipeline.py"
    if not pipeline_path.exists():
        raise RuntimeError(f"PCS pipeline module not found: {pipeline_path}")

    spec = importlib.util.spec_from_file_location("ivoice_pcs_pipeline", pipeline_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load PCS pipeline spec from {pipeline_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_generated_text(outputs) -> str:
    if isinstance(outputs, list) and outputs:
        first_item = outputs[0]
        if isinstance(first_item, dict):
            generated_text = first_item.get("generated_text", "")
            return str(generated_text).replace(" \\n ", "\n").strip()
    return ""
