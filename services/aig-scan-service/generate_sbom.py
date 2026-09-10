from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path


def main(output_path: str) -> None:
    packages = [
        {
            "SPDXID": "SPDXRef-Package-AI-Infra-Guard",
            "name": "AI-Infra-Guard",
            "versionInfo": "v4.6.0+e8931cc68001b66ad024fd87ef07394e9e96524a",
            "downloadLocation": "https://github.com/Tencent/AI-Infra-Guard",
            "filesAnalyzed": False,
            "licenseConcluded": "Apache-2.0",
            "licenseDeclared": "Apache-2.0",
        }
    ]
    for distribution in sorted(metadata.distributions(), key=lambda item: (item.metadata.get("Name") or "").lower()):
        name = distribution.metadata.get("Name") or "unknown"
        packages.append(
            {
                "SPDXID": f"SPDXRef-Package-{name.replace('_', '-').replace('.', '-')}",
                "name": name,
                "versionInfo": distribution.version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": distribution.metadata.get("License-Expression")
                or distribution.metadata.get("License")
                or "NOASSERTION",
            }
        )
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "agent-manager-aig-scan-service",
        "documentNamespace": "https://agent-manager.local/sbom/aig-scan-service/v4.6.0",
        "creationInfo": {"creators": ["Tool: agent-manager-aig-service-generate-sbom.py"]},
        "packages": packages,
    }
    Path(output_path).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
