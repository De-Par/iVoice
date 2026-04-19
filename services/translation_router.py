from __future__ import annotations

from dataclasses import dataclass

from core.translation import BaseTranslationEngine, build_translation_engine
from schemas.model import ModelDescriptor
from schemas.transcription import TranslationResult


@dataclass
class TranslationRouteEntry:
    descriptor: ModelDescriptor
    engine: BaseTranslationEngine | None = None


class TranslationRouter:
    def __init__(
        self,
        *,
        default_descriptor: ModelDescriptor,
        route_descriptors: list[ModelDescriptor] | None = None,
    ) -> None:
        self.default_descriptor = default_descriptor
        ordered_descriptors = [default_descriptor, *(route_descriptors or [])]
        self._routes = [
            TranslationRouteEntry(descriptor=descriptor) for descriptor in ordered_descriptors
        ]

    @property
    def default_route(self) -> TranslationRouteEntry:
        return self._routes[0]

    def get_default_engine(self) -> BaseTranslationEngine:
        return self.get_engine(self.default_route)

    def translate(
        self,
        text: str,
        *,
        source_language: str | None,
        target_language: str,
    ) -> TranslationResult:
        route = self.select_route(
            source_language=source_language,
            target_language=target_language,
        )
        engine = self.get_engine(route)
        return engine.translate(
            text,
            source_language=source_language,
            target_language=target_language,
        )

    def select_route(
        self,
        *,
        source_language: str | None,
        target_language: str,
    ) -> TranslationRouteEntry:
        exact_matches: list[TranslationRouteEntry] = []
        wildcard_matches: list[TranslationRouteEntry] = []

        for route in self._routes:
            descriptor = route.descriptor
            descriptor_target = descriptor.target_language or "en"
            if descriptor_target != target_language:
                continue

            descriptor_source = descriptor.source_language
            if descriptor_source is None:
                wildcard_matches.append(route)
            elif descriptor_source == source_language:
                exact_matches.append(route)

        for route in [*exact_matches, *wildcard_matches]:
            try:
                self.validate_language_pair(
                    route=route,
                    source_language=source_language,
                    target_language=target_language,
                )
            except RuntimeError:
                continue
            return route

        raise RuntimeError(
            "No configured translation route supports the requested language pair "
            f"{source_language or 'auto'}->{target_language}."
        )

    def validate_language_pair(
        self,
        *,
        route: TranslationRouteEntry | None = None,
        source_language: str | None,
        target_language: str,
    ) -> None:
        selected_route = route or self.select_route(
            source_language=source_language,
            target_language=target_language,
        )
        engine = self.get_engine(selected_route)
        validate_language_pair = getattr(engine, "validate_language_pair", None)
        if callable(validate_language_pair):
            validate_language_pair(
                source_language=source_language,
                target_language=target_language,
            )

    def iter_routes(self) -> list[TranslationRouteEntry]:
        return list(self._routes)

    def supported_source_languages(self, *, target_language: str) -> set[str]:
        supported: set[str] = set()
        for route in self._routes:
            descriptor = route.descriptor
            descriptor_target = descriptor.target_language or "en"
            if descriptor_target != target_language:
                continue
            if descriptor.source_language is not None:
                supported.add(descriptor.source_language)
        return supported

    def has_wildcard_route(self, *, target_language: str) -> bool:
        for route in self._routes:
            descriptor = route.descriptor
            descriptor_target = descriptor.target_language or "en"
            if descriptor_target != target_language:
                continue
            if descriptor.source_language is None:
                return True
        return False

    def get_engine(self, route: TranslationRouteEntry) -> BaseTranslationEngine:
        if route.engine is None:
            route.engine = build_translation_engine(route.descriptor)
        return route.engine
