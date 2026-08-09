#!/usr/bin/env python3
"""
PyPMXVMD - Python MikuMikuDance File Parser

A Python library for parsing and modifying MikuMikuDance (MMD) files:
- VMD (Vocaloid Motion Data) - Motion and animation data
- PMX (PolygonMoviemaker eXtended) - 3D model data
- VPD (Vocaloid Pose Data) - Pose/frame data

Usage:
    import pypmxvmd

    # Parse VMD motion file
    motion = pypmxvmd.load_vmd("motion.vmd")
    pypmxvmd.save_vmd(motion, "modified_motion.vmd")

    # Parse PMX model file
    model = pypmxvmd.load_pmx("model.pmx")
    pypmxvmd.save_pmx(model, "modified_model.pmx")

    # Parse VPD pose file
    pose = pypmxvmd.load_vpd("pose.vpd")
    pypmxvmd.save_vpd(pose, "modified_pose.vpd")
"""

from pathlib import Path
from typing import Literal, Optional, Union, overload

from .common.models.pmx import PmxModel

# Import models for type hints
from .common.models.vmd import VmdMotion
from .common.models.vpd import VpdPose
from .common.parsers.pmx_parser import PmxParser

# Import parsers
from .common.parsers.vmd_parser import VmdParser
from .common.parsers.vpd_parser import VpdParser

# PMX completeness contracts
from .common.pmx import (
    IncompletePmxError,
    IncompletePmxWriterError,
    PmxDocument,
    PmxParseReport,
    PmxParseResult,
    PmxPatchError,
    PmxValidationError,
    UnsupportedPmxFeatureError,
)

__version__ = "2.7.1"
__author__ = "PythonImporter"
__description__ = "Python MikuMikuDance File Parser"

# Core parser instances (reused for efficiency)
_vmd_parser = VmdParser()
_pmx_parser = PmxParser()
_vpd_parser = VpdParser()


