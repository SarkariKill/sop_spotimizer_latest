"""Provision the mandatory local Docling PDF models once, before services start."""
import importlib.metadata
import json
import os
from pathlib import Path

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")

from document_ingestion import get_models_path

MODEL_PROFILE = "docling-layout-v2-tableformer"


def ensure_models():
    destination = get_models_path()
    marker = destination / ".kenvue-docling-models.json"
    versions = {name: importlib.metadata.version(name) for name in ("docling", "docling-core", "docling-ibm-models")}
    try:
        saved = json.loads(marker.read_text())
        files = saved.get("files", [])
        if saved.get("profile") == MODEL_PROFILE and saved.get("versions") == versions and files and all(
            (destination / item["path"]).is_file() and (destination / item["path"]).stat().st_size == item["size"]
            for item in files
        ):
            print(f"Docling local models ready: {destination}")
            return destination
    except (OSError, ValueError, KeyError):
        pass
    from docling.utils.model_downloader import download_models
    from docling.models.layout_model import LayoutModel
    from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_V2
    print(f"Preparing Docling layout and table models at {destination}. First setup needs internet access.", flush=True)
    LayoutModel.download_models(local_dir=destination / DOCLING_LAYOUT_V2.model_repo_folder,
                                layout_model_config=DOCLING_LAYOUT_V2, progress=True)
    download_models(output_dir=destination, progress=True, with_layout=False, with_tableformer=True,
                    with_code_formula=False, with_picture_classifier=False, with_rapidocr=False,
                    with_easyocr=False)
    required_roots = [destination / DOCLING_LAYOUT_V2.model_repo_folder, destination / "ds4sd--docling-models"]
    files = [{"path": str(path.relative_to(destination)), "size": path.stat().st_size}
             for root in required_roots for path in root.rglob("*") if path.is_file() and ".cache" not in path.parts
             and not path.name.startswith(".kenvue-")]
    if not files:
        raise RuntimeError("Docling model provisioning produced no local model files")
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps({"profile": MODEL_PROFILE, "versions": versions, "files": files}, indent=2))
    temporary.replace(marker)
    print(f"Docling local models ready: {destination}")
    return destination


if __name__ == "__main__":
    ensure_models()
