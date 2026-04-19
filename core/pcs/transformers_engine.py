from __future__ import annotations

import logging
import re
from pathlib import Path
from time import perf_counter

from core.pcs.base import BasePCSEngine
from core.text_cleanup import clean_command_text
from schemas.command import PCSNormalizationResult
from schemas.runtime import ModelPreparationResult

logger = logging.getLogger(__name__)

_WORD_CLEANUP_RE = re.compile(r"^[\s\u2581]+|[\s\u2581]+$")


class TransformersPCSEngine(BasePCSEngine):
    family_name = "punctuation"
    provider_name = "transformers"

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
        self._tokenizer = None
        self._model = None
        self._runtime_kind: str | None = None
        self._torch = None

    @property
    def model_source(self) -> str:
        if self.model_path is not None:
            return str(self.model_path)
        return self.model_name

    def prepare(self) -> ModelPreparationResult:
        self._get_runtime()
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

        tokenizer, model = self._get_runtime()
        started_at = perf_counter()
        if self._runtime_kind == "seq2seq":
            normalized = self._run_seq2seq(cleaned, tokenizer, model)
        else:
            normalized = self._run_token_classification(cleaned, tokenizer, model)
        inference_seconds = perf_counter() - started_at
        final_text = clean_command_text(normalized) or cleaned
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

    def _get_runtime(self):
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer, self._model

        try:
            import torch
            from transformers import (
                AutoConfig,
                AutoModelForSeq2SeqLM,
                AutoModelForTokenClassification,
                AutoTokenizer,
            )
        except ImportError as error:
            raise RuntimeError(
                "PCS runtime requires `transformers`, `sentencepiece`, `ftfy`, and a supported "
                "PyTorch installation."
            ) from error

        self._configure_torch_runtime(torch)
        model_device = self._resolve_device(torch)
        source = self._resolve_runtime_source()
        logger.info(
            "Initializing PCS family=%s provider=%s model_source=%s device=%s "
            "cpu_threads=%s local_files_only=%s download_root=%s",
            self.family_name,
            self.provider_name,
            source,
            model_device,
            self.cpu_threads,
            self.local_files_only,
            self.download_root,
        )

        try:
            tokenizer_kwargs = {
                "cache_dir": None if isinstance(source, Path) else self.download_root,
                "local_files_only": self.local_files_only,
            }
            try:
                self._tokenizer = AutoTokenizer.from_pretrained(
                    str(source),
                    **tokenizer_kwargs,
                )
            except ValueError as error:
                if not _should_retry_with_slow_tokenizer(error):
                    raise
                logger.info("Falling back to slow PCS tokenizer for model_source=%s", source)
                self._tokenizer = AutoTokenizer.from_pretrained(
                    str(source),
                    use_fast=False,
                    **tokenizer_kwargs,
                )
            config = AutoConfig.from_pretrained(
                str(source),
                cache_dir=None if isinstance(source, Path) else self.download_root,
                local_files_only=self.local_files_only,
            )
            if getattr(config, "is_encoder_decoder", False):
                self._model = AutoModelForSeq2SeqLM.from_pretrained(
                    str(source),
                    cache_dir=None if isinstance(source, Path) else self.download_root,
                    local_files_only=self.local_files_only,
                )
                self._runtime_kind = "seq2seq"
            else:
                self._model = AutoModelForTokenClassification.from_pretrained(
                    str(source),
                    cache_dir=None if isinstance(source, Path) else self.download_root,
                    local_files_only=self.local_files_only,
                )
                self._runtime_kind = "token-classification"
        except Exception as error:
            if self.local_files_only:
                if _looks_like_incompatible_pcs_bundle(source):
                    raise RuntimeError(
                        "Configured PCS model is not compatible with the `transformers` PCS "
                        "runtime. The local bundle looks like an ONNX/NeMo export, not a "
                        "standard Hugging Face Transformers checkpoint. Use a compatible PCS "
                        "model or implement a dedicated PCS provider for this bundle."
                    ) from error
                raise RuntimeError(
                    "Local PCS model is not available. Run `ivoice-install-model pcs` once with "
                    "internet access or set `pcs.model_path`."
                ) from error
            raise

        self._model.to(model_device)
        self._model.eval()
        self._torch = torch
        return self._tokenizer, self._model

    def _resolve_runtime_source(self) -> str | Path:
        if self.model_path is not None:
            return self.model_path
        if not self.local_files_only or self.download_root is None:
            return self.model_name

        repo_dir = self.download_root / f"models--{self.model_name.replace('/', '--')}"
        snapshots_dir = repo_dir / "snapshots"
        if not snapshots_dir.exists():
            return self.model_name

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

        return self.model_name

    def _configure_torch_runtime(self, torch_module) -> None:
        if self.cpu_threads <= 0:
            return
        try:
            torch_module.set_num_threads(self.cpu_threads)
        except Exception:
            logger.warning(
                "Failed to apply PCS cpu_threads=%s for model=%s",
                self.cpu_threads,
                self.model_name,
            )

    def _resolve_device(self, torch_module) -> str:
        if self.device != "auto":
            return self.device
        if torch_module.cuda.is_available():
            return "cuda"
        mps = getattr(torch_module.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
        return "cpu"

    def _run_seq2seq(self, text: str, tokenizer, model) -> str:
        inputs = tokenizer(text, return_tensors="pt", truncation=True)
        model_device = next(model.parameters()).device
        inputs = {key: value.to(model_device) for key, value in inputs.items()}
        with self._torch.no_grad():
            output = model.generate(**inputs, max_length=self.max_length)
        return tokenizer.decode(output[0], skip_special_tokens=True).strip()

    def _run_token_classification(self, text: str, tokenizer, model) -> str:
        inputs = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
        )
        model_device = next(model.parameters()).device
        inputs = {key: value.to(model_device) for key, value in inputs.items()}
        with self._torch.no_grad():
            outputs = model(**inputs)

        predictions = outputs.logits.argmax(dim=-1)[0].tolist()
        tokens = tokenizer.convert_ids_to_tokens(inputs["input_ids"][0])
        labels: list[tuple[str, str]] = []
        previous_word_index = None
        word_ids_method = getattr(inputs, "word_ids", None)
        if callable(word_ids_method):
            word_ids = inputs.word_ids(batch_index=0)
        else:
            word_ids = list(range(len(tokens)))
        for token, prediction, word_index in zip(tokens, predictions, word_ids, strict=False):
            if token in getattr(tokenizer, "all_special_tokens", ()):
                continue
            if word_index is None or word_index == previous_word_index:
                continue
            previous_word_index = word_index
            token_text = _clean_token(token)
            if not token_text:
                continue
            label = model.config.id2label.get(prediction, "O")
            labels.append((token_text, str(label)))

        if not labels:
            return text

        rebuilt: list[str] = []
        for index, (token_text, label) in enumerate(labels):
            rendered = _apply_case(token_text, label)
            if index > 0:
                rebuilt.append(" ")
            rebuilt.append(rendered)
            punctuation = _extract_punctuation(label)
            if punctuation:
                rebuilt.append(punctuation)
        return "".join(rebuilt)