def load_vmd(file_path: Union[str, Path], more_info: bool = False) -> VmdMotion:
    """
    Load VMD motion file.

    Args:
        file_path: Path to VMD file
        more_info: Whether to include additional parsing information

    Returns:
        VmdMotion object

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    return _vmd_parser.parse_file(file_path, more_info=more_info)


def save_vmd(motion: VmdMotion, file_path: Union[str, Path]) -> None:
    """
    Save VMD motion to file.

    Args:
        motion: VmdMotion object to save
        file_path: Output file path

    Raises:
        ValueError: If motion data is invalid
        IOError: If file cannot be written
    """
    _vmd_parser.write_file(motion, file_path)


@overload
def load_pmx(
    file_path: Union[str, Path],
    more_info: bool = False,
    *,
    mode: Literal["strict"] = "strict",
    implementation: str = "auto",
    strict_eof: Optional[bool] = None,
    track_spans: Literal[True],
) -> PmxDocument: ...


@overload
def load_pmx(
    file_path: Union[str, Path],
    more_info: bool = False,
    *,
    mode: Literal["document"],
    implementation: str = "auto",
    strict_eof: Optional[bool] = None,
    track_spans: bool = False,
) -> PmxDocument: ...


@overload
def load_pmx(
    file_path: Union[str, Path],
    more_info: bool = False,
    *,
    mode: Literal["strict"] = "strict",
    implementation: str = "auto",
    strict_eof: Optional[bool] = None,
    track_spans: Literal[False] = False,
) -> PmxModel: ...


@overload
def load_pmx(
    file_path: Union[str, Path],
    more_info: bool = False,
    *,
    mode: Literal["partial"],
    implementation: str = "auto",
    strict_eof: Optional[bool] = None,
    track_spans: bool = False,
) -> PmxParseResult: ...


@overload
def load_pmx(
    file_path: Union[str, Path],
    more_info: bool = False,
    *,
    mode: str,
    implementation: str = "auto",
    strict_eof: Optional[bool] = None,
    track_spans: bool = False,
) -> Union[PmxDocument, PmxModel, PmxParseResult]: ...


def load_pmx(
    file_path: Union[str, Path],
    more_info: bool = False,
    *,
    mode: str = "strict",
    implementation: str = "auto",
    strict_eof: Optional[bool] = None,
    track_spans: bool = False,
) -> Union[PmxDocument, PmxModel, PmxParseResult]:
    """
    Load PMX model file.

    Args:
        file_path: Path to PMX file
        more_info: Whether to include additional parsing information
        mode: ``strict`` returns PmxModel; ``partial`` returns PmxParseResult;
            ``document`` returns a source-backed PmxDocument
        implementation: ``auto``, ``python``, ``fast``, or ``cython``
        strict_eof: Defaults to True for strict and False for partial mode
        track_spans: In strict mode, return a PmxDocument with field spans

    Returns:
        PmxModel or an explicit PmxParseResult in partial mode

    Raises:
        FileNotFoundError: If file doesn't exist
        IncompletePmxError: If strict EOF was requested but not reached
        ValueError: If a mode, implementation, or file format is invalid
    """
    if not isinstance(mode, str):
        raise ValueError("PMX read mode must be a string")
    if strict_eof is not None and type(strict_eof) is not bool:
        raise ValueError("strict_eof must be a bool or None")
    if type(track_spans) is not bool:
        raise ValueError("track_spans must be a bool")
    selected = mode.lower()
    if selected == "document":
        if strict_eof is False:
            raise ValueError("document PMX mode requires strict_eof=True")
        return load_pmx_document(
            file_path,
            more_info,
            implementation=implementation,
            track_spans=True,
        )
    if selected == "strict":
        if strict_eof is False:
            raise ValueError(
                "strict PMX mode requires strict_eof=True; use mode='partial' "
                "for diagnostic incomplete results"
            )
        if track_spans:
            return load_pmx_document(
                file_path,
                more_info,
                implementation=implementation,
                track_spans=True,
            )
        return _pmx_parser.parse_file(
            file_path,
            more_info=more_info,
            implementation=implementation,
            strict_eof=True,
            track_spans=track_spans,
        )
    if selected == "partial":
        result = _pmx_parser.parse_file_partial(
            file_path,
            more_info=more_info,
            implementation=implementation,
            track_spans=track_spans,
        )
        if strict_eof is True and not result.report.is_complete:
            raise IncompletePmxError(result.report)
        return result
    raise ValueError(
        f"Unknown PMX read mode: {mode!r}; expected strict, partial, or document"
    )


def load_pmx_partial(
    file_path: Union[str, Path],
    more_info: bool = False,
    implementation: str = "auto",
    *,
    track_spans: bool = False,
) -> PmxParseResult:
    """Load PMX with an explicit implementation and return completeness evidence.

    The result includes a :class:`PmxParseReport` describing loaded sections,
    byte offsets and missing mandatory sections.  PMX 2.0 results can be
    complete; unsupported PMX 2.1 content remains explicitly incomplete.
    Incomplete models returned by this diagnostic API are rejected by the
    canonical writer and are not proof that high-level PMX editing is available.
    """
    return _pmx_parser.parse_file_partial(
        file_path,
        more_info=more_info,
        implementation=implementation,
        track_spans=track_spans,
    )


def load_pmx_document(
    file_path: Union[str, Path],
    more_info: bool = False,
    *,
    implementation: str = "auto",
    track_spans: bool = True,
) -> PmxDocument:
    """Load a complete PMX 2.0 snapshot with fixed-width source field spans."""
    if type(track_spans) is not bool:
        raise ValueError("track_spans must be a bool")
    if not track_spans:
        raise ValueError("PmxDocument requires track_spans=True")
    return PmxDocument.from_file(
        file_path,
        more_info=more_info,
        implementation=implementation,
    )


def write_pmx(
    model: Union[PmxModel, PmxDocument],
    file_path: Union[str, Path],
    *,
    mode: str = "canonical",
) -> None:
    """Validate and write PMX through an explicit fail-closed mode."""
    _pmx_parser.write_file(model, file_path, mode=mode)


def save_pmx(
    model: Union[PmxModel, PmxDocument],
    file_path: Union[str, Path],
    *,
    mode: str = "canonical",
) -> None:
    """
    Validate and atomically save a canonical PMX 2.0 model.

    Args:
        model: PmxModel object to save
        file_path: Output file path
        mode: ``canonical`` for PmxModel or ``lossless_patch`` for PmxDocument

    Raises:
        PmxValidationError: If the model is invalid, incomplete, or unsupported
        IOError: If file cannot be written
    """
    write_pmx(model, file_path, mode=mode)


def load_vpd(file_path: Union[str, Path], more_info: bool = False) -> VpdPose:
    """
    Load VPD pose file.

    Args:
        file_path: Path to VPD file
        more_info: Whether to include additional parsing information

    Returns:
        VpdPose object

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    return _vpd_parser.parse_file(file_path, more_info=more_info)


