"""Read configured Sources with existing providers and readers."""

import asyncio
import io
import json
from pathlib import Path
from typing import Any, Dict, List

from agno.db.schemas.sources import validate_source_fields
from agno.knowledge.document import Document
from agno.utils.string import hash_string_sha256


def _documents(source: Dict[str, Any]) -> List[Document]:
    validate_source_fields({key: source.get(key) for key in ("type", "reference", "credential_ref", "config")})
    reference = source["reference"]
    if source["type"] == "website":
        from agno.knowledge.reader.website_reader import WebsiteReader

        return WebsiteReader(chunk=False, max_depth=0, max_links=1).read(reference)
    from agno.context.mode import ContextMode
    from agno.context.workspace import WorkspaceContextProvider
    from agno.knowledge.reader.markdown_reader import MarkdownReader

    root = Path(reference).expanduser().resolve()
    provider = WorkspaceContextProvider(root=root if root.is_dir() else root.parent, mode=ContextMode.tools)
    if not provider.status().ok:
        raise ValueError("Source root is unavailable")
    workspace = provider.get_tools()[0]
    paths = (source.get("config") or {}).get("paths")
    if not paths:
        if root.is_file():
            paths = [root.name]
        else:
            listing = workspace.list_files(recursive=True, max_depth=100)
            if listing.startswith("Error"):
                raise ValueError("Source listing failed")
            paths = [
                entry["path"]
                for entry in json.loads(listing)["files"]
                if entry["type"] == "file" and (source["type"] == "git" or entry["path"].endswith((".md", ".markdown")))
            ]
    documents = []
    reader = MarkdownReader(chunk=False)
    for path in sorted(paths):
        content = workspace.read_file(path)
        if content.startswith("Error"):
            raise ValueError("Source read failed")
        # Workspace owns path confinement and exclusions. Remove only its display line numbers.
        content = "\n".join(line.split("\t", 1)[1] for line in content.split("\n") if "\t" in line)
        link = (provider.root / path).as_uri()
        if source["type"] == "markdown":
            loaded = reader.read(io.StringIO(content), name=path)
        else:
            loaded = [Document(name=path, content=content)]
        if not loaded:
            raise ValueError("Source reader returned no documents")
        for document in loaded:
            document.meta_data["url"] = link
        documents.extend(loaded)
    return documents


def read_source(source: Dict[str, Any], run_id: str) -> List[Dict[str, Any]]:
    """Return evidence only after every selected document was read successfully."""
    if not run_id:
        raise ValueError("Source evidence requires a run id")
    documents = _documents(source)
    if not documents:
        raise ValueError("Source reader returned no documents")
    return [
        {
            "source_id": source["id"],
            "run_id": run_id,
            "content_hash": hash_string_sha256(document.content),
            "link": document.meta_data.get("url") or source["reference"],
            "content": document.content,
        }
        for document in documents
    ]


async def aread_source(source: Dict[str, Any], run_id: str) -> List[Dict[str, Any]]:
    """Offload file/provider reads; native database calls remain async in the manager."""
    return await asyncio.to_thread(read_source, source, run_id)
