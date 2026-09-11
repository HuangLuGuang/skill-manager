import zipfile

import pytest
from fastapi import HTTPException
from agent_manager.api.router import _safe_extract_zip


def test_extraction_enforces_shared_file_budget(tmp_path):
    archive = tmp_path / 'test.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('a.svg', 'a')
        zf.writestr('b.svg', 'b')
    with pytest.raises(HTTPException) as error:
        _safe_extract_zip(archive, tmp_path / 'out', budget={'files': 49999, 'bytes': 0})
    assert error.value.status_code == 413
    assert not (tmp_path / 'out/b.svg').exists()


def test_extraction_enforces_shared_size_budget(tmp_path):
    archive = tmp_path / 'test.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('SKILL.md', 'example')
    with pytest.raises(HTTPException):
        _safe_extract_zip(archive, tmp_path / 'out', budget={'files': 0, 'bytes': 1024 ** 3 - 1})
    assert not (tmp_path / 'out/SKILL.md').exists()