def save_vpd(pose: VpdPose, file_path: Union[str, Path]) -> None:
    """
    Save VPD pose to file.

    Args:
        pose: VpdPose object to save
        file_path: Output file path

    Raises:
        ValueError: If pose data is invalid
        IOError: If file cannot be written
    """
    _vpd_parser.write_file(pose, file_path)


# Convenience functions for auto-detection
def load(
    file_path: Union[str, Path],
    more_info: bool = False,
    *,
    mode: Optional[str] = None,
    implementation: str = "auto",
    strict_eof: Optional[bool] = None,
    track_spans: bool = False,
) -> Union[VmdMotion, PmxDocument, PmxModel, PmxParseResult, VpdPose]:
    """
    Automatically detect file type and load appropriate format.

    Args:
        file_path: Path to file
        more_info: Whether to include additional parsing information
        mode: PMX read mode; omit for VMD/VPD
        implementation: PMX parser implementation
        strict_eof: PMX EOF policy
        track_spans: Return a source-backed PMX document for PMX strict reads

    Returns:
        VmdMotion, PmxModel, or VpdPose object

    Raises:
        ValueError: If file type cannot be determined or is unsupported
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    pmx_options_used = (
        mode is not None
        or implementation != "auto"
        or strict_eof is not None
        or track_spans
    )
    if suffix == ".vmd":
        if pmx_options_used:
            raise ValueError("PMX mode options cannot be used when loading VMD")
        return load_vmd(file_path, more_info)
    elif suffix == ".pmx":
        return load_pmx(
            file_path,
            more_info,
            mode="strict" if mode is None else mode,
            implementation=implementation,
            strict_eof=strict_eof,
            track_spans=track_spans,
        )
    elif suffix == ".vpd":
        if pmx_options_used:
            raise ValueError("PMX mode options cannot be used when loading VPD")
        return load_vpd(file_path, more_info)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def save(
    data: Union[VmdMotion, PmxDocument, PmxModel, VpdPose],
    file_path: Union[str, Path],
    *,
    mode: Optional[str] = None,
) -> None:
    """
    Automatically detect data type and save in appropriate format.

    Args:
        data: VmdMotion, PmxModel, or VpdPose object
        file_path: Output file path
        mode: PMX write mode; omit for VMD/VPD

    Raises:
        ValueError: If data type is unsupported
    """
    if isinstance(data, VmdMotion):
        if mode is not None:
            raise ValueError("PMX write mode cannot be used when saving VMD")
        save_vmd(data, file_path)
    elif isinstance(data, PmxDocument):
        save_pmx(data, file_path, mode="lossless_patch" if mode is None else mode)
    elif isinstance(data, PmxModel):
        save_pmx(data, file_path, mode="canonical" if mode is None else mode)
    elif isinstance(data, VpdPose):
        if mode is not None:
            raise ValueError("PMX write mode cannot be used when saving VPD")
        save_vpd(data, file_path)
    else:
        raise ValueError(f"Unsupported data type: {type(data)}")


# ===== 文本解析和导出功能 =====


def load_vmd_text(file_path: Union[str, Path], more_info: bool = False) -> VmdMotion:
    """
    Load VMD motion file from text format.

    Args:
        file_path: Path to VMD text file
        more_info: Whether to include additional parsing information

    Returns:
        VmdMotion object

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    return _vmd_parser.parse_text_file(file_path, more_info=more_info)


def save_vmd_text(motion: VmdMotion, file_path: Union[str, Path]) -> None:
    """
    Save VMD motion to text file.

    Args:
        motion: VmdMotion object to save
        file_path: Output text file path

    Raises:
        ValueError: If motion data is invalid
        IOError: If file cannot be written
    """
    _vmd_parser.write_text_file(motion, file_path)