def _clean_token(token: str) -> str:
    return _WORD_CLEANUP_RE.sub("", token).replace("##", "")


def _apply_case(token: str, label: str) -> str:
    upper_label = label.upper()
    if "ALLCAPS" in upper_label or "UPPER" in upper_label:
        return token.upper()
    if "CAP" in upper_label or "TITLE" in upper_label or "INIT" in upper_label:
        return token[:1].upper() + token[1:].lower()
    if "LOWER" in upper_label:
        return token.lower()
    return token


def _extract_punctuation(label: str) -> str:
    upper_label = label.upper()
    if "QUESTION" in upper_label or upper_label.endswith("?") or "_Q" in upper_label:
        return "?"
    if "EXCL" in upper_label or upper_label.endswith("!") or "_E" in upper_label:
        return "!"
    if "COMMA" in upper_label or upper_label.endswith(","):
        return ","
    if (
        "FULLSTOP" in upper_label
        or "PERIOD" in upper_label
        or "DOT" in upper_label
        or upper_label.endswith(".")
    ):
        return "."
    if "COLON" in upper_label or upper_label.endswith(":"):
        return ":"
    if "SEMICOLON" in upper_label or upper_label.endswith(";"):
        return ";"
    return ""


def _should_retry_with_slow_tokenizer(error: ValueError) -> bool:
    message = str(error).lower()
    return "backend tokenizer" in message or "slow tokenizer" in message


def _looks_like_incompatible_pcs_bundle(source: str | Path) -> bool:
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_dir():
        return False

    expected_transformers_files = {
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "sentencepiece.bpe.model",
        "spiece.model",
        "model.safetensors",
        "pytorch_model.bin",
    }
    present_files = {path.name for path in source_path.iterdir() if path.is_file()}
    if present_files & expected_transformers_files:
        return False

    incompatible_markers = {"model.onnx", ".nemo", "config.yaml", "pipeline.py"}
    if "model.onnx" in present_files:
        return True
    if "config.yaml" in present_files and "pipeline.py" in present_files:
        return True
    return any(name.endswith(".nemo") for name in present_files) or bool(
        present_files & incompatible_markers
    )
