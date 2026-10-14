"""check_frozen_imports.py의 별칭 규칙: 같은 파일이 다른 이름으로도 등록된 TensorFlow 모듈
(tensorflow.compat.v1 ↔ 실제 파일 tensorflow/_api/v2/compat/v1/__init__.py)만, 실제 이름이 앱(PYZ)에 있을 때 통과."""

import os

import check_frozen_imports as cfi

SITE = sorted(cfi.SITE_DIRS)[0]


def site_path(*parts):
    return os.path.join(SITE, *parts)


def test_tensorflow_compat_alias_accepted_when_real_name_is_in_app():
    path = site_path("tensorflow", "_api", "v2", "compat", "v1", "__init__.py")
    modules = {"tensorflow._api.v2.compat.v1"}
    assert cfi.tensorflow_alias_of("tensorflow.compat.v1", path, modules) == "tensorflow._api.v2.compat.v1"


def test_tensorflow_alias_rejected_when_real_name_missing_from_app():
    path = site_path("tensorflow", "_api", "v2", "compat", "v1", "__init__.py")
    assert cfi.tensorflow_alias_of("tensorflow.compat.v1", path, set()) is None


def test_alias_rule_only_for_tensorflow_namespace():
    """tensorflow 밖의 모듈은 경로가 다른 실제 이름을 가리켜도 받아 주지 않음 (진짜 누락을 가리지 않게)."""
    path = site_path("urllib3", "__init__.py")
    assert cfi.tensorflow_alias_of("requests.packages.urllib3", path, {"urllib3"}) is None
    assert cfi.tensorflow_alias_of("tensorflow_io_gcs_filesystem", site_path("x", "__init__.py"), {"x"}) is None


def test_same_name_is_not_an_alias():
    path = site_path("tensorflow", "python", "__init__.py")
    assert cfi.tensorflow_alias_of("tensorflow.python", path, {"tensorflow.python"}) is None
