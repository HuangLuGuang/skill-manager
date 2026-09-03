from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path


def main(output_path: str) -> None:
    packages = []
    for distribution in sorted(metadata.distributions(), key=lambda item: (item.metadata.get("Name") or "").lower()):
        name = distribution.metadata.get("Name") or "unknown"
        known_licenses = {"aig-agent-scan": "Apache-2.0", "aig-mcp-scan": "Apache-2.0", "loguru": "MIT"}
        declared_license = (
            known_licenses.get(name.lower())
            or distribution.metadata.get("License-Expression")
            or distribution.metadata.get("License")
            or "NOASSERTION"
        )
        packages.append(
            {
                "SPDXID": f"SPDXRef-Package-{name.replace('_', '-').replace('.', '-')}",
                "name": name,
                "versionInfo": distribution.version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": declared_license,
            }
        )
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "agent-manager-security-worker-python-packages",
        "documentNamespace": "https://agent-manager.local/sbom/agent-security-worker/v2",
        "creationInfo": {"creators": ["Tool: agent-manager-generate-sbom.py"]},
        "packages": packages,
    }
    Path(output_path).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
