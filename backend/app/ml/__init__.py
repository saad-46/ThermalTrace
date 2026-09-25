"""ML package.

Windows note: LightGBM ≥ 4.6.0 (required — 4.5.0 has a remote-code-execution advisory,
PYSEC-2024-231) no longer bundles the OpenMP runtime (vcomp140.dll). scikit-learn, already a
dependency, vendors that exact runtime, so its directory is registered for DLL resolution before
LightGBM loads. This avoids asking developers to install system-wide redistributables. Linux/Docker
use libgomp from the image and are unaffected.
"""
import os
import sys


def _register_openmp_runtime() -> None:
    if sys.platform != "win32":
        return
    try:
        import sklearn

        libs = os.path.join(os.path.dirname(sklearn.__file__), ".libs")
        if os.path.isfile(os.path.join(libs, "vcomp140.dll")):
            os.add_dll_directory(libs)
    except (ImportError, OSError):  # LightGBM will raise its own clear error if the runtime is truly absent
        pass


_register_openmp_runtime()
