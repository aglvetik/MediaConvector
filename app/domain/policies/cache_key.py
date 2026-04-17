from app.domain.enums.platform import Platform


def build_cache_key(platform: Platform, resource_type: str, resource_id: str) -> str:
    normalized_resource_type = resource_type.strip().lower()
    normalized_resource_id = resource_id.strip()
    return f"{platform.value}:{normalized_resource_type}:{normalized_resource_id}"

