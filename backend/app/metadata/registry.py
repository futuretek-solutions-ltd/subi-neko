from .base import MetadataProvider
from .anidb import AniDBProvider
from .anilist import AniListProvider

_PROVIDER_CLASSES = {
    "anidb": AniDBProvider,
    "anilist": AniListProvider,
}

# Singletons — important for AniDB rate limiting lock
_instances: dict[str, MetadataProvider] = {}


def get_provider(name: str) -> MetadataProvider:
    if name not in _instances:
        cls = _PROVIDER_CLASSES.get(name)
        if cls is None:
            raise KeyError(f"Unknown metadata provider: {name!r}. Available: {list(_PROVIDER_CLASSES)}")
        _instances[name] = cls()
    return _instances[name]


def list_providers() -> list[str]:
    return list(_PROVIDER_CLASSES)