def load_pmx_text(file_path: Union[str, Path], more_info: bool = False) -> PmxModel:
    """
    Load PMX model file from text format.

    Args:
        file_path: Path to PMX text file
        more_info: Whether to include additional parsing information

    Returns:
        PmxModel object

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    return _pmx_parser.parse_text_file(file_path, more_info=more_info)


def save_pmx_text(model: PmxModel, file_path: Union[str, Path]) -> None:
    """
    Save PMX model to text file.

    Args:
        model: PmxModel object to save
        file_path: Output text file path

    Raises:
        ValueError: If model data is invalid
        IOError: If file cannot be written
    """
    _pmx_parser.write_text_file(model, file_path)


def load_vpd_text(file_path: Union[str, Path], more_info: bool = False) -> VpdPose:
    """
    Load VPD pose file from structured text format.

    Args:
        file_path: Path to VPD text file (can be original VPD or structured text)
        more_info: Whether to include additional parsing information

    Returns:
        VpdPose object

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid
    """
    return _vpd_parser.parse_text_file(file_path, more_info=more_info)


def save_vpd_text(pose: VpdPose, file_path: Union[str, Path]) -> None:
    """
    Save VPD pose to structured text file.

    Args:
        pose: VpdPose object to save
        file_path: Output text file path

    Raises:
        ValueError: If pose data is invalid
        IOError: If file cannot be written
    """
    _vpd_parser.write_text_file(pose, file_path)


def load_text(file_path: Union[str, Path], more_info: bool = False):
    """
    Automatically detect text file type and load appropriate format.

    Args:
        file_path: Path to text file
        more_info: Whether to include additional parsing information

    Returns:
        VmdMotion, PmxModel, or VpdPose object

    Raises:
        ValueError: If file type cannot be determined or is unsupported
    """
    path = Path(file_path)

    # Try to detect format by reading first few lines
    try:
        with open(path, "r", encoding="utf-8") as f:
            first_lines = [f.readline().strip() for _ in range(3)]
    except UnicodeDecodeError:
        # Try shift_jis encoding for VPD files
        with open(path, "r", encoding="shift_jis") as f:
            first_lines = [f.readline().strip() for _ in range(3)]

    # Check for file format indicators
    if any("version:" in line for line in first_lines):
        if any(
            "boneframe_ct:" in line or "morphframe_ct:" in line for line in first_lines
        ):
            return load_vmd_text(file_path, more_info)
        elif any("vertex_count:" in line for line in first_lines):
            return load_pmx_text(file_path, more_info)
    elif first_lines[0] == "Vocaloid Pose Data file" or any(
        "model_name:" in line for line in first_lines
    ):
        return load_vpd_text(file_path, more_info)

    # Fallback to file extension
    suffix = path.suffix.lower()
    if suffix == ".txt":
        # Try VMD text format first (most common)
        try:
            return load_vmd_text(file_path, more_info)
        except ValueError:
            try:
                return load_pmx_text(file_path, more_info)
            except ValueError:
                return load_vpd_text(file_path, more_info)
    else:
        raise ValueError(f"Cannot determine text file format for: {file_path}")


def save_text(data, file_path: Union[str, Path]) -> None:
    """
    Automatically detect data type and save in appropriate text format.

    Args:
        data: VmdMotion, PmxModel, or VpdPose object
        file_path: Output text file path

    Raises:
        ValueError: If data type is unsupported
    """
    if isinstance(data, VmdMotion):
        save_vmd_text(data, file_path)
    elif isinstance(data, PmxModel):
        save_pmx_text(data, file_path)
    elif isinstance(data, VpdPose):
        save_vpd_text(data, file_path)
    else:
        raise ValueError(f"Unsupported data type: {type(data)}")


# Export public API
__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__description__",
    # Binary file functions
    "load_vmd",
    "save_vmd",
    "load_pmx",
    "load_pmx_partial",
    "load_pmx_document",
    "save_pmx",
    "write_pmx",
    "load_vpd",
    "save_vpd",
    # Text file functions
    "load_vmd_text",
    "save_vmd_text",
    "load_pmx_text",
    "save_pmx_text",
    "load_vpd_text",
    "save_vpd_text",
    # Auto-detection functions
    "load",
    "save",
    "load_text",
    "save_text",
    # Model classes (for type hints)
    "VmdMotion",
    "PmxModel",
    "PmxDocument",
    "PmxParseReport",
    "PmxParseResult",
    "IncompletePmxError",
    "IncompletePmxWriterError",
    "PmxValidationError",
    "PmxPatchError",
    "UnsupportedPmxFeatureError",
    "VpdPose",
]
