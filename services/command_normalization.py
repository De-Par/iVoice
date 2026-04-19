from __future__ import annotations

from core.language import (
    LanguageDetectionError,
    analyze_text_language_spans,
    detect_text_language,
    detect_text_script,
    normalize_language_code,
)
from schemas.command import (
    CommandNormalizationResult,
    CommandSource,
    CommandSpan,
    LanguageResolution,
    NormalizedCommand,
)
from schemas.config import AppSettings
from schemas.runtime import ModelPreparationResult
from services.translation_router import TranslationRouter


class CommandNormalizationService:
    def __init__(
        self,
        settings: AppSettings,
        translation_router: TranslationRouter,
    ) -> None:
        self.settings = settings
        self.translation_router = translation_router

    def warm_up_routes(self) -> list[ModelPreparationResult]:
        components: list[ModelPreparationResult] = []
        for route in self.translation_router.iter_routes():
            engine = self.translation_router.get_engine(route)
            components.append(engine.prepare())
        return components

    def resolve_language(
        self,
        text: str,
        *,
        language: str | None = None,
        fallback_language: str | None = None,
        allow_detection: bool = True,
        source_if_explicit: str = "explicit",
        source_if_fallback: str = "fallback",
    ) -> LanguageResolution:
        explicit_language = normalize_language_code(language)
        if explicit_language is not None:
            return LanguageResolution(language=explicit_language, source=source_if_explicit)

        if allow_detection:
            detected_language = detect_text_language(text)
            return LanguageResolution(language=detected_language, source="detected")

        fallback = normalize_language_code(fallback_language)
        if fallback is not None:
            return LanguageResolution(language=fallback, source=source_if_fallback)

        return LanguageResolution(language=None, source="unknown")

    def normalize_command(
        self,
        text: str,
        *,
        modality: str,
        language: str | None = None,
        fallback_language: str | None = None,
        allow_detection: bool = True,
        allow_segmented_fallback: bool = False,
        source_if_explicit: str = "explicit",
        source_if_fallback: str = "fallback",
    ) -> CommandNormalizationResult:
        source_text = text.strip()
        if not source_text:
            raise ValueError("Command text cannot be empty.")

        target_language = normalize_language_code(self.settings.translation.target_language) or "en"
        if allow_segmented_fallback and self._should_prefer_span_normalization(source_text):
            return self._normalize_command_by_spans(
                source_text,
                modality=modality,
                fallback_language=language or fallback_language,
                target_language=target_language,
            )
        try:
            resolution = self.resolve_language(
                source_text,
                language=language,
                fallback_language=fallback_language,
                allow_detection=allow_detection,
                source_if_explicit=source_if_explicit,
                source_if_fallback=source_if_fallback,
            )
        except LanguageDetectionError as error:
            if language is not None:
                raise
            message = str(error).lower()
            if "mixed scripts" in message or "ambiguous" in message:
                return self._normalize_command_by_spans(
                    source_text,
                    modality=modality,
                    fallback_language=fallback_language,
                    target_language=target_language,
                )
            raise

        command_source = CommandSource(
            text=source_text,
            modality=modality,
            language=resolution.language,
            language_source=resolution.source,
        )

        if not self.settings.translation.enabled:
            return CommandNormalizationResult(
                source=command_source,
                normalized=NormalizedCommand(
                    text=source_text,
                    target_language=target_language,
                    status="disabled",
                    message="Translation is disabled.",
                ),
                spans=[
                    CommandSpan(
                        text=source_text,
                        kind="text",
                        language=resolution.language,
                        language_source=resolution.source,
                        status="disabled",
                        normalized_text=source_text,
                    )
                ],
            )

        if resolution.language is not None and resolution.language == target_language:
            return CommandNormalizationResult(
                source=command_source,
                normalized=NormalizedCommand(
                    text=source_text,
                    target_language=target_language,
                    status="skipped",
                    message="Command already matches target language.",
                    preserved_span_count=1,
                ),
                spans=[
                    CommandSpan(
                        text=source_text,
                        kind="text",
                        language=resolution.language,
                        language_source=resolution.source,
                        status="kept",
                        normalized_text=source_text,
                    )
                ],
            )

        try:
            translation = self.translation_router.translate(
                source_text,
                source_language=resolution.language,
                target_language=target_language,
            )
        except RuntimeError:
            if language is not None and not allow_segmented_fallback:
                raise
            return self._normalize_command_by_spans(
                source_text,
                modality=modality,
                fallback_language=language or fallback_language,
                target_language=target_language,
            )

        return CommandNormalizationResult(
            source=command_source,
            normalized=NormalizedCommand(
                text=translation.text,
                target_language=translation.target_language,
                status="translated",
                translated_span_count=1,
                translation_family=translation.translation_family,
                translation_provider=translation.translation_provider,
                translation_model_name=translation.model_name,
                translation_inference_seconds=translation.inference_seconds,
            ),
            spans=[
                CommandSpan(
                    text=source_text,
                    kind="text",
                    language=resolution.language,
                    language_source=resolution.source,
                    status="translated",
                    normalized_text=translation.text,
                    translation_family=translation.translation_family,
                    translation_provider=translation.translation_provider,
                    translation_model_name=translation.model_name,
                )
            ],
        )

    def _normalize_command_by_spans(
        self,
        text: str,
        *,
        modality: str,
        fallback_language: str | None,
        target_language: str,
    ) -> CommandNormalizationResult:
        analyzed_spans = analyze_text_language_spans(text)
        command_spans: list[CommandSpan] = []
        normalized_parts: list[str] = []
        translated_count = 0
        preserved_count = 0
        translation_seconds = 0.0
        translatable_span_count = 0
        untranslated_span_count = 0

        for span in analyzed_spans:
            if span.kind == "literal":
                command_spans.append(
                    CommandSpan(
                        text=span.text,
                        kind="literal",
                        language_source="literal",
                        status="literal",
                        normalized_text=span.text,
                    )
                )
                normalized_parts.append(span.text)
                continue

            translation_candidates = self._iter_span_language_candidates(
                span_language=span.language,
                span_text=span.text,
                target_language=target_language,
            )
            if not translation_candidates:
                command_spans.append(
                    CommandSpan(
                        text=span.text,
                        kind="text",
                        language=None,
                        language_source=span.language_source,
                        status="preserved",
                        normalized_text=span.text,
                    )
                )
                normalized_parts.append(span.text)
                preserved_count += 1
                continue

            if translation_candidates[0][0] == target_language:
                command_spans.append(
                    CommandSpan(
                        text=span.text,
                        kind="text",
                        language=translation_candidates[0][0],
                        language_source=translation_candidates[0][1],
                        status="kept",
                        normalized_text=span.text,
                    )
                )
                normalized_parts.append(span.text)
                preserved_count += 1
                continue

            translatable_span_count += 1
            translation = None
            selected_language = None
            selected_language_source = span.language_source
            for candidate_language, candidate_source in translation_candidates:
                if candidate_language == target_language:
                    continue
                try:
                    translation = self.translation_router.translate(
                        span.text.strip(),
                        source_language=candidate_language,
                        target_language=target_language,
                    )
                except RuntimeError:
                    continue
                selected_language = candidate_language
                selected_language_source = candidate_source
                break

            if translation is None or selected_language is None:
                untranslated_span_count += 1
                command_spans.append(
                    CommandSpan(
                        text=span.text,
                        kind="text",
                        language=translation_candidates[0][0],
                        language_source=translation_candidates[0][1],
                        status="preserved",
                        normalized_text=span.text,
                    )
                )
                normalized_parts.append(span.text)
                preserved_count += 1
                continue

            normalized_text = _restore_surrounding_whitespace(span.text, translation.text)
            command_spans.append(
                CommandSpan(
                    text=span.text,
                    kind="text",
                    language=selected_language,
                    language_source=selected_language_source,
                    status="translated",
                    normalized_text=normalized_text,
                    translation_family=translation.translation_family,
                    translation_provider=translation.translation_provider,
                    translation_model_name=translation.model_name,
                )
            )
            normalized_parts.append(normalized_text)
            translated_count += 1
            translation_seconds += translation.inference_seconds

        normalized_text = "".join(normalized_parts).strip() or text
        first_translated_span = next(
            (span for span in command_spans if span.status == "translated"),
            None,
        )
        status, message = _summarize_partial_normalization(
            translated_count=translated_count,
            preserved_count=preserved_count,
            translatable_span_count=translatable_span_count,
            untranslated_span_count=untranslated_span_count,
        )
        return CommandNormalizationResult(
            source=CommandSource(
                text=text,
                modality=modality,
                language=None,
                language_source="segmented",
            ),
            normalized=NormalizedCommand(
                text=normalized_text,
                target_language=target_language,
                status=status,
                message=message,
                translated_span_count=translated_count,
                preserved_span_count=preserved_count,
                translation_family=(
                    first_translated_span.translation_family
                    if first_translated_span is not None
                    else None
                ),
                translation_provider=(
                    first_translated_span.translation_provider
                    if first_translated_span is not None
                    else None
                ),
                translation_model_name=(
                    first_translated_span.translation_model_name
                    if first_translated_span is not None
                    else None
                ),
                translation_inference_seconds=translation_seconds or None,
            ),
            spans=command_spans,
        )

    def build_error_result(
        self,
        text: str,
        *,
        modality: str,
        message: str,
        normalized_text: str,
        language: str | None = None,
        language_source: str = "unknown",
    ) -> CommandNormalizationResult:
        target_language = normalize_language_code(self.settings.translation.target_language) or "en"
        default_route = self.translation_router.default_route.descriptor
        return CommandNormalizationResult(
            source=CommandSource(
                text=text,
                modality=modality,
                language=normalize_language_code(language),
                language_source=language_source,
            ),
            normalized=NormalizedCommand(
                text=normalized_text,
                target_language=target_language,
                status="error",
                message=message,
                translation_family=default_route.family,
                translation_provider=default_route.provider,
                translation_model_name=default_route.model_name,
            ),
            spans=[
                CommandSpan(
                    text=text,
                    kind="text",
                    language=normalize_language_code(language),
                    language_source=language_source,
                    status="error",
                    normalized_text=normalized_text,
                    translation_family=default_route.family,
                    translation_provider=default_route.provider,
                    translation_model_name=default_route.model_name,
                )
            ],
        )

    def _iter_span_language_candidates(
        self,
        *,
        span_language: str | None,
        span_text: str,
        target_language: str,
    ) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(language: str | None, source: str) -> None:
            normalized_language = normalize_language_code(language)
            if normalized_language is None or normalized_language in seen:
                return
            candidates.append((normalized_language, source))
            seen.add(normalized_language)

        add(span_language, "detected")

        if self.translation_router.has_wildcard_route(target_language=target_language):
            return candidates

        script_matches = self._guess_route_languages_for_script(
            span_text,
            target_language=target_language,
        )
        if len(script_matches) == 1:
            add(script_matches[0], "script_guess")

        return candidates

    def _guess_route_languages_for_script(
        self,
        text: str,
        *,
        target_language: str,
    ) -> list[str]:
        script = detect_text_script(text)
        if script not in {"latin", "cyrillic"}:
            return []

        script_map = {
            "latin": {
                "en",
                "de",
                "es",
                "fr",
                "it",
                "nl",
                "no",
                "da",
                "sv",
                "fi",
                "pt",
                "pl",
                "cs",
                "sk",
                "sl",
                "hr",
                "ro",
                "hu",
                "tr",
            },
            "cyrillic": {
                "ru",
                "uk",
                "bg",
                "sr",
                "mk",
                "be",
            },
        }
        supported_languages = self.translation_router.supported_source_languages(
            target_language=target_language
        )
        return sorted(
            language for language in supported_languages if language in script_map[script]
        )

    def _should_prefer_span_normalization(self, text: str) -> bool:
        scripts = {
            detect_text_script(span.text)
            for span in analyze_text_language_spans(text)
            if span.kind == "text"
        }
        scripts.discard("other")
        scripts.discard("mixed")
        return len(scripts) > 1


def _restore_surrounding_whitespace(source_text: str, translated_text: str) -> str:
    leading = source_text[: len(source_text) - len(source_text.lstrip())]
    trailing = source_text[len(source_text.rstrip()) :]
    return f"{leading}{translated_text.strip()}{trailing}"


def _summarize_partial_normalization(
    *,
    translated_count: int,
    preserved_count: int,
    translatable_span_count: int,
    untranslated_span_count: int,
) -> tuple[str, str | None]:
    if translated_count > 0 and untranslated_span_count == 0 and preserved_count == 0:
        return "translated", "Translated command span by span."
    if translated_count > 0:
        return "partial", "Partially normalized command; unsupported spans were preserved."
    if translatable_span_count == 0 and preserved_count > 0:
        return "skipped", "No translatable spans were detected."
    return "error", "No supported spans could be normalized."
