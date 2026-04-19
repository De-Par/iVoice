from __future__ import annotations

import json
from pathlib import Path

from schemas.command import CommandNormalizationResult
from schemas.transcription import RunArtifacts, RunMetadata, TranscriptionRun


class RunArtifactStore:
    def build_artifacts(
        self,
        *,
        run_dir: str | Path,
        audio_path: str | Path,
    ) -> RunArtifacts:
        return RunArtifacts.from_run_dir(
            run_dir,
            audio_path=audio_path,
        )

    def load_metadata(self, run_dir: str | Path) -> RunMetadata:
        artifacts = self.build_artifacts(run_dir=run_dir, audio_path="")
        metadata_path = Path(artifacts.metadata_path)
        if not metadata_path.exists():
            raise FileNotFoundError(f"Run metadata not found: {metadata_path}")
        return RunMetadata.model_validate(json.loads(metadata_path.read_text(encoding="utf-8")))

    def write_transcript(self, artifacts: RunArtifacts, text: str) -> None:
        self._ensure_run_dir(artifacts)
        Path(artifacts.transcript_path).write_text(text + "\n", encoding="utf-8")

    def write_transcript_en(self, artifacts: RunArtifacts, text: str) -> None:
        self._ensure_run_dir(artifacts)
        Path(artifacts.transcript_en_path).write_text(text + "\n", encoding="utf-8")

    def transcript_en_exists(self, artifacts: RunArtifacts) -> bool:
        return Path(artifacts.transcript_en_path).exists()

    def write_command_artifacts(
        self,
        *,
        artifacts: RunArtifacts,
        source_text: str,
        normalized_text: str,
        normalization_result: CommandNormalizationResult,
    ) -> None:
        self._ensure_run_dir(artifacts)
        Path(artifacts.source_path).write_text(source_text + "\n", encoding="utf-8")
        Path(artifacts.command_en_path).write_text(normalized_text + "\n", encoding="utf-8")
        Path(artifacts.normalization_spans_path).write_text(
            json.dumps(
                [span.model_dump(mode="json") for span in normalization_result.spans],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def write_metadata(self, artifacts: RunArtifacts, metadata: RunMetadata) -> None:
        self._ensure_run_dir(artifacts)
        Path(artifacts.metadata_path).write_text(
            json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def build_run(self, artifacts: RunArtifacts, metadata: RunMetadata) -> TranscriptionRun:
        return TranscriptionRun(
            artifacts=artifacts,
            metadata=metadata,
        )

    def _ensure_run_dir(self, artifacts: RunArtifacts) -> None:
        Path(artifacts.run_dir).mkdir(parents=True, exist_ok=True)
