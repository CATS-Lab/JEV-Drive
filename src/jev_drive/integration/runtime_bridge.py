"""Explicit JEV-only policy hook; no global monkey-patching."""

from functools import lru_cache
import os
import json
from pathlib import Path
from ..config import Config
from ..state.state_builder import JevStateBuilder
from ..state.schema import encode
from .alpasim_adapter import AlpasimAdapter


@lru_cache(maxsize=8)
def adapter(scene_id, manifest_path, config_path, annotation_path):
    manifest = json.loads(Path(manifest_path).read_text())
    path = Path(manifest[scene_id])
    if not path.is_file():
        raise FileNotFoundError(f"scene artifact not found: {path}")
    return AlpasimAdapter(
        path, Config.load(config_path or None), annotation_path or None
    )


def build_payload(state, event, renderer_payload):
    source = adapter(
        state.unbound.scene_id,
        os.environ["JEV_SCENE_MANIFEST"],
        os.environ.get("JEV_CONFIG", ""),
        os.environ.get("JEV_SIGNAL_ANNOTATIONS", ""),
    )
    snapshot = source.from_runtime(state, event)
    return encode(JevStateBuilder(source.config).build(snapshot, renderer_payload))
