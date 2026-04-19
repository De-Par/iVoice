from __future__ import annotations

from core.pcs.base import BasePCSEngine
from core.pcs.identity_engine import IdentityPCSEngine
from core.pcs.onnx_engine import ONNXPCSEngine
from core.pcs.transformers_engine import TransformersPCSEngine
from schemas.model import ModelDescriptor


def build_pcs_engine(descriptor: ModelDescriptor) -> BasePCSEngine:
    family = descriptor.family.lower()
    provider = descriptor.provider.lower()

    if family == "identity" and provider == "identity":
        return IdentityPCSEngine(model_name=descriptor.model_name)

    if family == "punctuation" and provider == "transformers":
        return TransformersPCSEngine(
            model_name=descriptor.model_name,
            model_path=descriptor.model_path,
            download_root=descriptor.download_root,
            local_files_only=descriptor.local_files_only,
            device=descriptor.device or "auto",
            cpu_threads=descriptor.cpu_threads or 0,
            max_length=descriptor.max_length or 256,
        )

    if family == "punctuation" and provider == "onnx":
        return ONNXPCSEngine(
            model_name=descriptor.model_name,
            model_path=descriptor.model_path,
            download_root=descriptor.download_root,
            local_files_only=descriptor.local_files_only,
            device=descriptor.device or "auto",
            cpu_threads=descriptor.cpu_threads or 0,
            max_length=descriptor.max_length or 256,
        )

    raise ValueError(
        f"Unsupported PCS runtime: family={descriptor.family} provider={descriptor.provider}"
    )
